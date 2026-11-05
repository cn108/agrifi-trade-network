# AgriFi Trade Network — Agent Rules

Read at the start of every session: this file, `docs/PROJECT_STATUS.md`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, then inspect the actual repository. Do not trust conversation history alone.

## Product
Nigerian-first B2B agricultural marketplace. NOT an AI agent, crop predictor, lender, blockchain or
automated trader. No real money: payments/refunds/settlements/ledger are **simulated** and labelled so.
Spec: `AgriFi_AI_Agent_Build_Specification.md`.

## Stack
Django + DRF (`backend/`, modular monolith, `/api/v1/`), PostgreSQL authoritative, Simple JWT,
Angular + Tailwind (`web/`), .NET MAUI + SQLite outbox (`mobile/AgriFi.Mobile/` UI, `mobile/AgriFi.Mobile.Core/` logic, `mobile/AgriFi.Mobile.Tests/` xUnit; focused Android 15 emulator journeys verified, offline capture/sync journey outstanding). Legacy React in `frontend/` is preserved, not extended.

## Commands (run in `backend/`)
- Fast tests (SQLite): `$env:AGRIFI_USE_SQLITE='1'; $env:DJANGO_DEBUG='true'; python manage.py test`
- Checks: `python manage.py check` and `python manage.py makemigrations --check --dry-run`
- PostgreSQL tests (needs Docker, from repo root): `docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test`; CI also runs on PostgreSQL 16.
- Angular tests/build (from `web/`): `npm test` and `npm run build`
- MAUI compile (restore Core first; do NOT pass `-p:TargetFramework`, it leaks into Core): `dotnet restore mobile\AgriFi.Mobile.Core\AgriFi.Mobile.Core.csproj; dotnet restore mobile\AgriFi.Mobile\AgriFi.Mobile.csproj -p:TargetFrameworks=net10.0-windows10.0.19041.0; dotnet build mobile\AgriFi.Mobile\AgriFi.Mobile.csproj -p:TargetFrameworks=net10.0-windows10.0.19041.0 --no-restore` (restore Core again afterwards if its assets get clobbered)
- MAUI Core tests: `dotnet test mobile\AgriFi.Mobile.Tests` (in this sandbox the vstest host cannot connect; run the xunit.runner.console `net6.0\xunit.console.dll` on the built test dll with `DOTNET_ROLL_FORWARD=LatestMajor`, see PROJECT_STATUS)
- Test counts: Django's "Ran N" includes skipped tests; report run/skipped/passed separately.
- Never describe SQLite results as proof of PostgreSQL behaviour or concurrency.

## Engineering rules
- Never trust client identity, prices or totals. Identity = authenticated JWT only.
- Money = integer kobo; quantities = Decimal(12,3); UUID PKs; timezone-aware timestamps.
- Important invariants live in DB constraints; stock/financial changes use `transaction.atomic()` and
  `select_for_update()` (stock lock order: listing, batch, reservation; batch review locks only batch).
- Stock has ONE source of truth: the append-only `StockMovement` ledger (+ `Reservation` rows). Never store balances.
- Financial and stock history is immutable; correct with compensating entries.
- Writes to stock go only through `agrifi/inventory/services.py`.
- Don't claim anything works unless verified. No secrets in git. Don't do unrelated dependency cleanup.
- Tools: this workspace was initially not a git repo; initialize or publish a repository only when explicitly requested. Use `apply_patch` for source edits; create directories before creating files in them.

## Update docs after meaningful work
`docs/PROJECT_STATUS.md` (exact state and next tasks), `docs/DECISIONS.md`, `docs/ARCHITECTURE.md`.
