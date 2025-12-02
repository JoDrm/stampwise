#!/usr/bin/env node

/**
 * Script postinstall pour Stampwise
 * Vérifie les prérequis et guide l'utilisateur
 */

const { execSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

const COLORS = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  cyan: '\x1b[36m',
  bold: '\x1b[1m'
};

function log(message, color = '') {
  console.log(`${color}${message}${COLORS.reset}`);
}

function checkPython() {
  const candidates = ['python3', 'python'];

  for (const cmd of candidates) {
    try {
      const version = execSync(`${cmd} --version`, { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
      const match = version.match(/Python (\d+)\.(\d+)/);
      if (match) {
        const major = parseInt(match[1]);
        const minor = parseInt(match[2]);
        if (major >= 3 && minor >= 8) {
          return { found: true, command: cmd, version: version.trim() };
        }
      }
    } catch {
      continue;
    }
  }

  return { found: false };
}

function checkPoppler() {
  try {
    execSync('pdftoppm -v', { stdio: ['pipe', 'pipe', 'pipe'] });
    return true;
  } catch {
    return false;
  }
}

async function main() {
  log('\n📦 Stampwise - Installation\n', COLORS.bold + COLORS.cyan);

  // Vérifier Python
  log('Vérification de Python...', COLORS.yellow);
  const python = checkPython();

  if (!python.found) {
    log('❌ Python 3.8+ non trouvé!', COLORS.red);
    log('\nInstallez Python depuis: https://www.python.org/downloads/', COLORS.yellow);
    log('Assurez-vous que Python est dans votre PATH.\n');
    process.exit(0); // Ne pas faire échouer npm install
  }

  log(`✅ ${python.version} trouvé (${python.command})`, COLORS.green);

  // Vérifier Poppler (requis pour pdf2image)
  log('\nVérification de Poppler (pdf2image)...', COLORS.yellow);
  const hasPoppler = checkPoppler();

  if (!hasPoppler) {
    log('⚠️  Poppler non trouvé (requis pour le traitement PDF)', COLORS.yellow);
    log('\nInstallez Poppler:', COLORS.cyan);
    log('  macOS:   brew install poppler');
    log('  Ubuntu:  sudo apt-get install poppler-utils');
    log('  Windows: https://github.com/oschwartz10612/poppler-windows/releases\n');
  } else {
    log('✅ Poppler trouvé', COLORS.green);
  }

  // Installer les dépendances Python
  log('\nInstallation des dépendances Python...', COLORS.yellow);

  const requirementsPath = path.join(__dirname, '..', 'python', 'requirements.txt');

  if (!fs.existsSync(requirementsPath)) {
    log('⚠️  requirements.txt non trouvé, skip installation', COLORS.yellow);
    return;
  }

  try {
    execSync(`${python.command} -m pip install -r "${requirementsPath}" --quiet`, {
      stdio: 'inherit'
    });
    log('✅ Dépendances Python installées', COLORS.green);
  } catch (error) {
    log('⚠️  Échec installation des dépendances Python', COLORS.yellow);
    log('   Exécutez manuellement:', COLORS.cyan);
    log(`   ${python.command} -m pip install -r ${requirementsPath}\n`);
  }

  // Message de succès
  log('\n✨ Stampwise installé avec succès!\n', COLORS.bold + COLORS.green);
  log('Utilisation:', COLORS.cyan);
  log(`
  import { Stampwise } from 'stampwise';

  const stampwise = new Stampwise();

  const result = await stampwise.stamp({
    pdfPath: './document.pdf',
    stampPath: './stamp.png',
    outputPath: './output.pdf',
    documentIndex: 1,
    prefix: 'DOC'
  });
  `);

  log('Documentation: https://github.com/jodrm/stampwise\n', COLORS.cyan);
}

main().catch(console.error);
