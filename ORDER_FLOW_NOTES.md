# ORDER_FLOW_NOTES.md — Required submission

## 1. Example order-event sequence
The following sequence demonstrates a full lifecycle from placement through payment, restaurant rejection, and two-stage refund reconciliation:

Order initial state: `order_id="ORD-999"`, `total_paise=6000`, `status="PLACED"`, `payment_status="UNPAID"`.

| Step | Event | Expected order/payment/refund state | Actual result |
|---|---|---|---|
| 1 | `{"event_id": "EV-01", "type": "payment_confirmed"}` | `status="PLACED"`, `payment_status="PAID"`, `refund_due_paise=0`, `refunded_paise=0`, `processed_event_ids=["EV-01"]` | Matched expected state exactly |
| 2 | `{"event_id": "EV-02", "type": "restaurant_rejected"}` | `status="REJECTED"`, `payment_status="PAID"`, `refund_due_paise=6000`, `refunded_paise=0`, `processed_event_ids=["EV-01", "EV-02"]` | Matched expected state exactly |
| 3 | `{"event_id": "EV-03", "type": "refund_processed", "amount_paise": 2500}` | `status="REJECTED"`, `payment_status="PAID"`, `refund_due_paise=6000`, `refunded_paise=2500`, `processed_event_ids=["EV-01", "EV-02", "EV-03"]` | Matched expected state exactly (partial refund) |
| 4 | `{"event_id": "EV-04", "type": "refund_processed", "amount_paise": 3500}` | `status="REJECTED"`, `payment_status="REFUNDED"`, `refund_due_paise=6000`, `refunded_paise=6000`, `processed_event_ids=["EV-01", "EV-02", "EV-03", "EV-04"]` | Matched expected state exactly (full refund complete) |

## 2. Three edge cases

### Case 1: Post-dispatch cancellation attempt
- **Input / Sequence**: Order transitions `PLACED` -> `restaurant_accepted` (`ACCEPTED`) -> `dispatch_started` (`OUT_FOR_DELIVERY`). Then customer sends `cancel_requested` (`{"event_id": "EV-CANCEL", "type": "cancel_requested"}`).
- **Expected behaviour**: Cancellation is rejected because the order has already left the restaurant. Status must remain `OUT_FOR_DELIVERY` and no refund is marked due.
- **Actual observed result**: Status remained `OUT_FOR_DELIVERY`; `refund_due_paise` remained 0.
- **Verifying test**: `tests/test_contract.py::test_cancel_after_dispatch_is_ignored` and `tests/test_regression_and_edge_cases.py::test_edge_case_cancellation_after_dispatch_and_delivery`.

### Case 2: Out-of-order payment confirmation following cancellation
- **Input / Sequence**: An unpaid order is cancelled (`cancel_requested`), resulting in `status="CANCELLED"`, `payment_status="UNPAID"`, `refund_due_paise=0`. Later, delayed webhook delivers `payment_confirmed` (`{"event_id": "EV-LATE-PAY", "type": "payment_confirmed"}`).
- **Expected behaviour**: Because customer funds were captured for an unfulfillable cancelled order, `payment_status` becomes `PAID` and `refund_due_paise` is initialized to the order's `total_paise` (allowing subsequent refunds).
- **Actual observed result**: `payment_status` updated to `PAID`, `refund_due_paise` updated to `total_paise`, and subsequent refund processed cleanly to `REFUNDED`.
- **Verifying test**: `tests/test_regression_and_edge_cases.py::test_edge_case_late_payment_after_cancellation`.

### Case 3: Replay idempotency under conflicting payload
- **Input / Sequence**: An event with `event_id="EV-IDEMP"` is processed as `payment_confirmed`. A subsequent event with identical `event_id="EV-IDEMP"` arrives with a conflicting type `restaurant_accepted` or `refund_processed`.
- **Expected behaviour**: Idempotency check verifies `event_id` against `processed_event_ids` and discards the duplicate event without mutating state or appending to the processed event log.
- **Actual observed result**: Order state remained untouched; `processed_event_ids` contained exactly one instance of `"EV-IDEMP"`.
- **Verifying test**: `tests/test_regression_and_edge_cases.py::test_edge_case_duplicate_event_with_conflicting_payload`.

## 3. Assumptions and limitations
- **Monetary unit**: All currency amounts are non-negative integer paise (1 INR = 100 paise). Floating-point amounts are strictly rejected to avoid decimal truncation errors.
- **Eligibility bounds**: Only orders with `payment_status == "PAID"` and `status` in `("REJECTED", "CANCELLED")` are eligible for refunds. Orders in `PLACED`, `ACCEPTED`, `OUT_FOR_DELIVERY`, or `DELIVERED` are not eligible for automated refunds via `refund_processed`.
- **Single full refund state**: The `payment_status` remains `PAID` during partial refunds and transitions to `REFUNDED` only when `refunded_paise == refund_due_paise`.
- **In-memory deduplication limitation**: Deduplication relies on `processed_event_ids` within each order dictionary. In a production distributed architecture, deduplication should be backed by distributed locks, transactional outboxes, or database unique constraints.
