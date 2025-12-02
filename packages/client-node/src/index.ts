import { spawn } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

// ============== Types ==============

export interface StampOptions {
  /** Chemin du PDF à traiter */
  pdfPath: string;
  /** Chemin de l'image du tampon (PNG recommandé) */
  stampPath: string;
  /** Chemin du PDF de sortie */
  outputPath: string;
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
  /** Succès de l'opération */
  success: boolean;
  /** Chemin du PDF généré */
  outputPath: string;
  /** Coordonnées des tampons placés */
  coordinates: StampCoordinates[];
  /** Nombre de pages traitées */
  pagesProcessed: number;
}

export interface StampwiseConfig {
  /** Chemin vers l'exécutable Python (défaut: 'python3' ou 'python') */
  pythonPath?: string;
  /** Répertoire des polices personnalisées */
  fontsDir?: string;
}

interface ProcessorResult {
  success: boolean;
  output?: string;
  error?: string;
  coordinates?: Array<{
    pageNumber: number;
    x: number;
    y: number;
    size: number;
  }>;
  pagesProcessed?: number;
}

// ============== Helpers ==============

/**
 * Trouve le chemin Python disponible sur le système
 */
function findPythonPath(): string {
  const candidates = ['python3', 'python'];

  for (const candidate of candidates) {
    try {
      const { execSync } = require('child_process');
      execSync(`${candidate} --version`, { stdio: 'ignore' });
      return candidate;
    } catch {
      continue;
    }
  }

  throw new Error(
    'Python non trouvé. Installez Python 3.8+ et assurez-vous qu\'il est dans le PATH.\n' +
    'https://www.python.org/downloads/'
  );
}

/**
 * Vérifie si les dépendances Python sont installées
 */
async function checkDependencies(pythonPath: string): Promise<boolean> {
  return new Promise((resolve) => {
    const proc = spawn(pythonPath, ['-c', 'import fitz, cv2, pdf2image, PIL, img2pdf']);
    proc.on('close', (code) => resolve(code === 0));
  });
}

/**
 * Installe les dépendances Python
 */
async function installDependencies(pythonPath: string): Promise<void> {
  const requirementsPath = path.join(__dirname, '..', 'python', 'requirements.txt');

  return new Promise((resolve, reject) => {
    const proc = spawn(pythonPath, ['-m', 'pip', 'install', '-r', requirementsPath, '--quiet']);

    let stderr = '';
    proc.stderr.on('data', (data) => { stderr += data.toString(); });

    proc.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`Échec installation des dépendances Python:\n${stderr}`));
      }
    });
  });
}

// ============== Main Class ==============

/**
 * Stampwise - Tamponnage intelligent de PDF
 *
 * @example
 * ```typescript
 * import { Stampwise } from 'stampwise';
 *
 * const stampwise = new Stampwise();
 *
 * const result = await stampwise.stamp({
 *   pdfPath: './document.pdf',
 *   stampPath: './stamp.png',
 *   outputPath: './output.pdf',
 *   documentIndex: 1,
 *   prefix: 'DOC'
 * });
 *
 * console.log(`PDF généré: ${result.outputPath}`);
 * console.log(`${result.pagesProcessed} pages traitées`);
 * ```
 */
export class Stampwise {
  private pythonPath: string;
  private fontsDir?: string;
  private initialized: boolean = false;

  constructor(config: StampwiseConfig = {}) {
    this.pythonPath = config.pythonPath || findPythonPath();
    this.fontsDir = config.fontsDir;
  }

  /**
   * Initialise Stampwise (vérifie et installe les dépendances si nécessaire)
   */
  async init(): Promise<void> {
    if (this.initialized) return;

    const hasDepends = await checkDependencies(this.pythonPath);

    if (!hasDepends) {
      console.log('Installation des dépendances Python...');
      await installDependencies(this.pythonPath);
      console.log('Dépendances installées avec succès.');
    }

    this.initialized = true;
  }

  /**
   * Tamponne un PDF
   *
   * @param options - Options de tamponnage
   * @returns Résultat du tamponnage avec les coordonnées
   *
   * @example
   * ```typescript
   * const result = await stampwise.stamp({
   *   pdfPath: './facture.pdf',
   *   stampPath: './tampon.png',
   *   outputPath: './facture_tamponnee.pdf',
   *   documentIndex: 1,
   *   prefix: 'PIECE'
   * });
   * ```
   */
  async stamp(options: StampOptions): Promise<StampResult> {
    // Auto-init si pas encore fait
    await this.init();

    // Validation des entrées
    if (!fs.existsSync(options.pdfPath)) {
      throw new Error(`PDF non trouvé: ${options.pdfPath}`);
    }
    if (!fs.existsSync(options.stampPath)) {
      throw new Error(`Image du tampon non trouvée: ${options.stampPath}`);
    }

    // Créer le répertoire de sortie si nécessaire
    const outputDir = path.dirname(options.outputPath);
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }

