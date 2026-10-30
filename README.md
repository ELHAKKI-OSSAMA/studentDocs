# StudentDocs

Plateforme de gestion des demandes de documents administratifs étudiants : portail web, intégration email assistée par IA avec validation humaine, suivi par machine d'état.

- [Architecture, sécurité et workflows](docs/architecture.md)
- [Schéma de base de données](docs/database.md)
- [API](docs/api.md)

## État d'avancement

| Phase | Contenu | État |
|---|---|---|
| 0 | Socle : Docker, migrations, santé, CI | ✅ |
| 1 | Authentification et RBAC, catalogue académique, espaces étudiant et admin, FR/EN/AR | ✅ |
| 2 | Demandes web (multi-documents, justificatifs), vérification des inscriptions, workflow, attribution, messages, documents délivrés, notifications in-app | ✅ |
| 3 | Pipeline documentaire sécurisé : validation stricte, SHA-256, stockage S3 privé, antivirus ClamAV asynchrone (Celery), quarantaine, téléchargement réservé aux fichiers sains | ✅ |
| 4–6 | Email et IA, notifications email, durcissement | à venir |

## Stack

| Couche | Technologie |
|---|---|
| Entrée | Caddy (une seule origine : `/api/v1` → backend, le reste → frontend) |
| Frontend | Next.js 16, TypeScript, Tailwind CSS 4, shadcn/ui (Base UI), TanStack Query, i18n FR/EN/AR (RTL) |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, argon2, JWT |
| Base | PostgreSQL 17 |
| Queue | Celery + Redis (envoi des emails) |
| Stockage | S3-compatible (SeaweedFS en local) |
| Antivirus | ClamAV (clamd, analyse INSTREAM par le worker) |
| Mail (dev) | Mailpit |

## Démarrage

Prérequis : Docker et Docker Compose.

```bash
cp .env.example .env
```

Remplacez ensuite chaque valeur `replace-…` dans `.env`. Pour obtenir les comptes de démonstration, définissez aussi `SEED_DEMO_PASSWORD`. Puis lancez :

```bash
docker compose up -d --build --wait
```

Au démarrage, les migrations puis le seed (catalogue et comptes de démonstration) s'exécutent automatiquement.

L'image ClamAV embarque une base de signatures et `freshclam` la met à jour au démarrage (volume `clamavdb`) ; compter une à quelques minutes selon le réseau. Le worker attend que ClamAV soit prêt ; l'API, elle, démarre sans l'attendre (les fichiers restent alors en analyse et ne sont pas téléchargeables). ClamAV demande environ 1,5 Go de mémoire.

| Service | URL |
|---|---|
| Application | http://localhost:3000 |
| API (OpenAPI hors production) | http://localhost:8000/docs |
| Mailpit (emails de développement) | http://localhost:8025 |

Comptes de démonstration (mot de passe = `SEED_DEMO_PASSWORD`) :

| Compte | Rôle |
|---|---|
| `superadmin@univ-demo.ma` | SUPER_ADMIN |
| `admin@univ-demo.ma` | ADMIN |
| `etudiant@etu.univ-demo.ma` | STUDENT |

Pour l'auto-inscription, utilisez une adresse `@etu.univ-demo.ma` ; le lien de confirmation arrive dans Mailpit.

## Variables d'environnement (documents et antivirus)

| Variable | Défaut | Rôle |
|---|---|---|
| `MAX_UPLOAD_BYTES` | `10485760` (10 Mo) | taille maximale d'un fichier ; doit rester ≤ `CLAMAV_STREAM_MAX_BYTES` |
| `CLAMAV_STREAM_MAX_BYTES` | `26214400` (25 Mo) | limite de flux de clamd (`StreamMaxLength`), appliquée au conteneur ClamAV |
| `STORAGE_TENANT` | `default` | préfixe des clés de stockage (`tenants/<tenant>/…`) |
| `CLAMAV_HOST` / `CLAMAV_PORT` | `clamav` / `3310` | démon ClamAV (fixés dans `docker-compose.yml`) |
| `CLAMAV_TIMEOUT_SECONDS` | `60` | délai maximal d'une analyse (socket) |
| `SCAN_QUEUE` | `documents` | file Celery des analyses |
| `SCAN_MAX_RETRIES` / `SCAN_RETRY_BASE_SECONDS` | `5` / `10` | nouvelles tentatives si ClamAV est indisponible (délai exponentiel), puis statut `ERROR` |

Les identifiants S3 (`S3_ACCESS_KEY`, `S3_SECRET_KEY`) viennent uniquement de `.env`.

Relation entre les deux limites : un fichier plus gros que `CLAMAV_STREAM_MAX_BYTES` ne pourrait jamais être analysé et finirait en `ERROR`. Le backend et le worker **refusent donc de démarrer** si `MAX_UPLOAD_BYTES > CLAMAV_STREAM_MAX_BYTES`. La même variable configure le conteneur ClamAV, ce qui garde les deux valeurs alignées. La limite de 10 Mo est aussi vérifiée dans le navigateur, comme simple confort : la vérification qui fait foi est celle du serveur.

