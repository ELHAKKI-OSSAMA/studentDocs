# Base de données (PostgreSQL 17)

Conventions :
- clés primaires `uuid` (`gen_random_uuid()`) ;
- dates `timestamptz` ;
- `created_at` et `updated_at` partout (trigger `set_updated_at`) ;
- contraintes nommées de façon déterministe ;
- libellés administrables en `jsonb` i18n `{"fr": "...", "en": "...", "ar": "..."}` ;
- enums stockés en `VARCHAR` avec contrainte `CHECK` (migrations plus simples que les enums natifs PostgreSQL).
- multi-établissement : **reporté**. Pas de `tenant_id` au MVP, l'ajout se fera par migration le moment venu.

> **État** : les sections *Identité et accès*, *Référentiel académique* et *Étudiants* sont implémentées (migration `0002`). Les sections suivantes décrivent le schéma cible des phases 2 à 5.

Extensions installées par la migration `0001` : `pgcrypto`, `citext`, `pg_trgm`.

## Identité et accès

```
users(id, email CITEXT UNIQUE, password_hash NULL, role (STUDENT|ADMIN|SUPER_ADMIN), first_name, last_name,
      locale (fr|en|ar), is_active, email_verified_at, last_login_at, failed_login_count, locked_until,
      sessions_revoked_at)          -- JWT émis avant cet instant = refusés
auth_identities(id, user_id FK CASCADE, provider (LOCAL|CAS|MICROSOFT|GOOGLE), subject, last_used_at,
      UNIQUE(provider, subject))     -- prépare le SSO
email_verification_tokens(id, user_id FK, token_hash UNIQUE, created_at, expires_at, used_at)
refresh_tokens(id, user_id FK, family_id (index), token_hash UNIQUE, created_at, expires_at,
      rotated_at, revoked_at, ip INET, user_agent)
permissions(code PK, description)
role_permissions(role, permission_code FK, PK(role, permission_code))   -- données insérées par migration
allowed_email_domains(id, domain CITEXT UNIQUE, is_active)
```

## Référentiel académique

```
academic_years(id, label UNIQUE '2026-2027', start_date, end_date, status ENUM(ACTIVE, ARCHIVED),
               CHECK(end_date > start_date))
branch_categories(id, code UNIQUE, name_i18n, sort_order, is_active)      -- Licence, Master, Doctorat…
branches(id, category_id FK RESTRICT, code, name_i18n, is_active, UNIQUE(category_id, code))
study_levels(id, category_id FK RESTRICT, code, name_i18n, sort_order, is_active, UNIQUE(category_id, code))
document_types(id, code UNIQUE, name_i18n, description_i18n, delivery_mode (DIGITAL|PICKUP),
               requires_attachment, max_quantity CHECK 1..10, processing_days CHECK 0..90, is_active)
document_type_categories(document_type_id FK, category_id FK, PK)   -- aucune ligne = toutes catégories
```

Les types de documents sont désactivés plutôt que supprimés dès qu'ils sont référencés.

## Étudiants

```
students(id, user_id FK UNIQUE CASCADE, student_number UNIQUE NULL)    -- noms dans users (minimisation)
student_enrollments(id, student_id FK CASCADE, academic_year_id FK RESTRICT, branch_id FK RESTRICT,
                    study_level_id FK RESTRICT, UNIQUE(student_id, academic_year_id, branch_id),
                    status CHECK (PENDING | VERIFIED | REJECTED) DEFAULT PENDING,
                    source CHECK (SELF_DECLARED | ADMIN | IMPORT) DEFAULT SELF_DECLARED,
                    reviewed_by_id FK users SET NULL, reviewed_at, review_note)   -- index (status)
-- Pas de table `admins` : le rôle et les permissions suffisent (ajout si des attributs propres apparaissent).
```

## Demandes (migration `0003_requests_workflow`)

```
requests(id, reference UNIQUE 'REQ-2026-000123', student_id FK NOT NULL, enrollment_id FK NOT NULL,
         academic_year_id FK, branch_id FK, study_level_id FK,        -- copie de l'inscription
         source CHECK (WEB | EMAIL | ADMIN_CREATED),
         status CHECK (SUBMITTED, RECEIVED, IN_REVIEW, NEEDS_INFORMATION, PROCESSING, APPROVED,
                       READY_FOR_PICKUP, DOCUMENT_AVAILABLE, COMPLETED, REJECTED, CANCELLED),
         priority CHECK (LOW | NORMAL | HIGH | URGENT), assigned_to_id FK users NULL,
         reason NULL, extra_info NULL, status_reason NULL,           -- motif de refus / d'annulation
         submitted_at, closed_at NULL, version INT,                  -- verrouillage optimiste
         created_at, updated_at)
request_items(id, request_id FK CASCADE, document_type_id FK, quantity CHECK (1..10), position,
              UNIQUE(request_id, document_type_id))
request_status_history(id BIGINT, request_id FK, from_status NULL, to_status, actor_user_id NULL,
                       actor_role (STUDENT | ADMIN | SUPER_ADMIN | SYSTEM), comment NULL, created_at)
                       -- append-only (trigger forbid_modification)
request_sequences(year INT PK, last_value INT)   -- numérotation atomique : INSERT … ON CONFLICT DO UPDATE … RETURNING
```

