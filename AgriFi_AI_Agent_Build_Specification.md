# AgriFi Trade Network — AI Agent Build Specification
Version 1.0 | 3 November 2026

## Purpose
This document is the primary build brief for an AI coding agent. It defines what to build, why, the technology stack, project structure, data model, business rules, API plan, implementation sequence, and acceptance criteria. The agent must inspect the existing repository before changing anything.

## 1. Product mission
AgriFi Trade Network is a B2B agricultural marketplace connecting farmers and bulk buyers. Farmers record harvest availability and publish crop listings. Buyers discover supply and place traceable orders. The platform manages stock reservations, fulfilment states, simulated payments, and operational records.

Initial market: Nigeria. Design for possible West African expansion, but do not build regional features prematurely.

### Product principles
- Trust and correctness before feature breadth.
- PostgreSQL/backend is authoritative for shared inventory, orders, payments, permissions, and posted ledger entries.
- Offline mobile capture is supported, but offline records do not become authoritative stock until validated and accepted by the server.
- Use a modular monolith, not microservices, for the first release.
- Important business and financial changes must be traceable and auditable.
- Deliver in small, tested, documented milestones.

### First-release scope (P0)
- Authentication, roles, farmer and buyer profiles.
- Crop categories and catalogue listings.
- Harvest batches.
- Stock movements, stock availability, reservations.
- Single-seller orders, order items and status history.
- Simulated payment and refund flows.
- Basic double-entry ledger.
- Audit events.
- Idempotent mobile sync endpoint.
- Basic buyer/operations web workflows.
- Reproducible local setup and automated tests.

P1: notifications, richer analytics/reports, reservation-expiry worker, richer dispute handling, monitoring.
P2: SMS/USSD, logistics integrations, credit assessment, live payment integration, real-money escrow arrangement, lending, cross-border workflows.

### Important boundary
The first release uses simulated payments and an escrow-style workflow only. Do not accept, hold, transfer, or imply custody of real customer funds. Do not claim the product legally provides escrow. Real payment gateways, regulated escrow, lending, or cross-border settlement require separate legal, provider, compliance, security, and product review.

For MVP, each order belongs to one buyer and one seller. Do not implement multi-seller checkout. If needed later, use a parent checkout with separate seller orders.

## 2. Roles
- Farmer: manage own profile, harvest batches and listings; view own orders and sync status.
- Buyer: browse active listings; create and view own orders; use simulated payment flow.
- Operations administrator: review listings/users, manage permitted operational states, investigate disputes. Privileged actions must be authorised and audited.
- Finance operator: inspect simulated payments, refunds and ledger reports. Cannot edit/delete posted journals. No real-money transfers.
- System account: background tasks only, with least privilege.

## 3. Technology stack
| Layer | Technology |
|---|---|
| Backend | Python, Django, Django REST Framework |
| Authoritative database | PostgreSQL |
| Farmer mobile | .NET MAUI + local SQLite |
| Buyer/operations web | Angular + Tailwind CSS |
| Background jobs | Celery + Redis when needed |
| API | Versioned REST/JSON under `/api/v1/` |
| Local environment | Docker Compose recommended for PostgreSQL and optional Redis |
| Tests | Django/pytest, DRF API tests, PostgreSQL integration and concurrency tests |
| Quality | Formatting, linting, CI checks |
| Deployment | Repeatable setup; secrets via environment/secret manager |

Use a modular monolith: one Django deployment, domain-separated apps, one PostgreSQL database. Keep business rules in explicit service functions/classes. Views should authenticate, validate request shape, call services, and serialize responses. Avoid putting critical logic only in model signals.

Do not add microservices, Kubernetes, event streaming, or unnecessary infrastructure for the MVP. Explain and pin every new dependency.

## 4. Repository structure
Adapt to the existing repository; never overwrite before inspecting it.

