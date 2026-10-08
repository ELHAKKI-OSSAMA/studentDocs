# Architecture

## Principes

1. **Modular monolith** : un backend FastAPI découpé par domaines, un worker Celery partageant le même code, un frontend Next.js. Pas de microservices.
2. **L'IA propose, l'humain décide** : le pipeline IA produit une `AiExtraction` attachée à un `EmailCase`. Une `Request` n'est créée que par le service `requests`, **après validation humaine** (MVP : toujours).
3. **Règles déterministes** pour tout ce qui est métier : transitions d'état, permissions, formats, accès aux fichiers.
4. **Fournisseurs interchangeables** derrière des interfaces : `EmailProvider`, `LLMProvider`, `NotificationChannel`, `DocumentGenerator`, stockage S3.

## Vue d'ensemble

### Point d'entrée unique (Caddy)

```
Navigateur ─▶ Caddy :3000 ─┬─ /api/v1/* ─▶ FastAPI (backend:8000)
                           └─ le reste  ─▶ Next.js (frontend:3000)
```

- Une seule origine : les cookies de session restent first-party et la protection CSRF repose sur le double-submit.
- Caddy **remplace** tout `X-Forwarded-For` envoyé par le client. Le backend ne fait confiance qu'à l'IP fixe de Caddy (`TRUSTED_PROXIES=["172.30.0.10/32"]`), ce qui rend le rate limiting par IP infalsifiable.
- Next.js ne relaie pas l'API : il ne remplit `X-Forwarded-For` que s'il est absent, donc ce serait falsifiable.

```
Étudiant ─▶ Next.js ─▶ API FastAPI ─▶ services de domaine ─▶ PostgreSQL
                                    └▶ stockage S3 (fichiers, URLs signées)

Boîte mail ─IMAP─▶ worker: email.ingest ─▶ EmailCase(NEW)
                          ─▶ ai.pipeline ─▶ AiExtraction + EmailCase(NEEDS_REVIEW)
Admin (écran AI Review) ─▶ identifie l'étudiant, corrige, confirme ─▶ Request(RECEIVED, source=EMAIL)
```

## Modules backend (`backend/app/`)

