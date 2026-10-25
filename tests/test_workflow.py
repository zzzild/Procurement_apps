from decimal import Decimal

import pytest

from app.extensions import db
from app.models import GoodsReceipt, PurchaseOrder, PurchaseOrderItem, PurchaseRequest, PurchaseRequestItem, User, Vendor, VendorQuotation, VendorQuotationItem
from app.services import create_purchase_order, receive_goods


def setup_approved_request():
    requester = User.query.filter_by(role="requester").first()
    procurement = User.query.filter_by(role="procurement").first()
    vendor = Vendor(vendor_code="V-1", name="Vendor One", is_active=True)
    pr = PurchaseRequest(request_number="PR-1", requester_id=requester.id, title="Paper", description="Office use", status="approved")
    pr.items.append(PurchaseRequestItem(item_name="Paper", quantity=Decimal("10"), unit="ream", estimated_unit_price=Decimal("50000")))
    db.session.add_all([vendor, pr])
    db.session.flush()
    quote = VendorQuotation(purchase_request_id=pr.id, vendor_id=vendor.id, quotation_number="Q-1", total_price=Decimal("450000"), created_by=procurement.id)
    quote.items.append(VendorQuotationItem(purchase_request_item_id=pr.items[0].id, item_name="Paper", quantity=Decimal("10"), unit="ream", unit_price=Decimal("45000")))
    db.session.add(quote)
    db.session.commit()
    return pr, quote, procurement


def test_pr_creation_and_approval_access(client, login):
    login("requester")
    response = client.post("/requests", data={"title": "Paper", "description": "Ops", "item_name[]": "Paper", "quantity[]": "2", "unit[]": "ream", "estimated_unit_price[]": "50000"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"pending approval" in response.data.lower()
    assert client.post("/requests/1/decision", data={"decision": "approved"}).status_code == 403


def test_po_and_receipt_quantity_guard(app):
    with app.app_context():
        pr, quote, procurement = setup_approved_request()
        po = create_purchase_order(pr, quote, procurement)
        db.session.commit()
        assert po.status == "issued"
        receiver = User.query.filter_by(role="receiver").first()
        with pytest.raises(ValueError, match="melebihi"):
            receive_goods(po, {str(po.items[0].id): "11"}, {}, "", receiver)
        db.session.rollback()
        receipt = receive_goods(po, {str(po.items[0].id): "4"}, {}, "First delivery", receiver)
        db.session.commit()
        assert po.status == "partially_received"
        receive_goods(po, {str(po.items[0].id): "6"}, {}, "Balance", receiver)
        db.session.commit()
        assert po.status == "fully_received"
        assert pr.status == "completed"


def test_end_to_end_role_handoffs(client, login, app):
    response = login("requester")
    response = client.post("/requests", data={"title": "Monitor", "description": "For support desk", "item_name[]": ["Monitor", "HDMI cable"], "quantity[]": ["2", "2"], "unit[]": ["unit", "unit"], "estimated_unit_price[]": ["2500000", "100000"]}, follow_redirects=True)
    assert response.status_code == 200
    assert b"pending approval" in response.data.lower()
    with app.app_context():
        pr_id = PurchaseRequest.query.filter_by(title="Monitor").one().id

    client.post("/logout")
    login("approver")
    response = client.post(f"/requests/{pr_id}/decision", data={"decision": "approved", "reason": "Within budget"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"approved" in response.data.lower()

    client.post("/logout")
    login("procurement")
    response = client.post("/vendors", data={"name": "Office Supply Co", "email": "sales@example.test"}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        vendor_id = Vendor.query.filter_by(name="Office Supply Co").one().id
        pr = db.session.get(PurchaseRequest, pr_id)
        item_ids = [item.id for item in pr.items]
    response = client.post(f"/vendors/{vendor_id}", data={"name": "Office Supply Co", "contact_person": "Procurement Desk", "is_active": "on"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Procurement Desk" in response.data
    response = client.post(f"/requests/{pr_id}/quotations/new", data={"vendor_id": str(vendor_id), "quotation_number": "Q-ROUTE-1", f"unit_price_{item_ids[0]}": "2400000", f"unit_price_{item_ids[1]}": "90000"}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        quote_id = VendorQuotation.query.filter_by(quotation_number="Q-ROUTE-1").one().id
    response = client.post(f"/requests/{pr_id}/purchase-order", data={"quotation_id": str(quote_id)}, follow_redirects=True)
    assert response.status_code == 200
    assert b"PO-" in response.data
    with app.app_context():
        po_id = PurchaseOrder.query.filter_by(purchase_request_id=pr_id).one().id
        po_item_ids = [item.id for item in db.session.get(PurchaseOrder, po_id).items]

    client.post("/logout")
    login("receiver")
    response = client.post(f"/purchase-orders/{po_id}/receipts", data={f"quantity_{po_item_ids[0]}": "2", f"quantity_{po_item_ids[1]}": "2", "notes": "Delivery accepted"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"fully received" in response.data.lower()
