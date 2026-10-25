from datetime import datetime, timezone
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    __table_args__ = (db.CheckConstraint("role IN ('requester','approver','procurement','receiver')", name="ck_user_role_valid"),)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PurchaseRequest(db.Model):
    __tablename__ = "purchase_requests"
    id = db.Column(db.Integer, primary_key=True)
    request_number = db.Column(db.String(30), unique=True, nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default="pending_approval", index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    approved_at = db.Column(db.DateTime(timezone=True))
    approval_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    requester = db.relationship("User", foreign_keys=[requester_id])
    approver = db.relationship("User", foreign_keys=[approved_by])
    items = db.relationship("PurchaseRequestItem", cascade="all, delete-orphan", order_by="PurchaseRequestItem.id")
    quotations = db.relationship("VendorQuotation", back_populates="purchase_request")
    purchase_order = db.relationship("PurchaseOrder", back_populates="purchase_request", uselist=False)
    __table_args__ = (db.CheckConstraint("status IN ('pending_approval','approved','rejected','in_procurement','ordered','completed')", name="ck_request_status_valid"),)


class PurchaseRequestItem(db.Model):
    __tablename__ = "purchase_request_items"
    id = db.Column(db.Integer, primary_key=True)
    purchase_request_id = db.Column(db.Integer, db.ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False)
    item_name = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    estimated_unit_price = db.Column(db.Numeric(14, 2), nullable=False, default=Decimal("0"))
    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_request_item_quantity_positive"), db.CheckConstraint("estimated_unit_price >= 0", name="ck_request_item_price_nonnegative"))


class Vendor(db.Model):
    __tablename__ = "vendors"
    id = db.Column(db.Integer, primary_key=True)
    vendor_code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(180), nullable=False)
    contact_person = db.Column(db.String(120))
    email = db.Column(db.String(255))
    phone = db.Column(db.String(40))
    address = db.Column(db.Text)
    rating = db.Column(db.Numeric(3, 2))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    quotations = db.relationship("VendorQuotation", back_populates="vendor")
    __table_args__ = (db.CheckConstraint("rating IS NULL OR (rating >= 0 AND rating <= 5)", name="ck_vendor_rating_range"),)


class VendorQuotation(db.Model):
    __tablename__ = "vendor_quotations"
    id = db.Column(db.Integer, primary_key=True)
    purchase_request_id = db.Column(db.Integer, db.ForeignKey("purchase_requests.id"), nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    quotation_number = db.Column(db.String(80), nullable=False)
    quotation_date = db.Column(db.Date)
    valid_until = db.Column(db.Date)
    delivery_days = db.Column(db.Integer)
    total_price = db.Column(db.Numeric(14, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="IDR")
    document_path = db.Column(db.String(500))
    ocr_status = db.Column(db.String(32), nullable=False, default="not_requested")
    ocr_text = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    purchase_request = db.relationship("PurchaseRequest", back_populates="quotations")
    vendor = db.relationship("Vendor", back_populates="quotations")
    creator = db.relationship("User")
    items = db.relationship("VendorQuotationItem", cascade="all, delete-orphan", order_by="VendorQuotationItem.id")
    __table_args__ = (db.UniqueConstraint("vendor_id", "quotation_number", name="uq_vendor_quotation_number"), db.CheckConstraint("total_price >= 0", name="ck_quotation_total_nonnegative"), db.CheckConstraint("ocr_status IN ('not_requested','processed','failed')", name="ck_quotation_ocr_status_valid"))


class VendorQuotationItem(db.Model):
    __tablename__ = "vendor_quotation_items"
    id = db.Column(db.Integer, primary_key=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey("vendor_quotations.id", ondelete="CASCADE"), nullable=False)
    purchase_request_item_id = db.Column(db.Integer, db.ForeignKey("purchase_request_items.id"))
    item_name = db.Column(db.String(180), nullable=False)
    quantity = db.Column(db.Numeric(12, 2), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    __table_args__ = (db.CheckConstraint("quantity > 0", name="ck_quotation_item_quantity_positive"), db.CheckConstraint("unit_price >= 0", name="ck_quotation_item_price_nonnegative"))


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"
    id = db.Column(db.Integer, primary_key=True)
    po_number = db.Column(db.String(30), unique=True, nullable=False)
    purchase_request_id = db.Column(db.Integer, db.ForeignKey("purchase_requests.id"), unique=True, nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    quotation_id = db.Column(db.Integer, db.ForeignKey("vendor_quotations.id"), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="issued", index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    purchase_request = db.relationship("PurchaseRequest", back_populates="purchase_order")
    vendor = db.relationship("Vendor")
    quotation = db.relationship("VendorQuotation")
    creator = db.relationship("User")
    items = db.relationship("PurchaseOrderItem", cascade="all, delete-orphan", order_by="PurchaseOrderItem.id")
    receipts = db.relationship("GoodsReceipt", cascade="all, delete-orphan", order_by="GoodsReceipt.received_at")
    __table_args__ = (db.CheckConstraint("status IN ('issued','partially_received','fully_received')", name="ck_po_status_valid"),)


class PurchaseOrderItem(db.Model):
    __tablename__ = "purchase_order_items"
    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    request_item_id = db.Column(db.Integer, db.ForeignKey("purchase_request_items.id"), nullable=False)
    item_name = db.Column(db.String(180), nullable=False)
    quantity_ordered = db.Column(db.Numeric(12, 2), nullable=False)
    unit = db.Column(db.String(32), nullable=False)
    unit_price = db.Column(db.Numeric(14, 2), nullable=False)
    __table_args__ = (db.CheckConstraint("quantity_ordered > 0", name="ck_po_item_quantity_positive"), db.CheckConstraint("unit_price >= 0", name="ck_po_item_price_nonnegative"))


class GoodsReceipt(db.Model):
    __tablename__ = "goods_receipts"
    id = db.Column(db.Integer, primary_key=True)
    receipt_number = db.Column(db.String(30), unique=True, nullable=False)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id"), nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    receiver = db.relationship("User")
    items = db.relationship("GoodsReceiptItem", cascade="all, delete-orphan")


class GoodsReceiptItem(db.Model):
    __tablename__ = "goods_receipt_items"
    id = db.Column(db.Integer, primary_key=True)
    goods_receipt_id = db.Column(db.Integer, db.ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False)
    purchase_order_item_id = db.Column(db.Integer, db.ForeignKey("purchase_order_items.id"), nullable=False)
    quantity_received = db.Column(db.Numeric(12, 2), nullable=False)
    condition = db.Column(db.String(40), nullable=False)
    notes = db.Column(db.Text)
    order_item = db.relationship("PurchaseOrderItem")
    __table_args__ = (db.CheckConstraint("quantity_received > 0", name="ck_receipt_quantity_positive"), db.CheckConstraint("condition IN ('good','damaged','incomplete')", name="ck_receipt_condition_valid"))


class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(60), nullable=False)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    user = db.relationship("User")