```text
agrifi-trade-network/
  backend/
    manage.py
    config/
      settings/
      urls.py
      asgi.py
      wsgi.py
    agrifi/
      accounts/
      catalog/
      inventory/
      orders/
      payments/
      ledger/
      sync/
      audit/
      notifications/   # add when needed
      analytics/       # add when needed
    tests/
    requirements/ or pyproject.toml
    Dockerfile
  mobile/
    AgriFi.Mobile/
  web/
    agrifi-dashboard/
  docs/
    product-requirements.md
    system-design.md
    database-design.md
    api-contract.md
    decisions/
  docker-compose.yml
  .env.example
  .gitignore
  README.md
```

Django app ownership:
- `accounts`: custom User, roles, farmer/buyer profiles and permissions.
- `catalog`: crop categories, listings and catalogue search.
- `inventory`: harvest batches, stock movements, reservations and availability.
- `orders`: orders, items, status transitions/history and disputes.
- `payments`: simulated payment attempts, refunds and settlements.
- `ledger`: ledger accounts, journal entries/lines, posting and reversal services.
- `sync`: idempotent sync operations and receipts/conflict responses.
- `audit`: append-only business audit events.
- Add notifications/analytics only when requirements are ready.

## 5. Database design
PostgreSQL is the source of truth. SQLite on mobile is only a local cache/outbox.

### Core entities
- `User`: UUID, normalized unique email, Django password hash, active flag, timestamps.
- `UserRole`: user FK, role; unique user-role pair.
- `FarmerProfile`: one-to-one user, display name, region/location, verification status.
- `BuyerProfile`: one-to-one user, business name, region/location, verification status.
- `CropCategory`: name, unique slug, active flag.
- `Listing`: seller FK, category FK, name/description, unit code, unit price in minor units, currency, status.
- `HarvestBatch`: farmer FK, crop/category, quantity and unit, harvested/created dates, optional client-generated sync ID.
- `StockMovement`: listing FK, movement type, documented signed quantity delta/direction, reference, actor, timestamp.
- `Reservation`: listing/order-item FKs, quantity, status, expiry and timestamps.
- `CustomerOrder`: buyer FK, seller, status, currency, server-calculated total, timestamps.
- `OrderItem`: order/listing FKs; seller, crop/description, unit, quantity, unit price and line-total snapshots.
- `OrderStatusHistory`: order FK, previous/new status, actor, timestamp, reason.
- `Dispute`: order FK, opener, reason, status, resolution fields/timestamps.
- `Payment`: order FK, mode/provider, amount in minor units, currency, status, idempotency key, timestamps.
- `Refund`: payment FK, amount, reason, status, idempotency key, timestamps.
- `Settlement`: payee, amount, currency, status, reference and simulated metadata.
- `LedgerAccount`: unique code, account type, optional owner, currency, active flag.
- `JournalEntry`: unique reference, source type/ID, status, created/posted timestamps, reversal reference.
- `JournalLine`: journal/account FKs, debit and credit minor units; exactly one side positive.
- `SyncOperation`: user, client operation UUID, type, status, result/error, timestamps.
- `AuditEvent`: actor, action, object type/ID, timestamp, safe metadata; append-only policy.

### Constraints and conventions
- Create a custom Django user model before the first migration.
- Use UUID primary keys for business entities unless justified otherwise.
- Use timezone-aware timestamps.
- Use `DecimalField` for fractional quantities with defined precision/scale and explicit units.
- Store money as integer minor units (`BigIntegerField`, e.g. kobo), never floating point. Include currency code.
- Use `TextChoices`/enums and database constraints for row-level invariants.
- Unique constraints: normalized email, role pair, category slug, idempotency scope, journal reference, `(user_id, operation_id)`.
- Index common query paths: listing status/category and seller/status; harvest farmer/date; stock movement listing/date; reservation listing/status/expiry; order buyer/date and status/date; payment order/status; journal account/entry; audit object/date.
- Use `PROTECT`/`RESTRICT` for important financial/history relationships. Do not casually delete orders, posted payments, journals, or audit events.
- Order items must preserve price/seller/crop/unit snapshots so later listing edits do not alter past orders.

### Explicit stock-source decision
Before implementing inventory, decide whether listing stock derives directly from harvest batches or whether the listing has a separate stock balance maintained by stock movements. Select one authoritative strategy. If listings draw from multiple batches, define allocation and traceability. Never maintain two competing stock authorities.

