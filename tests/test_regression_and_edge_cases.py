"""Regression and edge-case test suite for OrderOps service."""
import json
from pathlib import Path
import pytest
from models import new_order
from service import apply_order_event, reconcile_orders, export_awaiting_refund_csv


def make_event(event_id, kind, **kwargs):
    return {"event_id": event_id, "type": kind, **kwargs}


def test_edge_case_cancellation_after_dispatch_and_delivery():
    """Verify cancellation requests after dispatch or delivery are strictly ignored."""
    order_dispatched = new_order("ORD-DISP", 5000, "OUT_FOR_DELIVERY")
    out_disp = apply_order_event(order_dispatched, make_event("E-C1", "cancel_requested"))
    assert out_disp["status"] == "OUT_FOR_DELIVERY"
    assert out_disp["refund_due_paise"] == 0

    order_delivered = new_order("ORD-DELV", 5000, "DELIVERED")
    out_delv = apply_order_event(order_delivered, make_event("E-C2", "cancel_requested"))
    assert out_delv["status"] == "DELIVERED"
    assert out_delv["refund_due_paise"] == 0


def test_edge_case_late_payment_after_cancellation():
    """Verify payment confirmation arriving after cancellation sets refund_due_paise."""
    order = new_order("ORD-LATE", 3500, "PLACED")
    # Customer cancels before paying
    cancelled = apply_order_event(order, make_event("E-1", "cancel_requested"))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["payment_status"] == "UNPAID"
    assert cancelled["refund_due_paise"] == 0

    # Payment confirmation arrives late
    paid_late = apply_order_event(cancelled, make_event("E-2", "payment_confirmed"))
    assert paid_late["status"] == "CANCELLED"
    assert paid_late["payment_status"] == "PAID"
    assert paid_late["refund_due_paise"] == 3500

    # Eligible for refund now
    refunded = apply_order_event(paid_late, make_event("E-3", "refund_processed", amount_paise=3500))
    assert refunded["refunded_paise"] == 3500
    assert refunded["payment_status"] == "REFUNDED"


def test_edge_case_late_payment_after_restaurant_rejection():
    """Verify payment confirmation arriving after rejection sets refund_due_paise."""
    order = new_order("ORD-REJ-LATE", 4200, "PLACED")
    rejected = apply_order_event(order, make_event("E-R1", "restaurant_rejected"))
    assert rejected["status"] == "REJECTED"
    assert rejected["payment_status"] == "UNPAID"
    assert rejected["refund_due_paise"] == 0

    paid_late = apply_order_event(rejected, make_event("E-R2", "payment_confirmed"))
    assert paid_late["status"] == "REJECTED"
    assert paid_late["payment_status"] == "PAID"
    assert paid_late["refund_due_paise"] == 4200


def test_edge_case_multi_step_partial_refunds_and_overpayment_protection():
    """Verify cumulative partial refunds match exact due amount and reject exceeding amounts."""
    order = new_order("ORD-PARTIAL", 10000, "CANCELLED")
    order.update(payment_status="PAID", refund_due_paise=10000)

    # 1st refund: 4000
    step1 = apply_order_event(order, make_event("R-1", "refund_processed", amount_paise=4000))
    assert step1["refunded_paise"] == 4000
    assert step1["payment_status"] == "PAID"

    # 2nd refund: 7000 (exceeds remaining 6000 -> must be rejected)
    step2_invalid = apply_order_event(step1, make_event("R-2-INVALID", "refund_processed", amount_paise=7000))
    assert step2_invalid["refunded_paise"] == 4000
    assert step2_invalid["payment_status"] == "PAID"

    # 2nd refund valid: 3500 (remaining is now 2500)
    step2 = apply_order_event(step1, make_event("R-2", "refund_processed", amount_paise=3500))
    assert step2["refunded_paise"] == 7500
    assert step2["payment_status"] == "PAID"

    # 3rd refund valid: 2500 (fully refunded)
    step3 = apply_order_event(step2, make_event("R-3", "refund_processed", amount_paise=2500))
    assert step3["refunded_paise"] == 10000
    assert step3["payment_status"] == "REFUNDED"

    # 4th refund: order is now REFUNDED, no further refunds allowed
    step4 = apply_order_event(step3, make_event("R-4", "refund_processed", amount_paise=100))
    assert step4["refunded_paise"] == 10000
    assert step4["payment_status"] == "REFUNDED"


