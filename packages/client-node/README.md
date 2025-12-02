# stampwise

<p align="center">
  <img src="https://img.shields.io/npm/v/stampwise?style=flat-square" alt="npm version" />
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="license" />
  <img src="https://img.shields.io/badge/typescript-5.0+-blue?style=flat-square" alt="typescript" />
</p>

<p align="center">
  <b>SDK TypeScript pour le service de tamponnage automatique de PDF</b>
</p>

---

## Installation

```bash
npm install stampwise
# ou
yarn add stampwise
# ou
pnpm add stampwise
```

## Quick Start

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
  prefix: 'DOC'
});

// Sauvegarder le résultat
fs.writeFileSync('stamped.pdf', result.pdf);
console.log(`${result.pagesProcessed} pages traitées`);
```

## Configuration

```typescript
const client = new PdfStampClient({
  baseUrl: 'http://localhost:8000', // URL du service Stampwise
  timeout: 300000,                   // Timeout en ms (défaut: 5 min)
  headers: {                         // Headers personnalisés
    'Authorization': 'Bearer token'
  }
});
```

## API

### `stamp(options): Promise<StampResult>`

Tamponne un PDF et retourne le fichier résultant.

```typescript
interface StampOptions {
  pdfUrl?: string;                    // URL du PDF
  googleDrive?: {                     // Source Google Drive
    fileId: string;
    accessToken: string;
  };
  oodrive?: {                         // Source OoDrive
    fileId: string;
    accessToken: string;
  };
  stampUrl: string;                   // URL de l'image du tampon (PNG)
  documentIndex?: number;             // Numéro de pièce (défaut: 1)
  prefix?: string;                    // Préfixe (ex: "DOC")
  stampOnlyFirstPage?: boolean;       // Tamponner uniquement page 1
}

interface StampResult {
  pdf: Buffer;                        // PDF tamponné
  coordinates: StampCoordinates[];    // Positions des tampons
  pagesProcessed: number;             // Nombre de pages
}
```

### `stampMetadata(options): Promise<StampMetadataResult>`

Tamponne et retourne uniquement les métadonnées (sans le PDF).

```typescript
const metadata = await client.stampMetadata({
  pdfUrl: 'https://example.com/doc.pdf',
  stampUrl: 'https://example.com/stamp.png'
});

console.log(metadata.coordinates);
// [{pageNumber: 1, x: 450, y: 50, size: 300}, ...]
```

### `health(): Promise<HealthStatus>`

Vérifie l'état du service.

```typescript
const status = await client.health();
console.log(status.grpcService); // "connected"
```

## Exemples

### Depuis Google Drive

```typescript
const result = await client.stamp({
  googleDrive: {
    fileId: '1abc123...',
    accessToken: 'ya29.a0AfH6...'
  },
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
  prefix: 'PIECE'
});
```

### Première page uniquement

```typescript
const result = await client.stamp({
  pdfUrl: 'https://example.com/document.pdf',
  stampUrl: 'https://example.com/stamp.png',
  stampOnlyFirstPage: true
});
```

### Gestion des erreurs

```typescript
try {
  const result = await client.stamp({...});
} catch (error) {
  if (error.response?.status === 400) {
    console.error('Requête invalide:', error.response.data);
  } else if (error.response?.status === 500) {
    console.error('Erreur serveur:', error.response.data);
  } else {
    console.error('Erreur réseau:', error.message);
  }
}
```

## Prérequis

Ce SDK nécessite le service Stampwise en cours d'exécution :

```bash
# Cloner et lancer le service
git clone https://github.com/jodrm/stampwise.git
cd stampwise
docker-compose up -d

# Le service est disponible sur http://localhost:8000
```

## Documentation complète

Voir le [repository principal](https://github.com/jodrm/stampwise) pour :
- Documentation de l'API REST
- Configuration avancée
- Mode debug
- Algorithme de détection

## License

MIT - voir [LICENSE](https://github.com/jodrm/stampwise/blob/main/LICENSE)
