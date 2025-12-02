# stampwise

<p align="center">
  <img src="https://img.shields.io/npm/v/stampwise?style=flat-square" alt="npm version" />
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="license" />
  <img src="https://img.shields.io/badge/node-16+-green?style=flat-square" alt="node" />
  <img src="https://img.shields.io/badge/python-3.8+-blue?style=flat-square" alt="python" />
</p>

<p align="center">
  <b>Tamponnage intelligent et automatique de documents PDF</b>
</p>

<p align="center">
  Stampwise analyse vos PDF, détecte les zones blanches disponibles<br/>
  et place intelligemment vos tampons sans chevaucher le contenu existant.
</p>

---

## Fonctionnalités

- **100% autonome** - Pas de serveur externe requis
- **Détection intelligente** des espaces blancs sur chaque page
- **Évitement automatique** du texte, images, QR codes et tableaux
- **Taille adaptative** du tampon selon l'espace disponible
- **Numérotation** automatique des pièces (ex: "Pièce n° DOC-1")
- **Multi-plateforme** - macOS, Linux, Windows

## Prérequis

- **Node.js** 16+
- **Python** 3.8+
- **Poppler** (pour pdf2image)

### Installation de Poppler

```bash
# macOS
brew install poppler

# Ubuntu/Debian
sudo apt-get install poppler-utils

# Windows
# Télécharger depuis: https://github.com/oschwartz10612/poppler-windows/releases
```

## Installation

```bash
npm install stampwise
```

Les dépendances Python sont installées automatiquement lors du `npm install`.

## Utilisation

### API simple

```typescript
import { stampPdf } from 'stampwise';

const result = await stampPdf({
  pdfPath: './document.pdf',
  stampPath: './stamp.png',
  outputPath: './output.pdf',
  documentIndex: 1,
  prefix: 'DOC'
});

console.log(`PDF généré: ${result.outputPath}`);
console.log(`${result.pagesProcessed} pages traitées`);
```

### API complète

```typescript
import { Stampwise } from 'stampwise';

const stampwise = new Stampwise({
  pythonPath: '/usr/bin/python3',  // Optionnel
  fontsDir: './fonts'               // Optionnel
});

const result = await stampwise.stamp({
  pdfPath: './facture.pdf',
  stampPath: './tampon.png',
  outputPath: './facture_tamponnee.pdf',
  documentIndex: 1,
  prefix: 'PIECE',
  stampOnlyFirstPage: false
});

// Afficher les positions des tampons
result.coordinates.forEach((coord) => {
  console.log(`Page ${coord.pageNumber}: tampon à (${coord.x}, ${coord.y}), taille: ${coord.size}px`);
});
```

### Avec des Buffers

```typescript
import { Stampwise } from 'stampwise';
import fs from 'fs';

const stampwise = new Stampwise();

const pdfBuffer = fs.readFileSync('./document.pdf');
const stampBuffer = fs.readFileSync('./stamp.png');

const result = await stampwise.stampBuffer(pdfBuffer, stampBuffer, {
  documentIndex: 1,
  prefix: 'DOC'
});

// result.pdf est un Buffer
fs.writeFileSync('./output.pdf', result.pdf);
```

## API Reference

### `stampPdf(options)`

Fonction raccourcie pour tamponner un PDF.

### `Stampwise`

Classe principale avec configuration avancée.

#### Constructor

```typescript
new Stampwise(config?: StampwiseConfig)
```

| Option | Type | Description |
|--------|------|-------------|
| `pythonPath` | `string` | Chemin vers Python (défaut: auto-détecté) |
| `fontsDir` | `string` | Répertoire des polices personnalisées |

#### `stamp(options): Promise<StampResult>`

Tamponne un PDF.

| Option | Type | Requis | Description |
|--------|------|--------|-------------|
| `pdfPath` | `string` | ✓ | Chemin du PDF source |
| `stampPath` | `string` | ✓ | Chemin de l'image du tampon |
| `outputPath` | `string` | ✓ | Chemin du PDF de sortie |
| `documentIndex` | `number` | | Numéro de pièce (défaut: 1) |
| `prefix` | `string` | | Préfixe (ex: "DOC") |
| `stampOnlyFirstPage` | `boolean` | | Tamponner uniquement la 1ère page |

#### `stampBuffer(pdfBuffer, stampBuffer, options)`

Tamponne un PDF depuis des Buffers.

### Types

```typescript
interface StampResult {
  success: boolean;
  outputPath: string;
  coordinates: StampCoordinates[];
  pagesProcessed: number;
}

interface StampCoordinates {
  pageNumber: number;
  x: number;
  y: number;
  size: number;
}
```

## Algorithme

Stampwise utilise OpenCV et des techniques de vision par ordinateur pour :

1. **Détecter le texte** via analyse morphologique
2. **Détecter les images** via analyse du Laplacien
3. **Détecter les lignes** de séparation et tableaux
4. **Trouver une zone blanche** optimale (95%+ blanc)
5. **Adapter la taille** du tampon à l'espace disponible (90-300px)

## Dépannage

### Python non trouvé

```bash
# Vérifier l'installation
python3 --version

# Si Python n'est pas dans le PATH, spécifiez le chemin:
const stampwise = new Stampwise({
  pythonPath: '/chemin/vers/python3'
});
```

### Poppler non trouvé

```
Error: Unable to get page count. Is poppler installed?
```

Installez Poppler (voir section Prérequis).

### Dépendances Python manquantes

```bash
# Installation manuelle
pip3 install PyMuPDF numpy opencv-python-headless pdf2image Pillow img2pdf
```

## License

MIT - voir [LICENSE](https://github.com/jodrm/stampwise/blob/main/LICENSE)

## Liens

- [GitHub](https://github.com/jodrm/stampwise)
- [Issues](https://github.com/jodrm/stampwise/issues)
- [npm](https://www.npmjs.com/package/stampwise)
