# Operations: configuration, scheduling, backup and restore

Status legend: **Verified** = executed in this workspace; **Unverified** = written but never executed (reason given).

## Environment variables
| Variable | Default | Purpose |
|---|---|---|
| `DJANGO_SECRET_KEY` | none (required when not testing) | Signing key. Never commit. |
| `DJANGO_DEBUG` | false | Enables debug and open OpenAPI/Swagger routes. Keep false in production. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts. |
| `DJANGO_CORS_ALLOWED_ORIGINS` | Angular dev origin | Browser origins allowed to call the API. |
| `AGRIFI_USE_SQLITE` / `AGRIFI_SQLITE_PATH` | unset | Use SQLite (dev/fast tests only). |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_CONN_MAX_AGE` | agrifi / agrifi / empty / localhost / 5432 / 60 | PostgreSQL connection. |
| `DJANGO_CACHE_DB_TABLE` | unset | Shared DB cache for throttling across workers. Run `python manage.py createcachetable` once. |
| `THROTTLE_AUTH_IP`, `THROTTLE_LOGIN_EMAIL` | `30/min`, `10/min` | Auth throttle rates. |
| `DJANGO_NUM_PROXIES` | `0` | Number of trusted reverse proxies in front of the API. `0` throttles on the socket address and ignores `X-Forwarded-For` (spoof-proof but, behind a proxy, every client shares the proxy's address; set this to the real proxy count). |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | off | Trust `X-Forwarded-Proto` from a TLS-terminating proxy (the proxy must overwrite client-supplied values). |
| `DJANGO_SECURE_SSL_REDIRECT` | off | Redirect HTTP to HTTPS. |
| `DJANGO_HSTS_SECONDS`, `DJANGO_HSTS_INCLUDE_SUBDOMAINS` | `0`, off | HSTS; enable only once HTTPS is permanent. `manage.py check --deploy` reports the remaining opt-ins (include-subdomains, preload). |
| `JWT_REFRESH_COOKIE_NAME`, `_SAMESITE`, `_MAX_AGE`, `_SECURE` | agrifi_refresh / Lax / 604800 / see compose | Refresh cookie. Set secure true behind HTTPS. |
| `ORDER_RESERVATION_TTL_HOURS` | 48 | Order stock hold duration. |
| `DJANGO_LOG_LEVEL` | INFO | JSON logs carry `request_id`. |
| `MAINTENANCE_INTERVAL_SECONDS` | 60 | Compose scheduler period. |

## Scheduled jobs
`python manage.py run_maintenance` runs, in order: `expire_reservations`, `cancel_expired_orders`, `purge_expired_refresh_tokens`, and `purge_old_idempotency_records`. Idempotency replay records are retained for 365 days from creation, then eligible for deletion; clients must not depend on replays after that window. A failing job is logged and does not stop the others; the command then exits non-zero. Jobs are idempotent and safe to overlap (stock changes lock rows).

- **Compose:** the `scheduler` service runs `run_maintenance --interval ${MAINTENANCE_INTERVAL_SECONDS:-60}`. *Unverified* (Docker daemon not running).
- **Linux cron (every minute):** `* * * * * cd /app && python manage.py run_maintenance`
- **Windows Task Scheduler:** action `python manage.py run_maintenance` in `backend\`, repeat every 1 minute.
- **Verified:** command logic and failure isolation (`agrifi/accounts/test_maintenance.py`, SQLite); the idempotency purge age boundary is covered by `agrifi/idempotency/tests.py`.

## Operational monitoring
The application exposes separate probes: `/healthz/` is process liveness; `/readyz/` checks PostgreSQL and returns only a generic `503` when the database cannot be reached. The Compose API health check uses readiness so an API container with a disconnected database is not reported healthy. These probes and structured JSON stdout logs are a baseline, not a complete monitoring service.

Route container health and JSON logs to the deployment's existing monitoring stack. Alert on: API readiness failures; repeated API 5xx responses or elevated request duration; PostgreSQL unavailable, low disk, or exhausted connections; repeated/non-zero maintenance-job exits; and no successful off-host backup within 24 hours. Page on sustained API/database outage; send other alerts to the operations queue. Tune thresholds from a measured baseline before production. Include `request_id` when investigating errors; do not export credentials, request bodies, tokens, or sensitive user data into logs or alert payloads.

Monitoring/alert delivery, latency metrics, backup freshness checks, and alert routing have **not** been deployed or end-to-end verified in this workspace. `/readyz/` validates only database connectivity; it does not verify migrations, writable capacity, scheduled jobs, or external services.

## Backup and restore
Money and stock history are immutable ledgers, so a restore must be a whole-database restore, never a partial row edit. Retain audit and finance records for at least seven years; at that point review legal/accounting requirements before archival or deletion. Never mutate posted history to satisfy retention.

### PostgreSQL test run (2026-11-05)
The isolated PostgreSQL 16 Compose run completed successfully: **280 tests run, 279 passed, 1 skipped, 0 failures**. The run checked fresh migrations, reversal/re-application of trigger migrations, PostgreSQL constraints/triggers, and row-lock/concurrency paths. The SQLite-only backup test is the single expected skip. Full output: `artifacts/verification/postgresql16-2026-11-05.log`.

The previous PostgreSQL run (2026-11-04) reported five errors. The rerun exposed a finance `TransactionTestCase` setup collision caused by serialized rollback re-inserting content types after `post_migrate`; the PostgreSQL finance test now recreates only its four system ledger accounts in `setUp`, without serialized rollback. The isolated test stack uses an ephemeral PostgreSQL data directory and is separate from application data. This local run is not a hosted CI result.

### PostgreSQL (production)
Backup (custom format, compressed):
```
pg_dump --format=custom --no-owner --file agrifi_YYYYMMDD.dump "$DB_NAME"
```
Restore into a **new, empty** database, then verify before switching traffic:
```
createdb agrifi_restore
pg_restore --no-owner --dbname agrifi_restore agrifi_YYYYMMDD.dump
DB_NAME=agrifi_restore python manage.py migrate --check
```
Verification after restore (must pass): `GET /api/v1/finance/reports/` returns `trial_balance` entries all with `balanced: true`; stock ledger totals match reservations; the immutability triggers exist (`\d+ inventory_stockmovement`, `audit_auditevent_immutable`). Schedule daily backups, keep off-host copies, and test a restore at least quarterly. Do not use `pg_restore --clean` against the live database.

**Verified 2026-11-05 in a disposable PostgreSQL 16 environment:** migrated and seeded demo records, created one simulated payment/journal, produced a custom-format `pg_dump`, restored into a new scratch database, compared user/listing/stock/audit/journal/journal-line row counts, ran `manage.py migrate --check`, checked all 12 immutable/balance triggers, and confirmed journal headers and lines balance. The scratch environment was removed after the run. Log: `artifacts/verification/postgres-restore-2026-11-05.log`. This validates the restore procedure for that fixture only; it is not a production backup schedule, off-host storage test, or recovery-time exercise.

### SQLite (development only)
Copy the file while the server is stopped, or use `sqlite3 db.sqlite3 ".backup backup.sqlite3"`. Restore by replacing the file while stopped. **Verified** (SQLite online-backup API, `agrifi/test_backup_restore.py`): the copy passes `integrity_check` and `foreign_key_check` and has identical row counts.

## Deployment checklist (unverified end to end)
1. Set the variables above (secret key, DB password, hosts, CORS, secure cookie).
2. `docker compose up --build` (postgres, migrate, api, scheduler) or equivalent.
3. `python manage.py createcachetable` when `DJANGO_CACHE_DB_TABLE` is set.
4. Terminate TLS in front of the API; `/healthz/` is the health endpoint.
5. Ship JSON logs; search by `request_id` (also returned in the `X-Request-ID` header and error body).
6. CI (`.github/workflows/backend.yml`) runs migrations, reversal, schema validation and tests on PostgreSQL 16; it has never executed (no git remote).