Commandes d'exploitation :

```bash
docker compose exec backend python -m app.scripts.rescan
```

Relance l'analyse des fichiers restés en `SCANNING` (le worker le fait aussi à chaque démarrage). Avec `--errors`, les fichiers en `ERROR` sont aussi réanalysés, par exemple après une panne de ClamAV.

## Emails entrants et IA (Phase 4)

Une boîte institutionnelle est relevée en IMAP (lecture seule) par le service `beat` ; chaque email devient un dossier revu par un humain dans `/admin/emails`. L'IA ne fait que proposer : aucune demande n'est jamais créée sans validation humaine.

| Variable | Défaut | Rôle |
|---|---|---|
| `IMAP_HOST` / `IMAP_PORT` / `IMAP_SSL` | vide / `993` / `true` | serveur IMAP ; relève désactivée si `IMAP_HOST` est vide ; `IMAP_SSL=false` refusé en production |
| `IMAP_USERNAME` / `IMAP_PASSWORD` / `IMAP_FOLDER` / `IMAP_ADDRESS` | — / — / `INBOX` / = username | compte relevé (secret dans `.env` uniquement) |
| `EMAIL_POLL_SECONDS` | `60` | période de relève |
| `EMAIL_TRUSTED_AUTHSERV_IDS` | `[]` | authserv-id des serveurs de réception dont les `Authentication-Results` sont crus (sinon aucun étudiant n'est identifié automatiquement) |
| `AI_PROVIDER` | `none` | `none` ou `openai_compatible` ; jamais de bascule vers un autre fournisseur |
| `AI_BASE_URL` / `AI_MODEL` / `AI_API_KEY` | — | ex. `http://ollama:11434/v1` |
| `AI_ALLOW_EXTERNAL` | `false` | décision explicite requise pour un fournisseur hors réseau privé |
| `AI_TIMEOUT_SECONDS` / `AI_JSON_MODE` | `60` / `json_schema` | `json_object` pour les serveurs sans sortie structurée |

`AI_READ_ATTACHMENTS` doit rester `false` : seul le corps de l'email est envoyé au modèle dans cette phase. Avec un modèle local (Ollama, vLLM, LM Studio), aucune donnée ne sort vers Internet ; si ce modèle tombe, les dossiers passent simplement en revue humaine.

## Tests

Backend : pytest, sur les vrais services Postgres, Redis, S3, ClamAV et Mailpit, avec la base isolée `<POSTGRES_DB>_test` remise à zéro à chaque exécution. Un vrai worker Celery est démarré par la suite de tests sur une file dédiée (`test-documents-…`), que le worker de la stack ne consomme pas. Le scénario antivirus utilise uniquement le fichier de test standard EICAR, assemblé à l'exécution (aucun fichier du dépôt ne contient la signature).

Depuis la Phase 4, les tests utilisent aussi GreenMail (serveur SMTP/IMAP de test) et un serveur LLM de test (HTTP compatible OpenAI, réponses scriptées) : démarrez la stack avec la surcouche de test, qui n'est jamais utilisée en production.

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --build --wait
```

```bash
docker compose exec backend pytest -q
```

Le code du conteneur est en lecture seule : pour Ruff, désactivez le cache.

```bash
docker compose exec -e RUFF_NO_CACHE=true backend ruff check .
```

Frontend, tests unitaires et contrôles statiques :

```bash
cd frontend && npm test && npm run typecheck && npm run lint
```

Frontend, tests de bout en bout (Playwright) contre la stack Docker démarrée :

```bash
cd frontend && npx playwright install chromium && npm run test:e2e
```

La suite E2E (stack lancée avec `docker-compose.test.yml`) couvre aussi les emails entrants : email SMTP → relève IMAP → extraction → correction, association, conversion → workflow jusqu'à `COMPLETED` ; réponse `Re: [REQ-…]` rattachée au fil ; pièce EICAR en quarantaine jamais envoyée à l'IA ; injection de prompt sans aucune action automatique. Elle couvre notamment le cycle complet d'une demande (inscription vérifiée → demande avec justificatif → attribution → demande d'information → réponse → approbation → dépôt du document final → téléchargement → clôture) et les cas refusés (isolation entre étudiants, transitions interdites, permission retirée, motif obligatoire, référence invalide). Le scénario « permission retirée » modifie temporairement `role_permissions` via `docker compose exec postgres psql` et la restaure.

Lancer la suite E2E plusieurs fois de suite peut atteindre la limite d'inscriptions par IP (10 par heure par défaut). Augmentez `RATE_LIMIT_REGISTER_PER_IP` dans votre `.env` local si besoin.

## Migrations

Pour appliquer les migrations :

```bash
docker compose exec backend alembic upgrade head
```

Pour générer une nouvelle migration :

```bash
docker compose exec backend alembic revision --autogenerate -m "description"
```

## Note pour les contributeurs (Windows)

Après tout `npm install <paquet>`, régénérez le lockfile proprement : `rm -rf node_modules package-lock.json && npm install`. Sinon, npm sous Windows omet des dépendances optionnelles Linux et `npm ci` échoue dans Docker.
