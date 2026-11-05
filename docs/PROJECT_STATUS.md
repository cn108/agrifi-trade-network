# AgriFi Trade Network — Project Status

**Updated:** 2026-11-05  
**Milestone:** MVP implementation present; release verification incomplete  
**Production readiness:** Not approved. PostgreSQL suite and a disposable restore scenario now pass locally; hosted CI, Android device verification, production deployment/operations, and external reviews remain incomplete.

## Product scope

AgriFi is a Nigerian-first B2B agricultural marketplace. Its first release covers farmer/buyer accounts, catalogue, harvest review, ledger-derived inventory, orders and disputes, simulated finance, audit, browser workflows, and offline harvest capture. Payments and settlements are simulations only. Real funds, lending, AI prediction, blockchain, and automated trading are out of scope.

## Current implementation and verification

| Area | Current evidence | State |
|---|---|---|
| Django API | SQLite suite: 280 run, 259 passed, 21 skipped, 0 failures (2026-11-05). `manage.py check` and `makemigrations --check --dry-run` pass with SQLite selected. PostgreSQL behavior is covered separately below. | Verified locally |
| PostgreSQL | PostgreSQL 16 Compose suite: 280 run, 279 passed, 1 skipped, 0 failures (2026-11-05). Clean migrations and reversal/re-application passed; PostgreSQL trigger, deferred constraint, and concurrency tests ran. Full log: `artifacts/verification/postgresql16-2026-11-05.log`. | Verified locally; CI run pending |
| Angular | 21 passed, 1 skipped; production build passes. Playwright Chromium: 5/5 tests passed against an isolated temporary SQLite API, including buyer lifecycle, operations/finance, and farmer workspace. | Verified for these journeys |
| Angular visual design | Refreshed shared palette, responsive dashboard and catalogue layouts, account surfaces, keyboard focus, and reduced-motion handling. Production build passes; the buyer dashboard loaded in the running browser at desktop width. Narrow viewport review remains pending. | Build and desktop preview verified |
| MAUI Core | 48/48 xUnit tests pass, including buffered login-body and legacy API validation error coverage. MAUI Windows target builds with 0 warnings and 0 errors after updating SQLite dependencies. `dotnet test` emitted a non-blocking NU1900 warning because vulnerability metadata access was denied. | Verified for Core tests and Windows compile |
| MAUI Android | Local `net10.0-android` build succeeds with 0 errors and produces APKs. One non-blocking XA0033 warning remains because Android tooling does not parse the Microsoft OpenJDK 21.0.13.0.2 version string. On Android 15 API 35, valid farmer sign-in loaded profile/categories and the session restored after app restart; invalid credentials displayed the API rejection, negative quantity was rejected before a local draft was saved, and an unavailable API displayed a short network message. The app stayed open through each case and was left in the signed-in workspace. | Compile and these emulator journeys verified locally; broader device coverage pending |
| Dependency security | Updated `sqlite-net-pcl` from 1.9.172 to 1.11.285 in Core and UI projects. NuGet reports no vulnerable packages for Core; `npm audit` reports 0 vulnerabilities. | Updated; recheck full platform matrix in CI |
| CI | PostgreSQL, Angular/E2E, MAUI Core tests, and Android compile workflows are defined in `.github/workflows/`; this workspace has no Git repository or remote, so hosted workflows cannot be triggered here. Local PostgreSQL and client equivalents are being run. | Hosted CI not verified |
| OpenAPI | `drf-spectacular --validate --fail-on-warn` passes using the local OpenAPI environment. | Verified locally; CI run pending |
| PostgreSQL backup/restore | Disposable PostgreSQL 16 database with demo stock/audit data and one simulated payment/journal was dumped, restored to a new database, and checked. Six table counts matched; migrations, 12 immutable/balance triggers, and journal balance passed. Log: `artifacts/verification/postgres-restore-2026-11-05.log`. | Verified for this disposable scenario; production schedule/storage pending |
| Operational monitoring | Compose API health now uses `/readyz/`; liveness/readiness probes respond locally and JSON logs carry request IDs. Alert rules and delivery are documented but no monitoring stack or alert route is deployed. | Baseline improved; monitoring service pending |
| Accounting review | Prepared `docs/ACCOUNTING_REVIEW.md` with simulated postings, questions, and reviewer record. No qualified accountant has reviewed or approved it. | External review pending |
| Production settings check | `manage.py check --deploy` on local placeholder settings reports 3 warnings: HSTS unset, SSL redirect unset, and the deliberately short check-only secret key. | Staging/proxy configuration must be supplied and rechecked |