| Module | Responsabilité |
|---|---|
| `core` | configuration, DB, erreurs, middleware, santé, stockage, logs |
| `auth` | login local, sessions/JWT, `auth_identities` (prêt pour SSO/CAS/Microsoft) |
| `users` | comptes, rôles, permissions |
| `students` | profils étudiants, inscriptions par année, vérification des inscriptions |
| `academic` | années, catégories, branches, types de documents |
| `requests` | agrégat Request, machine d'état (`workflow.py`), actions (`actions.py`), numérotation |
| `documents` | validation (`validation.py`), stockage S3 privé (`storage.py`), antivirus (`scanner.py`, `scanning.py`), téléchargement autorisé (`service.py`) |
| `messages` | fil de messages par demande |
| `email` | `EmailProvider` (IMAP d'abord), ingestion, `EmailCase` |
| `ai` | `LLMProvider` (Claude, OpenAI-compatible, Ollama), prompts versionnés, pipeline |
| `notifications` | `NotificationService` (in-app en Phase 2 ; canal email en Phase 5) |
| `audit` | journal append-only |
| `admin` | dashboard et statistiques |
| `worker` | application Celery, tâches (`mail.send`, `documents.scan`), contexte (`context.py`) |

Chaque module suit `models.py`, `schemas.py`, `repository.py`, `service(s)`, `router.py`.

## Authentification et autorisation (Phase 1, implémenté)

- **Mots de passe** : argon2id. Un hash factice est vérifié quand le compte n'existe pas, pour ne pas révéler son existence par le temps de réponse.
- **Sessions** :
  - un JWT d'accès de 15 min (cookie `sd_access`, httpOnly) ;
  - un refresh token opaque, stocké hashé (SHA-256) en base, regroupé par *famille* et **renouvelé à chaque usage**. La réutilisation d'un token déjà renouvelé révoque toute la famille.
- **Révocation** :
  - logout : révocation de la famille, et le `jti` du JWT d'accès est mis en liste noire dans Redis jusqu'à son expiration ;
  - logout-all, désactivation ou changement de rôle : `users.sessions_revoked_at` invalide tous les JWT émis avant cet instant.
- **État du compte** : `is_active` et la vérification de l'email sont relus en base à **chaque requête**.
- **CSRF** : double-submit (cookie `sd_csrf` et en-tête `X-CSRF-Token`) sur toute requête modifiante portant un cookie de session.
- **Brute force** :
  - quota par IP dans Redis (connexion et inscription), configurable par l'environnement ;
  - verrouillage du compte 15 min après 5 échecs.
- **RBAC** : les routes exigent des **permissions** (`Requires(Perm.X)`). La table `role_permissions` est initialisée par migration.

| Permission | STUDENT | ADMIN | SUPER_ADMIN |
|---|:-:|:-:|:-:|
| `profile.self`, `catalog.read` | ✓ | ✓ | ✓ |
| `enrollment.self` | ✓ | | |
| `admin.access`, `dashboard.read`, `students.read`, `users.read` | | ✓ | ✓ |
| `catalog.manage`, `users.manage`, `settings.manage` | | | ✓ |
| `request.create`, `request.read_own` | ✓ | | |
| `requests.read`, `requests.process`, `requests.assign`, `requests.approve`, `requests.reject`, `enrollments.verify` | | ✓ | ✓ |

- **Identités** : la table `auth_identities` contient `LOCAL` aujourd'hui. CAS, MICROSOFT et GOOGLE pourront être branchés sans changer le modèle utilisateur.
- **Inscription** : uniquement avec un email dont le domaine figure dans `allowed_email_domains` (géré par le super-admin). L'email de vérification part par le worker Celery, puis SMTP (Mailpit en développement).

## Frontend (Phases 1 et 2, implémenté)

- Next.js 16 (App Router), shadcn/ui (Base UI, mode RTL : propriétés CSS logiques), TanStack Query.
- **i18n** : routes `/{fr|en|ar}/…` et dictionnaires JSON.
  - `t()` est typé : une clé inexistante est une erreur de compilation.
  - Des tests vérifient que les clés sont identiques dans les trois langues et que chaque code d'erreur du backend est traduit.
  - En arabe, `<html dir="rtl">`. Le choix de langue est conservé dans le cookie `NEXT_LOCALE` et dans `users.locale`.
- `proxy.ts` gère le préfixe de langue et les redirections d'ergonomie (cookie indicatif `sd_session`). **Toute autorisation réelle est faite par l'API.**
- Phase 2 : nouvelle demande, mes demandes, détail (suivi, messages, réponse, annulation), mes documents, notifications ; côté admin : liste filtrable des demandes, détail (étudiant, pièces, suivi, attribution, transitions, dépôt du document final, messages), vérification des inscriptions, tableau de bord. Les envois de fichiers passent par `FormData` ; les téléchargements par `fetch` authentifié puis un blob (jamais d'URL de stockage).
- Le client API ajoute l'en-tête CSRF. Sur une réponse 401, il rafraîchit la session une seule fois, en partageant la même requête entre appels concurrents, puis rejoue l'appel.

## Workflow d'une demande (`Request`) — Phase 2, implémenté

```
SUBMITTED ──▶ RECEIVED ──▶ IN_REVIEW ──▶ PROCESSING ──▶ APPROVED ──┬─▶ DOCUMENT_AVAILABLE ──▶ COMPLETED
  (web)     (système)        │  ▲                                  └─▶ READY_FOR_PICKUP ─────▶ COMPLETED
                             ▼  │
                     NEEDS_INFORMATION

REJECTED  : depuis RECEIVED, IN_REVIEW, NEEDS_INFORMATION, PROCESSING (admin, motif obligatoire)
CANCELLED : depuis SUBMITTED ou RECEIVED (étudiant) ; depuis tout état non terminal (admin, motif obligatoire)
```

La table des transitions est une donnée pure (`backend/app/requests/workflow.py`, `TRANSITIONS`) : source, cible, acteur (SYSTEM / STUDENT / STAFF), permission requise, commentaire obligatoire. Toutes les transitions passent par `RequestActions.transition` (`actions.py`), qui écrit `request_status_history` (append-only), l'audit et la notification de l'étudiant. Aucun endpoint ne permet de fixer un statut librement.

| Transition | Acteur | Permission | Garde |
|---|---|---|---|
| SUBMITTED → RECEIVED | système | — | automatique, dans la même transaction que la création |
| RECEIVED → IN_REVIEW | admin | `requests.process` | — |
| IN_REVIEW → NEEDS_INFORMATION | admin | `requests.process` | commentaire obligatoire, envoyé comme message `INFORMATION_REQUEST` |
| NEEDS_INFORMATION → IN_REVIEW | étudiant | propriétaire | réponse (`/respond`) : message `INFORMATION_RESPONSE` + fichiers éventuels |
| NEEDS_INFORMATION → IN_REVIEW | admin | `requests.process` | reprise manuelle |
| IN_REVIEW → PROCESSING | admin | `requests.process` | — |
| PROCESSING → APPROVED | admin | `requests.approve` | — |
| APPROVED → DOCUMENT_AVAILABLE | admin | `requests.process` | aucun item PICKUP et au moins un document `ISSUED` déposé |
| APPROVED → READY_FOR_PICKUP | admin | `requests.process` | au moins un item PICKUP ; document `ISSUED` exigé s'il y a aussi des items DIGITAL |
| DOCUMENT_AVAILABLE / READY_FOR_PICKUP → COMPLETED | admin | `requests.process` | clôture manuelle |
| … → REJECTED | admin | `requests.reject` | motif obligatoire (`status_reason`, visible par l'étudiant) |
| SUBMITTED / RECEIVED → CANCELLED | étudiant | propriétaire | au-delà de RECEIVED : `409 transition_not_allowed` |

Concurrence : la demande est verrouillée (`SELECT … FOR UPDATE`) pendant une action, et `version` assure un verrouillage optimiste (`409 concurrent_update`). La référence `REQ-YYYY-NNNNNN` est attribuée atomiquement par un upsert sur `request_sequences`.

L'API calcule pour chaque lecture de demande `available_transitions`, `can_cancel`, `can_respond`, `can_message`, `can_assign` et `can_upload_document`, d'après l'état et les permissions de l'utilisateur. L'interface n'affiche que ces actions et ne déduit jamais une permission.

### Règles de création (backend, toutes appliquées côté serveur)

- L'inscription appartient à l'étudiant et est **VERIFIED** (`422 enrollment_not_verified` sinon) ; son année et sa filière sont actives.
- Chaque type de document est actif, autorisé pour la catégorie de la filière, demandé une seule fois, en quantité ≤ `max_quantity`.
- Si un type exige un justificatif, le fichier `attachment:<document_type_id>` est obligatoire (`attachment_required`) ; tout autre fichier est refusé (`unexpected_file`).
- Requête unique `multipart/form-data` : partie `payload` (JSON) + fichiers. Les fichiers déjà envoyés au stockage sont supprimés si la transaction échoue.
- L'inscription est copiée sur la demande (année, filière, niveau) : une correction ultérieure de l'inscription ne modifie pas l'historique.

### Inscriptions

Déclarées par l'étudiant (`PENDING`, source `SELF_DECLARED`), puis vérifiées, corrigées ou refusées par un admin (`enrollments.verify`). Le refus exige une note. Le vérificateur et la date sont conservés (`reviewed_by_id`, `reviewed_at`). Une inscription vérifiée ne peut plus être supprimée par l'étudiant. La source `IMPORT` est prévue pour un futur import CSV / Apogée (non implémenté).

### Attribution

Manuelle uniquement (`requests.assign`) : l'assigné doit être un utilisateur actif dont le rôle a `requests.process`. `assigned_to_id` et le filtre `assigned=me|unassigned|<id>` préparent une attribution automatique ultérieure.

## Fichiers (Phase 3, implémenté)

### Cycle de vie d'un document

```
upload (multipart)
  → validation stricte (avant tout stockage)          refus 422, rien n'est stocké
  → copie en flux dans un fichier temporaire + SHA-256
  → stockage S3 privé, clé non devinable
  → ligne `documents` : scan_status = SCANNING          transaction commitée
  → tâche Celery `documents.scan` (file `documents`)    envoyée APRÈS le commit
  → ClamAV (INSTREAM)
        ├─ OK                → CLEAN      téléchargeable
        ├─ <signature> FOUND → INFECTED   objet déplacé en quarantaine, jamais servi
        └─ panne / erreur    → nouvelles tentatives, puis ERROR (jamais servi, réanalysable)
```

Le même pipeline sert pour les trois sources de fichiers : pièces justificatives de l'étudiant, pièces jointes de messages (des deux côtés) et documents finaux déposés par l'administration. Aucun fichier, même déposé par un admin, ne contourne l'antivirus.

### Validation (`documents/validation.py`)

- Taille maximale configurable (`MAX_UPLOAD_BYTES`), mesurée pendant la copie : un fichier trop gros est rejeté sans être lu en entier.
- Type réel détecté par les *magic bytes* : PDF, PNG ou JPEG uniquement. Un exécutable renommé `document.pdf` est refusé (`file_type_not_allowed`).
- L'extension du nom doit correspondre au contenu (`file_extension_mismatch`), et le type MIME déclaré par le navigateur, s'il est informatif, aussi (`file_mime_mismatch`). Le `Content-Type` du client n'est jamais utilisé comme vérité.
- Extensions dangereuses refusées partout dans le nom, par exemple `facture.exe.pdf` (`file_name_not_allowed`).
- Nom affiché normalisé (`safe_filename` : sans chemin, sans caractères de contrôle ni d'inversion de sens, 100 caractères). Le nom d'origine nettoyé est conservé pour le personnel (`original_filename`), jamais utilisé comme clé.

### Stockage privé (`documents/storage.py`)

- Bucket privé : aucun accès anonyme (vérifié par test sur le vrai SeaweedFS).
- Clés : `tenants/<tenant>/requests/<request_id>/<uuid aléatoire>`. Elles ne contiennent jamais le nom du fichier. Le préfixe `tenants/<tenant>` (`STORAGE_TENANT`) prépare le multi-tenant sans l'implémenter.
- Quarantaine : `quarantine/tenants/…`, après détection.
- `storage_key` n'apparaît dans aucune réponse de l'API.
- Envoi en flux (`upload_fileobj`, multipart S3 pour les gros fichiers), lecture en morceaux de 64 Ko pour l'analyse comme pour le téléchargement : le fichier n'est jamais chargé en entier en mémoire.

### Antivirus (`documents/scanner.py`, `documents/scanning.py`, `worker/tasks.py`)

- `ClamdScanner` parle directement au démon ClamAV (protocole INSTREAM sur TCP, sans dépendance). Seule une réponse explicite `OK` donne CLEAN. `… FOUND` donne INFECTED (la signature est conservée pour le personnel). Toute autre réponse, par exemple une limite de taille dépassée, est une erreur.
- **Idempotence** : la tâche verrouille la ligne (`SELECT … FOR UPDATE SKIP LOCKED`) et ne traite qu'un document encore `SCANNING`. Une tâche exécutée deux fois, ou en parallèle, ne fait rien (`SKIPPED`). Le résultat, l'audit et la notification sont écrits dans une seule transaction.
- **Redémarrage du worker** : `acks_late` et `reject_on_worker_lost` font rejouer une tâche interrompue (le document est resté `SCANNING`, la transaction ayant été annulée). Au démarrage, le worker remet aussi en file tous les documents `SCANNING` (message perdu, Redis indisponible au moment de l'envoi).
- **Panne de ClamAV** (connexion refusée, délai dépassé) : la tâche est rejouée avec un délai exponentiel (`SCAN_MAX_RETRIES`, `SCAN_RETRY_BASE_SECONDS`), puis le document passe en `ERROR / scanner_unavailable`. Pendant ce temps, l'API continue d'accepter les dépôts, mais aucun fichier n'est téléchargeable. Un admin peut relancer l'analyse d'un fichier en `ERROR` ; `python -m app.scripts.rescan --errors` le fait en masse.
- **Objet introuvable** : `ERROR / file_missing`. **Exception imprévue** : `ERROR / scan_failed`. Une exception ne rend jamais un fichier disponible (*fail closed*).
- **Garde métier** : DOCUMENT_AVAILABLE, ainsi que READY_FOR_PICKUP lorsqu'il y a des documents numériques, exige un document final CLEAN (`issued_document_not_clean`). Un document final INFECTED ou en ERROR peut être supprimé (suppression logique, objet effacé, audit conservé) puis remplacé tant que la demande est en PROCESSING ou APPROVED.
- **Notifications in-app** à l'auteur du dépôt : `DOCUMENT_INFECTED`, `DOCUMENT_SCAN_FAILED`.

### Téléchargement (`documents/service.py`)

Ordre des contrôles : authentification (401) → permission (403) → appartenance de la demande pour un étudiant (404, même réponse qu'une demande inexistante) → document de cette demande, non supprimé, visible (404) → `scan_status == CLEAN` (sinon `409 document_not_available`, avec `details.scan_status`). Le refus est audité (`DOCUMENT_DOWNLOAD_REFUSED`), tout comme le succès (`DOCUMENT_DOWNLOADED`). La réponse est diffusée en flux avec `Content-Disposition: attachment`, `Content-Length`, `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff` et `Content-Security-Policy: default-src 'none'; sandbox`. Il n'y a pas d'URL présignée.

### Audit

`DOCUMENT_UPLOADED` (type, taille, SHA-256), `DOCUMENT_SCANNED` (résultat, détail, tentatives, SHA-256), `DOCUMENT_DOWNLOADED`, `DOCUMENT_DOWNLOAD_REFUSED`, `DOCUMENT_DELETED`, `DOCUMENT_RESCAN_REQUESTED`. Ni le contenu des fichiers ni les clés de stockage ne sont écrits dans les journaux applicatifs.

### Doublons

Le SHA-256 est indexé : des fichiers identiques peuvent être retrouvés. Ils ne sont jamais supprimés automatiquement, l'historique est conservé.

### Limites connues

- ClamAV ne détecte que ce que ses signatures connaissent. Il n'y a pas d'analyse comportementale ni de nettoyage des PDF (JavaScript embarqué, etc.).
- Taille maximale : `MAX_UPLOAD_BYTES` (10 Mo) doit rester ≤ `CLAMAV_STREAM_MAX_BYTES` (`StreamMaxLength` de clamd, 25 Mo, fixé sur le conteneur par la même variable). La configuration est validée au démarrage : une configuration incohérente empêche le backend et le worker de démarrer, au lieu de laisser des fichiers finir en `ERROR`.
- **Documents délivrés** (`ISSUED`) : déposés par l'admin en PROCESSING ou APPROVED ; invisibles pour l'étudiant tant que la demande n'est pas DOCUMENT_AVAILABLE, READY_FOR_PICKUP ou COMPLETED.

## Messages et notifications (Phase 2, implémenté)

- Fil par demande, dans les deux sens, avec fichiers joints. `author_side` (STUDENT / STAFF) et `kind` (MESSAGE, INFORMATION_REQUEST, INFORMATION_RESPONSE). Le nom des agents n'est pas montré à l'étudiant (« Administration »).
- Lu / non lu : `read_at`, mis à jour quand le destinataire ouvre le fil ; les listes affichent le nombre de messages non lus.
- Mêmes règles d'accès que la demande : un autre étudiant reçoit `404`.
- Notifications **in-app** (`notifications`) : réception, changement de statut, information demandée, nouveau message, réponse de l'étudiant, attribution. Compteur dans l'en-tête (rafraîchi toutes les 30 s). L'envoi par email est prévu en Phase 5.

## Workflow d'un email entrant (`EmailCase`)

```
NEW ──▶ AI_PROCESSING ──▶ NEEDS_REVIEW ──▶ CONVERTED   (Request créée et liée)
              │                 ├────────▶ LINKED      (rattaché à une Request existante : relance, réponse)
              ▼                 └────────▶ DISMISSED   (spam, hors sujet, doublon) — motif obligatoire
            FAILED ──(relance)──▶ AI_PROCESSING
IGNORED : filtré de façon déterministe (auto-reply, bounce, Message-ID déjà vu)
```

- `EmailCase.student_id` est **nullable** : un expéditeur inconnu ou une adresse personnelle n'est jamais rejeté automatiquement. L'admin identifie l'étudiant avant la conversion.
- `Request.student_id` est **NOT NULL**.
- Au MVP, aucune conversion n'est automatique, même avec une confiance HIGH. Le flag `email_auto_convert` (désactivé) est prévu pour plus tard, une fois la précision mesurée.

## Confidentialité IA

Le `LLMProvider` déclare `is_local`. Si le fournisseur configuré est local (Ollama, vLLM), aucun appel réseau sortant n'est permis vers un fournisseur externe et il n'y a pas de bascule automatique vers un fournisseur cloud. Le contenu des emails est passé comme donnée non fiable, délimitée, sans aucun outil exposé au modèle.

## Infrastructure de développement

`docker compose up` démarre `postgres`, `redis`, `storage` (SeaweedFS, compatible S3), `clamav` (antivirus), `mailpit` (SMTP de test), les tâches ponctuelles `migrate` et `storage-init`, puis `backend`, `worker` et `frontend`. Le worker consomme les files `celery` (emails) et `documents` (analyses) et attend que ClamAV soit sain. `/health/ready` inclut maintenant `antivirus`.
