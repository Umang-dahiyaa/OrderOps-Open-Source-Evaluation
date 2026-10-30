"""Starter order lifecycle and refund service; all data is synthetic."""
import csv
import io
from copy import deepcopy


def apply_order_event(order: dict, event: dict) -> dict:
    """Return an updated copy of order.

    Order keys: order_id, total_paise, status, payment_status, refund_due_paise,
    refunded_paise, processed_event_ids.
    """
    if not isinstance(order, dict):
        return order if order is not None else {}

    out = deepcopy(order)
    out.setdefault("payment_status", "UNPAID")
    out.setdefault("refund_due_paise", 0)
    out.setdefault("refunded_paise", 0)
    out.setdefault("processed_event_ids", [])

    if not isinstance(event, dict):
        return out

    event_id = event.get("event_id")
    if event_id is not None and event_id in out["processed_event_ids"]:
        return out

    kind = event.get("type")

    if kind == "payment_confirmed":
        out["payment_status"] = "PAID"
        if out.get("status") in ("REJECTED", "CANCELLED"):
            out["refund_due_paise"] = out.get("total_paise", 0)
    elif kind == "restaurant_accepted" and out.get("status") == "PLACED":
        out["status"] = "ACCEPTED"
    elif kind == "restaurant_rejected" and out.get("status") == "PLACED":
        out["status"] = "REJECTED"
        if out.get("payment_status") == "PAID":
            out["refund_due_paise"] = out.get("total_paise", 0)
    elif kind == "cancel_requested" and out.get("status") in ("PLACED", "ACCEPTED"):
        out["status"] = "CANCELLED"
        if out.get("payment_status") == "PAID":
            out["refund_due_paise"] = out.get("total_paise", 0)
    elif kind == "dispatch_started" and out.get("status") == "ACCEPTED":
        out["status"] = "OUT_FOR_DELIVERY"
    elif kind == "order_delivered" and out.get("status") == "OUT_FOR_DELIVERY":
        out["status"] = "DELIVERED"
    elif kind == "refund_processed":
        # Validate eligibility: only eligible cancelled/rejected orders that were paid
        # and have outstanding refundable amount.
        is_eligible = (
            out.get("status") in ("REJECTED", "CANCELLED")
            and out.get("payment_status") == "PAID"
            and out.get("refund_due_paise", 0) > 0
        )
        amount = event.get("amount_paise")
        is_valid_amount = (
            type(amount) is int
            and amount > 0
        )
        if is_eligible and is_valid_amount:
            remaining_due = out.get("refund_due_paise", 0) - out.get("refunded_paise", 0)
            if amount <= remaining_due:
                out["refunded_paise"] += amount
                if out["refunded_paise"] == out["refund_due_paise"]:
                    out["payment_status"] = "REFUNDED"

    if event_id is not None:
        out["processed_event_ids"].append(event_id)
    return out


def reconcile_orders(internal: list[dict] | None, provider: list[dict] | None) -> dict:
    """Compare transaction summaries keyed by order_id."""
    report = {
        "matched": [],
        "missing_from_provider": [],
        "missing_from_internal": [],
        "amount_mismatches": [],
        "status_mismatches": [],
    }
    if internal is None:
        internal = []
    if provider is None:
        provider = []

    left = {}
    for r in internal:
        if isinstance(r, dict) and r.get("order_id") is not None:
            left[r["order_id"]] = r

    right = {}
    for r in provider:
        if isinstance(r, dict) and r.get("order_id") is not None:
            right[r["order_id"]] = r

    for key in sorted(set(left) | set(right), key=lambda x: str(x)):
        if key not in right:
            report["missing_from_provider"].append(key)
        elif key not in left:
            report["missing_from_internal"].append(key)
        else:
            a, b = left[key], right[key]

            amt_a = a.get("amount_paise") if a.get("amount_paise") is not None else a.get("total_paise")
            amt_b = b.get("amount_paise") if b.get("amount_paise") is not None else b.get("total_paise")
            amt_mismatch = (amt_a != amt_b)

            status_a = a.get("status")
            status_b = b.get("status")
            status_mismatch = (status_a != status_b)

            if amt_mismatch:
                report["amount_mismatches"].append(key)
            if status_mismatch:
                report["status_mismatches"].append(key)
            if not amt_mismatch and not status_mismatch:
                report["matched"].append(key)

    return report


def export_awaiting_refund_csv(orders: list[dict]) -> str:
    """Generate a CSV report of orders that are eligible for or awaiting refund."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["order_id", "status", "payment_status", "total_paise", "refund_due_paise", "refunded_paise", "outstanding_paise"])
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        due = order.get("refund_due_paise", 0)
        refunded = order.get("refunded_paise", 0)
        outstanding = due - refunded
        if outstanding > 0 and order.get("payment_status") == "PAID":
            writer.writerow([
                order.get("order_id", ""),
                order.get("status", ""),
                order.get("payment_status", ""),
                order.get("total_paise", 0),
                due,
                refunded,
                outstanding,
            ])
    return output.getvalue()
