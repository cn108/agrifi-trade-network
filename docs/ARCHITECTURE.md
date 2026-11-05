# AgriFi Trade Network — Architecture

Contract: `AgriFi_AI_Agent_Build_Specification.md`. This file records the architecture as built.

## Scope
Nigerian-first B2B agricultural marketplace (conventional marketplace + supply chain).
Not: AI/chatbot, crop prediction, lending/credit scoring, blockchain, automated trading.
No real money: payments, refunds, settlements and ledger are **simulated** and labelled so.

## Stack
- Backend: Django 5.2 + DRF, Simple JWT, modular monolith in `backend/agrifi/*`. API under `/api/v1/`.
- DB: PostgreSQL (authoritative). SQLite only for fast local tests (`AGRIFI_USE_SQLITE=1`) and the mobile cache.
- Web: Angular 22 + Tailwind in `web/`; legacy React in `frontend/` is preserved, not being extended.
- Mobile: .NET MAUI + SQLite offline outbox (`mobile/AgriFi.Mobile/`; initial implementation).
- Async: Celery + Redis only if needed.

## Backend modules
| App | Responsibility |
|---|---|
| `accounts` | Custom user, roles, farmer/buyer profiles, JWT auth, permission helpers |
| `catalog` | Crop categories, listings (price in integer kobo) |
| `inventory` | Harvest batches, stock movements, reservations, stock services |
| `idempotency` | Reusable `IdempotencyRecord` (owner, scope, key, fingerprint, stored response) |
| `orders` | Single-seller checkout, immutable order snapshots, transitions and disputes |
| `finance` | Simulated payments, refunds, settlements and append-only journal |
| `audit` | Append-only audit events for sensitive authentication, inventory, order and finance actions |
| `sync` | Versioned mobile operation envelope and receipts, delegated to existing idempotency and harvest services |

Cross-cutting request middleware supplies correlation IDs and structured logs; DRF errors use a shared response envelope. `/healthz/` is liveness and `/readyz/` checks PostgreSQL readiness; the Compose API health check uses readiness. Finance reporting is read-only and aggregates the immutable journal. `run_maintenance` performs reservation expiry, expired-order cancellation, refresh-token cleanup and the 365-day idempotency-record purge; Compose provides a scheduler service. Alert delivery and deployed monitoring remain outstanding; see `OPERATIONS.md` and `PROJECT_STATUS.md`.
## Web dashboard (Phase 5 — workflows implemented; selected journeys verified 2026-11-05)
- Angular standalone application is scaffolded in `web/`; it is separate from the preserved React
  project in `frontend/`.
- Public buyer/farmer registration, login, self-service profiles and role-guarded routes use the
  `/api/v1/` API.
- Refresh tokens use the API's HttpOnly cookie transport and CSRF header. The short-lived access
  token is held in application memory only; browser storage is not used.
- Farmer workflows support harvest-batch submission, listing create/edit, and stock allocation from
  the ledger. Buyers can browse offers and check out with server-calculated prices. Order details,
  permitted transitions, disputes, operations review/moderation, and simulated finance actions are
  wired to backend endpoints.
- Finance actions are explicitly labelled simulated; they do not activate a payment provider or
  move money. Backend permissions and validation remain authoritative.
- Unit tests (21 passed, 1 skipped), production build, and five Chromium E2E journeys passed against
  a temporary SQLite API seeded for the test run. These results do not establish production-origin behaviour.
- The dashboard base API URL is configured in `web/src/environments/environment.ts`; local CORS
  must allow the exact dashboard origin (`http://localhost:4200`).
- The shared Angular visual system uses a restrained harvest-green palette, responsive card grids,
  touch-friendly horizontal workspace navigation, clear keyboard focus states, and reduced-motion
  support. Dashboard, catalogue, and account surfaces share the same spacing and surface language;
  these presentation choices do not alter API or business rules.

## Farmer mobile application (Phase 6)
- Projects: `mobile/AgriFi.Mobile.Core/` (plain `net10.0`: ApiClient, OutboxStore, sync service, models;
  depends only on `ISecureStore`, `IAppSettings`, `IHarvestBatchApi`), `mobile/AgriFi.Mobile/` (MAUI UI + `Adapters/`
  implementing the abstractions over `SecureStorage`/`Preferences`), `mobile/AgriFi.Mobile.Tests/` (xUnit with an in-process fake API).