def test_edge_case_simultaneous_amount_and_status_mismatch():
    """Verify an order with both amount mismatch and status mismatch is recorded in both."""
    internal = [{"order_id": "ORD-BOTH", "amount_paise": 2000, "status": "ACCEPTED"}]
    provider = [{"order_id": "ORD-BOTH", "amount_paise": 2500, "status": "CANCELLED"}]

    report = reconcile_orders(internal, provider)
    assert report["amount_mismatches"] == ["ORD-BOTH"]
    assert report["status_mismatches"] == ["ORD-BOTH"]
    assert report["matched"] == []
    assert report["missing_from_provider"] == []
    assert report["missing_from_internal"] == []


def test_edge_case_malformed_and_boundary_inputs():
    """Verify service robustness against None, non-dict, and missing fields."""
    # None and non-dict orders
    assert apply_order_event(None, make_event("E-1", "payment_confirmed")) == {}
    assert apply_order_event("not-a-dict", make_event("E-1", "payment_confirmed")) == "not-a-dict"

    # None and non-dict events
    order = new_order("O-1", 1000)
    assert apply_order_event(order, None) == {
        "order_id": "O-1", "total_paise": 1000, "status": "PLACED",
        "payment_status": "UNPAID", "refund_due_paise": 0, "refunded_paise": 0,
        "processed_event_ids": []
    }
    assert apply_order_event(order, {})["status"] == "PLACED"

    # Reconcile with None inputs
    empty_rep = reconcile_orders(None, None)
    assert empty_rep == {
        "matched": [], "missing_from_provider": [], "missing_from_internal": [],
        "amount_mismatches": [], "status_mismatches": []
    }

    # Reconcile with non-dict elements or missing order_id
    dirty_internal = [None, "invalid", {"other_key": 123}, {"order_id": "ORD-VALID", "amount_paise": 500, "status": "PLACED"}]
    dirty_provider = [{"order_id": "ORD-VALID", "amount_paise": 500, "status": "PLACED"}]
    report = reconcile_orders(dirty_internal, dirty_provider)
    assert report["matched"] == ["ORD-VALID"]


def test_edge_case_duplicate_event_with_conflicting_payload():
    """Verify an event ID replayed with conflicting type/amount is ignored due to idempotency."""
    order = new_order("ORD-IDEMP", 5000, "PLACED")
    event1 = make_event("EV-CONFLICT", "payment_confirmed")
    after_ev1 = apply_order_event(order, event1)
    assert after_ev1["payment_status"] == "PAID"
    assert after_ev1["processed_event_ids"] == ["EV-CONFLICT"]

    # Conflicting event reusing the same event_id
    event1_conflict = make_event("EV-CONFLICT", "restaurant_accepted")
    after_conflict = apply_order_event(after_ev1, event1_conflict)
    # Status must NOT transition to ACCEPTED because EV-CONFLICT was already processed
    assert after_conflict["status"] == "PLACED"
    assert after_conflict["processed_event_ids"] == ["EV-CONFLICT"]


def test_stretch_export_awaiting_refund_csv():
    """Verify stretch goal awaiting-refund CSV export functionality."""
    orders = [
        {"order_id": "ORD-1", "status": "CANCELLED", "payment_status": "PAID", "total_paise": 5000, "refund_due_paise": 5000, "refunded_paise": 2000},
        {"order_id": "ORD-2", "status": "REJECTED", "payment_status": "PAID", "total_paise": 3000, "refund_due_paise": 3000, "refunded_paise": 0},
        {"order_id": "ORD-3", "status": "DELIVERED", "payment_status": "PAID", "total_paise": 4000, "refund_due_paise": 0, "refunded_paise": 0},
        {"order_id": "ORD-4", "status": "CANCELLED", "payment_status": "REFUNDED", "total_paise": 2500, "refund_due_paise": 2500, "refunded_paise": 2500},
    ]
    csv_text = export_awaiting_refund_csv(orders)
    lines = [line.strip() for line in csv_text.strip().splitlines()]
    assert len(lines) == 3  # header + ORD-1 + ORD-2
    assert lines[0] == "order_id,status,payment_status,total_paise,refund_due_paise,refunded_paise,outstanding_paise"
    assert "ORD-1,CANCELLED,PAID,5000,5000,2000,3000" in lines[1:]
    assert "ORD-2,REJECTED,PAID,3000,3000,0,3000" in lines[1:]

