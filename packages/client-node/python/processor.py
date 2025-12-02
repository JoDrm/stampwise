#!/usr/bin/env python3
"""
Stampwise PDF Processor - CLI autonome
Traitement local des PDFs sans serveur externe
"""

import sys
import json
import argparse
import tempfile
import os
import logging
from pathlib import Path

# Imports pour le traitement PDF
import fitz  # PyMuPDF
import numpy as np
import cv2
from pdf2image import convert_from_path, pdfinfo_from_path
from PIL import Image, ImageDraw, ImageFont
import img2pdf
from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from functools import lru_cache

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Augmenter la limite PIL pour les grandes images
Image.MAX_IMAGE_PIXELS = 933120000


class PDFProcessor:
    """Processeur PDF autonome pour le tamponnage intelligent"""

    def __init__(self, stamp_size_max=300, stamp_size_min=90, low_dpi=200):
        self.stamp_size_max = stamp_size_max
        self.stamp_size_min = stamp_size_min
        self.low_dpi = low_dpi
        self.margin = 10
        self.max_workers = min(8, multiprocessing.cpu_count())
        self._stamp_cache = {}
        self._kernel_cache = {}

    @lru_cache(maxsize=32)
    def _get_text_detection_kernel(self, size):
        """Cache les kernels pour éviter de les recréer"""
        return cv2.getStructuringElement(cv2.MORPH_RECT, size)

    def find_whitest_space(self, image):
        """
        Trouve le meilleur emplacement pour un tampon en évitant les zones de contenu.
        """
        height, width = image.shape

        stamp_size_max = self.stamp_size_max
        stamp_size_min = self.stamp_size_min

        # Masques pour les différents types de contenu
        forbidden_mask = np.zeros((height, width), dtype=np.uint8)

        # Détection par seuillage
        _, binary = cv2.threshold(image, 220, 255, cv2.THRESH_BINARY)
        inverted = 255 - binary

        # Détection horizontale et verticale
        horizontal_kernel = self._get_text_detection_kernel((30, 1))
        horizontal_lines = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, horizontal_kernel)

        vertical_kernel = self._get_text_detection_kernel((1, 15))
        vertical_lines = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, vertical_kernel)

        small_kernel = self._get_text_detection_kernel((3, 3))
        small_elements = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, small_kernel)

        text_combined = cv2.bitwise_or(horizontal_lines, vertical_lines)
        text_combined = cv2.bitwise_or(text_combined, small_elements)

        dilate_kernel = self._get_text_detection_kernel((30, 15))
        text_mask = cv2.dilate(text_combined, dilate_kernel, iterations=1)
        forbidden_mask = cv2.bitwise_or(forbidden_mask, text_mask)

        # Détection des lignes de séparation
        _, line_binary = cv2.threshold(image, 200, 255, cv2.THRESH_BINARY_INV)

        if width > 100:
            kernel_long = self._get_text_detection_kernel((max(100, width // 3), 1))
            lines_long = cv2.morphologyEx(line_binary, cv2.MORPH_OPEN, kernel_long)
            line_dilate = self._get_text_detection_kernel((1, 15))
            lines_long = cv2.dilate(lines_long, line_dilate, iterations=1)
            forbidden_mask = cv2.bitwise_or(forbidden_mask, lines_long)

        # Détection des images (zones à forte variation)
        blurred = cv2.GaussianBlur(image, (5, 5), 0)
        laplacian = cv2.Laplacian(blurred, cv2.CV_64F)
        laplacian_abs = np.abs(laplacian)
        _, image_detection = cv2.threshold(laplacian_abs.astype(np.uint8), 30, 255, cv2.THRESH_BINARY)

        contours, _ = cv2.findContours(image_detection, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            if cv2.contourArea(contour) > 5000:
                contour_mask = np.zeros((height, width), dtype=np.uint8)
                cv2.fillPoly(contour_mask, [contour], 255)
                image_dilate = self._get_text_detection_kernel((30, 30))
                contour_mask = cv2.dilate(contour_mask, image_dilate, iterations=1)
                forbidden_mask = cv2.bitwise_or(forbidden_mask, contour_mask)

        # Recherche de zone blanche
        _, white_binary = cv2.threshold(image, 245, 255, cv2.THRESH_BINARY)

        min_margin = 5
        min_zone_size = stamp_size_min + 2 * min_margin
        max_zone_size = max(stamp_size_max + 2 * min_margin, 410)

        search_sizes = list(range(max_zone_size, min_zone_size - 1, -5))

        best_position = None
        best_stamp_size = 0

        for square_size in search_sizes:
            if best_stamp_size >= stamp_size_max:
                break

            search_width = width - square_size
            search_height = height - square_size

            if search_width <= 0 or search_height <= 0:
                continue

            step = max(5, square_size // 30) if square_size >= stamp_size_max else max(10, square_size // 20)

            for y in range(0, search_height, step):
                for x in range(0, search_width, step):
                    roi_forbidden = forbidden_mask[y:y + square_size, x:x + square_size]

                    if np.sum(roi_forbidden) == 0:
                        roi_white = white_binary[y:y + square_size, x:x + square_size]
                        white_ratio = np.mean(roi_white) / 255.0

                        if white_ratio > 0.95:
                            available_stamp_size = min(square_size - 2 * min_margin, stamp_size_max)
                            if available_stamp_size >= stamp_size_min:
                                if available_stamp_size >= stamp_size_max:
                                    return {"x": float(x), "y": float(y), "size": float(square_size), "stamp_size": float(available_stamp_size)}
                                if available_stamp_size > best_stamp_size:
                                    best_position = (x, y, square_size, available_stamp_size)
                                    best_stamp_size = available_stamp_size

                    if best_stamp_size >= stamp_size_max:
                        break
                if best_stamp_size >= stamp_size_max:
                    break

        if best_position:
            x, y, sq_size, st_size = best_position
            return {"x": float(x), "y": float(y), "size": float(sq_size), "stamp_size": float(st_size)}

        # Fallback: coins de la page
        corners = [
            (width - stamp_size_min - 40, 20),
            (20, 20),
            (width - stamp_size_min - 40, height - stamp_size_min - 40),
            (20, height - stamp_size_min - 40),
        ]

        for cx, cy in corners:
            if 0 <= cx < width - stamp_size_min and 0 <= cy < height - stamp_size_min:
                return {"x": float(cx), "y": float(cy), "size": float(stamp_size_min + 20), "stamp_size": float(stamp_size_min)}

        # Dernier recours
        return {"x": float(width - stamp_size_min - 40), "y": 20.0, "size": float(stamp_size_min + 20), "stamp_size": float(stamp_size_min)}

    def _process_single_page(self, args):
        """Traite une seule page"""
        page_num, pdf_path, stamp_path, index, prefix, fonts_dir = args

        try:
            page_img = convert_from_path(pdf_path, dpi=self.low_dpi, first_page=page_num, last_page=page_num)[0]
            gray_image = cv2.cvtColor(np.array(page_img), cv2.COLOR_RGB2GRAY)

            coords = self.find_whitest_space(gray_image)

            if coords and coords.get("x", -1) >= 0:
                page_img = page_img.convert("RGBA")
                x = int(coords['x'])
                y = int(coords['y'])
                stamp_size = int(coords.get("stamp_size", self.stamp_size_max))
                zone_size = int(coords.get("size", stamp_size))
                margin = (zone_size - stamp_size) // 2

                # Charger et redimensionner le tampon
                cache_key = (stamp_path, stamp_size)
                if cache_key not in self._stamp_cache:
                    stamp_img = Image.open(stamp_path).convert("RGBA")
                    self._stamp_cache[cache_key] = stamp_img.resize((stamp_size, stamp_size), Image.Resampling.LANCZOS)

                stamp_img = self._stamp_cache[cache_key].copy()
                page_img.paste(stamp_img, (x + margin, y + margin), stamp_img)

                # Ajouter le texte
                draw = ImageDraw.Draw(page_img)
                font_size = int(stamp_size * 0.12)

                font = None
                if fonts_dir:
                    font_path = os.path.join(fonts_dir, "OpenSans-regular.ttf")
                    if os.path.exists(font_path):
                        try:
                            font = ImageFont.truetype(font_path, font_size)
                        except Exception:
                            pass

                if font is None:
                    try:
                        font = ImageFont.load_default()
                    except Exception:
                        font = None

                if font:
                    text_line1 = "Pièce n°"
                    text_line2 = f"{prefix}-{index}" if prefix else str(index)

                    center_x = x + margin + stamp_size // 2
                    center_y = y + margin + stamp_size // 2

                    try:
                        bbox1 = draw.textbbox((0, 0), text_line1, font=font)
                        text_width1 = bbox1[2] - bbox1[0]
                        text_height1 = bbox1[3] - bbox1[1]
                        bbox2 = draw.textbbox((0, 0), text_line2, font=font)
                        text_width2 = bbox2[2] - bbox2[0]
                    except AttributeError:
                        text_width1, text_height1 = font.getsize(text_line1)
                        text_width2, _ = font.getsize(text_line2)

                    draw.text((center_x - text_width1/2, center_y - text_height1 - 10), text_line1, fill="black", font=font)
                    draw.text((center_x - text_width2/2, center_y + 10), text_line2, fill="black", font=font)

            # Sauvegarder en PNG
            temp_img = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            page_img.convert("RGB").save(temp_img, format='PNG', compress_level=9)
            temp_img.close()

            return page_num, temp_img.name, coords

        except Exception as e:
            logger.error(f"Erreur traitement page {page_num}: {e}")
            raise

    def process_document(self, pdf_path, stamp_path, index=1, prefix="", stamp_only_first_page=False, fonts_dir=None):
        """Traite le document PDF"""
        try:
            info = pdfinfo_from_path(pdf_path)
            num_pages = info['Pages']

            pages_to_process = 1 if stamp_only_first_page else num_pages

            # Adaptation du DPI selon la taille
            if num_pages > 100:
                self.low_dpi = 150
            elif num_pages > 20:
                self.low_dpi = 180

            page_args = [(i+1, pdf_path, stamp_path, index, prefix, fonts_dir) for i in range(pages_to_process)]

            # Traitement parallèle
            workers = min(self.max_workers, pages_to_process)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                results = list(executor.map(self._process_single_page, page_args))

            results.sort(key=lambda x: x[0])
            stamped_image_paths = [r[1] for r in results]
            coordinates = [r[2] for r in results]

            # Créer le PDF final
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                output_path = tmp_file.name

            if stamp_only_first_page and num_pages > 1:
                # Fusionner première page tamponnée avec le reste
                with open(output_path, "wb") as f:
                    f.write(img2pdf.convert(stamped_image_paths))

                # Charger et fusionner
                stamped_pdf = fitz.open(output_path)
                original_pdf = fitz.open(pdf_path)

                final_pdf = fitz.open()
                final_pdf.insert_pdf(stamped_pdf, from_page=0, to_page=0)
                if num_pages > 1:
                    final_pdf.insert_pdf(original_pdf, from_page=1, to_page=num_pages-1)

                final_output = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False).name
                final_pdf.save(final_output)

                stamped_pdf.close()
                original_pdf.close()
                final_pdf.close()
                os.remove(output_path)
                output_path = final_output
            else:
                with open(output_path, "wb") as f:
                    f.write(img2pdf.convert(stamped_image_paths))

            # Nettoyage
            for path in stamped_image_paths:
                if os.path.exists(path):
                    os.remove(path)

            return output_path, coordinates

        except Exception as e:
            logger.error(f"Erreur traitement document: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(description='Stampwise PDF Processor')
    parser.add_argument('--pdf', required=True, help='Chemin du PDF à traiter')
    parser.add_argument('--stamp', required=True, help='Chemin de l\'image du tampon')
    parser.add_argument('--output', required=True, help='Chemin du PDF de sortie')
    parser.add_argument('--index', type=int, default=1, help='Numéro de la pièce')
    parser.add_argument('--prefix', default='', help='Préfixe de numérotation')
    parser.add_argument('--first-page-only', action='store_true', help='Tamponner uniquement la première page')
    parser.add_argument('--fonts-dir', help='Répertoire des polices')
    parser.add_argument('--json', action='store_true', help='Sortie JSON')

    args = parser.parse_args()

    # Vérifications
    if not os.path.exists(args.pdf):
        print(json.dumps({"success": False, "error": f"PDF non trouvé: {args.pdf}"}))
        sys.exit(1)

    if not os.path.exists(args.stamp):
        print(json.dumps({"success": False, "error": f"Tampon non trouvé: {args.stamp}"}))
        sys.exit(1)

    try:
        processor = PDFProcessor()
        output_path, coordinates = processor.process_document(
            args.pdf,
            args.stamp,
            args.index,
            args.prefix,
            args.first_page_only,
            args.fonts_dir
        )

        # Copier vers la destination finale
        if output_path != args.output:
            import shutil
            shutil.move(output_path, args.output)

        result = {
            "success": True,
            "output": args.output,
            "coordinates": [
                {
                    "pageNumber": i + 1,
                    "x": coord["x"] if coord else -1,
                    "y": coord["y"] if coord else -1,
                    "size": coord.get("stamp_size", coord.get("size", 0)) if coord else 0
                }
                for i, coord in enumerate(coordinates)
            ],
            "pagesProcessed": len(coordinates)
        }

        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
        sys.exit(1)


if __name__ == '__main__':
    main()
