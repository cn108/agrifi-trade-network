# Product Requirements Document

Status legend: **Implemented** (code + SQLite tests), **Partial**, **Planned** (not started). Nothing here is PostgreSQL-verified, browser-tested or run on an Android device unless stated; see [PROJECT_STATUS.md](./PROJECT_STATUS.md). Source spec: `AgriFi_AI_Agent_Build_Specification.md`; deviations are in [DECISIONS.md](./DECISIONS.md) and [COMPLIANCE_ASSESSMENT.md](./COMPLIANCE_ASSESSMENT.md).

## 1. Product
A Nigerian-first B2B agricultural marketplace connecting farmers (sellers) with buyers, with operations and finance back-office roles. It is **not** an AI agent, crop predictor, lender, blockchain system or automated trader. **No real money moves**: payments, refunds, settlements and the ledger are simulated and labelled so.

## 2. Users and roles
| Role | Purpose |
|---|---|
| farmer | Records harvest batches (also offline from mobile), corrects rejected batches, publishes listings, fulfils orders |
| buyer | Browses listings, places orders, pays (simulated), opens disputes |
| operations_admin | Reviews harvest batches, manages stock allocation, resolves disputes, reads audit events |
| finance_operator | Reads journals, reports; records simulated refunds/settlements |
| system | Non-interactive maintenance identity |

## 3. Functional requirements
| # | Requirement | Status |
|---|---|---|
| F1 | Email registration, login, JWT refresh rotation, logout/revocation, roles | Implemented |
| F2 | Farmer and buyer profiles | Implemented |
| F3 | Crop categories and listings (price in integer kobo) | Implemented |
| F4 | Harvest batch submission with idempotent client sync id | Implemented |
| F5 | Operations accept/reject batches; rejected batches corrected by resubmission | Implemented |
| F6 | Single-source-of-truth stock ledger, reservations, allocation to listings | Implemented |
| F7 | Orders with state machine (pending, confirmed, shipped, delivered, completed, cancelled, disputed, dispute_resolved) and stock reservation | Implemented |
| F8 | Disputes (one open per order) and resolution | Implemented |
| F9 | Simulated payments, refunds, settlements with balanced double-entry journal | Implemented |
| F10 | Finance reports (trial balance, summaries) | Implemented |
| F11 | Append-only audit events and read API | Implemented |
| F12 | Mobile offline outbox and generic sync receipts (`harvest_batch.create` only) | Implemented (client never run against live server or device) |
| F13 | Angular web console (farmer, ops, buyer, finance pages) | Implemented (21 unit tests pass, 1 skipped, build passes, five local API/demo-data Playwright journeys pass; broader production-origin coverage pending) |
| F14 | Reservation expiry and maintenance scheduling | Implemented (`run_maintenance`; scheduler container unverified) |
| F15 | Real payments, KYC, notifications, SMS/WhatsApp, logistics, ratings/reviews, analytics | Planned (the legacy `agrifi/models.py` scaffolding for these is dead code) |

## 4. Non-functional requirements
| # | Requirement | Status |
|---|---|---|
| N1 | Money integer kobo; quantities Decimal(12,3); UUID PKs; aware timestamps | Implemented |
| N2 | Invariants enforced in DB constraints and triggers | Implemented; **triggers unverified on PostgreSQL** |
| N3 | Request correlation id, standard error envelope | Implemented |
| N4 | Auth/registration throttling | Implemented (per-process cache by default) |
| N5 | OpenAPI contract (`docs/openapi.yml`), validated | Implemented |
| N6 | Backup/restore runbook | SQLite restore test passes; a seeded disposable PostgreSQL 16 dump/restore check passes; production backup schedule/off-host restore remains unverified |
| N7 | CI on PostgreSQL 16 | Configured; **never executed** |
| N8 | Monitoring, retention policy, load testing | Retention periods defined by owner (DECISIONS 47); monitoring and load testing remain planned |

## 5. Out of scope
Real money movement, lending, prediction, automated trading, blockchain.
