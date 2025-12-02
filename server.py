import grpc
from concurrent import futures
import fitz
import numpy as np
import cv2
from pdf2image import convert_from_path, pdfinfo_from_path
import tempfile
import requests
import io
import img2pdf
from PIL import Image, ExifTags, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import os
import multiprocessing
from functools import lru_cache
import gc

import logging
Image.MAX_IMAGE_PIXELS = 933120000

# Import des fichiers protobuf générés
import pdf_service_pb2
import pdf_service_pb2_grpc

# Configuration du logging selon l'environnement
log_level = logging.DEBUG if os.getenv('ENABLE_DEBUG', 'false').lower() == 'true' else logging.INFO
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

# Configurer tempfile pour utiliser /tmp
# En production, /tmp est sur disque (volume) pour éviter saturation RAM avec gros PDFs
# En dev, peut être sur tmpfs (RAM) pour meilleures performances
if os.path.exists('/tmp'):
    tempfile.tempdir = '/tmp'
    logging.info(f"Fichiers temporaires configurés pour utiliser /tmp")

class PDFProcessor:
    """
    Classe qui gère tout le traitement des PDFs : détection des espaces vides
    et ajout des tampons.
    """

    def __init__(self, high_dpi=300, low_dpi=200, stamp_size_max=300, stamp_size_min=90, enable_debug=False):
        """
          Initialise le processeur PDF avec les paramètres nécessaires.

          Args:
              high_dpi (int): Résolution haute pour la conversion finale (par défaut 300)
              low_dpi (int): Résolution pour la détection (par défaut 200, augmenté pour meilleure qualité)
              stamp_size_max (int): Taille maximale du tampon en pixels (par défaut 300)
              stamp_size_min (int): Taille minimale du tampon en pixels pour lisibilité (par défaut 90)
              enable_debug (bool): Active la sauvegarde des images de debug (activé par défaut)
          """
        self.high_dpi = high_dpi
        self.low_dpi = low_dpi  # DPI par défaut augmenté pour meilleure qualité
        self.points_per_inch = 72

        self.stamp_size_max = stamp_size_max
        self.stamp_size_min = stamp_size_min
        self.margin = 10  # Marge de sécurité réduite en pixels (entre le carré extérieur et le tampon)
        self.enable_debug = enable_debug
        self.enable_ocr = False  # Désactiver OCR par défaut pour gagner en performance
        self.max_workers = min(8, multiprocessing.cpu_count())  # Augmenté à 8 workers pour gros fichiers
        self._stamp_cache = {}  # Cache pour les tampons redimensionnés
        self._kernel_cache = {}  # Cache pour les kernels OpenCV

    def download_from_gdrive(self, file_id, access_token):
        """
        Télécharge un fichier depuis Google Drive en utilisant l'API.

        Args:
            file_id (str): L'identifiant du fichier sur Google Drive
            access_token (str): Le jeton d'accès OAuth2 pour l'authentification

        Returns:
            BytesIO: Le contenu du fichier sous forme de buffer
        """
        try:
            # Construction des en-têtes avec le token d'authentification
            headers = {
                'Authorization': f'Bearer {access_token}'
            }

            # URL de l'API Google Drive pour télécharger le fichier
            url = f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media'

            # Téléchargement du fichier
            response = requests.get(url, headers=headers, stream=True)
            response.raise_for_status()

            # Retourne le contenu sous forme de BytesIO
            return io.BytesIO(response.content)

        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur lors du téléchargement depuis Google Drive: {str(e)}")
            raise ValueError(f"Échec du téléchargement depuis Google Drive: {str(e)}")

    def download_file(self, url):
        """Télécharge un fichier depuis une URL."""
        try:
            response = requests.get(url)
            response.raise_for_status()
            logging.info(f"Téléchargement du fichier depuis {url} réussi")
            return io.BytesIO(response.content)
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur lors du téléchargement : {str(e)}")
            raise ValueError(f"Erreur lors du téléchargement : {str(e)}")

    def download_from_oodrive(self, ooDriveFile):
        """Télécharge un fichier depuis Oodrive."""
        try:
            headers = {
                'XClientId': 'broker-defense',
                'Authorization': f'Bearer {ooDriveFile.accessToken}'
            }
            response = requests.get(f"https://sharing.oodrive.com/share/api/v1/io/items/{ooDriveFile.id}", headers=headers)
            response.raise_for_status()
            return io.BytesIO(response.content)
        except requests.exceptions.RequestException as e:
            logging.error(f"Erreur lors du téléchargement depuis Oodrive: {str(e)}")

    @lru_cache(maxsize=32)
    def _get_text_detection_kernel(self, size):
        """Cache les kernels pour éviter de les recréer"""
        return cv2.getStructuringElement(cv2.MORPH_RECT, size)

    def find_whitest_space(self, image):
        """
        Trouve le meilleur emplacement pour un tampon en évitant absolument les zones de texte,
        images et QR codes. La taille du tampon est adaptative entre min et max.
        Version optimisée sans OCR par défaut.
        """
        height, width = image.shape

        # Tailles adaptatives du tampon
        stamp_size_max = self.stamp_size_max
        stamp_size_min = self.stamp_size_min
        margin = self.margin

        # Créer des masques séparés pour chaque type d'élément détecté
        forbidden_mask = np.zeros((height, width), dtype=np.uint8)
        text_mask = np.zeros((height, width), dtype=np.uint8)
        image_mask = np.zeros((height, width), dtype=np.uint8)
        qrcode_mask = np.zeros((height, width), dtype=np.uint8)

        # ÉTAPE 1 : DÉTECTION DES LIGNES DE TEXTE (OCR optionnel)
        if self.enable_ocr:
            try:
                import pytesseract

                # Configuration simple pour détecter les lignes de texte
                config = '--psm 6 -l fra'  # Mode bloc uniforme en français

                # Obtenir les données OCR ligne par ligne
                data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)

                # Parcourir chaque élément détecté
                for i in range(len(data['text'])):
                    text = str(data['text'][i]).strip()
                    confidence = int(data['conf'][i]) if data['conf'][i] != '-1' else 0

                    # Si c'est du texte avec une confiance raisonnable
                    if len(text) > 0 and confidence > 30:
                        x = data['left'][i]
                        y = data['top'][i]
                        w = data['width'][i]
                        h = data['height'][i]

                        # Vérifier que les coordonnées sont valides
                        if x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= width and y + h <= height:
                            # Marquer SEULEMENT la zone de texte détectée avec une petite marge
                            margin_x = 5   # Marge horizontale réduite de 50%
                            margin_y = 2   # Marge verticale réduite de 50%

                            text_start_x = max(0, x - margin_x)
                            text_end_x = min(width, x + w + margin_x)
                            text_start_y = max(0, y - margin_y)
                            text_end_y = min(height, y + h + margin_y)

                            # Marquer SEULEMENT la zone de texte avec marge, pas toute la ligne
                            text_mask[text_start_y:text_end_y, text_start_x:text_end_x] = 255
                            forbidden_mask[text_start_y:text_end_y, text_start_x:text_end_x] = 255

            except (ImportError, Exception) as e:
                logging.warning(f"OCR non disponible: {e}")
                self.enable_ocr = False  # Désactiver pour les prochaines pages

        if not self.enable_ocr:
            # Détection améliorée par seuillage (plus sensible au texte)
            _, binary = cv2.threshold(image, 220, 255, cv2.THRESH_BINARY)  # Seuil plus élevé pour détecter plus de texte

            # Inversion pour avoir le texte en blanc
            inverted = 255 - binary

            # Détection des composants connectés (texte et graphiques)
            # Détection horizontale (lignes de texte)
            horizontal_kernel = self._get_text_detection_kernel((30, 1))  # Kernel plus petit pour être plus précis
            horizontal_lines = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, horizontal_kernel)

            # Détection verticale (colonnes, tableaux)
            vertical_kernel = self._get_text_detection_kernel((1, 15))
            vertical_lines = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, vertical_kernel)

            # Détection des petits éléments (points, caractères isolés)
            small_kernel = self._get_text_detection_kernel((3, 3))
            small_elements = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, small_kernel)

            # Combiner toutes les détections de texte
            text_combined = cv2.bitwise_or(horizontal_lines, vertical_lines)
            text_combined = cv2.bitwise_or(text_combined, small_elements)

            # Dilater modérément pour créer des zones de protection autour du texte
            dilate_kernel = self._get_text_detection_kernel((30, 15))  # Zone de protection réduite
            text_mask = cv2.dilate(text_combined, dilate_kernel, iterations=1)  # 1 itération au lieu de 2
            forbidden_mask = cv2.bitwise_or(forbidden_mask, text_mask)

        # DÉTECTION DES LIGNES HORIZONTALES (traits de séparation, bordures de tableaux)
        # Ces lignes sont souvent manquées par la détection de texte car elles sont continues
        try:
            # Seuiller pour détecter les lignes noires (seuil plus bas pour capturer les lignes fines)
            _, line_binary = cv2.threshold(image, 200, 255, cv2.THRESH_BINARY_INV)
            
            # Détecter les lignes horizontales longues (traits de séparation)
            # Utiliser plusieurs kernels de différentes longueurs pour détecter les lignes de différentes tailles
            line_masks = []
            
            # Lignes très longues (au moins 1/3 de la largeur) - traits de séparation principaux
            if width > 100:
                kernel_long = self._get_text_detection_kernel((max(100, width // 3), 1))
                lines_long = cv2.morphologyEx(line_binary, cv2.MORPH_OPEN, kernel_long)
                line_masks.append(lines_long)
            
            # Lignes moyennes (au moins 1/5 de la largeur) - traits de séparation secondaires
            if width > 60:
                kernel_medium = self._get_text_detection_kernel((max(60, width // 5), 1))
                lines_medium = cv2.morphologyEx(line_binary, cv2.MORPH_OPEN, kernel_medium)
                line_masks.append(lines_medium)
            
            # Lignes courtes mais significatives (au moins 1/10 de la largeur) - bordures de tableaux
            if width > 30:
                kernel_short = self._get_text_detection_kernel((max(30, width // 10), 1))
                lines_short = cv2.morphologyEx(line_binary, cv2.MORPH_OPEN, kernel_short)
                line_masks.append(lines_short)
            
            # Combiner toutes les détections de lignes horizontales
            detected_horizontal_lines = np.zeros((height, width), dtype=np.uint8)
            for mask in line_masks:
                detected_horizontal_lines = cv2.bitwise_or(detected_horizontal_lines, mask)
            
            # Dilater verticalement pour créer une zone de protection autour des lignes
            # Les lignes peuvent être fines, on veut éviter de placer le tampon même près d'elles
            line_dilate_kernel = self._get_text_detection_kernel((1, 15))  # Dilater de 15px verticalement (7-8px de chaque côté)
            detected_horizontal_lines = cv2.dilate(detected_horizontal_lines, line_dilate_kernel, iterations=1)
            
            # Ajouter au masque interdit
            forbidden_mask = cv2.bitwise_or(forbidden_mask, detected_horizontal_lines)
            
            # Détecter aussi les lignes verticales longues (bordures de colonnes)
            vertical_line_masks = []
            
            if height > 100:
                vertical_kernel_long = self._get_text_detection_kernel((1, max(100, height // 3)))
                vertical_lines_long = cv2.morphologyEx(line_binary, cv2.MORPH_OPEN, vertical_kernel_long)
                vertical_line_masks.append(vertical_lines_long)
            
            if height > 60:
                vertical_kernel_medium = self._get_text_detection_kernel((1, max(60, height // 5)))
                vertical_lines_medium = cv2.morphologyEx(line_binary, cv2.MORPH_OPEN, vertical_kernel_medium)
                vertical_line_masks.append(vertical_lines_medium)
            
            # Combiner les lignes verticales
            detected_vertical_lines = np.zeros((height, width), dtype=np.uint8)
            for mask in vertical_line_masks:
                detected_vertical_lines = cv2.bitwise_or(detected_vertical_lines, mask)
            
            # Dilater horizontalement pour créer une zone de protection
            vertical_line_dilate_kernel = self._get_text_detection_kernel((15, 1))  # Dilater de 15px horizontalement
            detected_vertical_lines = cv2.dilate(detected_vertical_lines, vertical_line_dilate_kernel, iterations=1)
            
            # Ajouter au masque interdit
            forbidden_mask = cv2.bitwise_or(forbidden_mask, detected_vertical_lines)
            
            logging.debug(f"Détection des lignes: {np.sum(detected_horizontal_lines > 0)} pixels horizontaux, {np.sum(detected_vertical_lines > 0)} pixels verticaux")
            
        except Exception as e:
            logging.warning(f"Erreur lors de la détection des lignes: {e}")

        # DÉTECTION DES IMAGES (zones avec beaucoup de variations de gris)
        # Les images ont généralement plus de variations que le texte simple
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        laplacian = cv2.Laplacian(blurred, cv2.CV_64F)
        laplacian_abs = np.abs(laplacian)
        
        # Seuiller pour trouver les zones avec beaucoup de détails (images)
        _, image_detection = cv2.threshold(laplacian_abs.astype(np.uint8), 30, 255, cv2.THRESH_BINARY)
        
        # Filtrer les grandes zones (probablement des images, pas du texte)
        # Le texte a généralement des zones plus petites et linéaires
        contours, _ = cv2.findContours(image_detection, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_image_area = 5000  # Surface minimale pour considérer une zone comme image
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area > min_image_area:
                # Créer un masque pour cette zone d'image
                contour_mask = np.zeros((height, width), dtype=np.uint8)
                cv2.fillPoly(contour_mask, [contour], 255)
                
                # Dilater pour créer une zone de protection réduite
                image_dilate_kernel = self._get_text_detection_kernel((30, 30))
                contour_mask = cv2.dilate(contour_mask, image_dilate_kernel, iterations=1)
                
                image_mask = cv2.bitwise_or(image_mask, contour_mask)
                forbidden_mask = cv2.bitwise_or(forbidden_mask, contour_mask)

        # DÉTECTION DES QR CODES (patterns carrés répétitifs)
        # Les QR codes ont des patterns caractéristiques : carrés noirs/blancs alternés
        try:
            # Détecter les contours carrés (caractéristiques des QR codes)
            _, qr_binary = cv2.threshold(image, 128, 255, cv2.THRESH_BINARY)
            qr_contours, _ = cv2.findContours(qr_binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filtrer les contours qui ressemblent à des QR codes (carrés imbriqués)
            for contour in qr_contours:
                area = cv2.contourArea(contour)
                # Les QR codes ont généralement des zones de taille moyenne
                if 1000 < area < 50000:
                    # Vérifier si c'est approximativement carré
                    x, y, w, h = cv2.boundingRect(contour)
                    aspect_ratio = float(w) / h if h > 0 else 0
                    
                    # Les QR codes sont généralement proches du carré (ratio entre 0.7 et 1.3)
                    if 0.7 < aspect_ratio < 1.3:
                        # Vérifier la densité de pixels (QR codes ont beaucoup de variations)
                        roi = image[y:y+h, x:x+w]
                        if roi.size > 0:
                            std_dev = np.std(roi)
                            # Les QR codes ont une variance élevée (beaucoup de noir/blanc)
                            if std_dev > 40:
                                # Marquer cette zone comme QR code potentiel
                                qr_mask = np.zeros((height, width), dtype=np.uint8)
                                cv2.fillPoly(qr_mask, [contour], 255)
                                
                                # Dilater modérément autour des QR codes
                                qr_dilate_kernel = self._get_text_detection_kernel((40, 40))
                                qr_mask = cv2.dilate(qr_mask, qr_dilate_kernel, iterations=1)
                                
                                qrcode_mask = cv2.bitwise_or(qrcode_mask, qr_mask)
                                forbidden_mask = cv2.bitwise_or(forbidden_mask, qr_mask)
        except Exception as e:
            logging.warning(f"Erreur lors de la détection des QR codes: {e}")

        # ÉTAPE 2 : RECHERCHE ADAPTATIVE DE ZONES BLANCHES
        # Le tampon utilisera toute la taille disponible dans la zone trouvée (moins une petite marge minimale)
        
        # Marge minimale pour éviter les bords (très réduite)
        min_margin = 5  # Marge minimale de sécurité en pixels

        # Créer une image binaire pour détecter les zones blanches
        _, white_binary = cv2.threshold(image, 245, 255, cv2.THRESH_BINARY)  # Seuil plus strict pour le blanc

        # Essayer différentes tailles de zone de recherche (de max à min)
        # Priorité : trouver la zone la plus grande possible dans la fourchette 200-300px
        # Le tampon utilisera toute la zone disponible jusqu'à 300px max
        min_zone_size = stamp_size_min + 2 * min_margin  # Zone minimale pour tampon de 200px
        # Chercher jusqu'à 500px de zone pour trouver les grandes zones blanches
        # Le tampon sera limité à 300px mais on cherche des zones plus grandes pour être sûr de trouver
        max_zone_size = max(stamp_size_max + 2 * min_margin, 410)  # Zone maximale de recherche (500px)
        
        # Rechercher de la plus grande taille vers la plus petite (priorité à la taille max)
        search_sizes_to_try = list(range(max_zone_size, min_zone_size - 1, -5))  # Pas de 10px pour précision
        if search_sizes_to_try[-1] != min_zone_size:
            search_sizes_to_try.append(min_zone_size)

        logging.info(f"Recherche de zones libres - Tailles testées: {search_sizes_to_try[:5]}...{search_sizes_to_try[-3:]} (tampon: {stamp_size_min}-{stamp_size_max}px)")

        # Pour chaque taille de zone, chercher une zone libre
        # PRIORITÉ : Arrêter dès qu'on trouve une zone de taille maximale (300px)
        best_position = None
        best_stamp_size = 0
        
        for square_size in search_sizes_to_try:
            # Si on a déjà trouvé une zone maximale (300px), arrêter immédiatement
            if best_stamp_size >= stamp_size_max:
                break
                
            # Calculer la zone de recherche effective
            search_width = width - square_size
            search_height = height - square_size

            if search_width <= 0 or search_height <= 0:
                # Taille trop grande pour cette page, essayer la suivante
                continue

            # RECHERCHE OPTIMISÉE : Pas adaptatif selon la taille de zone
            # Pour les grandes zones (proche de 300px), utiliser un pas plus petit pour ne rien rater
            if square_size >= stamp_size_max + 2 * min_margin - 20:  # Zones proches du max
                step = max(5, square_size // 30)  # Pas très fin pour grandes zones
            else:
                step = max(10, square_size // 20)  # Pas moyen pour zones moyennes
            
            logging.debug(f"Recherche zone {square_size}px avec pas de {step}px")

            # Recherche avec pas adaptatif
            for y in range(0, search_height, step):
                for x in range(0, search_width, step):

                    # VÉRIFICATION STRICTE : Aucune zone interdite tolérée
                    roi_forbidden = forbidden_mask[y:y + square_size, x:x + square_size]

                    if np.sum(roi_forbidden) == 0:  # ZÉRO pixel interdit - STRICTE
                        # Vérifier que la zone est bien blanche
                        roi_white = white_binary[y:y + square_size, x:x + square_size]
                        white_ratio = np.mean(roi_white) / 255.0

                        # Pour les grandes zones, assouplir légèrement le critère de blancheur (95% au lieu de 98%)
                        white_threshold = 0.95 if square_size >= stamp_size_max + 2 * min_margin - 20 else 0.98
                        if white_ratio > white_threshold:
                            # Calculer la taille du tampon : utiliser toute la zone disponible
                            # Limiter à stamp_size_max (300px) et vérifier le minimum (200px)
                            available_stamp_size = min(square_size - 2 * min_margin, stamp_size_max)
                            # Vérifier que la taille minimale est respectée
                            if available_stamp_size >= stamp_size_min:
                                # Si c'est la taille maximale (300px), arrêter immédiatement
                                if available_stamp_size >= stamp_size_max:
                                    best_position = (x, y, white_ratio, available_stamp_size, square_size)
                                    best_stamp_size = available_stamp_size
                                    logging.info(f"Zone maximale (300px) trouvée immédiatement à ({x}, {y}) - Taille zone: {square_size}px - Taille tampon: {available_stamp_size}px")
                                    break
                                
                                # Sinon, garder la meilleure trouvée jusqu'à présent
                                if available_stamp_size > best_stamp_size:
                                    best_position = (x, y, white_ratio, available_stamp_size, square_size)
                                    best_stamp_size = available_stamp_size
                                    logging.debug(f"Meilleure zone trouvée: {square_size}px -> tampon {available_stamp_size}px à ({x}, {y})")
                    
                    # Sortir de la boucle x si on a trouvé la taille maximale (300px)
                    if best_stamp_size >= stamp_size_max:
                        break
                
                # Sortir de la boucle y si on a trouvé la taille maximale (300px)
                if best_stamp_size >= stamp_size_max:
                    break
            
            # Sortir de la boucle square_size si on a trouvé la taille maximale (300px)
            if best_stamp_size >= stamp_size_max:
                break

        # Si on a trouvé une position, l'utiliser
        if best_position:
            best_x, best_y, best_white, found_stamp_size, found_square_size = best_position
            
            # Affiner la recherche autour de la meilleure position trouvée (seulement pour la taille trouvée)
            # Réduire le rayon d'affinage pour performance
            refine_radius = 5  # Réduit de 10 à 5
            best_refined = None
            best_refined_stamp_size = found_stamp_size
            
            search_width = width - found_square_size
            search_height = height - found_square_size
            
            if search_width > 0 and search_height > 0:
                # Recherche fine autour de la meilleure position (pas de 2px pour performance)
                fine_step = 2  # Augmenté de 1 à 2 pour performance
                for y in range(max(0, best_y - refine_radius), min(search_height, best_y + refine_radius + 1), fine_step):
                    for x in range(max(0, best_x - refine_radius), min(search_width, best_x + refine_radius + 1), fine_step):
                        roi_forbidden = forbidden_mask[y:y + found_square_size, x:x + found_square_size]
                        if np.sum(roi_forbidden) == 0:
                            roi_white = white_binary[y:y + found_square_size, x:x + found_square_size]
                            white_ratio = np.mean(roi_white) / 255.0
                            if white_ratio > 0.98:
                                # Utiliser toute la zone disponible, limitée à 300px max
                                available_stamp_size = min(found_square_size - 2 * min_margin, stamp_size_max)
                                if available_stamp_size >= stamp_size_min:
                                    if available_stamp_size > best_refined_stamp_size:
                                        best_refined_stamp_size = available_stamp_size
                                        best_refined = (x, y, white_ratio, available_stamp_size, found_square_size)
            
            # Utiliser la position affinée si meilleure, sinon la position originale
            if best_refined and best_refined_stamp_size > found_stamp_size:
                best_x, best_y, best_white, found_stamp_size, found_square_size = best_refined
                logging.info(f"Zone optimale trouvée (affinée) à ({best_x}, {best_y}) - Taille zone: {found_square_size}px - Taille tampon: {found_stamp_size}px - Blancheur: {best_white:.3f}")
            else:
                logging.info(f"Zone optimale trouvée à ({best_x}, {best_y}) - Taille zone: {found_square_size}px - Taille tampon: {found_stamp_size}px - Blancheur: {best_white:.3f}")
            
            return {
                "x": float(best_x),
                "y": float(best_y),
                "size": float(found_square_size),
                "stamp_size": float(found_stamp_size)
            }, forbidden_mask, text_mask, image_mask, qrcode_mask

        # AUCUNE ZONE TOTALEMENT LIBRE TROUVÉE
        logging.warning("Aucune zone totalement libre trouvée - Passage au fallback")

        # FALLBACK : Chercher dans les coins avec recherche adaptative de taille
        # Le tampon utilisera toute la taille disponible dans la zone trouvée
        corner_positions_base = [
            (width - 20, 20),  # Haut droite
            (20, 20),  # Haut gauche
            (width - 20, height - 20),  # Bas droite
            (20, height - 20),  # Bas gauche
            (width - 50, 50),  # Haut droite avec plus de marge
            (50, 50),  # Haut gauche avec plus de marge
            (width // 2, 20),  # Centre haut
        ]

        best_corner = None
        best_stamp_size = 0
        best_forbidden_ratio = 1.0
        best_white_ratio = 0.0

        # Essayer chaque taille de zone dans chaque coin
        # OPTIMISATION : Utiliser un pas plus grand pour les tailles (50px au lieu de toutes)
        fallback_sizes = list(range(stamp_size_max + 2 * min_margin, min_zone_size - 1, -50))
        if fallback_sizes[-1] != min_zone_size:
            fallback_sizes.append(min_zone_size)
            
        for square_size in fallback_sizes:
            # Si on a déjà trouvé la taille maximale (300px), arrêter
            if best_corner and best_stamp_size >= stamp_size_max:
                break
                
            for corner_x_base, corner_y_base in corner_positions_base:
                corner_x = corner_x_base - square_size
                corner_y = corner_y_base
                
                if (corner_x >= 0 and corner_y >= 0 and
                    corner_x + square_size <= width and corner_y + square_size <= height):

                    # Analyser cette position de coin
                    roi_forbidden = forbidden_mask[corner_y:corner_y + square_size, corner_x:corner_x + square_size]
                    roi_white = white_binary[corner_y:corner_y + square_size, corner_x:corner_x + square_size]

                    forbidden_ratio = np.sum(roi_forbidden) / (square_size * square_size)
                    white_ratio = np.mean(roi_white) / 255.0

                    # Priorité 1: Zéro zone interdite (strict)
                    # Priorité 2: Taille maximale (300px)
                    # Priorité 3: Maximum de blancheur
                    if forbidden_ratio == 0 and white_ratio > 0.95:
                        # Utiliser toute la zone disponible, limitée à 300px max
                        available_stamp_size = min(square_size - 2 * min_margin, stamp_size_max)
                        # Vérifier que la taille minimale est respectée
                        if available_stamp_size >= stamp_size_min:
                            # Si c'est la taille maximale (300px), arrêter immédiatement
                            if available_stamp_size >= stamp_size_max:
                                best_forbidden_ratio = forbidden_ratio
                                best_white_ratio = white_ratio
                                best_stamp_size = available_stamp_size
                                best_corner = {
                                    "x": float(corner_x),
                                    "y": float(corner_y),
                                    "size": float(square_size),
                                    "stamp_size": float(available_stamp_size)
                                }
                                break
                            
                            if available_stamp_size > best_stamp_size or (available_stamp_size == best_stamp_size and white_ratio > best_white_ratio):
                                best_forbidden_ratio = forbidden_ratio
                                best_white_ratio = white_ratio
                                best_stamp_size = available_stamp_size
                                best_corner = {
                                    "x": float(corner_x),
                                    "y": float(corner_y),
                                    "size": float(square_size),
                                    "stamp_size": float(available_stamp_size)
                                }
            
            # Sortir de la boucle square_size si on a trouvé la taille maximale (300px)
            if best_corner and best_stamp_size >= stamp_size_max:
                break

        if best_corner:
            logging.warning(f"Position de fallback choisie - Taille zone: {best_corner['size']}px - Taille tampon: {best_stamp_size}px - Zones interdites: {best_forbidden_ratio*100:.1f}% - Blancheur: {best_white_ratio:.3f}")
            return best_corner, forbidden_mask, text_mask, image_mask, qrcode_mask

        # 4. POSITIONS DE SECOURS avec recherche adaptative
        # Le tampon utilisera toute la taille disponible dans la zone trouvée
        fallback_positions_base = [
            (width - 50, 50),  # Haut droite avec plus de marge
            (50, 50),  # Haut gauche avec plus de marge
            (width - 50, height - 50),  # Bas droite
            (50, height - 50),  # Bas gauche
            (width // 2, 50),  # Haut centre
            (width // 2, height - 50),  # Bas centre
        ]

        best_fallback = None
        best_fallback_stamp_size = 0
        best_fallback_white_ratio = 0.0

        # Essayer chaque taille de zone dans chaque position de secours
        # OPTIMISATION : Utiliser le même pas réduit pour performance
        for square_size in fallback_sizes:
            # Si on a déjà trouvé une zone acceptable, arrêter
            if best_fallback and best_fallback_stamp_size >= stamp_size_min:
                break
                
            for x_base, y_base in fallback_positions_base:
                x = x_base - square_size
                y = y_base
                
                if (x >= 0 and y >= 0 and
                    x + square_size <= width and y + square_size <= height):

                    # VALIDATION ULTRA-STRICTE même pour les positions de secours
                    roi_forbidden = forbidden_mask[y:y + square_size, x:x + square_size]

                    # AUCUN chevauchement autorisé, même en fallback
                    if np.sum(roi_forbidden) == 0:
                        # Vérification supplémentaire de la blancheur
                        roi_white = white_binary[y:y + square_size, x:x + square_size]
                        white_ratio = np.mean(roi_white) / 255.0

                        # Même en fallback, exiger 95% de blanc minimum
                        if white_ratio > 0.95:
                            # Utiliser toute la zone disponible, limitée à 300px max
                            available_stamp_size = min(square_size - 2 * min_margin, stamp_size_max)
                            # Vérifier que la taille minimale est respectée
                            if available_stamp_size >= stamp_size_min:
                                if available_stamp_size > best_fallback_stamp_size or (available_stamp_size == best_fallback_stamp_size and white_ratio > best_fallback_white_ratio):
                                    best_fallback_stamp_size = available_stamp_size
                                    best_fallback_white_ratio = white_ratio
                                    best_fallback = {
                                        "x": float(x),
                                        "y": float(y),
                                        "size": float(square_size),
                                        "stamp_size": float(available_stamp_size)
                                    }

        if best_fallback:
            logging.info(f"Position de secours trouvée - Taille zone: {best_fallback['size']}px - Taille tampon: {best_fallback_stamp_size}px")
            return best_fallback, forbidden_mask, text_mask, image_mask, qrcode_mask

        # DERNIER RECOURS: Si aucune position sûre n'est trouvée
        # Calculer le pourcentage de contenu de la page
        total_pixels = height * width
        forbidden_pixels = np.sum(forbidden_mask > 0)
        content_ratio = forbidden_pixels / total_pixels if total_pixels > 0 else 1.0

        logging.warning(f"AUCUNE POSITION SÛRE TROUVÉE - Page dense: {content_ratio*100:.1f}% de contenu détecté")

        # Essayer les coins avec validation STRICTE (0% de chevauchement) avec recherche adaptative
        # Le tampon utilisera toute la taille disponible dans la zone trouvée
        emergency_positions_base = [
            (width - 20, height - 20),  # Coin bas droite (priorité 1)
            (20, height - 20),       # Coin bas gauche (priorité 2)
            (width - 20, 20),        # Coin haut droite (priorité 3)
            (20, 20),                # Coin haut gauche (priorité 4)
        ]

        best_emergency = None
        best_emergency_stamp_size = 0
        best_emergency_white_ratio = 0.0
        best_emergency_overlap = 1.0  # Ratio de chevauchement (0.0 = aucun, 1.0 = total)

        # Essayer chaque taille de zone dans chaque position d'urgence (SANS chevauchement)
        for square_size in search_sizes_to_try:
            for emergency_x_base, emergency_y_base in emergency_positions_base:
                emergency_x = emergency_x_base - square_size
                emergency_y = emergency_y_base

                if (emergency_x >= 0 and emergency_y >= 0 and
                    emergency_x + square_size <= width and emergency_y + square_size <= height):

                    roi_forbidden = forbidden_mask[emergency_y:emergency_y + square_size,
                                                 emergency_x:emergency_x + square_size]
                    forbidden_ratio = np.sum(roi_forbidden) / (square_size * square_size)

                    # Essayer d'abord SANS chevauchement
                    if forbidden_ratio == 0:
                        roi_white = white_binary[emergency_y:emergency_y + square_size,
                                               emergency_x:emergency_x + square_size]
                        white_ratio = np.mean(roi_white) / 255.0

                        if white_ratio > 0.95:
                            available_stamp_size = min(square_size - 2 * min_margin, stamp_size_max)
                            if available_stamp_size >= stamp_size_min:
                                if available_stamp_size > best_emergency_stamp_size or (available_stamp_size == best_emergency_stamp_size and white_ratio > best_emergency_white_ratio):
                                    best_emergency_stamp_size = available_stamp_size
                                    best_emergency_white_ratio = white_ratio
                                    best_emergency_overlap = 0.0
                                    best_emergency = {
                                        "x": float(emergency_x),
                                        "y": float(emergency_y),
                                        "size": float(square_size),
                                        "stamp_size": float(available_stamp_size)
                                    }

        if best_emergency and best_emergency_overlap == 0.0:
            logging.info(f"Position d'urgence sans chevauchement trouvée - Taille zone: {best_emergency['size']}px - Taille tampon: {best_emergency_stamp_size}px")
            return best_emergency, forbidden_mask, text_mask, image_mask, qrcode_mask

        # FALLBACK ULTIME : Autoriser un chevauchement MINIMAL (5-10%) dans les coins
        # Toujours trouver une zone pour placer le tampon
        logging.warning(f"Recherche avec chevauchement minimal autorisé (≤10%)")

        MAX_ALLOWED_OVERLAP = 0.10  # Maximum 10% de chevauchement autorisé

        # Réinitialiser la recherche avec chevauchement minimal autorisé
        best_emergency = None
        best_emergency_stamp_size = 0
        best_emergency_white_ratio = 0.0
        best_emergency_overlap = 1.0

        # Essayer chaque taille de zone dans chaque position d'urgence (AVEC chevauchement minimal)
        for square_size in search_sizes_to_try:
            for emergency_x_base, emergency_y_base in emergency_positions_base:
                emergency_x = emergency_x_base - square_size
                emergency_y = emergency_y_base

                if (emergency_x >= 0 and emergency_y >= 0 and
                    emergency_x + square_size <= width and emergency_y + square_size <= height):

                    roi_forbidden = forbidden_mask[emergency_y:emergency_y + square_size,
                                                 emergency_x:emergency_x + square_size]
                    forbidden_ratio = np.sum(roi_forbidden) / (square_size * square_size)

                    # Autoriser jusqu'à 10% de chevauchement
                    if forbidden_ratio <= MAX_ALLOWED_OVERLAP:
                        roi_white = white_binary[emergency_y:emergency_y + square_size,
                                               emergency_x:emergency_x + square_size]
                        white_ratio = np.mean(roi_white) / 255.0

                        # Critère de blancheur plus souple (90% au lieu de 95%)
                        if white_ratio > 0.90:
                            available_stamp_size = min(square_size - 2 * min_margin, stamp_size_max)
                            if available_stamp_size >= stamp_size_min:
                                # Critères de sélection (par ordre de priorité):
                                # 1. Plus grande taille de tampon
                                # 2. Moins de chevauchement
                                # 3. Plus grande blancheur
                                is_better = False
                                if available_stamp_size > best_emergency_stamp_size:
                                    is_better = True
                                elif available_stamp_size == best_emergency_stamp_size:
                                    if forbidden_ratio < best_emergency_overlap:
                                        is_better = True
                                    elif forbidden_ratio == best_emergency_overlap and white_ratio > best_emergency_white_ratio:
                                        is_better = True

                                if is_better:
                                    best_emergency_stamp_size = available_stamp_size
                                    best_emergency_white_ratio = white_ratio
                                    best_emergency_overlap = forbidden_ratio
                                    best_emergency = {
                                        "x": float(emergency_x),
                                        "y": float(emergency_y),
                                        "size": float(square_size),
                                        "stamp_size": float(available_stamp_size)
                                    }

        if best_emergency:
            overlap_percent = best_emergency_overlap * 100
            logging.warning(f"Position d'urgence avec chevauchement minimal trouvée - Taille zone: {best_emergency['size']}px - Taille tampon: {best_emergency_stamp_size}px - Chevauchement: {overlap_percent:.1f}%")
            return best_emergency, forbidden_mask, text_mask, image_mask, qrcode_mask

        # SI VRAIMENT AUCUNE POSITION N'EST TROUVÉE (cas extrêmement rare)
        # Placer dans le coin haut droite par défaut avec la taille minimale
        logging.error(f"PAGE EXTRÊMEMENT DENSE ({content_ratio*100:.1f}% de contenu) - Placement forcé dans le coin haut droite")

        # Calculer la position pour le coin haut droite avec taille minimale
        forced_square_size = stamp_size_min + 2 * min_margin
        forced_x = max(0, width - forced_square_size - 20)
        forced_y = 20

        # S'assurer que la position est dans les limites de la page
        if forced_x + forced_square_size > width:
            forced_x = max(0, width - forced_square_size)
        if forced_y + forced_square_size > height:
            forced_y = max(0, height - forced_square_size)

        forced_position = {
            "x": float(forced_x),
            "y": float(forced_y),
            "size": float(forced_square_size),
            "stamp_size": float(stamp_size_min)
        }

        # Calculer le chevauchement pour information
        roi_forbidden = forbidden_mask[forced_y:min(forced_y + forced_square_size, height),
                                     forced_x:min(forced_x + forced_square_size, width)]
        actual_size = roi_forbidden.size
        if actual_size > 0:
            forced_overlap = np.sum(roi_forbidden) / actual_size * 100
            logging.warning(f"Position forcée dans le coin haut droite - Chevauchement: {forced_overlap:.1f}%")

        return forced_position, forbidden_mask, text_mask, image_mask, qrcode_mask

    def save_debug_image(self, image, forbidden_mask, stamp_position, page_num, output_dir="/app/debug", 
                         text_mask=None, image_mask=None, qrcode_mask=None):
        """
        Sauvegarde une image de debug avec les masques et la position du tampon
        pour visualiser ce que l'algorithme détecte.
        Affiche séparément le texte (rouge), les images (bleu) et les QR codes (magenta).
        """
        try:
            import os

            # Créer le dossier debug s'il n'existe pas
            os.makedirs(output_dir, exist_ok=True)

            # Créer une image de debug en couleur
            debug_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

            # Appliquer les masques avec des couleurs différentes pour chaque type
            if text_mask is not None:
                # Rouge pour le texte
                text_overlay = debug_image.copy()
                text_overlay[text_mask > 0] = [0, 0, 255]  # Rouge pour texte
                debug_image = cv2.addWeighted(debug_image, 0.7, text_overlay, 0.3, 0)

            if image_mask is not None:
                # Bleu pour les images
                image_overlay = debug_image.copy()
                image_overlay[image_mask > 0] = [255, 0, 0]  # Bleu pour images
                debug_image = cv2.addWeighted(debug_image, 0.7, image_overlay, 0.3, 0)

            if qrcode_mask is not None:
                # Magenta pour les QR codes
                qr_overlay = debug_image.copy()
                qr_overlay[qrcode_mask > 0] = [255, 0, 255]  # Magenta pour QR codes
                debug_image = cv2.addWeighted(debug_image, 0.7, qr_overlay, 0.3, 0)

            # Vérifier si une position de tampon a été trouvée
            if stamp_position is None or stamp_position.get("x", -1) < 0:
                # Pas de tampon placé - afficher un message
                height, width = image.shape
                cv2.putText(debug_image, f"Page {page_num} - AUCUN TAMPON PLACE", (10, 30),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)
                
                # Calculer le pourcentage de contenu
                total_pixels = height * width
                forbidden_pixels = np.sum(forbidden_mask > 0)
                content_ratio = forbidden_pixels / total_pixels if total_pixels > 0 else 1.0
                
                cv2.putText(debug_image, f"Page trop dense: {content_ratio*100:.1f}% de contenu", (10, 70),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                
                # Sauvegarder l'image de debug
                debug_filename = f"{output_dir}/debug_page_{page_num:03d}_NO_STAMP.png"
                cv2.imwrite(debug_filename, debug_image)
                logging.warning(f"Image de debug sans tampon sauvegardée: {debug_filename}")
                return

            # Dessiner un rectangle vert pour la position du tampon
            x = int(stamp_position["x"])
            y = int(stamp_position["y"])
            size = int(stamp_position["size"])

            # Utiliser la taille adaptative du tampon si disponible
            stamp_size = stamp_position.get("stamp_size", self.stamp_size_max)
            actual_stamp_size = int(stamp_size)
            # Centrer le tampon dans la zone disponible (tampon utilise toute la zone jusqu'à 300px max)
            margin = (size - actual_stamp_size) // 2
            actual_x = x + margin
            actual_y = y + margin

            # Rectangle vert pour la zone de recherche (zone blanche disponible)
            cv2.rectangle(debug_image, (x, y), (x + size, y + size), (0, 200, 0), 2)  # Vert clair pour zone de recherche

            # Rectangle vert épais pour le tampon réel (utilise toute la zone disponible, centré)
            cv2.rectangle(debug_image, (actual_x, actual_y), 
                         (actual_x + actual_stamp_size, actual_y + actual_stamp_size), 
                         (0, 255, 0), 6)  # Vert épais pour tampon réel (plus visible)
            
            # Ajouter un remplissage semi-transparent pour mieux visualiser la zone du tampon
            overlay = debug_image.copy()
            cv2.rectangle(overlay, (actual_x, actual_y), 
                         (actual_x + actual_stamp_size, actual_y + actual_stamp_size), 
                         (0, 255, 0), -1)  # Remplissage vert
            cv2.addWeighted(overlay, 0.2, debug_image, 0.8, 0, debug_image)  # Semi-transparent

            # Ajouter du texte pour indiquer la page et la taille
            usage_percent = (actual_stamp_size / size * 100) if size > 0 else 0
            cv2.putText(debug_image, f"Page {page_num} - Zone verte trouvee: {size}x{size}px - Tampon: {actual_stamp_size}x{actual_stamp_size}px ({usage_percent:.1f}%)", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
            
            # Ajouter aussi un texte directement sur le rectangle vert pour plus de visibilité
            text_size_zone = cv2.getTextSize(f"Zone: {size}x{size}px", cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            text_x_zone = x + (size - text_size_zone[0]) // 2
            text_y_zone = y - 10 if y > 30 else y + size + 25
            cv2.putText(debug_image, f"Zone: {size}x{size}px", (text_x_zone, text_y_zone),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)  # Vert pour correspondre au rectangle

            # Calculer les pourcentages de chevauchement pour chaque type
            roi_mask = forbidden_mask[y:y + size, x:x + size]
            overlap_ratio = np.sum(roi_mask) / (size * size) * 100

            text_overlap = 0
            image_overlap = 0
            qr_overlap = 0
            
            if text_mask is not None:
                roi_text = text_mask[y:y + size, x:x + size]
                text_overlap = np.sum(roi_text) / (size * size) * 100
                
            if image_mask is not None:
                roi_image = image_mask[y:y + size, x:x + size]
                image_overlap = np.sum(roi_image) / (size * size) * 100
                
            if qrcode_mask is not None:
                roi_qr = qrcode_mask[y:y + size, x:x + size]
                qr_overlap = np.sum(roi_qr) / (size * size) * 100

            # Afficher les informations de chevauchement
            y_offset = 70
            cv2.putText(debug_image, f"Chevauchement total: {overlap_ratio:.1f}%", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            if text_mask is not None:
                y_offset += 30
                color = (0, 0, 255) if text_overlap > 0 else (200, 200, 200)
                cv2.putText(debug_image, f"  - Texte: {text_overlap:.1f}%", (10, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            if image_mask is not None:
                y_offset += 30
                color = (255, 0, 0) if image_overlap > 0 else (200, 200, 200)
                cv2.putText(debug_image, f"  - Images: {image_overlap:.1f}%", (10, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            
            if qrcode_mask is not None:
                y_offset += 30
                color = (255, 0, 255) if qr_overlap > 0 else (200, 200, 200)
                cv2.putText(debug_image, f"  - QR Codes: {qr_overlap:.1f}%", (10, y_offset),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            # Ajouter une légende
            y_offset += 50
            cv2.putText(debug_image, "Legende:", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            y_offset += 25
            cv2.putText(debug_image, "  Rouge = Texte", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            y_offset += 20
            cv2.putText(debug_image, "  Bleu = Images", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
            y_offset += 20
            cv2.putText(debug_image, "  Magenta = QR Codes", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
            y_offset += 20
            cv2.putText(debug_image, "  Vert = Position tampon", (10, y_offset),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            # Sauvegarder l'image de debug
            debug_filename = f"{output_dir}/debug_page_{page_num:03d}.png"
            cv2.imwrite(debug_filename, debug_image)

            # Log détaillé si problème détecté
            if overlap_ratio > 0:
                logging.warning(f"Page {page_num}: Chevauchement detecte! Total: {overlap_ratio:.1f}% | "
                              f"Texte: {text_overlap:.1f}% | Images: {image_overlap:.1f}% | QR: {qr_overlap:.1f}%")
            else:
                logging.info(f"Image de debug sauvegardée: {debug_filename}")

        except Exception as e:
            logging.error(f"Erreur lors de la sauvegarde debug: {e}")

    def _merge_first_page_with_rest(self, stamped_first_page_path, original_pdf_path, num_pages):
        """
        Fusionne la première page tamponnée avec le reste du PDF original
        """
        try:
            # Charger les deux PDFs avec PyMuPDF (fitz)
            stamped_pdf = fitz.open(stamped_first_page_path)
            original_pdf = fitz.open(original_pdf_path)

            # Créer un nouveau PDF
            output_pdf = fitz.open()

            # Ajouter la première page tamponnée
            output_pdf.insert_pdf(stamped_pdf, from_page=0, to_page=0)

            # Ajouter toutes les pages suivantes du PDF original (à partir de la page 2)
            if num_pages > 1:
                output_pdf.insert_pdf(original_pdf, from_page=1, to_page=num_pages-1)

            # Sauvegarder le PDF fusionné
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                output_path = tmp_file.name

            output_pdf.save(output_path)

            # Fermer les PDFs
            stamped_pdf.close()
            original_pdf.close()
            output_pdf.close()

            logging.info(f"Fusion terminée avec succès : {output_path}")
            return output_path

        except Exception as e:
            logging.error(f"Erreur lors de la fusion des PDFs : {e}")
            raise

    def _process_single_page(self, args):
        """Traite une seule page (pour le traitement parallèle)"""
        page_num, pdf_path, stamp_path, index, prefix = args

        try:
            # Conversion de la page
            page_img = convert_from_path(pdf_path, dpi=self.low_dpi,
                                        first_page=page_num, last_page=page_num)[0]

            # Optimisation : Conversion directe en array numpy
            # Pas de filtrage pour préserver les lignes fines
            gray_image = cv2.cvtColor(np.array(page_img), cv2.COLOR_RGB2GRAY)
            # Pas de medianBlur pour préserver les lignes fines

            # Détection de l'espace blanc
            result = self.find_whitest_space(gray_image)
            if len(result) == 5:
                coords, forbidden_mask, text_mask, image_mask, qrcode_mask = result
            else:
                # Fallback pour compatibilité
                coords, forbidden_mask = result[0], result[1]
                text_mask, image_mask, qrcode_mask = None, None, None

            # Si aucune position sûre n'a été trouvée, ne pas placer de tampon
            if coords is None:
                logging.warning(f"Page {page_num}: Aucune zone sûre trouvée - Tampon non placé")
                
                # Debug même si pas de tampon pour voir pourquoi
                if self.enable_debug:
                    # Créer une position fictive pour le debug (hors page)
                    fake_coords = {"x": -1000, "y": -1000, "size": 300}
                    self.save_debug_image(gray_image, forbidden_mask, fake_coords, page_num, 
                                         text_mask=text_mask, image_mask=image_mask, qrcode_mask=qrcode_mask)
                
                # Retourner la page sans tampon en PNG avec compression maximale pour réduire la taille
                temp_img = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                page_img.convert("RGB").save(temp_img, format='PNG', compress_level=9)
                temp_img.close()
                
                return page_num, temp_img.name, None

            # Debug optionnel
            if self.enable_debug:
                self.save_debug_image(gray_image, forbidden_mask, coords, page_num, 
                                     text_mask=text_mask, image_mask=image_mask, qrcode_mask=qrcode_mask)

            # Application du tampon si position trouvée et valide
            if coords is not None and coords.get("x", -1) >= 0 and coords.get("y", -1) >= 0:
                page_img = page_img.convert("RGBA")  # Conversion RGBA seulement si nécessaire
                x = int(coords['x'])
                y = int(coords['y'])

                # Utiliser la taille adaptative du tampon trouvée par l'algorithme
                # Le tampon utilise toute la zone disponible jusqu'à 300px max (centré)
                stamp_size = coords.get("stamp_size", self.stamp_size_max)
                zone_size = coords.get("size", stamp_size)
                
                # Utiliser le DPI réel de la page pour un meilleur calcul de taille
                # Ne pas réduire la taille du tampon avec le facteur DPI pour préserver la qualité
                # Le tampon sera appliqué à sa taille réelle trouvée par l'algorithme
                adjusted_stamp_size = int(stamp_size)  # Utiliser la taille réelle sans réduction DPI
                adjusted_zone_size = int(zone_size)  # Convertir en int pour les calculs
                # Centrer le tampon dans la zone disponible (tampon utilise toute la zone jusqu'à 300px max)
                adjusted_margin = (adjusted_zone_size - adjusted_stamp_size) // 2

                logging.info(f"Page {page_num}: Application du tampon de taille {stamp_size}px (ajusté: {adjusted_stamp_size}px) dans une zone de {adjusted_zone_size}px (centré, utilise {adjusted_stamp_size/adjusted_zone_size*100:.1f}% de la zone)")

                # Utiliser le cache pour le tampon redimensionné avec qualité maximale
                cache_key = (stamp_path, adjusted_stamp_size)
                if cache_key not in self._stamp_cache:
                    stamp_img = Image.open(stamp_path).convert("RGBA")
                    # Redimensionner avec LANCZOS pour la meilleure qualité
                    # Si le redimensionnement est important, faire un upscale progressif pour préserver les détails
                    original_size = max(stamp_img.width, stamp_img.height)
                    if adjusted_stamp_size > original_size * 1.5:
                        # Pour les grands agrandissements, redimensionner progressivement
                        intermediate_size = int(original_size * 1.5)
                        stamp_img = stamp_img.resize((intermediate_size, intermediate_size), Image.Resampling.LANCZOS)
                    # Redimensionnement final avec LANCZOS (meilleure qualité)
                    self._stamp_cache[cache_key] = stamp_img.resize((adjusted_stamp_size, adjusted_stamp_size),
                                                                   Image.Resampling.LANCZOS)
                stamp_img = self._stamp_cache[cache_key].copy()
                page_img.paste(stamp_img, (x + adjusted_margin, y + adjusted_margin), stamp_img)

                # Ajouter le texte avec taille augmentée
                draw = ImageDraw.Draw(page_img)
                font_size = int(adjusted_stamp_size * 0.12)  # Augmentation de 10% à 12% pour meilleure lisibilité
                font_path = "fonts/OpenSans-regular.ttf"

                try:
                    font = ImageFont.truetype(font_path, font_size)
                except Exception:
                    font = ImageFont.load_default()

                text_line1 = "Pièce n°"
                text_line2 = prefix + '-' + str(index) if prefix else str(index)

                center_x = x + adjusted_margin + adjusted_stamp_size // 2
                center_y = y + adjusted_margin + adjusted_stamp_size // 2

                try:
                    bbox1 = draw.textbbox((0, 0), text_line1, font=font)
                    text_width1 = bbox1[2] - bbox1[0]
                    text_height1 = bbox1[3] - bbox1[1]
                    bbox2 = draw.textbbox((0, 0), text_line2, font=font)
                    text_width2 = bbox2[2] - bbox2[0]
                    text_height2 = bbox2[3] - bbox2[1]
                except AttributeError:
                    text_width1, text_height1 = font.getsize(text_line1)
                    text_width2, text_height2 = font.getsize(text_line2)

                draw.text((center_x - text_width1/2, center_y - text_height1 - 10),
                         text_line1, fill="black", font=font)
                draw.text((center_x - text_width2/2, center_y + 10),
                         text_line2, fill="black", font=font)

            # Sauvegarde en PNG avec compression maximale pour préserver les lignes fines sans perte
            # compress_level=9 réduit la taille de ~30-40% par rapport à compress_level=1
            temp_img = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            page_img.convert("RGB").save(temp_img, format='PNG', compress_level=9)
            temp_img.close()

            return page_num, temp_img.name, coords

        except Exception as e:
            logging.error(f"Erreur traitement page {page_num}: {e}")
            raise

    def process_document(self, pdf_path, stamp_path, index=1, prefix="", stamp_only_first_page=False):
        """
        Processus optimisé avec traitement parallèle des pages et adaptation automatique
        """
        try:
            info = pdfinfo_from_path(pdf_path)
            num_pages = info['Pages']

            # Si on ne doit tamponner que la première page
            if stamp_only_first_page:
                logging.info(f"Tamponnage uniquement de la première page (sur {num_pages} pages totales)")
                
                # Récupérer les dimensions exactes de la première page originale
                original_pdf = fitz.open(pdf_path)
                first_page = original_pdf[0]
                page_rect = first_page.rect  # Récupère les dimensions de la page en points (72 DPI)
                page_width_pt = page_rect.width
                page_height_pt = page_rect.height
                original_pdf.close()
                
                logging.info(f"Dimensions de la première page originale : {page_width_pt}x{page_height_pt} points")
                
                # Traiter uniquement la première page
                page_args = [(1, pdf_path, stamp_path, index, prefix)]

                # Traiter la première page
                first_page_result = self._process_single_page(page_args[0])
                stamped_image_paths = [first_page_result[1]]
                coordinates = [first_page_result[2]]

                # Créer un PDF avec la première page tamponnée en préservant les dimensions exactes
                # Utiliser PyMuPDF directement pour garantir les mêmes dimensions
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                    stamped_first_page_path = tmp_file.name
                    try:
                        logging.info(f"Création du PDF avec la première page tamponnée (dimensions: {page_width_pt}x{page_height_pt} points)")
                        
                        # Charger l'image tamponnée
                        stamped_image = Image.open(stamped_image_paths[0])
                        
                        # Créer un nouveau PDF avec PyMuPDF en utilisant les dimensions exactes de la page originale
                        new_pdf = fitz.open()
                        # Créer une page avec les dimensions exactes de l'originale
                        new_page = new_pdf.new_page(width=page_width_pt, height=page_height_pt)
                        
                        # Convertir l'image en bytes pour l'insérer dans le PDF
                        img_bytes = io.BytesIO()
                        stamped_image.save(img_bytes, format='PNG')
                        img_bytes.seek(0)
                        
                        # Insérer l'image dans la page en la redimensionnant pour correspondre exactement aux dimensions de la page
                        # rect définit la zone où l'image sera placée (toute la page)
                        rect = fitz.Rect(0, 0, page_width_pt, page_height_pt)
                        new_page.insert_image(rect, stream=img_bytes.getvalue())
                        
                        # Sauvegarder le PDF
                        new_pdf.save(stamped_first_page_path)
                        new_pdf.close()
                        
                        logging.info(f"Première page tamponnée créée avec succès avec dimensions préservées ({page_width_pt}x{page_height_pt} points)")
                    except Exception as e:
                        logging.error(f"Erreur lors de la création du PDF de la première page : {e}")
                        raise

                # Fusionner avec le reste du PDF original
                if num_pages > 1:
                    logging.info(f"Fusion de la première page tamponnée avec les {num_pages - 1} pages restantes")
                    output_path = self._merge_first_page_with_rest(stamped_first_page_path, pdf_path, num_pages)
                else:
                    output_path = stamped_first_page_path

                # Nettoyage des fichiers temporaires
                for path in stamped_image_paths:
                    os.remove(path)
                if num_pages > 1 and stamped_first_page_path != output_path:
                    os.remove(stamped_first_page_path)

                return output_path, coordinates

            # Optimisation adaptative basée sur le nombre de pages
            # DPI réduit pour meilleure performance sans sacrifier trop la qualité
            cpu_count = multiprocessing.cpu_count()
            if num_pages > 300:
                # Gros fichier : plus de workers, DPI faible pour performance
                # Limiter à 2x le nombre de CPU pour éviter la surcharge sur serveurs limités
                adaptive_workers = min(16, max(2, cpu_count * 2))
                self.low_dpi = 120  # DPI faible pour performance
                logging.info(f"Gros fichier détecté ({num_pages} pages) - {adaptive_workers} workers, DPI {self.low_dpi}")
            elif num_pages > 100:
                # Fichier moyen : workers moyens, DPI moyen pour équilibre
                adaptive_workers = min(12, max(2, cpu_count * 2))
                self.low_dpi = 150  # DPI moyen pour équilibre qualité/performance
                logging.info(f"Fichier moyen détecté ({num_pages} pages) - {adaptive_workers} workers, DPI {self.low_dpi}")
            elif num_pages > 20:
                # Fichier petit-moyen : workers moyens, DPI correct
                adaptive_workers = min(8, max(2, cpu_count))
                self.low_dpi = 150  # DPI correct (réduit de 250)
                logging.info(f"Fichier petit-moyen détecté ({num_pages} pages) - {adaptive_workers} workers, DPI {self.low_dpi}")
            else:
                # Petit fichier : moins de workers, DPI bon pour qualité
                adaptive_workers = min(6, max(2, cpu_count))
                self.low_dpi = 200  # DPI bon pour qualité (réduit de 250)
                logging.info(f"Petit fichier détecté ({num_pages} pages) - {adaptive_workers} workers, DPI {self.low_dpi}")

            # Préparation des arguments pour le traitement parallèle
            page_args = [(i+1, pdf_path, stamp_path, index, prefix)
                        for i in range(num_pages)]

            # Traitement parallèle des pages avec workers adaptatifs
            with ThreadPoolExecutor(max_workers=adaptive_workers) as executor:
                results = list(executor.map(self._process_single_page, page_args))

            # Tri des résultats par numéro de page
            results.sort(key=lambda x: x[0])

            stamped_image_paths = [r[1] for r in results]
            coordinates = [r[2] for r in results]


            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                output_path = tmp_file.name
                try:
                    logging.info(f"Début de la conversion en PDF avec {len(stamped_image_paths)} images.")
                    for i, img_path in enumerate(stamped_image_paths):
                        logging.info(f"Image à convertir {i+1}/{len(stamped_image_paths)} : {img_path} (taille : {os.path.getsize(img_path)} octets)")
                    with open(output_path, "wb") as f:
                        # Options de compression optimisées pour img2pdf
                        f.write(img2pdf.convert(stamped_image_paths))
                    logging.info(f"Conversion en PDF terminée avec succès. Fichier : {output_path}")
                except Exception as e:
                    logging.error(f"Erreur lors de la conversion des images en PDF : {e}")
                    raise

            # Nettoyage des fichiers temporaires
            for path in stamped_image_paths:
                os.remove(path)

            return output_path, coordinates

        except Exception as e:
            logging.error(f"Erreur lors de la conversion du PDF en images : {str(e)}")
            raise ValueError(f"Erreur lors de la conversion du PDF en images : {str(e)}")

    # def process_document(self, pdf_path, stamp_path, index=1, prefix=""):
    #     """
    #     Traite le document avec une meilleure résolution et un prétraitement amélioré.
    #     """
    #     # Utiliser une résolution plus élevée pour une meilleure détection
    #     self.low_dpi = 300  # Augmentation significative de la résolution

    #     pages_low = convert_from_path(pdf_path, self.low_dpi)
    #     coordinates_low = []

    #     for page in pages_low:
    #         # Conversion en niveaux de gris
    #         gray_image = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2GRAY)

    #         # Amélioration du contraste
    #         gray_image = cv2.normalize(gray_image, None, alpha=0, beta=255, norm_type=cv2.NORM_MINMAX)

    #         # Réduction du bruit
    #         gray_image = cv2.medianBlur(gray_image, 3)

    #         coords = self.find_whitest_space(gray_image)
    #         coordinates_low.append(coords)

    #     # Conversion des coordonnées
    #     scale_factor = self.high_dpi / self.low_dpi
    #     coordinates_high = []
    #     for coord in coordinates_low:
    #         coord_high = {
    #             "x": coord["x"] * scale_factor,
    #             "y": coord["y"] * scale_factor,
    #             "size": coord["size"] * scale_factor
    #         }
    #         coordinates_high.append(coord_high)

    #     with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
    #         output_path = tmp_file.name

    #     stamped_pdf_path = self.add_stamp(pdf_path, stamp_path, coordinates_high, output_path, index, prefix)
    #     return stamped_pdf_path, coordinates_high


class PDFServicer(pdf_service_pb2_grpc.PDFServiceServicer):
    def __init__(self):
        # Configuration optimisée - debug désactivé par défaut en production pour meilleures performances
        # Le debug peut être activé via la variable d'environnement ENABLE_DEBUG=true
        # IMPORTANT: En production, forcer à False pour éviter la génération d'images debug gourmandes
        enable_debug = os.getenv('ENABLE_DEBUG', 'false').lower() == 'true'
        # Taille fixe : max 300px, min 200px - priorité à la zone la plus grande possible
        self.processor = PDFProcessor(stamp_size_max=300, stamp_size_min=200, enable_debug=False, low_dpi=200)

    def ProcessPDF(self, request, context):
        #TODO : ADD AUTHORISATION VERIFICATION BEARER TOKEN FROM CONTEXT
        pdf_path = None
        stamp_path = None
        processed_pdf_path = None

        try:
            # Télécharger le PDF source
            pdf_buffer = None

            print(request)

            if request.googleDriveFile and request.googleDriveFile.id and request.googleDriveFile.accessToken:
                pdf_buffer = self.processor.download_from_gdrive(request.googleDriveFile.id, request.googleDriveFile.accessToken)
            elif request.ooDriveFile and request.ooDriveFile.id and request.ooDriveFile.accessToken:
                pdf_buffer = self.processor.download_from_oodrive(request.ooDriveFile)
            elif request.pdf_url and request.pdf_url.strip():
                pdf_buffer = self.processor.download_file(request.pdf_url)
            else:
                raise ValueError("Aucun fichier source fourni")

            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as pdf_tmp:
                pdf_tmp.write(pdf_buffer.getvalue())
                pdf_path = pdf_tmp.name

            # Télécharger le tampon
            stamp_buffer = self.processor.download_file(request.stamp_url)
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as stamp_tmp:
                stamp_tmp.write(stamp_buffer.getvalue())
                stamp_path = stamp_tmp.name

            # Traiter le document

            try:
                logging.debug(f"Début Traitement du document")
                # Récupérer le paramètre stampOnlyFirstPage (par défaut False si non spécifié)
                stamp_only_first_page = getattr(request, 'stampOnlyFirstPage', False)
                logging.info(f"Paramètre stampOnlyFirstPage: {stamp_only_first_page}")

                processed_pdf_path, coordinates = self.processor.process_document(
                    pdf_path,
                    stamp_path,
                    request.document_index,
                    request.prefix,
                    stamp_only_first_page
                )
            except Exception as e:
                logging.error(f"Erreur lors du traitement : {str(e)}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(str(e))
                return pdf_service_pb2.PDFResponse()

            # Lire le PDF traité
            with open(processed_pdf_path, 'rb') as f:
                pdf_bytes = f.read()

            # Créer la réponse
            response = pdf_service_pb2.PDFResponse(
                processed_pdf=pdf_bytes,
                coordinates=[
                    pdf_service_pb2.Coordinates(
                        page_number=i+1,
                        x=coord['x'] if coord else -1,
                        y=coord['y'] if coord else -1,
                        size=coord['size'] if coord else 0
                    ) for i, coord in enumerate(coordinates)
                ]
            )

            return response

        except Exception as e:
            logging.error(f"Erreur lors du traitement : {str(e)}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pdf_service_pb2.PDFResponse()

        finally:
            # NETTOYAGE SYSTÉMATIQUE des fichiers temporaires
            # Cela évite l'accumulation de fichiers dans /tmp
            temp_files = [pdf_path, stamp_path, processed_pdf_path]
            for temp_file in temp_files:
                if temp_file and os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        logging.debug(f"Fichier temporaire supprimé : {temp_file}")
                    except Exception as cleanup_error:
                        logging.warning(f"Impossible de supprimer {temp_file} : {cleanup_error}")

            # Forcer le garbage collection pour libérer la mémoire RAM immédiatement
            # Particulièrement important après traitement de gros PDFs
            gc.collect()
            logging.debug("Garbage collection effectué - Mémoire RAM libérée")

def serve():
    """Démarre le serveur gRPC."""
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ('grpc.max_send_message_length', 200 * 1024 * 1024),  # 200MB
            ('grpc.max_receive_message_length', 200 * 1024 * 1024),  # 200MB
        ]
    )
    pdf_service_pb2_grpc.add_PDFServiceServicer_to_server(
        PDFServicer(), server)
    server.add_insecure_port('[::]:50051')
    server.start()
    print("Serveur démarré sur le port 50051")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