## 6. Business rules and state machines

### Inventory
- Submitted quantities must be positive; define one sign convention for stock movements.
- Available quantity = accepted stock on hand minus active, unexpired reservations.
- Offline harvest data is pending until server validation and sync acceptance.
- Stock-affecting operations must be atomic. Use `transaction.atomic()` and `select_for_update()` on the relevant inventory/listing row.
- Reject reservations exceeding availability. Concurrent requests must not oversell.
- Expiry must not release stock already consumed/confirmed.
- Do not double-count a reservation and a stock deduction for the same event.
- Test locking/concurrency against PostgreSQL; SQLite alone is insufficient.

Illustrative algorithm (adapt to final schema):
```python
with transaction.atomic():
    listing = Listing.objects.select_for_update().get(pk=listing_id)
    available = calculate_available_quantity(listing)
    if requested_quantity <= 0:
        raise ValidationError("Quantity must be positive")
    if requested_quantity > available:
        raise InsufficientStock()
    create_reservation(...)
```

### Order lifecycle
Suggested states: `pending`, `confirmed`, `fulfilment`, `completed`, `cancelled`, `disputed`.
Implement an explicit transition map defining who can perform each transition and its preconditions. Do not accept arbitrary status strings from clients. Record actor, timestamp, prior/new state and reason. Invalid transitions return a consistent 4xx response. Cancellation/expiry must release reservations exactly once.

### Pricing
The server calculates line totals and order totals. Never trust client-supplied prices, totals, seller IDs, currency or discounts. Preserve historical snapshots on order items.

## 7. API plan
All routes under `/api/v1/`. Define serializers, permissions, pagination, filtering, validation and a consistent error shape. Do not expose model internals directly.

| Area | Endpoint examples | Notes |
|---|---|---|
| Auth | `POST /auth/register`, `/auth/login`, `/auth/logout`, `GET /auth/me` | Decide/document secure session or token strategy |
| Catalogue | `GET /categories`, `GET /listings`, `GET /listings/{id}`, `POST /listings`, `PATCH /listings/{id}` | Seller manages own listings |
| Harvest | `GET/POST /harvest-batches`, `PATCH /harvest-batches/{id}` | Ownership and sync status |
| Inventory | `GET /listings/{id}/availability`, `GET /stock-movements`, `POST /reservations` | Writes through services |
| Orders | `POST /orders`, `GET /orders`, `GET /orders/{id}`, `POST /orders/{id}/transitions`, `/disputes` | Server totals and scoped access |
| Payments | `POST /orders/{id}/simulate-payment`, `GET /payments/{id}`, `POST /payments/{id}/simulate-refund` | Simulation only, idempotent |
| Ledger | `GET /finance/ledger-accounts`, `/journal-entries`, `/reports` | Finance/admin only |
| Sync | `POST /sync/operations`, `GET /sync/operations/{operation_id}` | Idempotent receipt |
| Audit | `GET /audit-events` | Restricted and paginated |

API requirements:
- Use appropriate HTTP status codes and stable error responses with machine code, message and field errors.
- Paginate collections and cap page sizes.
- Enforce object-level permissions on every endpoint; hiding UI controls is not security.
- Use explicit filters/order fields; do not expose arbitrary ORM ordering.
- Document examples/errors with OpenAPI or equivalent.
- Use idempotency for operations where retries could duplicate orders, reservations, payments, refunds or journals.

## 8. Offline-first synchronisation
The .NET MAUI app uses SQLite for local harvest records and a durable outbox. It is not a second inventory authority.

Local records should have client-generated UUID, local timestamps, sync status, and last error. Persist locally before confirming the save. On restart, resume queued operations. Show `pending`, `synced`, and `needs attention` states. Keep client IDs distinct from server IDs where useful.

Sync protocol:
1. Client saves record and outbox operation with unique operation UUID.
2. Client sends operation UUID, operation type, schema version, payload and server version if relevant.
3. Server authenticates, checks ownership/role, validates, and checks `(user_id, operation_id)`.
4. If already processed, return the stored result without repeating effects.
5. If new, apply transactionally, store outcome and return canonical server record/result.
6. Client stores response and marks operation synced.

