# approach.md - Required submission

## 1. Baseline
- Commands run before editing:
  - `python --version` -> `Python 3.15.2`
  - `python -m pip install -r requirements-dev.txt` -> installed `pytest-9.2.0`, `colorama-0.4.6`, `iniconfig-2.3.1`, `packaging-26.3`, `pluggy-1.7.0`, `pygments-2.21.0`
  - `python -m pytest -q` -> Untouched baseline test run: `62 failed, 150 passed in 0.60s` (212 total tests)
  - `python -m main` -> Untouched offline demo output:
    ```
    matched: []
    missing_from_provider: ['ORD-103']
    missing_from_internal: ['ORD-104']
    amount_mismatches: ['ORD-101', 'ORD-102']
    status_mismatches: []
    ```

## 2. Codebase understanding
- Important files and functions inspected:
  - `service.py`: Contains `apply_order_event(order: dict, event: dict) -> dict` and `reconcile_orders(internal: list[dict], provider: list[dict]) -> dict`.
  - `models.py`: Helper `new_order(order_id, total_paise, status="PLACED")` establishing internal order schema.
  - `fixtures.py` & `main.py`: Sample orders and provider transactions used to verify offline reconciliation.
  - `data/records.json` & `data/README.txt`: 150 internal orders, 163 provider records, 219 event examples, and edge case specifications.
  - `tests/test_contract.py` & `tests/test_acceptance_matrix.py`: Contract and acceptance test matrices specifying expected event transitions, refund rules, idempotency replay, and reconciliation report outputs.
  - `.github/workflows/tests.yml`: GitHub Actions workflow executing offline demo and pytest with JUnit reporting.
- Order lifecycle or data flow traced:
  - Normal happy path: `PLACED` -> `restaurant_accepted` -> `ACCEPTED` -> `dispatch_started` -> `OUT_FOR_DELIVERY` -> `order_delivered` -> `DELIVERED`.
  - Payment: `payment_confirmed` sets `payment_status = "PAID"`. If the order was already rejected or cancelled prior to payment confirmation, `refund_due_paise` is initialized to `total_paise`.
  - Failure/Rejection: `restaurant_rejected` transitions `PLACED` to `REJECTED`. If `payment_status == "PAID"`, `refund_due_paise` is set to `total_paise`.
  - Cancellation: `cancel_requested` transitions `PLACED` or `ACCEPTED` to `CANCELLED`. If `payment_status == "PAID"`, `refund_due_paise` is set to `total_paise`. Cancellation requested after dispatch (`OUT_FOR_DELIVERY` or `DELIVERED`) is ignored.
  - Refund processing: `refund_processed` requires the order to be in `REJECTED` or `CANCELLED` status, `payment_status == "PAID"`, and `refund_due_paise > 0`. The amount must be a positive integer and cannot exceed the remaining due (`refund_due_paise - refunded_paise`). `payment_status` becomes `"REFUNDED"` only when `refunded_paise == refund_due_paise`.
  - Reconciliation: Compares internal orders against provider records by `order_id`. Produces deterministic, sorted lists across five distinct categories: `matched`, `missing_from_provider`, `missing_from_internal`, `amount_mismatches`, and `status_mismatches`.
- How you confirmed your understanding:
  - Reviewed the 212 baseline assertions across test files, mapped the intentional defect comments in `service.py`, and inspected the synthetic dataset structures in `data/records.json`.

## 3. Investigation and implementation strategy
- Issue 1: Missing event idempotency
  - Observed symptom: Replaying events in `test_payment_event_replay_idempotent` (20 test cases) and `test_duplicate_event_is_idempotent` resulted in duplicate IDs appended to `processed_event_ids`.
  - Hypothesis: `apply_order_event` did not check if `event_id` had already been processed before executing transitions and appending to `processed_event_ids`.
  - Evidence: `service.py` line 43 blindly performed `out["processed_event_ids"].append(event_id)`.
  - Fix: Checked `if event_id is not None and event_id in out["processed_event_ids"]: return out` at function start, avoiding repeated execution or duplicated event lists.
