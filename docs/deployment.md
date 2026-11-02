# Déploiement en production : Vercel + Supabase + Gmail (SMTP)

Une seule base de code, un seul domaine public. Vercel héberge deux projets créés depuis le même dépôt GitHub :

```
navigateur ──► https://<domaine>  (projet Vercel « frontend », Next.js)
                 ├── pages
                 └── /api/v1/*  ──proxy serveur──►  projet Vercel « backend » (FastAPI, 1 fonction Python)
                                   + secret partagé              │
                                   + IP du client                ├──► Supabase Postgres (pooler, mode session)
                                                                 ├──► Supabase Storage (S3, bucket privé)
                                                                 └──► Gmail (SMTP, port 465)
```

Le proxy Next.js (`frontend/src/app/api/v1/[...path]/route.ts`) garde l'API sur le même domaine que le site :
cookies de session et protection CSRF fonctionnent sans changement. Le backend refuse tout appel qui n'a pas
le secret du proxy (`PROXY_SHARED_SECRET`), donc son adresse `*.vercel.app` n'est pas utilisable directement.

## Profil « serverless » et ce qu'il change

| Fonction | Stack Docker | Vercel |
|---|---|---|
| Emails sortants | file Celery | envoyés par Gmail pendant la requête (`TASK_MODE=inline`) |
| Limites anti-abus, jetons révoqués | Redis | table Postgres `ephemeral_keys` (`EPHEMERAL_STORE=postgres`) |
| Antivirus | ClamAV, fichier bloqué tant qu'il n'est pas CLEAN | **aucun** (`ANTIVIRUS=none`) : seuls les contrôles de type, taille et signature s'appliquent ; les fichiers sont marqués `antivirus_disabled` |
| Réception d'emails (IMAP) et IA | worker + Beat | **désactivées** |
| Taille max. d'un fichier | 10 Mo | **4 Mo** (Vercel refuse les requêtes > 4,5 Mo) |

Limites du plan Vercel **Hobby** : usage non commercial uniquement, 60 s maximum par requête.

## 1. Supabase

1. Créer un projet (région proche des utilisateurs, ex. `eu-west-3`). Noter le mot de passe de la base.
2. **Connect → Session pooler** : copier l'URL (port 5432) et la transformer en
   `postgresql+asyncpg://postgres.<ref>:<mot-de-passe>@aws-0-<région>.pooler.supabase.com:5432/postgres`.
   N'utilisez pas le « Transaction pooler » (port 6543) : il est incompatible avec asyncpg.
3. **Storage** : créer un bucket **privé** nommé `studentdocs`.
4. **Storage → S3 Connection** : copier l'endpoint et la région, puis créer une clé d'accès S3.

## 2. Gmail (envoi des emails)

1. Compte Google → **Sécurité** → activer la **validation en deux étapes**.
2. **Mots de passe des applications** (https://myaccount.google.com/apppasswords) : créer un mot de passe
   « StudentDocs » (16 caractères) : c'est `SMTP_PASSWORD`. `SMTP_USERNAME` et `MAIL_FROM` = l'adresse Gmail.

Limite Gmail : environ 500 emails par jour ; au-delà, passer à un service d'envoi dédié.

L'envoi peut aussi être configuré plus tard par le super admin dans **Paramètres → Serveur d'envoi (SMTP)** :
la configuration enregistrée en base remplace alors celle des variables d'environnement.

## 3. Initialiser la base Supabase (une seule fois, depuis votre poste)

Avec la stack Docker locale construite (`docker compose build backend`), dans un terminal à la racine du projet.
Remplacez `<DATABASE_URL>` par l'URL de l'étape 1.2 (entre guillemets) :

```bash
docker compose run --rm --no-deps -e DATABASE_URL="<DATABASE_URL>" backend alembic upgrade head
```

```bash
docker compose run --rm --no-deps -e DATABASE_URL="<DATABASE_URL>" -e APP_ENV=production -e SEED_DEMO_PASSWORD= -e SEED_STUDENT_EMAIL_DOMAIN=<domaine-étudiant> backend python -m app.scripts.seed
```

Puis le premier super admin (le mot de passe est demandé au clavier, il n'apparaît ni à l'écran ni dans l'historique) :

```bash
docker compose run --rm --no-deps -e DATABASE_URL="<DATABASE_URL>" -e SUPERADMIN_EMAIL=<email> -e SUPERADMIN_FIRST_NAME=<prénom> -e SUPERADMIN_LAST_NAME=<nom> backend python -m app.scripts.create_superadmin
```

Les autres administrateurs se créent ensuite dans l'application (**Utilisateurs**).

## 4. Vercel — projet « backend »

1. **Add New → Project**, importer le dépôt GitHub, **Root Directory : `backend`**, Framework : *Other*.
2. Variables d'environnement : voir [`deploy/backend.env.example`](../deploy/backend.env.example).
   Générer `SECRET_KEY` et `PROXY_SHARED_SECRET` avec `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. Déployer. Vérification : `https://<backend>.vercel.app/health/live` répond `{"status":"ok"}` ; toute autre
   adresse répond 404 sans le secret (c'est voulu).

## 5. Vercel — projet « frontend »

1. **Add New → Project**, même dépôt, **Root Directory : `frontend`**, Framework : *Next.js*.
2. Variables : voir [`deploy/frontend.env.example`](../deploy/frontend.env.example) (`BACKEND_URL` = adresse du
   projet backend, même `PROXY_SHARED_SECRET`).
3. Déployer, puis **Settings → Domains** : ajouter votre domaine. Reporter ce domaine dans `FRONTEND_URL` et
   `CORS_ORIGINS` du backend et redéployer le backend (les liens des emails utilisent `FRONTEND_URL`).

## 6. Vérifications après déploiement

- `https://<domaine>/api/v1/health/ready` → `{"status":"ok","checks":{"database":"ok","storage":"ok"}}`.
- Connexion du super admin, puis **Paramètres** : bouton « Tester l'envoi » vers votre adresse.
- Création d'un compte étudiant (domaine autorisé) : l'email de confirmation arrive.
- Dépôt d'une demande avec un PDF de moins de 4 Mo, puis téléchargement.

## Mises à jour

Chaque `git push` sur la branche de production redéploie les deux projets. Si un commit ajoute une migration,
relancer la commande `alembic upgrade head` de l'étape 3 **avant** de pousser le code qui en dépend.