Conflict/retry rules:
- Define conflict policy per entity; never silently overwrite server changes.
- Use server version/updated_at or explicit version numbers where concurrent edits matter.
- Retry transient network errors with exponential backoff and jitter.
- Retry ambiguous timeouts using the same idempotency key.
- Do not trust client timestamps to order stock or financial events.
- Validation conflicts need user attention, not endless automatic retry.

## 9. Simulated payments and ledger
All MVP payment workflows are simulated. Label them as simulated in UI, API, reports and documentation. Never call a live payment API.

Ledger requirements:
- Double-entry: debits equal credits for every posted journal and currency.
- Every journal has unique reference and source business-event reference.
- Each journal line has positive integer amount on exactly one side (debit XOR credit).
- Whole-entry balance is validated in a controlled posting service; row-level checks cannot guarantee cross-row balance.
- Posted journals/lines are immutable. Correct mistakes with reversal entries.
- Create journal and update related business state in one transaction.
- Idempotency and unique references prevent duplicate posting.
- Never hold a database transaction open during network calls.

Illustrative simulated payment: ₦100,000 = 10,000,000 kobo. A possible entry debits a simulated payment-clearing account and credits an order-funds liability account. This is illustrative only; define and review the chart of accounts and accounting semantics before coding. It does not imply real escrow/custody.

Posting sequence:
1. Begin transaction.
2. Lock and validate payment/order.
3. Check idempotency key and journal reference.
4. Validate current state.
5. Create journal and lines.
6. Verify debit/credit equality per currency; mark posted.
7. Update payment/order state and audit event in same transaction.
8. Commit; errors roll back all changes.

Refunds cannot exceed eligible captured/simulated-paid amount less successful prior refunds. Enforce under transaction locks and idempotency. Settlement is separate from payment success. All settlement activity in MVP is simulated.

## 10. Security, privacy and operations
- Never commit secrets, credentials, private keys or real customer data. Supply `.env.example` placeholders.
- Use Django password hashing; never invent custom password cryptography.
- Apply least privilege and object-level permissions.
- Validate server-side; use ORM parameterisation; justify any raw SQL.
- Test cross-user access by changing resource IDs.
- Configure allowed hosts, CORS, CSRF, secure cookies/TLS, debug and trusted origins per environment.
- Rate-limit login/abuse-prone endpoints where appropriate; avoid account-enumeration leaks.
- Never log passwords, tokens, payment secrets or unnecessary personal data.
- Use atomic transactions for multi-record operations.
- Add health/readiness checks, structured logs and request/correlation IDs.
- Document PostgreSQL backup and restore; test restoration before claiming it works.
- Define retention, deactivation, archival and deletion policies; preserve required financial/audit history.
- Use UTC/timezone-aware server timestamps.
- Monitor failed syncs, simulated payments, stock conflicts and worker failures.
- Performance/security goals are targets, not achieved claims; provide test/operational evidence.

## 11. Implementation roadmap

| Milestone | Deliverables | Exit criteria |
|---|---|---|
| M0 Inspect | Inspect repository, report current state/gaps, assumptions, task plan and architecture decisions | No destructive edits; agreed plan |
| M1 Foundation | Django project, settings, custom User, PostgreSQL config, `.env.example`, Docker Compose, health check, CI/tests | Fresh clone starts; migrations/tests pass |
| M2 Accounts/catalogue | Roles/profiles, categories, listings, permissions, pagination/filtering | Ownership and validation tests |
| M3 Inventory | Harvest batches, stock movements, reservations, availability | PostgreSQL concurrency tests prove no overselling |
| M4 Orders | Order creation, price snapshots, transitions/history, cancellation | Invalid transitions rejected; duplicate requests safe |
| M5 Finance | Simulated payments, refunds, ledger and audit integration | Balanced journals, idempotency and reversal tests |
| M6 Sync | Outbox/sync contract, duplicate handling and conflict responses | Repeated sync has no duplicate effects |
| M7 Clients | Angular buyer/ops workflows; .NET MAUI local capture/outbox/sync | Critical end-to-end journeys work |
| M8 Hardening | Security, observability, backup/restore, docs, deployment | Release checklist and known gaps documented |

