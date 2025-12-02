# Stampwise

<p align="center">
  <img src="https://img.shields.io/npm/v/stampwise?style=flat-square" alt="npm version" />
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="license" />
  <img src="https://img.shields.io/badge/python-3.8+-green?style=flat-square" alt="python" />
  <img src="https://img.shields.io/badge/node-16+-green?style=flat-square" alt="node" />
</p>

<p align="center">
  <b>Tamponnage intelligent et automatique de documents PDF</b>
</p>

<p align="center">
  Stampwise analyse vos PDF, détecte automatiquement les zones blanches disponibles<br/>
  et place intelligemment vos tampons sans chevaucher le contenu existant.
</p>

---

## Fonctionnalités

- **100% autonome** - Pas de serveur externe requis
- **Détection intelligente** des espaces blancs sur chaque page
- **Évitement automatique** du texte, images, QR codes et tableaux
- **Taille adaptative** du tampon selon l'espace disponible (90-300px)
- **Numérotation** automatique des pièces (ex: "Pièce n° DOC-1")
- **Multi-plateforme** - macOS, Linux, Windows
- **Haute performance** - Traitement parallèle optimisé

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Votre Application                   │
│              import { stampPdf } from 'stampwise'       │
└──────────────────────┬──────────────────────────────────┘
                       │ child_process (local)
┌──────────────────────▼──────────────────────────────────┐
│               Python Processor (embarqué)               │
│         OpenCV • NumPy • PyMuPDF • pdf2image           │
└─────────────────────────────────────────────────────────┘
```

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

Les dépendances Python sont installées automatiquement.

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

### Première page uniquement

```typescript
const result = await stampPdf({
  pdfPath: './document.pdf',
  stampPath: './stamp.png',
  outputPath: './output.pdf',
  documentIndex: 1,
  stampOnlyFirstPage: true  // Seule la 1ère page sera tamponnée
});
```

## API Reference

### `stampPdf(options): Promise<StampResult>`

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

| Option | Type | Requis | Description |
|--------|------|--------|-------------|
| `pdfPath` | `string` | ✓ | Chemin du PDF source |
| `stampPath` | `string` | ✓ | Chemin de l'image du tampon (PNG) |
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

## Algorithme de détection

Stampwise utilise OpenCV et des techniques de vision par ordinateur :

1. **Détection du texte** - Analyse morphologique (kernels horizontaux/verticaux)
2. **Détection des images** - Analyse du Laplacien pour les zones à forte variation
3. **Détection des QR codes** - Recherche de contours carrés avec variance élevée
4. **Détection des lignes** - Traits de séparation horizontaux/verticaux
5. **Recherche de zone** - Balayage adaptatif pour trouver une zone 95-98% blanche

L'algorithme priorise :
1. Zone totalement libre de taille maximale (300px)
2. Zone libre de taille réduite (jusqu'à 90px minimum)
3. Coins de la page (haut-droite, haut-gauche, etc.)
4. Position de secours avec chevauchement minimal (<10%)

## Développement

### Structure du projet

```
stampwise/
├── packages/
│   └── client-node/           # SDK NPM
│       ├── src/index.ts       # SDK TypeScript
│       ├── python/
│       │   ├── processor.py   # Moteur de traitement
│       │   └── requirements.txt
│       └── scripts/
│           └── postinstall.js # Installation auto
├── server.py                  # Service gRPC (optionnel)
├── api_gateway.py             # API REST (optionnel)
├── docker-compose.yml         # Déploiement Docker
└── fonts/                     # Polices pour le texte
```

### Setup local

```bash
# Cloner le repo
git clone https://github.com/jodrm/stampwise.git
cd stampwise

# SDK Node.js
cd packages/client-node
npm install
npm run build

# Tester
npm test
```

### Mode Docker (optionnel)

Pour déployer comme service REST :

```bash
docker-compose up -d
# API disponible sur http://localhost:8000
# Swagger UI sur http://localhost:8000/docs
```

## Dépannage

### Python non trouvé

```bash
# Vérifier l'installation
python3 --version

# Spécifier le chemin manuellement
const stampwise = new Stampwise({
  pythonPath: '/chemin/vers/python3'
});
```

### Poppler non trouvé

```
Error: Unable to get page count. Is poppler installed?
```

Voir section [Installation de Poppler](#installation-de-poppler).

### Dépendances Python manquantes

```bash
pip3 install PyMuPDF numpy opencv-python-headless pdf2image Pillow img2pdf
```

## Contribuer

Les contributions sont les bienvenues ! Voir [CONTRIBUTING.md](CONTRIBUTING.md).

1. Fork le projet
2. Créez votre branche (`git checkout -b feature/amazing-feature`)
3. Committez vos changements (`git commit -m 'feat: add amazing feature'`)
4. Push sur la branche (`git push origin feature/amazing-feature`)
5. Ouvrez une Pull Request

## License

MIT - voir [LICENSE](LICENSE) pour plus de détails.

## Liens

- [npm](https://www.npmjs.com/package/stampwise)
- [GitHub](https://github.com/jodrm/stampwise)
- [Issues](https://github.com/jodrm/stampwise/issues)

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/jodrm">jodrm</a>
</p>
