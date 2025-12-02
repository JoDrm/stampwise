# @jodrm/stampwise

Client SDK TypeScript/JavaScript pour le service de tamponnage automatique de PDF.

## Installation

```bash
npm install @jodrm/stampwise
# ou
yarn add @jodrm/stampwise
# ou
pnpm add @jodrm/stampwise
```

## Utilisation

### Configuration

```typescript
import { PdfStampClient } from '@jodrm/stampwise';

const client = new PdfStampClient({
  baseUrl: 'http://localhost:8000', // URL de votre service
  timeout: 300000, // 5 minutes (optionnel)
});
```

### Tamponner un PDF depuis une URL

```typescript
import fs from 'fs';

const result = await client.stamp({
  pdfUrl: 'https://example.com/document.pdf',
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
  prefix: 'DOC',
});

// Sauvegarder le PDF tamponné
fs.writeFileSync('document_tamponne.pdf', result.pdf);

// Voir les positions des tampons
console.log(`${result.pagesProcessed} pages traitées`);
result.coordinates.forEach((coord) => {
  console.log(`Page ${coord.pageNumber}: tampon à (${coord.x}, ${coord.y})`);
});
```

### Tamponner depuis Google Drive

```typescript
const result = await client.stamp({
  googleDrive: {
    fileId: '1abc123...',
    accessToken: 'ya29.a0AfH6...',
  },
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
  prefix: 'PIECE',
});
```

### Tamponner depuis OoDrive

```typescript
const result = await client.stamp({
  oodrive: {
    fileId: 'file-id-123',
    accessToken: 'token...',
  },
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
});
```

### Tamponner uniquement la première page

```typescript
const result = await client.stamp({
  pdfUrl: 'https://example.com/document.pdf',
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
  stampOnlyFirstPage: true, // Seule la 1ère page sera tamponnée
});
```

### Obtenir uniquement les métadonnées

Utile pour vérifier les positions avant de télécharger le PDF complet :

```typescript
const metadata = await client.stampMetadata({
  pdfUrl: 'https://example.com/document.pdf',
  stampUrl: 'https://example.com/stamp.png',
  documentIndex: 1,
});

console.log(metadata.success); // true
console.log(metadata.pagesProcessed); // 10
console.log(metadata.coordinates); // [{pageNumber: 1, x: 450, y: 50, size: 300}, ...]
```

### Vérifier l'état du service

```typescript
const health = await client.health();

console.log(health.status); // "healthy"
console.log(health.grpcService); // "connected"
console.log(health.version); // "1.0.0"
```

## API Reference

### `PdfStampClient`

#### Constructor

```typescript
new PdfStampClient(config: PdfStampConfig)
```

| Option    | Type                       | Description                      |
| --------- | -------------------------- | -------------------------------- |
| `baseUrl` | `string`                   | URL du service PDF Stamp         |
| `timeout` | `number`                   | Timeout en ms (défaut: 300000)   |
| `headers` | `Record<string, string>`   | Headers HTTP personnalisés       |

#### Methods

##### `stamp(options: StampOptions): Promise<StampResult>`

Tamponne un PDF et retourne le fichier résultant.

##### `stampMetadata(options: StampOptions): Promise<StampMetadataResult>`

Tamponne un PDF et retourne uniquement les métadonnées.

##### `health(): Promise<HealthStatus>`

Vérifie l'état du service.

### Types

#### `StampOptions`

```typescript
interface StampOptions {
  pdfUrl?: string;
  googleDrive?: { fileId: string; accessToken: string };
  oodrive?: { fileId: string; accessToken: string };
  stampUrl: string;
  documentIndex?: number; // défaut: 1
  prefix?: string; // défaut: ""
  stampOnlyFirstPage?: boolean; // défaut: false
}
```

#### `StampResult`

```typescript
interface StampResult {
  pdf: Buffer;
  coordinates: StampCoordinates[];
  pagesProcessed: number;
}
```

#### `StampCoordinates`

```typescript
interface StampCoordinates {
  pageNumber: number;
  x: number;
  y: number;
  size: number;
}
```

## Déploiement du service

Le service doit être déployé via Docker :

```bash
docker-compose up -d
```

Cela démarre :
- `pdf-processor` : Service gRPC de traitement (interne)
- `pdf-gateway` : API REST FastAPI sur le port 8000

## License

MIT
