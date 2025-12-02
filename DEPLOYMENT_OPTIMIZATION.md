# Configuration Optimale pour le Déploiement du Microservice PDF

## ⚠️ Oui, la vitesse dépend FORTEMENT du serveur

Le microservice effectue des opérations **très intensives en CPU** :

- Conversion PDF → Images (poppler-utils)
- Traitement d'images avec OpenCV (morphologie mathématique, détection)
- Traitement parallèle de plusieurs pages simultanément
- Redimensionnement d'images avec PIL

## 📊 Opérations les plus coûteuses

1. **Conversion PDF → Images** : I/O disque + CPU
2. **Opérations OpenCV** : Morphologie mathématique, détection de contours (100% CPU)
3. **Traitement parallèle** : Jusqu'à 12 workers simultanés pour gros fichiers
4. **Redimensionnement d'images** : CPU + mémoire

## 🎯 Configuration Recommandée

### Configuration Minimale (Petits PDFs < 50 pages)

- **CPU** : 2-4 cores (2.4 GHz+)
- **RAM** : 4 GB
- **Stockage** : SSD recommandé
- **Coût estimé** : ~20-30€/mois (Hetzner, OVH)

### Configuration Recommandée (Production - PDFs moyens 50-200 pages)

- **CPU** : 4-8 cores (2.8 GHz+)
- **RAM** : 8-16 GB
- **Stockage** : SSD NVMe (meilleur pour I/O)
- **Coût estimé** : ~50-80€/mois (Hetzner CPX31, OVH B2-7)

### Configuration Optimale (Gros PDFs > 200 pages)

- **CPU** : 8-16 cores (3.0 GHz+)
- **RAM** : 16-32 GB
- **Stockage** : SSD NVMe haute performance
- **Coût estimé** : ~100-200€/mois (Hetzner CPX41, AWS c5.2xlarge)

## 🐳 Configuration Docker Optimale

Ajoutez ces limites dans votre `docker-compose.yml` :

```yaml
pdf-whitespace-microservice:
  container_name: pdf-whitespace-microservice
  build:
    context: ./pdf-whitespace-microservice
    dockerfile: Dockerfile
  environment:
    JWT_KEY: ${JWT_KEY}
    # Optimisation OpenCV
    OMP_NUM_THREADS: "4" # Nombre de threads OpenCV (ajuster selon CPU)
    OPENBLAS_NUM_THREADS: "4"
  ports:
    - "50051:50051"
  networks:
    - pdf-whitespace-microservice-network
  volumes:
    - ./pdf-whitespace-microservice/debug:/app/debug
  # LIMITES DE RESSOURCES (IMPORTANT!)
  deploy:
    resources:
      limits:
        cpus: "8" # Maximum 8 cores
        memory: 16G # Maximum 16 GB RAM
      reservations:
        cpus: "4" # Minimum 4 cores garantis
        memory: 8G # Minimum 8 GB RAM garantis
  # Alternative pour docker-compose v2 (sans swarm)
  # cpus: '8'
  # mem_limit: 16g
  # mem_reservation: 8g
```

## 🔧 Optimisations du Code

### Variables d'environnement recommandées

```bash
# Dans votre .env ou docker-compose.yml
OMP_NUM_THREADS=4              # Threads OpenCV (1 par core physique recommandé)
OPENBLAS_NUM_THREADS=4         # Threads BLAS pour numpy
MKL_NUM_THREADS=4              # Threads Intel MKL (si disponible)
NUMEXPR_NUM_THREADS=4          # Threads NumExpr
```

### Ajustement du nombre de workers

Le code adapte automatiquement le nombre de workers selon le nombre de pages :

- **< 100 pages** : 4 workers, DPI 250
- **100-300 pages** : 8 workers, DPI 200
- **> 300 pages** : 12 workers, DPI 150

Vous pouvez ajuster ces valeurs dans `server.py` lignes 1078-1092.

## 📈 Benchmarks Attendus

### Configuration Minimale (4 cores, 8GB)

- PDF 10 pages : ~5-10 secondes
- PDF 50 pages : ~30-60 secondes
- PDF 200 pages : ~3-5 minutes

### Configuration Recommandée (8 cores, 16GB)

- PDF 10 pages : ~3-5 secondes
- PDF 50 pages : ~15-30 secondes
- PDF 200 pages : ~1-2 minutes

### Configuration Optimale (16 cores, 32GB)

- PDF 10 pages : ~2-3 secondes
- PDF 50 pages : ~10-15 secondes
- PDF 200 pages : ~45-60 secondes

## 🚀 Recommandations Spécifiques par Provider

### Hetzner Cloud

- **CPX31** (4 vCPU, 8GB) : ~15€/mois - Bon pour production moyenne
- **CPX41** (8 vCPU, 16GB) : ~30€/mois - Optimal pour production
- **CPX51** (16 vCPU, 32GB) : ~60€/mois - Pour très gros volumes

### AWS

- **c5.xlarge** (4 vCPU, 8GB) : ~150$/mois
- **c5.2xlarge** (8 vCPU, 16GB) : ~300$/mois
- **c5.4xlarge** (16 vCPU, 32GB) : ~600$/mois

### OVH

- **B2-7** (4 vCPU, 15GB) : ~20€/mois
- **B2-15** (8 vCPU, 30GB) : ~40€/mois
- **B2-30** (16 vCPU, 60GB) : ~80€/mois

## ⚡ Optimisations Supplémentaires

1. **Désactiver le debug en production** :

   ```python
   self.processor = PDFProcessor(..., enable_debug=False)
   ```

2. **Utiliser un cache Redis** pour les tampons redimensionnés (si plusieurs requêtes)

3. **Stockage temporaire sur RAM disk** (tmpfs) pour les fichiers temporaires :

   ```yaml
   volumes:
     - type: tmpfs
       target: /tmp
       tmpfs:
         size: 2G
   ```

4. **Monitoring** : Surveiller CPU, RAM, et temps de traitement pour ajuster

## 📝 Notes Importantes

- Le traitement est **100% CPU-bound** : plus de cores = traitement plus rapide
- La RAM est importante pour les gros PDFs (chaque page en mémoire)
- Le stockage SSD est critique pour les I/O de conversion PDF
- Le code utilise déjà le parallélisme optimal avec ThreadPoolExecutor

## 🔍 Vérification de Performance

Pour tester votre configuration, surveillez :

```bash
# Dans le conteneur Docker
htop  # Voir utilisation CPU/RAM
iostat  # Voir I/O disque
```

Les logs du microservice indiquent aussi :

- Nombre de workers utilisés
- DPI utilisé
- Temps de traitement par page
