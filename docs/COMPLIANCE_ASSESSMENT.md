# AgriFi Specification Compliance Assessment

**Updated:** 2026-11-05  
**Reference:** AgriFi Trade Network AI Agent Build Specification v1.0 (3 November 2026).  
**Scope:** Source/docs inspection and verification executed in the current workspace. This is not a production, legal, accounting, penetration-test, or performance certification.

## Classification

- **Verified (local)** means the named command/journey passed in this workspace; it does not imply PostgreSQL or production evidence.
- **Implemented, unverified** means code is present but required runtime/platform evidence is missing.
- **Partial** means some required behaviour or documentation is absent.
- **Deviation** means the implementation intentionally differs from the reference design and is documented.
- **Blocked** means the requirement cannot be verified here because a required external runtime/review is unavailable.

## Requirement matrix

| Specification area | Current implementation and evidence | State |
|---|---|---|
| M1 foundation, Django/DRF, custom user, PostgreSQL config, health checks | Implemented. `manage.py check`, clean PostgreSQL migrations and migration reversal/re-application pass. | Verified locally; hosted CI pending |
| Accounts, roles, profiles, JWT and object permissions | Implemented with regression tests for role/ownership paths. | PostgreSQL 16 suite passes locally |
| Catalogue and listings | Implemented with category/listing APIs, filters, server-side validation and Angular screens. | Verified on SQLite; browser coverage partial |
| Inventory and reservations | Ledger-derived balances, service-only stock writes, atomic services, idempotency, reservation lifecycle, immutable ORM and PostgreSQL trigger migrations. | PostgreSQL 16 trigger and concurrency suite passes locally |
| Orders, pricing, transitions and disputes | Single-seller checkout, server-calculated integer-kobo totals, snapshots, histories, reservations and dispute resolution. | PostgreSQL 16 transitions and locking/concurrency suite passes locally |
| Simulated payments, refunds, settlements and journal | Double-entry simulation, integer kobo, immutable records, reversals and report aggregates. No provider or real-funds integration. | PostgreSQL 16 deferred constraints pass locally; accountant review pending |
| Idempotency and mobile sync | Harvest create envelope/replay receipts delegate to shared `IdempotencyRecord` and harvest services; shared fixtures and Django contract tests exist. | Deviation; tested locally; live MAUI client run pending |
| Audit, correlation IDs, error envelope, throttling, OpenAPI | Implemented with tests and committed schema; cache defaults to per-process unless configured for shared workers. | SQLite/schema validation evidence recorded; CI/production config pending |
| Offline farmer client | SQLite outbox, owner scoping, retries/backoff, correction flow and sync receipt handling. | 47 Core xUnit tests pass; Windows compile passes; Android/live device pending |
| Browser client | Angular buyer, farmer, operations and finance workflows. 21 unit tests pass, 1 skipped; production build passes; 5 Playwright journeys pass against an isolated temporary SQLite API seeded for each run. | Verified for these tests; broader exploratory and production-origin testing pending |
| CI and clean environment | PostgreSQL, Angular/E2E, MAUI Core, and Windows-hosted Android compile workflows are defined. Hosted workflow results cannot be triggered from this non-Git workspace. | Implemented; hosted CI unverified |
| PostgreSQL migration, trigger, concurrency proof | PostgreSQL 16 Compose run: 280 tests, 279 passed, 1 skipped, 0 failures; migration reverse/reapply passed. Full log is retained under `artifacts/verification/`. | Verified locally; hosted CI remains pending |
| Backup/restore, retention, monitoring, performance | A seeded disposable PostgreSQL dump/restore passed row-count, migration, trigger, and journal-balance checks. Owner selected seven-year minimum for audit/finance and 365-day idempotency retention; purge is scheduled and tested. Monitoring service/alerts and performance evidence remain absent. | Restore verified for the test fixture; operations partial |
| Android build and live device sync | Android SDK missing locally (XA5300); a Windows-hosted CI compile job is configured but cannot be triggered without a Git remote; no device verification. | Blocked |

## Deviations and non-goals

1. Sync receipts are derived from `IdempotencyRecord`; there is no standalone `SyncOperation` table. Only `harvest_batch.create` is supported offline. This is documented in `DECISIONS.md`.
2. Order transition actions use named endpoints rather than one generic transition endpoint; the API validates the same state/role rules.
3. Payment, refund, settlement, and ledger operations are internal simulations only. Real payments/custody, lending, crop prediction, AI trading, and blockchain remain excluded by product scope.
4. Profile verification is a status workflow, not an external KYC integration.

## Decisions still required for final sign-off

- The owner selected a seven-year minimum for audit/finance and 365 days for idempotency records; obtain legal/privacy review before deployment and review any archive/deletion after the minimum period.
- A qualified accountant must review the simulated chart of accounts and cancellation/refund/fee/settlement semantics before production approval.
- PostgreSQL 16 suite and one disposable backup/restore scenario pass locally; hosted CI and production recovery evidence are still required.

## Exact verification recorded on 2026-11-05

- Backend: `AGRIFI_USE_SQLITE=1`, `DJANGO_DEBUG=true`, `python manage.py test --noinput` — **280 run, 259 passed, 21 skipped, 0 failures**.
- Backend: `python manage.py check` and `python manage.py makemigrations --check --dry-run` with SQLite — both pass. Local `manage.py check --deploy` reports 3 warnings (HSTS, SSL redirect, placeholder secret).
- OpenAPI: local `manage.py spectacular --validate --fail-on-warn` — pass.
- Web: `npm test` — **21 passed, 1 skipped**; `npm run build` — pass; `npm run e2e` — **5 passed** against a disposable temporary API/database.
- Mobile: `dotnet test mobile\AgriFi.Mobile.Tests --no-restore` — **47 passed, 0 failed**; Windows MAUI build — pass, 0 warnings/errors.
- Mobile security: NuGet reports no vulnerable transitive packages for `AgriFi.Mobile.Core` after the SQLite package update. A full platform/package matrix scan remains pending.
- Web security: `npm audit` — 0 vulnerabilities (all web dependencies).
- Android build — failed XA5300 because the Android SDK directory is unavailable.
- PostgreSQL 16 Compose — **280 run, 279 passed, 1 skipped, 0 failures**; migration reverse/reapply passes; Docker log retained at `artifacts/verification/postgresql16-2026-11-05.log`.
- PostgreSQL restore — seeded disposable database round-tripped with `pg_dump`/`pg_restore`; row counts, migrations, 12 immutability/balance triggers, and journal debit/credit totals passed. Log: `artifacts/verification/postgres-restore-2026-11-05.log`.
- Operational monitoring — Compose readiness now checks `/readyz/`; local probes and Compose syntax pass. A monitor/alert service and delivery route have not been deployed.
- Accounting — `docs/ACCOUNTING_REVIEW.md` is prepared; qualified review is pending.
- Android — build fails XA5300 because Android SDK is unavailable. Hosted Android CI cannot be triggered from this workspace.
