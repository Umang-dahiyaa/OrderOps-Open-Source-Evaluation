# Project notes

## Requirements completed
1. **Event Processing**: Implemented transitions for `payment_confirmed`, `restaurant_accepted`, `restaurant_rejected`, `cancel_requested`, `dispatch_started`, `order_delivered`, and `refund_processed`.
2. **State Transition Enforcement**: Cancellations after dispatch (`OUT_FOR_DELIVERY` or `DELIVERED`) are ignored. Invalid state changes are prohibited.
3. **Idempotency via Event IDs**: Verified `event_id` tracking in `processed_event_ids`. Duplicate events return the current order state unmodified.
4. **Integer Paise & Refund Safety**: Enforced positive integer paise (strictly rejecting booleans and floats). Cumulative refunds cannot exceed the outstanding refundable amount (`refund_due_paise - refunded_paise`).
5. **Separate Due and Refunded Tracking**: `refund_due_paise` and `refunded_paise` are tracked independently. `payment_status` transitions from `PAID` to `REFUNDED` only when `refunded_paise == refund_due_paise`.
6. **Reconciliation**: Reports `matched`, `missing_from_provider`, `missing_from_internal`, `amount_mismatches`, and `status_mismatches` deterministically.
7. **Resilient Input Handling**: Gracefully processes empty inputs, non-dict payloads, missing fields, and unknown event types without raising exceptions or corrupting order state.
8. **Optional Stretch Goal**: Added `export_awaiting_refund_csv` to export orders with outstanding refund balances.

## Files changed and why
- `service.py`:
  - Fixed idempotency early-exit check in `apply_order_event`.
  - Added strict refund eligibility, type check (`type(amount) is int and amount > 0`), and outstanding due bounds.
  - Added late payment confirmation handling for cancelled/rejected orders.
  - Implemented orthogonal status and amount reconciliation in `reconcile_orders` with field resolution between `amount_paise` and `total_paise`.
  - Added `export_awaiting_refund_csv` for stretch requirement.
- `tests/test_regression_and_edge_cases.py`:
  - Added 8 comprehensive regression tests covering dispatch cancellation, late payments, multi-step partial refunds, conflicting replays, simultaneous mismatches, malformed inputs, and CSV export.
- Documentation:
  - `approach.md`: Completed baseline, understanding, investigation, decisions, and verification.
  - `challenges.md`: Completed compulsory challenge document with concrete evidence and root causes.
  - `optimizations.md`: Completed optimizations, trade-offs, and future improvements.
  - `TESTING.md`: Completed environment details, 7 edge-case evidence records, regression tests, and zero failures summary.
  - `ORDER_FLOW_NOTES.md`: Completed lifecycle sequence, 3 edge cases, and architectural assumptions.

## Tests run
- `python -m pytest -q` -> 220 passed in 0.15s
- `python -m pytest -v` -> 220 passed
- `python -m main` -> Verified demo reconciliation outputs
- Ran validation against synthetic dataset `data/records.json` (150 orders, 163 provider records, 219 events).

## Assumptions
- Monetary values are in integer paise (1 INR = 100 paise).
- Eligible refund order statuses are `REJECTED` and `CANCELLED` with `PAID` payment status.
- Caller receives an immutable copy of the order on each transition.

## Known limitations
- Event history is maintained in-memory in `processed_event_ids`. In a distributed environment, an external distributed lock / transactional store should manage deduplication.

