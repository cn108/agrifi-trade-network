# AgriFi Trade Network — Validation Snapshot

**Updated:** 2026-11-05  
**Assessment:** Core MVP implementation is present. Production readiness is **not approved** pending PostgreSQL, CI, Android, restore, operational, and accounting evidence.

This snapshot supersedes earlier claims in this file that the project was 95% ready, that PostgreSQL was functionally equivalent to SQLite, or that deployment could proceed before PostgreSQL verification.

## Results from this workspace

| Check | Result |
|---|---|
| Django backend on SQLite | 280 tests run; 259 passed, 21 skipped, 0 failures |
| Django checks | `manage.py check` and `makemigrations --check --dry-run` pass with SQLite selected |
| OpenAPI | Local `spectacular --validate --fail-on-warn` passes |
| Angular | 21 passed, 1 skipped; production build passes |
| Browser E2E | 5 Chromium tests pass against an isolated temporary SQLite API and disposable seeded database |
| MAUI Core | 47/47 xUnit tests pass |
| MAUI Windows | Build succeeds with 0 warnings and 0 errors |
| MAUI Android | Build blocked by missing Android SDK (XA5300) |
| Dependency audits | `npm audit` reports 0 vulnerabilities; NuGet Core scan reports no vulnerable packages after the SQLite update |
| PostgreSQL | PostgreSQL 16 Compose: 280 tests run, 279 passed, 1 skipped, 0 failures; migration reversal/re-application passed. |
| PostgreSQL backup/restore | Seeded disposable database restored from custom-format dump; table counts, migrations, 12 immutable/balance triggers, and journal sums passed. |
| CI | Workflows are configured; hosted CI cannot be triggered because this workspace has no Git repository or remote. |
| Android | Build blocked by missing Android SDK (XA5300); no device journey. |
| Operations/accounting | Readiness probe and runbook updated; alert service, production backup schedule, qualified accounting and retention reviews, and load evidence remain outstanding. |

The local production-settings check reports HSTS and HTTPS redirect are not enabled and warns about the intentionally short check-only secret. Production settings must be checked again with the real TLS proxy and secret configuration.

## Interpretation

SQLite verifies application paths that can run on SQLite only. It does not prove PostgreSQL migrations, triggers, row locks, deferred constraints, or concurrency. Browser E2E verifies only the five named local journeys. Core xUnit tests use the test harness/fake API except for shared contract assertions; they do not replace a live MAUI-to-Django device run.

## Release recommendation

Do not deploy this project as production-ready. The PostgreSQL suite and a disposable restore scenario now pass locally. Still run hosted CI, verify Android/device sync, configure operational alerting and production backup storage, and complete the accounting/privacy reviews recorded in `PROJECT_STATUS.md` and `PRODUCTION_READINESS.md`.
