# Simulated Finance Review Packet

**Review status:** Awaiting qualified accountant review. Every finance event and journal in the product remains **SIMULATED — NO MONEY MOVED**. This packet is a technical summary for review, not accounting advice or approval.

## Current model

Amounts are integer NGN kobo. The system stores immutable simulated events and balanced, append-only journal entries; corrections use compensating reversal journals. There is no payment provider, bank account, custody, escrow, payout, tax calculation, commission, or real-money movement.

| Account code | Current label/type | Use in simulated postings |
|---|---|---|
| `SIM_PAYMENT_CLEARING` | Simulated payment clearing / asset | Debit for simulated capture; credit for simulated refund |
| `SELLER_PAYABLE` | Simulated seller payable / liability | Credit on capture; debit on pre-settlement refund and settlement |
| `SELLER_RECEIVABLE` | Simulated seller receivable / asset | Debit on refund recorded after simulated settlement |
| `SIM_PAYOUT_CLEARING` | Simulated payout clearing / asset | Credit on simulated settlement; no transfer occurs |

## Posting flows to review

1. **Capture simulation:** debit `SIM_PAYMENT_CLEARING`, credit `SELLER_PAYABLE`, for the order total.
2. **Refund before settlement:** debit `SELLER_PAYABLE`, credit `SIM_PAYMENT_CLEARING`, for the approved refund amount.
3. **Settlement simulation:** debit `SELLER_PAYABLE`, credit `SIM_PAYOUT_CLEARING`, for paid amount less previous refunds. This records an internal state only.
4. **Refund after settlement:** debit `SELLER_RECEIVABLE`, credit `SIM_PAYMENT_CLEARING`. This records a simulated recovery from the seller; there is no collection mechanism.
5. **Correction:** post an opposite-line reversal linked to the original journal; never edit posted history.

## Questions for the accountant

- Are account names, account types, normal balances, and the capture/refund/settlement entries coherent for this explicitly simulated demonstration?
- Should the simulated clearing accounts instead be classified differently or renamed to avoid implying cash, custody, or a payout obligation?
- Is the receivable treatment for a post-settlement refund appropriate as a simulation, and is the absence of a recovery process clear enough?
- Are the refund eligibility rules and net settlement calculation sound for the stated workflow?
- Are NGN-only postings, kobo precision, rounding, and report presentation adequate for the current scope?
- What accounting, tax, fee, reconciliation, retention, and audit controls would be required before any live-money feature is considered? Live-money functionality is out of scope for this release.

## Review record

| Field | Entry |
|---|---|
| Reviewer name and qualification | Pending |
| Firm/organization | Pending |
| Review date | Pending |
| Findings / required changes | Pending |
| Approved for simulated demonstration? | Pending |
| Approval for live funds | Not requested; live-money processing is out of scope |

**Release gate:** keep all finance UI, API responses, journal memos, and reports labelled simulation-only until a qualified accountant records review findings. Even after review, live payments, custody, refunds, or payouts require a separate product, legal, and security approval and implementation.
