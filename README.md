# Stampwise

<p align="center">
  <img src="https://img.shields.io/npm/v/stampwise?style=flat-square" alt="npm version" />
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="license" />
  <img src="https://img.shields.io/badge/python-3.11+-green?style=flat-square" alt="python" />
  <img src="https://img.shields.io/badge/node-16+-green?style=flat-square" alt="node" />
</p>

<p align="center">
  <b>Service intelligent de tamponnage automatique de documents PDF</b>
</p>

<p align="center">
  Stampwise analyse vos PDF, détecte automatiquement les zones blanches disponibles<br/>
  et place intelligemment vos tampons sans chevaucher le contenu existant.
</p>

---

## Fonctionnalités

- **Détection intelligente** des espaces blancs sur chaque page
- **Évitement automatique** du texte, images, QR codes et tableaux
- **Taille adaptative** du tampon selon l'espace disponible (90-300px)
- **Numérotation** automatique des pièces (ex: "Pièce n° DOC-1")
- **Multi-sources** : URL directe, Google Drive, OoDrive
- **API REST** simple avec documentation Swagger
- **SDK TypeScript** pour intégration Node.js
- **Haute performance** : traitement parallèle, optimisé pour les gros fichiers

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Votre Application                   │
│              npm install stampwise                      │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP/REST
┌──────────────────────▼──────────────────────────────────┐
│                  API Gateway (FastAPI)                  │
│                    Port 8000                            │
│              Swagger UI: /docs                          │
└──────────────────────┬──────────────────────────────────┘
                       │ gRPC (interne)
┌──────────────────────▼──────────────────────────────────┐
│               PDF Processor (Python)                    │
│         OpenCV • NumPy • PyMuPDF • Tesseract           │
└─────────────────────────────────────────────────────────┘
```

## Démarrage rapide

### 1. Cloner le repository

```bash
git clone https://github.com/jodrm/stampwise.git
cd stampwise
```

### 2. Lancer les services

```bash
docker-compose up -d
```

Les services démarrent :
- **API REST** : http://localhost:8000
- **Swagger UI** : http://localhost:8000/docs

### 3. Tester l'API

```bash
curl -X POST "http://localhost:8000/stamp" \
  -H "Content-Type: application/json" \
  -d '{
    "pdf_url": "https://example.com/document.pdf",
    "stamp_url": "https://example.com/stamp.png",
    "document_index": 1,
    "prefix": "DOC"
  }' \
  --output stamped.pdf
```

## Utilisation avec le SDK Node.js

### Installation

```bash
npm install stampwise
```

### Exemple

```typescript
import { PdfStampClient } from 'stampwise';
import fs from 'fs';

const client = new PdfStampClient({
  baseUrl: 'http://localhost:8000'
});

// Tamponner un PDF
const result = await client.stamp({
  pdfUrl: 'https://example.com/document.pdf',
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
  prefix: 'PIECE'
});

// Sauvegarder le résultat
fs.writeFileSync('document_tamponne.pdf', result.pdf);

// Afficher les positions des tampons
console.log(`${result.pagesProcessed} pages traitées`);
result.coordinates.forEach((coord) => {
  console.log(`Page ${coord.pageNumber}: tampon à (${coord.x}, ${coord.y}), taille: ${coord.size}px`);
});
```

### Sources supportées

```typescript
// Depuis une URL
await client.stamp({
  pdfUrl: 'https://example.com/doc.pdf',
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1
});

// Depuis Google Drive
await client.stamp({
  googleDrive: {
    fileId: '1abc123...',
    accessToken: 'ya29.a0AfH6...'
  },
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1
});

// Depuis OoDrive
await client.stamp({
  oodrive: {
    fileId: 'file-id',
    accessToken: 'token...'
  },
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1
});

// Première page uniquement
await client.stamp({
  pdfUrl: 'https://example.com/doc.pdf',
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
  stampOnlyFirstPage: true
});
```

## API Reference

### Endpoints

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/health` | État du service |
| `POST` | `/stamp` | Tamponne un PDF et retourne le fichier |
| `POST` | `/stamp/metadata` | Tamponne et retourne uniquement les métadonnées |

### POST /stamp

**Request Body**

```json
{
  "pdf_url": "https://example.com/document.pdf",
  "google_drive": {
    "file_id": "1abc...",
    "access_token": "ya29..."
  },
  "oodrive": {
    "file_id": "...",
    "access_token": "..."
  },
  "stamp_url": "https://example.com/stamp.png",
  "document_index": 1,
  "prefix": "DOC",
  "stamp_only_first_page": false
}
```