Test counts distinguish skips from passes. SQLite results do not establish PostgreSQL trigger, transaction, or concurrency behaviour.

## Exploratory browser input checks (2026-11-05)

- Registration: blank/invalid email, mismatched passwords, overlong buyer business name, and overlong farmer display name were blocked or shown as a form error before account creation. Read-only database check confirmed the probe email was not created.
- Marketplace search: a script-like query rendered as plain search text and returned “No matching offers”; no script ran.
- Checkout: zero, negative, and sub-step quantities disabled submit. A positive quantity above available stock received a conflict error; a read-only database comparison confirmed the order count, stock movements, and reservation rows were unchanged.
- Authorization: a buyer opening `/finance` was routed back to the buyer dashboard.
- Session follow-up: one checkout attempt after a long-lived browser session was redirected to sign-in instead of showing the stock conflict; immediately after a fresh sign-in, the same invalid quantity returned the expected conflict and created no order. Verify the cookie refresh path across the five-minute access-token expiry in a browser session.

These were manual checks of the local browser client and API, not a broad fuzz or security assessment.

## Android app and error handling checks (2026-11-05)

- A seeded farmer signed in from the Android 15 API 35 emulator. The API returned 200 for login,
  farmer profile and categories. Restarting the app restored the session and reloaded the original
  profile values. No profile changes or harvest drafts were submitted.
- Wrong credentials returned HTTP 401 and a concise sign-in error. A negative harvest quantity
  showed client-side validation and the outbox stayed empty. Pointing the app at an unused local
  port produced a readable network error; the app remained responsive. The configured API URL was
  restored and the app was left signed in.
- The first Android request exposed chunked JSON bodies being rejected by Django's local WSGI test
  server. The mobile client now buffers JSON into a byte-array body with a content length. Error
  display also accepts `message`, legacy `detail`, and field validation shapes without rendering
  raw HTML. Core tests: 48 passed, 0 skipped; Android build: 0 errors, 1 XA0033 tooling warning.
- This is a focused manual emulator check, not exhaustive malformed-input, offline-sync, or physical-device coverage.

## Local demo database note

Before the Playwright API was isolated, its first runs used the pre-existing API on port 8000 and wrote test data to `backend/db.sqlite3`: one completed simulated order (2 kg sale and simulated payment) and one pending order. The pending test order was cancelled through the normal order service to release its reservation. The completed order and its append-only stock/finance history were left intact. Future Playwright runs now use a temporary SQLite database that is removed after the run.

## Remaining release work

1. Run hosted CI end to end and address platform differences; no repository remote is configured in this workspace.
2. Perform a farmer sign-in/offline capture/sync journey on Android against the API; confirm the configured Android SDK/JDK paths are available on the CI runner.
3. Configure a monitoring service and alert routes, then exercise failure/backup-freshness alerts; the current Compose readiness check and runbook are only the baseline.
4. Provide production TLS/proxy/secret/cache settings and repeat `check --deploy`.
5. Obtain qualified accounting review of the simulated chart and refund/settlement semantics. Keep all finance operations simulation-only until then.
6. Obtain legal/privacy review of the retention policy and confirm off-host retention/archive controls before deployment.
7. Gather performance/load evidence and reconcile this status with `COMPLIANCE_ASSESSMENT.md` before production approval.

## Scope decisions

- Single-seller checkout and harvest-batch-only mobile sync are intentional, documented choices.
- Identity verification is an operational profile status, not an integrated KYC service.
- No live payment provider, custody of funds, lending, or credit decision is implemented or approved.

See `ARCHITECTURE.md`, `DECISIONS.md`, `SYSTEM_DESIGN.md`, `OPERATIONS.md`, and `COMPLIANCE_ASSESSMENT.md` for design and verification detail.