- The API is snake_case; the client binds with `JsonNamingPolicy.SnakeCaseLower`.
- .NET MAUI app: `mobile/AgriFi.Mobile/`. The backend remains the system of record.
- Login uses the mobile token response; access and rotating refresh tokens are stored with
  `SecureStorage`, not browser/local preferences. API base URL can be configured in-app.
- Harvest drafts are committed to a SQLite outbox before the UI confirms local save. Each draft
  is scoped to the authenticated user and keeps one `client_sync_id` across retries; server
  idempotency prevents duplicate batch creation and the local owner scope prevents cross-account sync.
- Active crop categories are cached locally for offline capture. The backend still validates the
  category, role, owner and batch payload during sync.
- Local states distinguish pending sync, submitted for review, accepted, rejected and failed.
  Transient network/time-out failures remain pending; permanent client validation/permission
  failures remain visible and retained. Manual retry reuses the same payload and operation ID.
- Draft editing rules: a never-sent pending draft is edited in place (same key); a `pending` draft that has been sent is
  locked (outcome unknown); a `failed` draft (4xx, nothing persisted) is edited with a NEW key; a server-`rejected` draft is
  immutable history and is corrected by a NEW draft (new key) carrying `resubmission_of`, with the original marked
  `CorrectedByDraftId`. The server enforces one correction per rejected batch (OneToOne + locked check).
- Sync passes are serialised; concurrent 401s trigger one token refresh; the server's `rejection_reason` is shown to the farmer.
- JSON writes are serialized to a buffered byte-array body with a known content length so Android
  requests work with WSGI servers that do not consume chunked request bodies. API error messages
  prefer `message`, then legacy `detail` or field validation text; HTML error pages are reduced to
  a short status fallback rather than displayed in the app.
- Windows target compiles; Core xUnit tests pass (48). The Android `net10.0-android` target now
  compiles locally and produces Debug APKs using the Android SDK and Microsoft OpenJDK 21. One
  non-blocking XA0033 warning remains because this Android tooling does not parse the JDK
  `21.0.13.0.2` version string. The app launches on the Android 15 API 35 emulator; valid farmer
  sign-in, profile/category reads and session restoration were verified against local Django.
  Invalid credentials, negative harvest quantity and unavailable API handling were also checked;
  each left the app responsive and no harvest draft was created. Startup required removing
  unsupported `SemanticProperties.LiveSetting` XAML from the message label. Physical-device,
  offline-sync and broader malformed-input verification remain outstanding.

## Cross-cutting rules
- UUID primary keys; PROTECT on business FKs; DB constraints for invariants.
- Money: integer minor units (kobo). Quantities: `Decimal(12,3)`.
- Identity comes only from the authenticated JWT, never client headers/body.
- Idempotent creation: record inserted first in the same transaction; unique constraint authoritative; only that violation is a replay.

## Inventory model (Phase 2) — business rules
**One source of truth: the append-only `StockMovement` ledger.** No stored balances anywhere.

Concepts
- `HarvestBatch`: a farmer's claim of physical supply. Lifecycle `submitted -> accepted | rejected`.
  Only an operations admin accepts/rejects. Only `submitted` batches are editable by the farmer.
  Acceptance posts a `RECEIPT` movement of the batch quantity (accepted quantity is then immutable).
- `Listing`: commercial offer. Backed only by quantity explicitly allocated from accepted batches.
- `StockMovement` (immutable; no update/delete, enforced in model + queryset and PostgreSQL
  row triggers installed by `inventory/0003_immutable_ledger_triggers`):
  - `RECEIPT(batch, +q)` — batch accepted.
  - `ALLOCATION(batch, listing, q)` — moves stock from the batch's free pool to the listing.
  - `DEALLOCATION(batch, listing, q)` — returns stock from the listing to the batch's free pool.
  - `SALE(batch, listing, q)` — listing stock consumed by a fulfilled order (Phase 3 caller).
