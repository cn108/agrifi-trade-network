# Database Design

Describes the Django models and migrations as implemented. PostgreSQL is authoritative; SQLite is used only for fast local tests. **None of the PostgreSQL triggers below has been executed on PostgreSQL** (environment blocker); the 18 PG-only tests are skipped on SQLite.

## Conventions
UUID primary keys; money as integer kobo (`BigInteger`/positive checks); quantities `Decimal(12,3)`; timezone-aware timestamps; status values as text choices.

## Tables by app
| App | Models | Notes |
|---|---|---|
| accounts | User (email login), UserRole, RevokedRefreshToken, FarmerProfile, BuyerProfile | `unique_user_role`; revoked refresh tokens keyed by JTI with expiry index and purge command |
| catalog | CropCategory, Listing | `listing_unit_price_positive`; indexes on status/category and seller/status |
| inventory | HarvestBatch, StockMovement, Reservation | Batch: `batch_quantity_positive`, `batch_farmer_sync_id_unique` (idempotency), resubmission/correction link (migration 0005). StockMovement is the **append-only ledger**: `move_quantity_positive`, `move_listing_matches_type`. Reservation: expiring holds, `resv_quantity_positive` |
| orders | Order, OrderItem, OrderStatusHistory, Dispute | `order_total_positive`, `order_buyer_not_seller`, item quantity/price/line-total positive checks, `dispute_one_open_per_order`; items and history immutable |
| finance | LedgerAccount, Journal, JournalLine, SimulatedPayment, Refund, Settlement | `journal_totals_balanced`, `journal_debits_positive`, `journal_source_kind_unique` (one journal per source), `journal_line_one_positive_side`, `journal_line_number_unique`; positive-amount checks on payment/refund/settlement |
| idempotency | IdempotencyRecord | `idempotency_owner_scope_key_unique`; indexes creation time for the 365-day replay-record retention purge; stores request fingerprint/result and backs sync receipts |
| audit | AuditEvent | Append-only; indexes on created time, action, object, actor |

There is **no stored stock balance**: availability is derived from `StockMovement` plus active `Reservation` rows. There is **no `SyncOperation` table** (DECISIONS 42). Idempotency replay records are retained 365 days from creation; audit and finance history has a seven-year minimum retention period, with legal/accounting review required before any later archival/deletion.

## Immutability
- ORM level: immutable model/queryset classes raise on update/delete (stock movements, order items/history, finance records, audit events).
- Database level (PostgreSQL): functions `agrifi_forbid_mutation`, `agrifi_validate_finance_journal`, immutable ledger/audit/order/finance triggers, and deferred journal-balance triggers. The PostgreSQL 16 Compose suite and trigger migration reversal/re-application passed locally on 2026-11-05; hosted CI is pending.
- Corrections are compensating entries (reversal journals, deallocation movements), never edits.

## Migrations
accounts 0001-0004, audit 0001-0002, catalog 0001, finance 0001-0002, idempotency 0001-0002, inventory 0001-0005, orders 0001-0003. `makemigrations --check` is clean. Reverse-migration tests exist only in the PostgreSQL CI path (not yet run).

## Concurrency rules
Stock/financial writes use `transaction.atomic()` + `select_for_update()`. Lock order: listing, batch, reservation; batch review locks only the batch. PostgreSQL-only concurrency tests pass in the local PostgreSQL 16 Compose suite; hosted CI is pending.

## Mobile local store (SQLite, MAUI)
`HarvestBatchDraft`: id, `ClientSyncId` (unique, the operation id), owner, payload fields, `SyncStatus` (pending/submitted/accepted/rejected/failed), `AttemptCount`, `RetryCount`, `NextAttemptAtUtc`, `LastError`, server batch id, rejection reason, correction links. `CachedCropCategory` caches categories. Columns are added by `CreateTable` on upgrade.

## Known gaps
Dead legacy file `backend/agrifi/models.py` (and `agrifi/settings.py`) is not an installed app and creates no tables. No retention/archival policy for audit events or idempotency records.
