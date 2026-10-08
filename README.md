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
| 3–6 | Antivirus et génération de documents, email et IA, notifications email, durcissement | à venir |

## Stack

| Couche | Technologie |
|---|---|
| Entrée | Caddy (une seule origine : `/api/v1` → backend, le reste → frontend) |
| Frontend | Next.js 16, TypeScript, Tailwind CSS 4, shadcn/ui (Base UI), TanStack Query, i18n FR/EN/AR (RTL) |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, argon2, JWT |
| Base | PostgreSQL 17 |
| Queue | Celery + Redis (envoi des emails) |
| Stockage | S3-compatible (SeaweedFS en local) |
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

## Tests

Backend : pytest, sur les vrais services Postgres, Redis, S3 et Mailpit, avec la base isolée `<POSTGRES_DB>_test` remise à zéro à chaque exécution.

```bash
docker compose exec backend pytest -q
```

Frontend, tests unitaires et contrôles statiques :

```bash
cd frontend && npm test && npm run typecheck && npm run lint
```

Frontend, tests de bout en bout (Playwright) contre la stack Docker démarrée :

```bash
cd frontend && npx playwright install chromium && npm run test:e2e
```

La suite E2E couvre notamment le cycle complet d'une demande (inscription vérifiée → demande avec justificatif → attribution → demande d'information → réponse → approbation → dépôt du document final → téléchargement → clôture) et les cas refusés (isolation entre étudiants, transitions interdites, permission retirée, motif obligatoire, référence invalide). Le scénario « permission retirée » modifie temporairement `role_permissions` via `docker compose exec postgres psql` et la restaure.

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
