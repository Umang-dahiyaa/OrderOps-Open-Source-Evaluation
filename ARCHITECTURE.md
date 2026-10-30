# OrderOps architecture notes

## Source file map
- `service.py`: Core domain logic containing state transition engine (`apply_order_event`), reconciliation comparator (`reconcile_orders`), and CSV export utility (`export_awaiting_refund_csv`).
- `models.py`: Helper model factory `new_order` instantiating synthetic order dictionaries with default schema keys.
- `fixtures.py`: Test fixtures and demo sample records for local evaluation.
- `main.py`: Executable entry point running offline reconciliation comparison.
- `data/records.json`: Expanded synthetic dataset containing 150 internal orders, 163 provider records, 219 event examples, and edge case catalog.
- `tests/test_contract.py`: Baseline contract tests enforcing immutable copy semantics, valid transitions, and report structure.
- `tests/test_acceptance_matrix.py`: Parametrized acceptance test matrix covering 200 state, refund, and reconciliation scenarios.
- `tests/test_regression_and_edge_cases.py`: Extended regression suite validating edge cases, malformed payloads, and stretch functionality.

## Order state transitions
```
[PLACED] ---- restaurant_accepted ----> [ACCEPTED] ---- dispatch_started ----> [OUT_FOR_DELIVERY] ---- order_delivered ----> [DELIVERED]
   |                                        |
   +---- restaurant_rejected ----> [REJECTED] +---- cancel_requested ----> [CANCELLED]
   |
   +---- cancel_requested ------> [CANCELLED]
```
- Transitions from `OUT_FOR_DELIVERY` or `DELIVERED` to `CANCELLED` are explicitly disallowed.
- Transitions from non-`PLACED` states to `ACCEPTED` or `REJECTED` are ignored.
- Delivery events arriving prior to `OUT_FOR_DELIVERY` are ignored.

## Payment and refund state flow
- Initial state: `payment_status="UNPAID"`, `refund_due_paise=0`, `refunded_paise=0`.
- Payment confirmation: Event `payment_confirmed` sets `payment_status="PAID"`. If the order is already `REJECTED` or `CANCELLED`, `refund_due_paise` is immediately set to `total_paise`.
- Cancellation / Rejection of paid orders: If `payment_status=="PAID"` when rejection or cancellation occurs, `refund_due_paise` is set to `total_paise`.
- Refund execution: `refund_processed` applies only if `status in ("REJECTED", "CANCELLED")`, `payment_status=="PAID"`, and `refund_due_paise > 0`.
  - Amount must be a positive integer (`type(amount) is int and amount > 0`).
  - Amount cannot exceed `refund_due_paise - refunded_paise`.
  - `payment_status` transitions to `REFUNDED` if and only if `refunded_paise == refund_due_paise`.

## Duplicate event strategy
- Every event with an `event_id` is recorded in `processed_event_ids`.
- At the entry of `apply_order_event`, the service evaluates `if event_id is not None and event_id in out["processed_event_ids"]: return out`.
- Any repeated event ID (even with conflicting payload or modified amounts) is immediately ignored without altering order state, guaranteeing strict idempotency.

## Three edge cases I tested
1. **Cancellation arriving after dispatch**: Order in `OUT_FOR_DELIVERY` receiving `cancel_requested` remains `OUT_FOR_DELIVERY` without triggering refund obligations.
2. **Delayed payment webhook**: Order cancelled while `UNPAID` then receiving `payment_confirmed` correctly updates `payment_status="PAID"` and calculates `refund_due_paise=total_paise`.
3. **Multi-step partial refund limits**: Cumulative partial refunds are capped at outstanding refundable balance, correctly rejecting any subsequent refund that would exceed `refund_due_paise`.