## 12. Testing and definition of done
Test layers:
- Models/constraints: unique email, valid statuses, positive quantities, one-sided journal line, currency/unit requirements.
- Services: availability, transitions, server pricing, refund cap, ledger balance.
- API: authentication, permissions, invalid payloads, pagination, ownership, stable errors, server-controlled totals.
- Integration: reservation/cancellation, payment-ledger atomicity, sync retry.
- PostgreSQL concurrency: two buyers competing for stock, duplicate payment and journal requests.
- Mobile sync: offline save, restart, retry, duplicate response and validation conflict.
- Security regression: cross-user access denied, role escalation blocked, secrets absent from API/logs.

Every milestone is done only when relevant tests pass, migrations work on a clean database, docs/env examples are updated, and the agent reports exact commands/results and known gaps.

MVP acceptance:
- Farmers manage only their own listings/harvest records.
- Buyers browse active listings and create orders with server-derived prices.
- Concurrent reservations cannot exceed available stock.
- Cancellation/expiry releases reservation exactly once.
- Order transitions are validated and recorded.
- Retried simulated payment cannot duplicate payment or ledger effects.
- Every posted journal balances per currency and cannot be edited/deleted through ordinary APIs.
- Duplicate sync returns prior result without repeating effects.
- Offline harvest data survives app restart and shows pending/synced status.
- A clean environment can follow README to install, configure PostgreSQL, migrate, test and run API.

## 13. Non-goals and decisions requiring approval
Do not implement real-money escrow/custody/payouts, live Paystack/Flutterwave/bank/card integrations, loans or automated credit decisions, multi-seller checkout, cross-border settlement, microservices/Kubernetes/event streaming, or AI crop/credit predictions in MVP.

Raise these decisions rather than guessing:
- Exact order/fulfilment transition permissions.
- Stock source of truth: harvest-batch-derived or listing stock balance.
- Batch allocation and traceability if listings draw from multiple batches.
- Chart of accounts and entries for cancellation, refunds, fees and settlement.
- Authentication approach shared by Angular and MAUI.
- Identity verification, privacy/retention and any future regulated payment arrangement.

## 14. Ready-to-use AI agent prompt
You are the senior engineer implementing AgriFi Trade Network. Treat this specification as the primary product and architecture contract. First inspect the repository and report its structure, existing implementation, test status and gaps. Do not overwrite or regenerate existing work without inspection.

Implement small, complete milestones. Begin with M0 and M1 only unless the project owner explicitly asks for more. Use Python, Django, DRF and PostgreSQL for the backend. Preserve the planned clients: .NET MAUI + SQLite for the offline-first farmer app, and Angular + Tailwind CSS for the buyer/operations dashboard.

Keep the backend a modular monolith. Put critical business logic in explicit services. Implement and test ownership permissions, server-calculated prices, safe stock reservations, valid order transitions, idempotent sync and simulated payment operations, and balanced immutable ledger postings. Use PostgreSQL-backed tests for row-locking/concurrency claims. Never use floating-point for money.

The first release must use simulated payments only. Do not call a live payment provider, move real funds, describe the system as legally providing escrow, implement lending, or claim compliance without explicit approval and appropriate external review.

For each milestone: state goal/assumptions; list planned files/migrations; implement the smallest vertical slice; add tests; run and report exact checks; update docs; list risks and next step. Be candid about anything not run, tested, mocked or incomplete. Never fabricate successful tests, production readiness, security guarantees or performance results.

If a requirement is ambiguous, explain options and recommend one. Ask for a decision when an incorrect choice could compromise data integrity, financial correctness, privacy, legal exposure or irreversible architecture. Otherwise choose a conventional low-complexity default and document it.

### First task
Inspect the repository and produce a short M1 plan. Then establish Django, custom user model, PostgreSQL configuration, environment template, health check, initial migration and minimal automated test. Do not proceed to orders, payments or mobile/web clients until the foundation is reproducible.

---
End of AgriFi Trade Network AI Agent Build Specification.