Index : `(status, created_at)`, `(student_id)`, `(assigned_to_id)`, `(academic_year_id)`, `(branch_id)`. La détection de doublons et le lien `email_case_id` arriveront avec l'intégration email (Phase 4).

## Messages et fichiers

```
request_messages(id, request_id FK, author_user_id FK, author_side CHECK (STUDENT | STAFF), seq BIGINT IDENTITY,
                 kind CHECK (MESSAGE | INFORMATION_REQUEST | INFORMATION_RESPONSE), body, read_at NULL, created_at)
                 -- index (request_id, seq) ; le fil est trié par seq (indépendant de l'horloge)
documents(id, request_id FK, request_item_id FK NULL, message_id FK NULL,
          kind CHECK (ATTACHMENT | ISSUED | MESSAGE),
          filename,                     -- nom affiché normalisé
          original_filename NULL,       -- nom envoyé, nettoyé (personnel uniquement)
          mime_type,                    -- détecté sur le contenu
          size_bytes, sha256,           -- calculés sur le contenu réel
          storage_key UNIQUE,           -- tenants/<tenant>/requests/<id>/<uuid> ou quarantine/…
          scan_status CHECK (NOT_SCANNED | SCANNING | CLEAN | INFECTED | ERROR) DEFAULT SCANNING,
          scan_detail NULL,             -- virus_detected:<signature> | scanner_unavailable | scanner_error
                                        -- | file_missing | scan_failed
          scan_attempts INT DEFAULT 0, scanned_at NULL, quarantined_at NULL,
          deleted_at NULL, deleted_by_id FK users NULL,   -- suppression logique (remplacement)
          uploaded_by_id FK, created_at)
          -- index (sha256) : doublons ; index partiel (scan_status) WHERE scan_status = 'SCANNING' : reprise
```

`storage_key` reste interne : l'API ne l'expose jamais. Seul un document `CLEAN` et non supprimé est téléchargeable. La migration `0004_document_scanning` fait passer en `SCANNING` les fichiers stockés avant l'antivirus (`NOT_SCANNED` / `PENDING`) ; le worker les analyse à son démarrage. Les notes internes entre admins et les pièces jointes d'emails viendront avec les phases suivantes.

## Email et IA

```
email_accounts(id, tenant_id, provider ENUM(IMAP, MS_GRAPH, GMAIL), address, settings_encrypted BYTEA, is_active)
email_messages(id, account_id FK, message_id_header UNIQUE, provider_uid, in_reply_to NULL,
               from_address CITEXT, from_name, subject, body_text, received_at, raw_storage_key)
email_cases(id, tenant_id, email_message_id FK UNIQUE,
            status ENUM(NEW, AI_PROCESSING, NEEDS_REVIEW, CONVERTED, LINKED, DISMISSED, FAILED, IGNORED),
            student_id FK NULL,                 -- identifié automatiquement (règles) ou par l'admin
            identification_method ENUM(SENDER_EMAIL, STUDENT_NUMBER, ADMIN_MANUAL) NULL,
            linked_request_id FK NULL, flags jsonb,   -- ambiguous, possible_duplicate, injection_suspected…
            reviewed_by FK NULL, reviewed_at, dismiss_reason NULL)
ai_extractions(id, email_case_id FK, provider, model, prompt_version, is_local_provider,
               latency_ms, tokens_in, tokens_out, output jsonb, confidence NUMERIC(4,3),
               confidence_level ENUM(HIGH, MEDIUM, LOW), rule_violations jsonb, error NULL,
               human_decision ENUM(CONFIRMED, CORRECTED, REJECTED) NULL, corrected_output jsonb NULL,
               created_at)
```

## Notifications et audit

```
notifications(id, user_id FK CASCADE, type, request_id FK NULL, reference NULL, status NULL,
              read_at NULL, created_at)      -- index (user_id, read_at) ; in-app uniquement en Phase 2
audit_logs(id BIGINT, actor_user_id NULL, action, entity, entity_id, ip INET NULL, details JSONB, created_at)
           -- append-only (trigger forbid_modification) ; index (entity, entity_id), (created_at), (actor_user_id)
```

Actions auditées en Phase 2 et 3 : `REQUEST_CREATED`, `STATUS_CHANGED`, `REQUEST_ASSIGNED`, `DOCUMENT_UPLOADED`, `DOCUMENT_DOWNLOADED`, `MESSAGE_SENT`, `ENROLLMENT_REVIEWED`, puis en Phase 3 `DOCUMENT_SCANNED`, `DOCUMENT_DOWNLOAD_REFUSED`, `DOCUMENT_DELETED`, `DOCUMENT_RESCAN_REQUESTED`.

Prévu pour la Phase 5 :

```
notification_deliveries(id, notification_id FK, channel (IN_APP | EMAIL), status, attempts, last_error, sent_at)
```

## Migrations

Les migrations Alembic se trouvent dans `backend/alembic/versions/`. Le test `test_models_and_migrations_are_in_sync` échoue si un modèle ORM diverge des migrations. Chaque phase ajoute ses tables.