- Issue 2: Unchecked refund eligibility and amount validation
  - Observed symptom: 35+ test failures in `test_invalid_refund_amounts_are_ignored`, `test_refund_eligibility_matrix`, and `test_refunds_cannot_exceed_due`. Unpaid orders, delivered orders, negative amounts, floats (`0.5`), booleans (`True`), and amounts exceeding outstanding due were processed as valid refunds.
  - Hypothesis: `service.py` did not check order status, payment status, remaining due balance, or input type.
  - Evidence: Line 38 of `service.py` had comment `# Bug to find: validate eligibility, positive amount and maximum refund` followed by `out["refunded_paise"] += event.get("amount_paise", 0)`.
  - Fix: Added strict precondition checks:
    1. `out.get("status") in ("REJECTED", "CANCELLED")`
    2. `out.get("payment_status") == "PAID"`
    3. `out.get("refund_due_paise", 0) > 0`
    4. `type(amount) is int and amount > 0` (preventing booleans and non-integers)
    5. `amount <= (out["refund_due_paise"] - out["refunded_paise"])`
    6. Set `payment_status = "REFUNDED"` only upon exact match `out["refunded_paise"] == out["refund_due_paise"]`.
- Issue 3: Status mismatches ignored in reconciliation & schema discrepancy
  - Observed symptom: `test_reconciliation_status_mismatch_matrix` (7 failures) and `test_reconcile_reports_status_difference` failed because status differences were placed in `matched`. In addition, `new_order` keys orders with `total_paise` while provider records use `amount_paise`, causing false amount mismatches in `main.py`.
  - Hypothesis: Starter reconciliation only checked `a.get("amount_paise") != b.get("amount_paise")` and defaulted everything else to `matched`.
  - Evidence: Comment in starter `service.py`: `# Deliberate starter defect: mismatched statuses may be called matched.`
  - Fix: Resolved amounts via `a.get("amount_paise") if a.get("amount_paise") is not None else a.get("total_paise")`, evaluated `amt_mismatch` and `status_mismatch` independently, recorded both when applicable, and only marked orders as `matched` when both amount and status matched.

## 4. Implementation decisions
- Main changes and why:
  - Guarded `apply_order_event` with deepcopy and type checking to prevent in-place mutation of caller objects.
  - Implemented exact type check `type(amount) is int` because in Python, `bool` is a subclass of `int` (`isinstance(True, int) == True`).
  - Added support for late-arriving payment confirmations (`payment_confirmed` on already cancelled/rejected orders) so the platform correctly reflects customer funds owed.
  - Added `export_awaiting_refund_csv` function in `service.py` satisfying the optional stretch deliverable.
- Alternatives considered and why rejected:
  - In-place mutation vs `deepcopy`: In-place mutation would improve speed slightly but violates immutability and fails tests protecting input parameters.
  - Raising exceptions for invalid events vs no-op: Raising exceptions would crash batch pipelines on malformed events; the specification requires resilient handling without state corruption.
- Assumptions:
  - Amounts are expressed in positive integer paise.
  - Outstanding refundable amount is strictly `refund_due_paise - refunded_paise`.

## 5. Verification
- Tests added or changed:
  - Preserved all 212 original test cases.
  - Added 8 comprehensive regression tests in `tests/test_regression_and_edge_cases.py` covering post-dispatch cancellation, late payment confirmation, multi-step partial refunds, conflicting payload replay, simultaneous mismatches, and CSV export.
- Commands run and actual results:
  - `python -m pytest -q` -> `220 passed in 0.15s`
  - `python -m main` -> Correctly reported 1 matched, 1 missing from provider, 1 missing from internal, 0 amount mismatches, 1 status mismatch.
  - Tested against `data/records.json` -> Reconciled 150 internal orders vs 163 provider records, processed 212 events with zero errors.
- Edge cases verified:
  - Cancellation after dispatch/delivery is ignored.
  - Payment confirmed after rejection/cancellation correctly computes refund due.
  - Cumulative partial refund limits.
  - Robustness against `None` and non-dict inputs.
- Remaining failures or known limitations:
  - 0 failures. All 220 tests pass.
