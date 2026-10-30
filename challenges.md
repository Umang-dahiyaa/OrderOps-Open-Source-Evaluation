# challenges.md - COMPULSORY submission

## 1. Challenge or confusing behaviour
During the investigation and implementation, three specific technical challenges emerged:
1. **Python Boolean Subtyping in Type Validation**: In Python, `bool` is a direct subclass of `int` (`issubclass(bool, int) is True`, and `isinstance(True, int) is True`). When testing `test_invalid_refund_amounts_are_ignored`, passing `True` or `False` as `amount_paise` bypassed a standard `isinstance(amount, int)` check and added 1 paise or 0 paise to `refunded_paise`.
2. **Cumulative Partial Refund Calculation Under Event Streams**: Single-refund bounds checks (`amount <= refund_due_paise`) fail when multiple partial refunds arrive sequentially. For instance, on a 5000 paise order, if a 4000 paise refund arrives followed by a 2000 paise refund, evaluating each against total `refund_due_paise` would erroneously accept the second refund, producing 6000 paise in refunds (an over-refund defect).
3. **Internal vs Provider Field Inconsistency During Reconciliation**: `models.new_order` and the synthetic records schema represent order value as `total_paise`, whereas payment provider records store `amount_paise`. Reconciling only against `amount_paise` caused false amount mismatches on completely identical transactions.

## 2. Evidence
- Minimal reproduction of boolean vulnerability:
  ```python
  amount = True
  isinstance(amount, int)  # Returns True!
  amount > 0              # Returns True (True == 1)!
  ```
  This caused test `test_invalid_refund_amounts_are_ignored[True]` to fail with:
  `AssertionError: assert 1 == 0`
- Cumulative refund test failure:
  In `test_refunds_cannot_exceed_due[4000-2000]`:
  `two = apply_order_event(one, ev("R2", "refund_processed", amount_paise=2000))`
  Resulted in `6000 == 4000` because total refunded exceeded 5000 paise.
- Status mismatch masking:
  Starter code `service.py` contained:
  ```python
  if a.get("amount_paise") != b.get("amount_paise"):
      report["amount_mismatches"].append(key)
  else:
      report["matched"].append(key)
  ```
  Which masked all status mismatches when amounts were equal.

## 3. What I tried
- Experiment 1 (Type check): First tried `isinstance(amount, int) and amount > 0`. Observed that `True` still passed and triggered an assertion error. Then tried `type(amount) is int and amount > 0`. This strictly matches integer instances and rejects booleans without requiring complex regex or casting.
- Experiment 2 (Remaining due balance): Tested checking `remaining = refund_due_paise - refunded_paise` and only accepting `amount <= remaining`. Ran `test_refunds_cannot_exceed_due` with all 20 parametrized combinations; all 20 passed.
- Experiment 3 (Independent mismatch classification): Tested decoupling amount comparisons and status comparisons into two independent checks rather than an if-else chain. Ran `test_reconciliation_status_mismatch_matrix` and verified both matrices passed.

## 4. Resolution
- **Type resolution**: Enforced `type(amount) is int and amount > 0`.
- **Refund boundary resolution**: Dynamically calculated `remaining_due = out.get("refund_due_paise", 0) - out.get("refunded_paise", 0)` and enforced `amount <= remaining_due`.
- **Status and schema resolution**: Extracted `amt_a` with fallback: `a.get("amount_paise") if a.get("amount_paise") is not None else a.get("total_paise")` (and analogously for `b`). Evaluated `amt_mismatch` and `status_mismatch` independently.

## 5. Proof and regression prevention
- The fixes are proven by:
  - `tests/test_acceptance_matrix.py::test_invalid_refund_amounts_are_ignored` (15 variants including `True`, `False`, floats, and bounds).
  - `tests/test_acceptance_matrix.py::test_refunds_cannot_exceed_due` (20 variants of cumulative partial refunds).
  - `tests/test_acceptance_matrix.py::test_reconciliation_status_mismatch_matrix` (12 variants).
  - New regression tests in `tests/test_regression_and_edge_cases.py` ensuring simultaneous mismatches and duplicate conflicting events cannot reintroduce errors.

## 6. Unresolved challenge or next step
- In the current implementation, `processed_event_ids` is stored as an in-memory list within each order dict. For orders with high event traffic (e.g. dozens of status updates, webhooks, retries), checking `event_id in out["processed_event_ids"]` incurs O(N) lookup time. In a production distributed setting, this should be backed by an indexed database unique constraint or a Redis set with TTL.
