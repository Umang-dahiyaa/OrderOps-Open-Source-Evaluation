# TESTING.md — Required submission

## Test command and environment
- Python version: `Python 3.15.2` (Windows 64-bit)
- Command run: `python -m pytest -v`
- Actual test summary: `220 passed in 0.17s` (212 starter acceptance/contract tests + 8 regression/edge-case tests)

## Edge-case evidence

| # | Case / input | Expected behaviour | Actual result | Test name or evidence |
|---|---|---|---|---|
| 1 | Order in `OUT_FOR_DELIVERY` receives `cancel_requested` | Cancellation ignored; status remains `OUT_FOR_DELIVERY` without refund due | Status remained `OUT_FOR_DELIVERY`, `refund_due_paise` = 0 | `test_edge_case_cancellation_after_dispatch_and_delivery` |
| 2 | Order cancelled while `UNPAID`, then `payment_confirmed` arrives late | Status stays `CANCELLED`, `payment_status` becomes `PAID`, `refund_due_paise` becomes `total_paise` | Status `CANCELLED`, `payment_status` `PAID`, `refund_due_paise` 3500 | `test_edge_case_late_payment_after_cancellation` |
| 3 | Cumulative partial refund exceeds outstanding due (10000 due, 4000 refunded, then 7000 requested) | 1st refund succeeds; 2nd refund exceeds remaining 6000 and is rejected | `refunded_paise` remained 4000; status remained `PAID` | `test_edge_case_multi_step_partial_refunds_and_overpayment_protection` |
| 4 | Non-integer refund amounts (`True`, `False`, `0.5`, `"10"`, negative) | Non-integer / negative amounts ignored; state unchanged | `refunded_paise` = 0, `payment_status` = `PAID` | `test_invalid_refund_amounts_are_ignored` |
| 5 | Order has both amount mismatch and status mismatch in reconciliation | Order is reported in both `amount_mismatches` and `status_mismatches`, excluded from `matched` | `amount_mismatches` = `['ORD-BOTH']`, `status_mismatches` = `['ORD-BOTH']`, `matched` = `[]` | `test_edge_case_simultaneous_amount_and_status_mismatch` |
| 6 | Event replayed with same `event_id` but conflicting payload (`type: "restaurant_accepted"`) | Replay is identified by `event_id` as duplicate and ignored; state unmutated | Order status remained `PLACED`; `processed_event_ids` retained single entry | `test_edge_case_duplicate_event_with_conflicting_payload` |
| 7 | Malformed inputs (`None` or non-dict order/event, missing fields) | Handled gracefully without raising uncaught exceptions | Returns clean empty/default dict structures without crashes | `test_edge_case_malformed_and_boundary_inputs` |

## Regression tests added
- `tests/test_regression_and_edge_cases.py::test_edge_case_cancellation_after_dispatch_and_delivery`: Prevents cancellation after dispatch or delivery.
- `tests/test_regression_and_edge_cases.py::test_edge_case_late_payment_after_cancellation`: Protects refund calculation when payments arrive out of order after cancellation.
- `tests/test_regression_and_edge_cases.py::test_edge_case_late_payment_after_restaurant_rejection`: Protects refund calculation when payments arrive after restaurant rejection.
- `tests/test_regression_and_edge_cases.py::test_edge_case_multi_step_partial_refunds_and_overpayment_protection`: Prevents over-refunding across multiple sequential partial refunds.
- `tests/test_regression_and_edge_cases.py::test_edge_case_simultaneous_amount_and_status_mismatch`: Prevents status mismatch masking when amounts also differ.
- `tests/test_regression_and_edge_cases.py::test_edge_case_malformed_and_boundary_inputs`: Protects service against `None` and non-dict inputs.
- `tests/test_regression_and_edge_cases.py::test_edge_case_duplicate_event_with_conflicting_payload`: Validates strict idempotency using `event_id`.
- `tests/test_regression_and_edge_cases.py::test_stretch_export_awaiting_refund_csv`: Verifies optional stretch CSV reporting for orders with outstanding refunds.

## Remaining failures or limitations
- 0 failing tests. All 220 tests pass.
- Known limitation: `processed_event_ids` is stored in-memory within order dictionaries; in a multi-node production deployment, event deduplication requires a shared transactional datastore.
