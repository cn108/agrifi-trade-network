# System Design Specification

Describes the system as built. For rationale see [DECISIONS.md](./DECISIONS.md); for runbooks [OPERATIONS.md](./OPERATIONS.md); module detail [ARCHITECTURE.md](./ARCHITECTURE.md).

## 1. Components
| Component | Tech | State |
|---|---|---|
| API | Django + DRF modular monolith, `/api/v1/` | Implemented, SQLite-tested |
| Database | PostgreSQL 16 (authoritative); SQLite for fast tests | PostgreSQL 16 suite and disposable restore pass locally; hosted CI pending |
| Web console | Angular + Tailwind (`web/`) | Unit tests, production build, and five browser journeys against an isolated temporary API pass; broader journeys and production-origin behaviour remain unverified |
| Mobile | .NET MAUI + SQLite outbox (`mobile/`), UI-free `AgriFi.Mobile.Core` | Core tested (47); Android build not verified |
| Legacy web | React (`frontend/`) | Preserved, not extended |
| Scheduler | `manage.py run_maintenance` (compose `scheduler` service) | Tested on SQLite; container unverified |

## 2. Backend modules
`accounts` (auth, roles, profiles) , `catalog`, `inventory` (harvest, stock ledger, reservations; the only writer of stock via `services.py`), `orders`, `finance` (simulated), `idempotency`, `audit`, `sync`, plus cross-cutting `request_context`, `api_errors`, `throttles`, `openapi`, `pagination`. Apps depend downward: orders and finance call inventory/idempotency services; audit is written by services inside the same transaction.

## 3. Key flows
- **Harvest to stock:** farmer submits batch (idempotent) -> ops accepts (batch locked, receipt movement appended) or rejects with reason -> farmer corrects by resubmission linked to the rejected batch -> ops allocates stock to a listing (movement).
- **Order:** buyer creates order (server prices from listing snapshots; stock reserved with expiry) -> seller confirms -> ship (stock consumed, FIFO sale movements) -> deliver -> complete. Cancel/expiry releases reservations. Dispute freezes completion until resolved.
- **Simulated finance:** payment/refund/settlement each post one balanced journal (one per source, enforced by constraint); reports aggregate the immutable journal per currency.
- **Mobile sync:** draft saved locally -> `POST sync/operations/` with `operation_id` = draft key -> receipt updates the draft; a replay or lost response is safe because the key never changes.

## 4. Cross-cutting design
- **Identity and authorisation:** JWT only; role permission classes plus per-object ownership filtering in querysets.
- **Integrity:** DB constraints first; append-only ledgers with ORM guards (and PG triggers, unverified); compensating entries for corrections.
- **Concurrency:** `transaction.atomic()` + `select_for_update()`, fixed lock order (listing, batch, reservation).
- **Idempotency:** record-first with a unique `(owner, scope, key)` constraint; the constraint, not a prior read, is authoritative under races. Shared conflict response (DECISIONS 44).
- **Observability:** `X-Request-ID` in logs and errors; JSON log lines; audit events for auth, review, stock, order and finance actions.
- **Abuse control:** throttles on login (IP and email hash), register, refresh; per-process cache unless `DJANGO_CACHE_DB_TABLE` is set.

## 5. Mobile reliability design
Outbox rows survive restarts. `SyncPolicy`: exponential backoff (5 s base, 15 min cap, ±25% jitter), 8 retryable attempts, then parked as `failed` for manual retry; backoff time is persisted (`NextAttemptAtUtc`). Retryable: 5xx, 408, 429, network errors, timeouts. 401 stops the pass without spending retries. Other 4xx are permanent. Cancellation propagates and leaves the draft queued. A resend always reuses the original operation id (DECISIONS 45).

## 6. Deployment
`docker-compose.yml`: postgres, api, worker/scheduler. `docker-compose.test.yml`: throwaway PostgreSQL run of migrations (with reversal) and the full suite. CI: `.github/workflows/backend.yml` (PostgreSQL 16, OpenAPI validation) and `clients.yml` (Angular, MAUI Core, Windows-hosted Android compile). **No workflow has executed.** The local Chromium Playwright suite passed five journeys on 2026-11-05 against a temporary SQLite API and disposable seeded database. Maintenance also purges idempotency replay records older than 365 days; audit and finance records have a seven-year minimum retention period subject to review before deletion.

## 7. Not implemented
Real payment/escrow, notifications, external KYC, live monitoring/alerting, audit/finance archival after the seven-year minimum, multi-region/HA, mobile operation types beyond harvest create.
