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
   - Votre environnement (OS, versions Python/Node.js, Docker)
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

# Créer un environnement virtuel Python
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -r requirements.txt
pip install -r requirements-gateway.txt

# Pour le SDK Node.js
cd packages/client-node
npm install
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
   # Lancer les services
   docker-compose up -d

   # Tester l'API
   curl http://localhost:8000/health
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
├── server.py              # Logique principale de traitement PDF
├── api_gateway.py         # API REST FastAPI
├── jwt_service.py         # Authentification
├── protos/                # Définitions gRPC
├── packages/
│   └── client-node/       # SDK TypeScript
├── fonts/                 # Polices embarquées
└── debug/                 # Images de debug (gitignored)
```

### Points d'entrée pour contribuer

| Domaine | Fichier | Difficulté |
|---------|---------|------------|
| Améliorer la détection | `server.py` → `find_whitest_space()` | Moyenne |
| Ajouter un endpoint | `api_gateway.py` | Facile |
| Améliorer le SDK | `packages/client-node/src/index.ts` | Facile |
| Optimiser les performances | `server.py` → `_process_single_page()` | Difficile |
| Ajouter une source (Dropbox, etc.) | `server.py` + `api_gateway.py` | Moyenne |

## Besoin d'aide ?

- Ouvrez une [Discussion](https://github.com/jodrm/stampwise/discussions)
- Contactez [@jodrm](https://github.com/jodrm)

Merci pour votre contribution !
