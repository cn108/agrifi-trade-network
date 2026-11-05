# Production Readiness — AgriFi Trade Network

**Updated:** 2026-11-05  
**Decision:** **Not approved for production.** Core MVP workflows are implemented, but database, deployment, recovery, Android, and operational evidence is incomplete.

## Evidence recorded in this workspace

- Backend on SQLite: 280 tests run, 259 passed, 21 skipped, no failures. Django system check and migration-drift check passed with SQLite selected.
- PostgreSQL: 280 run, 279 passed, 1 skipped, 0 failures against PostgreSQL 16 in Compose on 2026-11-05. Clean migration, trigger reversal/re-application, trigger, and concurrency paths passed. Full log: `artifacts/verification/postgresql16-2026-11-05.log`.
- Angular: 21 passed, 1 skipped; production build passed; 5 Playwright Chromium tests passed against an isolated temporary SQLite API and disposable seeded database.
- MAUI: 47 Core tests passed; Windows target build passed. Android build fails with XA5300 because Android SDK is unavailable.
- Dependency checks: `npm audit` found 0 vulnerabilities; NuGet found no vulnerable packages for MAUI Core after the SQLite package update. Full mobile platform matrix scan is pending.
- CI workflows are configured but cannot be triggered from this workspace because it has no Git repository or remote. A disposable PostgreSQL backup/restore check passed on 2026-11-05; production backup scheduling, off-host storage, monitoring/alert delivery, production deployment, and load targets remain unverified.
- `manage.py check --deploy` with placeholder local settings reports HSTS and HTTPS redirect not enabled plus a warning for the short test-only secret. Validate those settings with the real TLS proxy/staging configuration before release.

## Release gates

- [x] PostgreSQL 16 Compose suite passes locally, including migration reversal/reapplication and PostgreSQL-only tests. Hosted CI result remains pending.
- [ ] Green full CI run (backend, Angular unit tests/build/E2E, MAUI Core).
- [ ] Android target builds in CI and the critical farmer sync journey is verified on a device or emulator.
- [x] PostgreSQL backup and scratch-database restore are executed and recorded for a seeded disposable database. Production backup scheduling, off-host storage, and recovery-time testing remain pending.
- [ ] Production configuration is reviewed: secrets, hosts, CORS/CSRF, HTTPS, secure cookies, cache/throttling, logging, and scheduler.
- [ ] Owner-selected retention policy (7-year minimum audit/finance; 365-day idempotency replay window) receives legal/accounting review; monitoring and incident/rollback policies are approved and exercised.
- [ ] Qualified accounting review approves the simulated chart and posting semantics before any production sign-off.
- [ ] Performance and security claims have reproducible evidence; none are inferred from local unit tests.

## Scope boundary

The product is a conventional marketplace with simulated financial records. Do not connect payment providers, move or custody funds, add lending/credit decisions, or claim legal escrow or regulatory compliance. Refer to `PROJECT_STATUS.md` for current results and `OPERATIONS.md` for environment and recovery procedures.
