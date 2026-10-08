# API (v1)

Base: `/api/v1` (same origin as the web app, routed by Caddy). OpenAPI: `http://localhost:8000/docs` (disabled in production).

## Conventions

- **Session**: httpOnly cookies set at login: `sd_access` (JWT, 15 min, path `/api`) and `sd_refresh` (opaque, 14 days, path `/api/v1/auth`, rotated on each use).
- **CSRF**: every `POST/PATCH/PUT/DELETE` that carries a session cookie must send the `X-CSRF-Token` header, equal to the `sd_csrf` cookie. Exempt: `login`, `register`, `verify-email`, `resend-verification`.
- **Errors**: `{"error": {"code", "message", "details", "request_id"}}`. The frontend translates `code`, never `message`.
- **Authorization**: by permission (table `role_permissions`), not by role. A resource belonging to another student → `404`.
- **Pagination** (lists): `?limit=1..100&offset=` → `{items, total, limit, offset}`.
- **Uploads**: `multipart/form-data` only (`415 unsupported_media_type` otherwise). PDF, PNG and JPEG, detected from the content, 10 MB per file, 10 files per call.
- **Downloads**: streamed by the API after authorization (`Content-Disposition`, `Cache-Control: private, no-store`); storage keys and storage URLs are never exposed.

| Common code | HTTP |
|---|---|
| `not_authenticated` | 401 |
| `forbidden`, `csrf_failed`, `account_disabled`, `email_not_verified` | 403 |
| `not_found` | 404 |
| `already_exists`, `in_use`, `conflict`, `transition_not_allowed`, `concurrent_update`, `enrollment_verified` | 409 |
| `validation_error`, `invalid_reference`, `email_domain_not_allowed`, `enrollment_not_verified`, `attachment_required`, `file_type_not_allowed`, `file_too_large`, `message_required`, `issued_document_required`, `delivery_mode_mismatch`, `invalid_assignee`, … | 422 |
| `rate_limited` (`details.retry_after`) | 429 |

## Authentication `/auth`

| Method | Path | Permission | Description |
|---|---|---|---|
| POST | `/auth/register` | public, rate-limited per IP | Student registration (institutional domain only). Always `202` (no enumeration) |
| POST | `/auth/verify-email` | public | `{token}`, single use, 24 h |
| POST | `/auth/resend-verification` | public, rate-limited | Always `202` |
| POST | `/auth/login` | public, rate-limited per IP + lock after 5 failures | Sets the cookies, returns `Me` |
| POST | `/auth/refresh` | refresh cookie + CSRF | Rotation. Reusing an already-rotated token revokes the whole session family |
| POST | `/auth/logout` | CSRF | Revokes the family + denylists the access JWT (Redis) |
| POST | `/auth/logout-all` | authenticated | Revokes every session of the user |
| GET | `/auth/me` | authenticated | Profile + permissions |
| PATCH | `/auth/me` | `profile.self` | `first_name`, `last_name`, `locale` |

## Catalog (read) `/catalog` — `catalog.read`

`GET /catalog/academic-years` (ACTIVE only), `/catalog/branch-categories`, `/catalog/branches?category_id=`, `/catalog/study-levels?category_id=`, `/catalog/document-types?category_id=`. Only active entries are returned. Document types are filtered by their allowed categories.

## Student `/students/me` — `enrollment.self`

| Method | Path |
|---|---|
| GET / POST | `/students/me/enrollments` (active year, active branch, level in the same category as the branch) |
| DELETE | `/students/me/enrollments/{id}` (404 if it belongs to another student; `409 enrollment_verified` once verified) |

New enrollments are `PENDING` until an administrator verifies them.

## Student requests `/requests` — `request.create` / `request.read_own`

Another student's request (or document, or message thread) always answers `404`.

| Method | Path | Description |
|---|---|---|
| POST | `/requests` | multipart: `payload` = `{enrollment_id, items: [{document_type_id, quantity}], reason?, extra_info?}` + one `attachment:<document_type_id>` file per type that requires it. `201` → request detail (status `RECEIVED`, reference `REQ-YYYY-NNNNNN`). Rate-limited per user |
| GET | `/requests?status=` | My requests (paginated, with unread message counts) |
| GET | `/requests/summary` | Counters: `pending`, `in_progress`, `action_required`, `completed`, `closed` |
| GET | `/requests/documents` | Issued documents that are available to me |
| GET | `/requests/{id}` | Detail: items, documents, history, `available_transitions`, `can_*` flags |
| POST | `/requests/{id}/cancel` | Only from `SUBMITTED` / `RECEIVED` (`409 transition_not_allowed` afterwards) |
| GET / POST | `/requests/{id}/messages` | Thread; POST multipart `body` + `files` |
| POST | `/requests/{id}/respond` | Answer an information request: `NEEDS_INFORMATION → IN_REVIEW` |
| POST | `/requests/{id}/messages/read` | Mark the administration's messages as read |
| GET | `/requests/{id}/documents/{document_id}/download` | Authorized, audited download |

## Notifications `/notifications` — `profile.self`

`GET /notifications?unread_only=` (paginated), `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all`. Always scoped to the caller. In-app only (email delivery: Phase 5).

## Administration `/admin` — `admin.access` + the permission listed

| Method | Path | Permission |
|---|---|---|
| GET | `/admin/dashboard` | `dashboard.read` |
| GET | `/admin/students?q=` · `/admin/students/{id}` | `students.read` |
| GET | `/admin/users?role=&q=` | `users.read` |
| POST | `/admin/users` (creates ADMIN / SUPER_ADMIN) | `users.manage` |
| PATCH | `/admin/users/{id}` (`is_active`, `role`; never yourself; at least one active super-admin) | `users.manage` |
| GET / POST / DELETE | `/admin/settings/email-domains[/{id}]` | `settings.manage` |
| GET | `/admin/enrollments?status=&q=` (with reviewer name and date) | `enrollments.verify` |
| PATCH | `/admin/enrollments/{id}` `{status: VERIFIED\|REJECTED, review_note?, academic_year_id?, branch_id?, study_level_id?}` (rejection requires a note) | `enrollments.verify` |
| GET | `/admin/requests?status=&q=&academic_year_id=&branch_id=&category_id=&assigned=me\|unassigned\|<id>` | `requests.read` |
| GET | `/admin/requests/assignees` | `requests.assign` |
| GET | `/admin/requests/{id}` | `requests.read` |
| POST | `/admin/requests/{id}/transitions` `{to_status, comment?}` (state machine; comment required for `NEEDS_INFORMATION`, `REJECTED`, `CANCELLED`) | per transition: `requests.process`, `requests.approve`, `requests.reject` |
| POST | `/admin/requests/{id}/assign` `{assignee_id \| null}` | `requests.assign` |
| POST | `/admin/requests/{id}/documents` (multipart `files`, final documents, in `PROCESSING` / `APPROVED`) | `requests.process` |
| GET / POST | `/admin/requests/{id}/messages` · POST `/admin/requests/{id}/messages/read` | `requests.read` / `requests.process` |
| GET | `/admin/requests/{id}/documents/{document_id}/download` | `requests.read` |
| GET | `/admin/catalog/{entity}[/{id}]` | `catalog.read` |
| POST / PATCH / DELETE | `/admin/catalog/{entity}[/{id}]` | `catalog.manage` |

`{entity}` ∈ `academic-years`, `branch-categories`, `branches`, `study-levels`, `document-types`. Deleting an entry that is still referenced → `409 in_use` (deactivate it instead).

## Health

`GET /health/live`, `GET /health/ready` (database, Redis, storage; returns `503` without detail when a dependency is down).
