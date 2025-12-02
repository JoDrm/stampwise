# Mode Debug - Détection des problèmes de placement de tampon

## Activation

Le mode debug est maintenant **activé par défaut**. Les images de debug sont sauvegardées dans le dossier `/app/debug/` (ou `./debug/` en local).

## Visualisation des images de debug

Chaque page traitée génère une image de debug nommée `debug_page_XXX.png` qui montre :

### Couleurs utilisées

- **🔴 Rouge** : Zones de texte détectées (interdites)
- **🔵 Bleu** : Zones d'images détectées (interdites)
- **🟣 Magenta** : Zones de QR codes détectées (interdites)
- **🟢 Vert** : Position choisie pour le tampon
  - Rectangle fin : Zone de recherche (300x300px avec marges)
  - Rectangle épais : Position réelle du tampon (220x220px)

### Informations affichées

L'image de debug affiche également :
- Numéro de page
- Pourcentage de chevauchement total
- Pourcentage de chevauchement par type (Texte, Images, QR Codes)
- Légende des couleurs

## Détection améliorée

L'algorithme détecte maintenant :

1. **Texte** : Via morphologie mathématique (détection horizontale, verticale et petits éléments)
2. **Images** : Via détection de Laplacien (zones avec beaucoup de variations de gris)
3. **QR Codes** : Via détection de contours carrés avec variance élevée

## Logs détaillés

Si un chevauchement est détecté, un log d'avertissement est généré :

```
WARNING: Page X: Chevauchement detecte! Total: Y% | Texte: Z% | Images: W% | QR: V%
```

## Désactiver le debug

Pour désactiver le mode debug, modifier dans `PDFServicer.__init__()` :

```python
self.processor = PDFProcessor(stamp_size=300, enable_debug=False, low_dpi=200)
```

## Accéder aux images de debug

### En local
Les images sont sauvegardées dans `./debug/debug_page_XXX.png`

### Dans Docker
Les images sont dans `/app/debug/` du conteneur. Pour les récupérer :

```bash
docker cp <container_id>:/app/debug ./debug
```

## Analyse des problèmes

Si le tampon chevauche du contenu :

1. Vérifier l'image de debug correspondante
2. Identifier le type de contenu chevauché (texte/image/QR code)
3. Vérifier si la détection a bien fonctionné (zones colorées)
4. Si la détection a échoué, ajuster les paramètres de détection dans `find_whitest_space()`

## Paramètres ajustables

Dans `find_whitest_space()` :

- `min_image_area` (ligne ~215) : Surface minimale pour détecter une image (défaut: 5000)
- `qr_dilate_kernel` (ligne ~260) : Taille du kernel de dilatation pour QR codes (défaut: 80x80)
- `image_dilate_kernel` (ligne ~225) : Taille du kernel de dilatation pour images (défaut: 60x60)
- `dilate_kernel` (ligne ~199) : Taille du kernel de dilatation pour texte (défaut: 50x30)