    // Construire les arguments
    const processorPath = path.join(__dirname, '..', 'python', 'processor.py');
    const args = [
      processorPath,
      '--pdf', path.resolve(options.pdfPath),
      '--stamp', path.resolve(options.stampPath),
      '--output', path.resolve(options.outputPath),
      '--index', String(options.documentIndex ?? 1),
      '--prefix', options.prefix ?? '',
      '--json'
    ];

    if (options.stampOnlyFirstPage) {
      args.push('--first-page-only');
    }

    if (this.fontsDir) {
      args.push('--fonts-dir', this.fontsDir);
    }

    // Exécuter le processeur Python
    return new Promise((resolve, reject) => {
      const proc = spawn(this.pythonPath, args);

      let stdout = '';
      let stderr = '';

      proc.stdout.on('data', (data) => { stdout += data.toString(); });
      proc.stderr.on('data', (data) => { stderr += data.toString(); });

      proc.on('close', (code) => {
        if (code !== 0) {
          reject(new Error(`Erreur de traitement (code ${code}):\n${stderr}`));
          return;
        }

        try {
          const result: ProcessorResult = JSON.parse(stdout.trim());

          if (!result.success) {
            reject(new Error(result.error || 'Erreur inconnue'));
            return;
          }

          resolve({
            success: true,
            outputPath: result.output || options.outputPath,
            coordinates: result.coordinates || [],
            pagesProcessed: result.pagesProcessed || 0
          });
        } catch (e) {
          reject(new Error(`Erreur parsing résultat:\n${stdout}\n${stderr}`));
        }
      });

      proc.on('error', (err) => {
        reject(new Error(`Erreur exécution Python: ${err.message}`));
      });
    });
  }

  /**
   * Tamponne un PDF depuis un Buffer
   *
   * @param pdfBuffer - Buffer du PDF
   * @param stampBuffer - Buffer de l'image du tampon
   * @param options - Options de tamponnage
   * @returns Buffer du PDF tamponné avec métadonnées
   */
  async stampBuffer(
    pdfBuffer: Buffer,
    stampBuffer: Buffer,
    options: Omit<StampOptions, 'pdfPath' | 'stampPath' | 'outputPath'> = {}
  ): Promise<{ pdf: Buffer; coordinates: StampCoordinates[]; pagesProcessed: number }> {
    // Créer des fichiers temporaires
    const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'stampwise-'));
    const pdfPath = path.join(tmpDir, 'input.pdf');
    const stampPath = path.join(tmpDir, 'stamp.png');
    const outputPath = path.join(tmpDir, 'output.pdf');

    try {
      // Écrire les buffers
      fs.writeFileSync(pdfPath, pdfBuffer);
      fs.writeFileSync(stampPath, stampBuffer);

      // Traiter
      const result = await this.stamp({
        ...options,
        pdfPath,
        stampPath,
        outputPath
      });

      // Lire le résultat
      const pdf = fs.readFileSync(outputPath);

      return {
        pdf,
        coordinates: result.coordinates,
        pagesProcessed: result.pagesProcessed
      };
    } finally {
      // Nettoyer
      try {
        if (fs.existsSync(pdfPath)) fs.unlinkSync(pdfPath);
        if (fs.existsSync(stampPath)) fs.unlinkSync(stampPath);
        if (fs.existsSync(outputPath)) fs.unlinkSync(outputPath);
        fs.rmdirSync(tmpDir);
      } catch {
        // Ignorer les erreurs de nettoyage
      }
    }
  }
}

// ============== Fonction raccourcie ==============

/**
 * Fonction raccourcie pour tamponner un PDF
 *
 * @example
 * ```typescript
 * import { stampPdf } from 'stampwise';
 *
 * const result = await stampPdf({
 *   pdfPath: './document.pdf',
 *   stampPath: './stamp.png',
 *   outputPath: './output.pdf',
 *   documentIndex: 1,
 *   prefix: 'DOC'
 * });
 * ```
 */
export async function stampPdf(options: StampOptions): Promise<StampResult> {
  const stampwise = new Stampwise();
  return stampwise.stamp(options);
}

// Export par défaut
export default Stampwise;
