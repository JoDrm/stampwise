import axios, { AxiosInstance, AxiosResponse } from 'axios';

// ============== Types ==============

export interface PdfStampConfig {
  /** URL de base du service (ex: http://localhost:8000) */
  baseUrl: string;
  /** Timeout en millisecondes (défaut: 300000 = 5 min) */
  timeout?: number;
  /** Headers personnalisés */
  headers?: Record<string, string>;
}

export interface GoogleDriveSource {
  /** ID du fichier Google Drive */
  fileId: string;
  /** Token d'accès OAuth2 */
  accessToken: string;
}

export interface OoDriveSource {
  /** ID du fichier OoDrive */
  fileId: string;
  /** Token d'accès */
  accessToken: string;
}

export interface StampOptions {
  /** URL du PDF à traiter */
  pdfUrl?: string;
  /** Source Google Drive */
  googleDrive?: GoogleDriveSource;
  /** Source OoDrive */
  oodrive?: OoDriveSource;
  /** URL de l'image du tampon (PNG recommandé) */
  stampUrl: string;
  /** Numéro de la pièce (défaut: 1) */
  documentIndex?: number;
  /** Préfixe pour la numérotation (ex: 'DOC') */
  prefix?: string;
  /** Tamponner uniquement la première page */
  stampOnlyFirstPage?: boolean;
}

export interface StampCoordinates {
  /** Numéro de la page */
  pageNumber: number;
  /** Position X en pixels */
  x: number;
  /** Position Y en pixels */
  y: number;
  /** Taille du tampon en pixels */
  size: number;
}

export interface StampResult {
  /** PDF tamponné (Buffer) */
  pdf: Buffer;
  /** Coordonnées des tampons placés */
  coordinates: StampCoordinates[];
  /** Nombre de pages traitées */
  pagesProcessed: number;
}

export interface StampMetadataResult {
  /** Succès de l'opération */
  success: boolean;
  /** Message */
  message: string;
  /** Coordonnées des tampons placés */
  coordinates: StampCoordinates[];
  /** Nombre de pages traitées */
  pagesProcessed: number;
}

export interface HealthStatus {
  /** État du service */
  status: string;
  /** État de la connexion gRPC */
  grpcService: string;
  /** Version du service */
  version: string;
}

// ============== Client ==============

/**
 * Client SDK pour le service PDF Stamp
 *
 * @example
 * ```typescript
 * import { PdfStampClient } from '@jodrm/stampwise';
 *
 * const client = new PdfStampClient({
 *   baseUrl: 'http://localhost:8000'
 * });
 *
 * // Tamponner un PDF depuis une URL
 * const result = await client.stamp({
 *   pdfUrl: 'https://example.com/document.pdf',
 *   stampUrl: 'https://example.com/stamp.png',
 *   documentIndex: 1,
 *   prefix: 'DOC'
 * });
 *
 * // Sauvegarder le PDF
 * fs.writeFileSync('stamped.pdf', result.pdf);
 * ```
 */
export class PdfStampClient {
  private client: AxiosInstance;

  constructor(config: PdfStampConfig) {
    this.client = axios.create({
      baseURL: config.baseUrl,
      timeout: config.timeout ?? 300000, // 5 minutes par défaut
      headers: {
        'Content-Type': 'application/json',
        ...config.headers,
      },
    });
  }

  /**
   * Vérifie l'état du service
   */
  async health(): Promise<HealthStatus> {
    const response = await this.client.get<HealthStatus>('/health');
    return response.data;
  }

  /**
   * Tamponne un PDF et retourne le fichier résultant
   *
   * @param options - Options de tamponnage
   * @returns Le PDF tamponné avec ses métadonnées
   *
   * @example
   * ```typescript
   * // Depuis une URL
   * const result = await client.stamp({
   *   pdfUrl: 'https://example.com/doc.pdf',
   *   stampUrl: 'https://example.com/stamp.png',
   *   documentIndex: 1,
   *   prefix: 'PIECE'
   * });
   *
   * // Depuis Google Drive
   * const result = await client.stamp({
   *   googleDrive: {
   *     fileId: '1abc...',
   *     accessToken: 'ya29...'
   *   },
   *   stampUrl: 'https://example.com/stamp.png',
   *   documentIndex: 1
   * });
   * ```
   */
  async stamp(options: StampOptions): Promise<StampResult> {
    this.validateOptions(options);

    const payload = this.buildPayload(options);

    const response: AxiosResponse<ArrayBuffer> = await this.client.post(
      '/stamp',
      payload,
      {
        responseType: 'arraybuffer',
      }
    );

    // Extraire les métadonnées des headers
    const coordinatesHeader = response.headers['x-stamp-coordinates'];
    const pagesHeader = response.headers['x-pages-processed'];

    let coordinates: StampCoordinates[] = [];
    if (coordinatesHeader) {
      try {
        const rawCoords = JSON.parse(coordinatesHeader);
        coordinates = rawCoords.map((c: any) => ({
          pageNumber: c.page_number,
          x: c.x,
          y: c.y,
          size: c.size,
        }));
      } catch {
        // Ignorer les erreurs de parsing
      }
    }

    return {
      pdf: Buffer.from(response.data),
      coordinates,
      pagesProcessed: pagesHeader ? parseInt(pagesHeader, 10) : coordinates.length,
    };
  }

  /**
   * Tamponne un PDF et retourne uniquement les métadonnées (sans le PDF)
   *
   * Utile pour vérifier les positions des tampons avant téléchargement
   *
   * @param options - Options de tamponnage
   * @returns Métadonnées du tamponnage
   */
  async stampMetadata(options: StampOptions): Promise<StampMetadataResult> {
    this.validateOptions(options);

    const payload = this.buildPayload(options);

    const response = await this.client.post<{
      success: boolean;
      message: string;
      coordinates: Array<{
        page_number: number;
        x: number;
        y: number;
        size: number;
      }>;
      pages_processed: number;
    }>('/stamp/metadata', payload);

    return {
      success: response.data.success,
      message: response.data.message,
      coordinates: response.data.coordinates.map((c) => ({
        pageNumber: c.page_number,
        x: c.x,
        y: c.y,
        size: c.size,
      })),
      pagesProcessed: response.data.pages_processed,
    };
  }

  /**
   * Valide les options de tamponnage
   */
  private validateOptions(options: StampOptions): void {
    if (!options.pdfUrl && !options.googleDrive && !options.oodrive) {
      throw new Error(
        'Au moins une source PDF doit être fournie (pdfUrl, googleDrive ou oodrive)'
      );
    }

    if (!options.stampUrl) {
      throw new Error("L'URL du tampon (stampUrl) est requise");
    }
  }

  /**
   * Construit le payload pour l'API
   */
  private buildPayload(options: StampOptions): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      stamp_url: options.stampUrl,
      document_index: options.documentIndex ?? 1,
      prefix: options.prefix ?? '',
      stamp_only_first_page: options.stampOnlyFirstPage ?? false,
    };

    if (options.pdfUrl) {
      payload.pdf_url = options.pdfUrl;
    }

    if (options.googleDrive) {
      payload.google_drive = {
        file_id: options.googleDrive.fileId,
        access_token: options.googleDrive.accessToken,
      };
    }

    if (options.oodrive) {
      payload.oodrive = {
        file_id: options.oodrive.fileId,
        access_token: options.oodrive.accessToken,
      };
    }

    return payload;
  }
}

// Export par défaut
export default PdfStampClient;