| Champ | Type | Requis | Description |
|-------|------|--------|-------------|
| `pdf_url` | string | * | URL du PDF source |
| `google_drive` | object | * | Source Google Drive |
| `oodrive` | object | * | Source OoDrive |
| `stamp_url` | string | ✓ | URL de l'image du tampon (PNG) |
| `document_index` | integer | | Numéro de la pièce (défaut: 1) |
| `prefix` | string | | Préfixe de numérotation |
| `stamp_only_first_page` | boolean | | Tamponner uniquement la 1ère page |

\* Au moins une source PDF requise

**Response**

- `200 OK` : PDF tamponné (application/pdf)
- Headers :
  - `X-Stamp-Coordinates` : JSON des positions
  - `X-Pages-Processed` : Nombre de pages

## Configuration

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `GRPC_HOST` | Host du service gRPC | `localhost` |
| `GRPC_PORT` | Port du service gRPC | `50051` |
| `JWT_KEY` | Clé secrète JWT | - |
| `ENABLE_DEBUG` | Active les images de debug | `false` |
| `OMP_NUM_THREADS` | Threads OpenCV | `4` |

### Ressources Docker

```yaml
# docker-compose.yml
services:
  pdf-processor:
    cpus: '8'
    mem_limit: 16g
    mem_reservation: 8g
```

Ajustez selon votre serveur. Recommandations :
- **Petits fichiers** (<20 pages) : 2 CPU, 4GB RAM
- **Fichiers moyens** (20-100 pages) : 4 CPU, 8GB RAM
- **Gros fichiers** (>100 pages) : 8 CPU, 16GB RAM

## Mode Debug

Pour visualiser où l'algorithme place les tampons :

```bash
# Activer le debug
ENABLE_DEBUG=true docker-compose up -d

# Les images sont sauvegardées dans ./debug/
ls debug/
# debug_page_001.png
# debug_page_002.png
# ...
```

Les images montrent :
- 🔴 **Rouge** : Zones de texte détectées
- 🔵 **Bleu** : Images détectées
- 🟣 **Magenta** : QR codes détectés
- 🟢 **Vert** : Position du tampon

## Algorithme de détection

Stampwise utilise plusieurs techniques pour trouver l'emplacement optimal :

1. **Détection du texte** : Analyse morphologique OpenCV + OCR optionnel (Tesseract)
2. **Détection des images** : Analyse du Laplacien pour les zones à forte variation
3. **Détection des QR codes** : Recherche de contours carrés avec variance élevée
4. **Détection des lignes** : Traits de séparation horizontaux/verticaux
5. **Recherche de zone** : Balayage adaptatif pour trouver une zone 95-98% blanche

L'algorithme priorise :
1. Zone totalement libre de taille maximale (300px)
2. Zone libre de taille réduite (jusqu'à 90px minimum)
3. Coins de la page (haut-droite, haut-gauche, etc.)
4. Position de secours avec chevauchement minimal (<10%)

## Développement

### Structure du projet

```
stampwise/
├── server.py              # Service gRPC principal
├── api_gateway.py         # Gateway FastAPI
├── jwt_service.py         # Authentification JWT
├── docker-compose.yml     # Orchestration Docker
├── Dockerfile             # Image du processor
├── Dockerfile.gateway     # Image du gateway
├── protos/
│   └── pdf_service.proto  # Définition gRPC
├── packages/
│   └── client-node/       # SDK TypeScript
│       ├── src/index.ts
│       └── package.json
└── fonts/                 # Polices pour le texte
```

### Lancer en développement

```bash
# Service Python seul
pip install -r requirements.txt
python server.py

# Gateway seul
pip install -r requirements-gateway.txt
uvicorn api_gateway:app --reload --port 8000

# SDK Node.js
cd packages/client-node
npm install
npm run build
```

### Tests

```bash
# Tester l'API
curl http://localhost:8000/health

# Tester avec un PDF
curl -X POST "http://localhost:8000/stamp" \
  -H "Content-Type: application/json" \
  -d '{"pdf_url": "...", "stamp_url": "..."}' \
  --output test.pdf
```

## Contribuer

Les contributions sont les bienvenues !

1. Fork le projet
2. Créez votre branche (`git checkout -b feature/amazing-feature`)
3. Committez vos changements (`git commit -m 'Add amazing feature'`)
4. Push sur la branche (`git push origin feature/amazing-feature`)
5. Ouvrez une Pull Request

## License

MIT - voir [LICENSE](LICENSE) pour plus de détails.

## Support

- **Issues** : [GitHub Issues](https://github.com/jodrm/stampwise/issues)
- **Discussions** : [GitHub Discussions](https://github.com/jodrm/stampwise/discussions)

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/jodrm">jodrm</a>
</p>
