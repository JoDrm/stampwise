# Contribuer à Stampwise

Merci de votre intérêt pour contribuer à Stampwise ! Ce document vous guide à travers le processus de contribution.

## Code de conduite

Ce projet adhère au [Contributor Covenant](https://www.contributor-covenant.org/). En participant, vous vous engagez à respecter ce code.

## Comment contribuer

### Signaler un bug

1. Vérifiez que le bug n'a pas déjà été signalé dans les [Issues](https://github.com/jodrm/stampwise/issues)
2. Créez une nouvelle issue avec :
   - Un titre clair et descriptif
   - Les étapes pour reproduire le bug
   - Le comportement attendu vs le comportement observé
   - Votre environnement (OS, versions Python/Node.js)
   - Si possible, un PDF de test (anonymisé)

### Suggérer une amélioration

1. Ouvrez une [Discussion](https://github.com/jodrm/stampwise/discussions) pour proposer votre idée
2. Décrivez le problème que vous souhaitez résoudre
3. Proposez une solution si vous en avez une

### Soumettre du code

#### Setup de développement

```bash
# Cloner le repo
git clone https://github.com/jodrm/stampwise.git
cd stampwise

# Installer Poppler (requis)
# macOS: brew install poppler
# Ubuntu: sudo apt-get install poppler-utils

# SDK Node.js
cd packages/client-node
npm install
npm run build
```

#### Workflow

1. **Fork** le repository
2. **Créez une branche** depuis `main` :
   ```bash
   git checkout -b feature/ma-fonctionnalite
   # ou
   git checkout -b fix/mon-bugfix
   ```
3. **Faites vos modifications**
4. **Testez** vos changements :
   ```bash
   cd packages/client-node
   npm run build
   npm test
   ```
5. **Committez** avec un message clair :
   ```bash
   git commit -m "feat: ajoute support pour les PDF protégés"
   # ou
   git commit -m "fix: corrige la détection des QR codes"
   ```
6. **Push** votre branche :
   ```bash
   git push origin feature/ma-fonctionnalite
   ```
7. **Ouvrez une Pull Request**

#### Conventions de commit

Nous suivons [Conventional Commits](https://www.conventionalcommits.org/) :

- `feat:` Nouvelle fonctionnalité
- `fix:` Correction de bug
- `docs:` Documentation uniquement
- `style:` Formatage (pas de changement de code)
- `refactor:` Refactoring du code
- `test:` Ajout de tests
- `chore:` Maintenance (deps, build, etc.)

Exemples :

```
feat: ajoute le support des PDF cryptés
fix: corrige le placement du tampon sur les pages paysage
docs: améliore la documentation de l'API
refactor: optimise la détection des zones blanches
```

#### Standards de code

**Python**

- Suivre PEP 8
- Docstrings pour les fonctions publiques
- Type hints quand pertinent

**TypeScript**

- ESLint + Prettier
- Types explicites (pas de `any`)
- JSDoc pour les exports publics

#### Checklist PR

- [ ] Le code compile sans erreurs
- [ ] Les tests passent
- [ ] La documentation est à jour
- [ ] Le commit suit les conventions
- [ ] La PR a une description claire

## Structure du projet

```
stampwise/
├── packages/
│   └── client-node/               # SDK NPM (package principal)
│       ├── src/
│       │   └── index.ts           # SDK TypeScript
│       ├── python/
│       │   ├── processor.py       # Moteur de traitement PDF
│       │   └── requirements.txt   # Dépendances Python
│       ├── scripts/
│       │   └── postinstall.js     # Installation automatique
│       └── package.json
├── server.py                      # Service gRPC (optionnel, Docker)
├── api_gateway.py                 # API REST FastAPI (optionnel, Docker)
├── docker-compose.yml             # Déploiement Docker
├── fonts/                         # Polices embarquées
└── debug/                         # Images de debug (gitignored)
```

### Points d'entrée pour contribuer

| Domaine | Fichier | Difficulté |
|---------|---------|------------|
| Améliorer la détection | `packages/client-node/python/processor.py` → `find_whitest_space()` | Moyenne |
| Améliorer le SDK | `packages/client-node/src/index.ts` | Facile |
| Ajouter des options | `processor.py` + `index.ts` | Facile |
| Optimiser les performances | `processor.py` → `_process_single_page()` | Difficile |
| Support nouveaux formats | `processor.py` | Moyenne |

## Tests

### Tester le SDK

```bash
cd packages/client-node
npm run build

# Test manuel
node -e "
const { stampPdf } = require('./dist');
stampPdf({
  pdfPath: './test.pdf',
  stampPath: './stamp.png',
  outputPath: './output.pdf'
}).then(console.log).catch(console.error);
"
```

### Tester le processeur Python directement

```bash
cd packages/client-node/python

python3 processor.py \
  --pdf ./test.pdf \
  --stamp ./stamp.png \
  --output ./output.pdf \
  --index 1 \
  --prefix DOC \
  --json
```

## Mode Docker (optionnel)

Pour contribuer au service REST/gRPC :

```bash
# Lancer les services
docker-compose up -d

# Tester l'API
curl http://localhost:8000/health

# Logs
docker-compose logs -f
```

## Besoin d'aide ?

- Ouvrez une [Discussion](https://github.com/jodrm/stampwise/discussions)
- Contactez [@jodrm](https://github.com/jodrm)

Merci pour votre contribution !
