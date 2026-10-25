"""Idempotently create demo users and a compact end-to-end sample workflow."""
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.extensions import db
from app.models import ActivityLog, GoodsReceipt, GoodsReceiptItem, PurchaseOrder, PurchaseOrderItem, PurchaseRequest, PurchaseRequestItem, User, Vendor, VendorQuotation, VendorQuotationItem

app = create_app()


def seed():
    with app.app_context():
        db.create_all()
        users = {}
        accounts = [
            ("Alya Requester", "requester@procura.test", "requester"),
            ("Rafi Approver", "approver@procura.test", "approver"),
            ("Nadia Procurement", "procurement@procura.test", "procurement"),
            ("Dimas Receiver", "receiver@procura.test", "receiver"),
        ]
        for name, email, role in accounts:
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(name=name, email=email, role=role, is_active=True)
                user.set_password("ProcuraDemo2026!")
                db.session.add(user)
            users[role] = user
        db.session.flush()
        vendors = []
        for code, name in [("VEN-0001", "PT Sumber Teknologi"), ("VEN-0002", "CV Prima Office")]:
            vendor = Vendor.query.filter_by(vendor_code=code).first()
            if not vendor:
                vendor = Vendor(vendor_code=code, name=name, contact_person="Sales Team", email=f"sales@{code.lower()}.test", phone="021-555-0100", address="Jakarta, Indonesia", is_active=True)
                db.session.add(vendor)
            vendors.append(vendor)
        db.session.flush()

        def get_or_make(number, title, status, approved=False, with_po=False, partial=False):
            pr = PurchaseRequest.query.filter_by(request_number=number).first()
            if pr:
                return pr
            pr = PurchaseRequest(request_number=number, requester_id=users["requester"].id, title=title, description="Kebutuhan operasional tim untuk mendukung layanan internal.", status=status, approved_by=users["approver"].id if approved else None, approved_at=db.func.current_timestamp() if approved else None, approval_reason=("Ditolak karena pengadaan ditunda." if status == "rejected" else "Sesuai anggaran dan kebutuhan operasional.") if approved else None)
            pr.items.append(PurchaseRequestItem(item_name="Laptop bisnis 14 inci", description="RAM 16 GB, SSD 512 GB", quantity=Decimal("3"), unit="unit", estimated_unit_price=Decimal("12500000")))
            db.session.add(pr)
            db.session.flush()
            db.session.add(ActivityLog(user_id=users["requester"].id, action="request_created", entity_type="purchase_requests", entity_id=pr.id, description=f"Purchase request {pr.request_number} dibuat."))
            if approved:
                decision = "Ditolak karena pengadaan ditunda." if status == "rejected" else "Disetujui sesuai anggaran dan kebutuhan operasional."
                db.session.add(ActivityLog(user_id=users["approver"].id, action=f"request_{status if status == 'rejected' else 'approved'}", entity_type="purchase_requests", entity_id=pr.id, description=f"PR {pr.request_number}: {decision}"))
            if status in {"approved", "ordered", "in_procurement", "completed"}:
                for vendor, price, quote_no, days in [(vendors[0], Decimal("11900000"), f"QT-{number[-2:]}-A", 7), (vendors[1], Decimal("12200000"), f"QT-{number[-2:]}-B", 5)]:
                    q = VendorQuotation(purchase_request_id=pr.id, vendor_id=vendor.id, quotation_number=quote_no, quotation_date=date.today(), valid_until=date.today()+timedelta(days=30), delivery_days=days, total_price=price*3, currency="IDR", created_by=users["procurement"].id)
                    q.items.append(VendorQuotationItem(item_name="Laptop bisnis 14 inci", quantity=Decimal("3"), unit="unit", unit_price=price, purchase_request_item_id=pr.items[0].id))
                    db.session.add(q)
                db.session.flush()
                db.session.add(ActivityLog(user_id=users["procurement"].id, action="quotation_created", entity_type="vendor_quotations", entity_id=pr.quotations[0].id, description=f"Quotation options dicatat untuk {pr.request_number}."))
            if with_po:
                quote = pr.quotations[0]
                po = PurchaseOrder(po_number=f"PO-DEMO-{number[-2:]}", purchase_request_id=pr.id, vendor_id=quote.vendor_id, quotation_id=quote.id, status="partially_received" if partial else "issued", created_by=users["procurement"].id)
                db.session.add(po)
                db.session.flush()
                db.session.add(ActivityLog(user_id=users["procurement"].id, action="po_issued", entity_type="purchase_orders", entity_id=po.id, description=f"PO {po.po_number} diterbitkan."))
                order_item = PurchaseOrderItem(purchase_order_id=po.id, request_item_id=pr.items[0].id, item_name=pr.items[0].item_name, quantity_ordered=Decimal("3"), unit="unit", unit_price=quote.items[0].unit_price)
                db.session.add(order_item)
                if partial:
                    receipt = GoodsReceipt(receipt_number=f"GR-DEMO-{number[-2:]}", purchase_order_id=po.id, received_by=users["receiver"].id, notes="Penerimaan awal; satu unit menyusul.")
                    db.session.add(receipt)
                    db.session.flush()
                    db.session.add(GoodsReceiptItem(goods_receipt_id=receipt.id, purchase_order_item_id=order_item.id, quantity_received=Decimal("2"), condition="good"))
                    db.session.add(ActivityLog(user_id=users["receiver"].id, action="goods_received", entity_type="goods_receipts", entity_id=receipt.id, description=f"Penerimaan {receipt.receipt_number} dicatat."))
            return pr

        get_or_make("PR-DEMO-01", "Laptops for field team", "pending_approval")
        get_or_make("PR-DEMO-02", "Laptop replacement pool", "approved", approved=True)
        get_or_make("PR-DEMO-03", "Archived meeting room display", "rejected", approved=True)
        get_or_make("PR-DEMO-04", "Laptops phase one", "in_procurement", approved=True, with_po=True, partial=True)
        db.session.commit()
        print("Demo data is ready. Existing demo records were preserved.")


if __name__ == "__main__":
    seed()
