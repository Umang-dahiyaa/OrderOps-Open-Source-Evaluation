# optimizations.md - Required submission

## 1. Baseline and objective
- **Target of improvement**:
  - Correctness and idempotency verification under repeated and malformed event delivery.
  - Linear time reconciliation performance: `reconcile_orders` processes collections of orders and provider records.
  - Memory isolation: ensuring mutations do not leak to input references while avoiding unnecessary deep copies.
- **Evidence of headroom**:
  - Baseline tests failed 62/212 tests due to missing bounds and status checks.
  - The offline reconciliation demo output misclassified valid matching orders due to schema discrepancies (`total_paise` vs `amount_paise`).

## 2. Options considered
- **Option A: Early short-circuit for duplicate events**
  - *Expected benefit*: Avoids parsing event payloads, performing validations, and altering state when an event has already been seen.
  - *Risk/Trade-off*: Must ensure the idempotency check occurs before any state mutation so repeated events are pure no-ops. Implemented.
- **Option B: Replacing `deepcopy` with selective shallow copy**
  - *Expected benefit*: Faster execution per event by avoiding deep traversal of nested structures.
  - *Risk/Trade-off*: An order contains `processed_event_ids` (a list). A shallow copy would share the list between the original and returned order, violating callers' immutability expectations. Rejected; `deepcopy` was retained to guarantee complete isolation.
- **Option C: Pre-indexed dictionary mapping for reconciliation**
  - *Expected benefit*: Reduces cross-matching of `internal` and `provider` from O(N * M) nested scan to O(N + M) hash lookups, followed by O(K log K) deterministic key sorting.
  - *Risk/Trade-off*: Requires O(N + M) auxiliary memory for dictionary storage. Fully acceptable given transaction volumes. Implemented.
- **Option D: In-place array mutation vs pure functional copy**
  - *Expected benefit*: Lower allocation count.
  - *Risk/Trade-off*: Breaks contract tests verifying `input_order_is_not_mutated`. Rejected.

## 3. Changes implemented
- **Change 1: Hash-mapped order reconciliation with deterministic sort**
  - *Reason*: Converted `internal` and `provider` lists to dictionaries keyed by `order_id` in single linear passes, enabling O(1) attribute lookup and deterministic sorting of keys.
  - *Tests used to protect correctness*: `test_reconciliation_results_are_deterministic`, `test_reconciliation_amount_mismatch_matrix`, `test_reconciliation_status_mismatch_matrix`.
- **Change 2: Idempotency short-circuit**
  - *Reason*: Checked `event_id in out["processed_event_ids"]` immediately after copying, bypassing state transition logic on duplicate replays.
  - *Tests used to protect correctness*: `test_duplicate_event_is_idempotent`, `test_payment_event_replay_idempotent` (20 cases).
- **Change 3: Stream-based CSV export for stretch goal**
  - *Reason*: Implemented `export_awaiting_refund_csv` utilizing Python's built-in `csv.writer` and `io.StringIO` to generate reports with linear single-pass filtering.
  - *Tests used to protect correctness*: `test_stretch_export_awaiting_refund_csv`.

## 4. Trade-offs
- **Immutability vs Execution Speed**: Using `deepcopy` incurs a minor CPU allocation cost on each event, but guarantees thread safety, idempotency isolation, and zero side-effects on original objects.
- **Independent Mismatch Tracking**: Checking both amount and status independently means an order can appear in both `amount_mismatches` and `status_mismatches`. While this increases report size slightly, it prevents status discrepancies from being hidden when amounts differ (or vice versa).

## 5. Further improvements
- **Set-backed event tracking**: If orders endure large event volumes (hundreds of events), converting `processed_event_ids` to a set or Bloom filter will reduce lookup overhead from O(E) to O(1).
- **Batch event stream processing**: Provide an `apply_order_events(order, events: list[dict])` generator that executes batch updates in a single deep copy pass, avoiding copying after every individual event.
- **Typed Models (dataclass / Pydantic)**: Migrate the dynamic dictionary representation to typed frozen dataclasses to catch schema errors at lint or initialization time.
