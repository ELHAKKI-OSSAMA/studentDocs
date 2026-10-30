# API (v1)

Base: `/api/v1` (same origin as the web app, routed by Caddy). OpenAPI: `http://localhost:8000/docs` (disabled in production).

## Conventions

- **Session**: httpOnly cookies set at login: `sd_access` (JWT, 15 min, path `/api`) and `sd_refresh` (opaque, 14 days, path `/api/v1/auth`, rotated on each use).
- **CSRF**: every `POST/PATCH/PUT/DELETE` that carries a session cookie must send the `X-CSRF-Token` header, equal to the `sd_csrf` cookie. Exempt: `login`, `register`, `verify-email`, `resend-verification`.
- **Errors**: `{"error": {"code", "message", "details", "request_id"}}`. The frontend translates `code`, never `message`.
- **Authorization**: by permission (table `role_permissions`), not by role. A resource belonging to another student → `404`.
- **Pagination** (lists): `?limit=1..100&offset=` → `{items, total, limit, offset}`.
- **Uploads**: `multipart/form-data` only (`415 unsupported_media_type` otherwise). PDF, PNG and JPEG, detected from the content (magic bytes); the extension and the declared type must agree with it. `MAX_UPLOAD_BYTES` (10 MB default) per file, 10 files per call. Errors: `file_empty`, `file_too_large`, `file_type_not_allowed`, `file_extension_mismatch`, `file_mime_mismatch`, `file_name_not_allowed` (422).
- **Antivirus**: every stored file starts `SCANNING` and is scanned asynchronously by ClamAV, then becomes `CLEAN`, `INFECTED` or `ERROR`. Clients poll the request detail.
- **Downloads**: streamed by the API after authorization, **only for `CLEAN` files** (`409 document_not_available` with `details.scan_status` otherwise). Storage keys and storage URLs are never exposed.

Document object (in request details, message attachments and issued-document lists):

```json
{"id", "kind", "filename", "mime_type", "size_bytes", "sha256", "scan_status", "scan_reason",
 "scanned_at", "can_download", "request_item_id", "message_id", "created_at",
 "original_filename", "scan_detail"}
```

`scan_reason` is a code (`virus_detected`, `scanner_unavailable`, `scanner_error`, `file_missing`, `scan_failed`). `original_filename` and `scan_detail` (with the signature name) are only filled for staff.

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
| GET | `/requests/{id}/documents/{document_id}/download` | Authorized, audited download (CLEAN files only, `409` otherwise) |

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
| POST | `/admin/requests/{id}/documents` (multipart `files`, final documents, in `PROCESSING` / `APPROVED`; scanned like any upload) | `requests.process` |
| DELETE | `/admin/requests/{id}/documents/{document_id}` (final document, before delivery: soft delete, object removed, to replace it) | `requests.process` |
| POST | `/admin/requests/{id}/documents/{document_id}/rescan` (only from `ERROR`, else `409 rescan_not_allowed`) | `requests.process` |
| GET / POST | `/admin/requests/{id}/messages` · POST `/admin/requests/{id}/messages/read` | `requests.read` / `requests.process` |
| GET | `/admin/requests/{id}/documents/{document_id}/download` (CLEAN files only) | `requests.read` |
| GET | `/admin/catalog/{entity}[/{id}]` | `catalog.read` |
| POST / PATCH / DELETE | `/admin/catalog/{entity}[/{id}]` | `catalog.manage` |

`{entity}` ∈ `academic-years`, `branch-categories`, `branches`, `study-levels`, `document-types`. Deleting an entry that is still referenced → `409 in_use` (deactivate it instead).

## Inbound email `/admin/emails` — `admin.access` + the permission listed (no student endpoint)

| Method | Path | Permission |
|---|---|---|
| GET | `/admin/emails?status=&confidence=&q=&assigned=me\|unassigned` | `emails.read` |
| GET | `/admin/emails/stats` (counts, last mailbox poll, AI provider and whether it is local) | `emails.read` |
| GET | `/admin/emails/{id}` (sanitized text and HTML, candidates, AI proposal, correction, reviews, attachments, `can_*`) | `emails.read` |
| GET | `/admin/emails/{id}/raw` (original `.eml`, `Content-Disposition: attachment`, `nosniff`, audited) | `emails.read_raw` |
| GET | `/admin/emails/{id}/documents/{document_id}/download` (CLEAN only, else `409 document_not_available`) | `emails.read` |
| POST | `/admin/emails/{id}/documents/{document_id}/rescan` (from `ERROR`) | `emails.process` |
| POST | `/admin/emails/{id}/assign` `{assignee_id \| null}` | `emails.process` |
| POST | `/admin/emails/{id}/student` `{student_id, comment?}` | `emails.process` |
| PUT | `/admin/emails/{id}/extraction` (human correction, stored next to the AI proposal) | `emails.process` |
| POST | `/admin/emails/{id}/convert` `{student_id, enrollment_id, items[{document_type_id, quantity, attachment_ids[]}], reason?, extra_info?, version}` → `201` request (source `EMAIL`) | `emails.convert` + `requests.process` |
| POST | `/admin/emails/{id}/link` `{request_id, attachment_ids[], as_information_response, version}` | `emails.process` |
| POST | `/admin/emails/{id}/dismiss` · `/ignore` `{reason}` | `emails.dismiss` |
| POST | `/admin/emails/{id}/reopen` `{comment?}` | `emails.dismiss` |
| POST | `/admin/emails/{id}/retry` (FAILED, except `too_large`) · `/reextract` (when an AI provider is configured) | `emails.process` |

Errors: `409 email_case_status_conflict` (action not possible in this status), `409 concurrent_update` (stale `version` or concurrent action), `422 student_mismatch`, `422 attachment_not_clean`, `422 invalid_attachment`, `422 invalid_student`, `409 retry_not_possible`, `409 ai_disabled`, plus every request-creation error of Phase 2 (`enrollment_not_verified`, `document_type_not_allowed`, `quantity_exceeded`, `attachment_required`).

## Health

`GET /health/live`, `GET /health/ready` (database, Redis, storage, antivirus; returns `503` without detail when a dependency is down).
