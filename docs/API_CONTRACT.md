# API Contract

The machine-readable contract is [openapi.yml](./openapi.yml) (drf-spectacular, validated with `--fail-on-warn`, 44 paths). Shared client/server fixtures live in `contracts/` and are asserted by both the Django and MAUI tests. This document records the conventions; it does not duplicate every path.

Base path `/api/v1/`. Interactive docs `/api/v1/docs/` and schema `/api/v1/schema/` are open only when `DJANGO_DEBUG` is on, otherwise operations-admin only.

## Authentication
Simple JWT bearer tokens. Access lifetime 5 minutes, refresh 7 days with rotation and JTI revocation. `POST auth/register/`, `auth/login/`, `auth/refresh/`, `auth/logout/`, `GET auth/me/`. Identity is the token only; client-supplied identity, prices and totals are never trusted. Registration returns an identical 201 for existing emails (no enumeration).

## Request correlation
Every response carries `X-Request-ID` (an inbound valid id is echoed, otherwise generated). The same id appears in logs and in error bodies.

## Error envelope
```json
{"code": "validation_error", "message": "...", "detail": "...", "request_id": "...", "fields": {"quantity": ["..."]}}
```
`fields` appears for validation errors. Codes: `validation_error`, `not_authenticated`, `permission_denied`, `not_found`, `method_not_allowed`, `throttled` (429), `idempotency_conflict` (409), and domain codes raised by business rules. Unhandled errors return a JSON 500 with the same envelope and no stack trace.

## Pagination and filtering
List endpoints return `{count, next, previous, results}` (page size 25). Audit events support filtering; finance reports accept ISO `start`/`end`.

## Idempotency
Mutating create endpoints take a client-generated key in the request body: `client_sync_id` (harvest batches), `client_request_id` (orders, allocations, finance postings). There is no `Idempotency-Key` header. Same key + same payload returns the stored result (200); same key + different payload returns 409 `idempotency_conflict`. Never reuse a key for a different payload. Replay records are retained for 365 days after creation; a client must not rely on replay after that window.

## Resource groups (all in `openapi.yml`)
| Group | Paths | Who |
|---|---|---|
| Auth/profiles | `auth/*`, `auth/profiles/farmer|buyer/` | any / own role |
| Catalog | `categories/`, `listings/` (+ `allocate`, `deallocate`, `stock`) | read: authenticated; write: farmer / ops |
| Harvest | `harvest-batches/` (+ `accept`, `reject`) | farmer (own), ops review |
| Stock | `stock-movements/` | ops, owner-scoped |
| Orders | `orders/` (+ `confirm`, `ship`, `deliver`, `complete`, `cancel`, `dispute`), `disputes/` (+ `resolve`) | buyer/seller/ops per transition |
| Finance (simulated) | `simulated-payments/`, `simulated-refunds/`, `simulated-settlements/`, `finance/journal-entries/`, `finance/ledger-accounts/`, `finance/reports/` | buyer pays; finance operator / ops read |
| Audit | `audit-events/` | operations admin, read-only |
| Sync | `sync/operations/` | farmer |

## Sync operations (mobile)
`POST sync/operations/`
```json
{"operation_id": "<uuid>", "operation_type": "harvest_batch.create", "schema_version": 1,
 "payload": {"category": "<uuid>", "quantity": "10.500", "unit_code": "kg", "harvested_on": "2026-01-15", "notes": "", "client_sync_id": "<same uuid>"}}
```
Receipt: `{operation_id, operation_type, schema_version, status, replayed, resource_id, processed_at, result}` where `result` is the harvest batch. 201 first application, 200 replay, 409 payload conflict, 400 validation (`payload.client_sync_id` must equal `operation_id`; compared as UUIDs), 401 unauthenticated, 403 non-farmer. `GET sync/operations/{operation_id}/` returns the receipt for the caller's own operations (lowercase UUID only). Only `harvest_batch.create` exists; anything else is 400. Fixtures: `contracts/sync-harvest-create.request.json`, `contracts/sync-harvest-create.receipt.json`.

## Status values
Harvest: `submitted`, `accepted`, `rejected` (MAUI also has local `pending`, `failed`). Orders: `pending`, `confirmed`, `shipped`, `delivered`, `completed`, `cancelled`, `disputed`, `dispute_resolved`.

## Verification state
Shared Django/MAUI contract and reliability tests pass locally; the PostgreSQL 16 suite also passes in Compose. The MAUI client has not yet been run against a live Django service on Android or a device.