- `Reservation`: temporary hold of listing stock for an order. `active -> released | consumed | expired`.
  Pending-order reservations expire (default 48h for checkout; 15m for general reservations).
  Seller confirmation commits the reservation by clearing `expires_at`; it remains active and
  reduces availability until shipment consumes it. Committed reservations do not expire.

Derived quantities (always computed from rows, never stored)
- `batch_free   = Σ RECEIPT − Σ ALLOCATION + Σ DEALLOCATION`  (per batch)
- `listing_on_hand = Σ ALLOCATION − Σ DEALLOCATION − Σ SALE`  (per listing)
- `reserved     = Σ qty of active reservations where expires_at is NULL or expires_at > now`
- `available    = listing_on_hand − reserved`

Rules
1. Allocation requires: batch accepted; batch farmer == listing seller; same category and unit; `0 < qty <= batch_free`.
2. Deallocation requires `qty <= available` and `qty <=` net quantity allocated from that batch to that listing.
3. Reservation requires listing `active` and `0 < qty <= available`. Expired holds stop counting immediately (computed at read time) and are marked `expired` by `expire_reservations`. A confirmed order has a non-expiring active reservation.
4. Shipping a confirmed order consumes its reservations and posts `SALE` movements drawn FIFO from the listing's allocated batches. Release frees an unshipped pending-order hold without movement; consumed, released and expired holds cannot be consumed.
5. Stock-changing lock order (PostgreSQL `select_for_update`): listing, then batch for allocation/deallocation, or reservation for reserve/commit/consume. Batch acceptance/rejection locks only the batch and never waits on another lock. Every stock-changing operation runs in `transaction.atomic()` and takes the listing lock before computing availability, so concurrent writers serialize and overselling is prevented.
6. Corrections are made with new compensating movements, never by editing history.

## Orders (Phase 3)
- Checkout is a single-seller transaction. It locks listings in UUID order, checks active status,
  derives unit prices from database rows, computes integer-kobo line totals (half-up rounding),
  reserves stock, then persists immutable listing/category/seller/unit/price/quantity snapshots.
- `Order` state transitions are explicit and recorded as immutable `OrderStatusHistory` rows.
  Buyer/seller/operations-admin ownership is checked in the service, not just at the endpoint.
- Checkout idempotency uses `IdempotencyRecord` scope `order.create`; key namespace is per buyer.
  Same payload replays the stored response (200), changed payload conflicts (409).
- Pending order cancellation releases reservations. Confirm commits the hold (so it cannot expire);
  shipment consumes it and posts stock sales. An expiry command cancels only pending orders whose
  holds expired.
- Disputes are operational records, not financial remedies. Buyer-favoured pre-shipment resolution
  releases unshipped stock; a post-shipment buyer-favoured resolution ends in `dispute_resolved`.
  No refund/payment is performed; any simulated financial outcome belongs to Phase 4.

## Simulated finance (Phase 4)
- **No actual funds move.** Payment, refund, payout and clearing labels are explicitly simulated.
  The system does not call payment providers, accept money, custody funds, or send payouts.
- A simulated payment is permitted only for the buyer's confirmed order. Before shipping, the
  order requires one simulated success. Posting debits `SIM_PAYMENT_CLEARING` and credits
  `SELLER_PAYABLE`, both internal simulated accounts.
- An operations/finance operator can create an internal settlement only after order completion.
  It debits `SELLER_PAYABLE` and credits `SIM_PAYOUT_CLEARING`; this is not a bank transfer.
- Refunds require a buyer-favoured dispute resolution and are capped at simulated paid amount
  less prior refunds under order/payment row locks. Before settlement they debit `SELLER_PAYABLE`;
  after settlement they debit `SELLER_RECEIVABLE`; both credit the simulated payment clearing.
- `Journal`/`JournalLine` rows and financial event records are append-only. A service validates
  positive integer-kobo lines, currency agreement, and balance before posting. PostgreSQL uses
  deferred constraint triggers to validate final cross-row line totals at transaction commit,
  plus UPDATE/DELETE triggers. SQLite runs the service checks but cannot verify these triggers.
- Corrections add a new reversal journal; originals are not edited. Journal/account balances are
  derived from lines, never stored.
