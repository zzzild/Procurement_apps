from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urljoin, urlparse

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import ActivityLog, GoodsReceipt, PurchaseOrder, PurchaseRequest, PurchaseRequestItem, User, Vendor, VendorQuotation, VendorQuotationItem
from .permissions import roles_required
from .services import create_purchase_order, log_action, receive_goods, run_ocr

auth = Blueprint("auth", __name__)
main = Blueprint("main", __name__)
ROLES = {"requester": "Requester", "approver": "Approver", "procurement": "Procurement Staff", "receiver": "Receiver"}


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if user and user.is_active and user.check_password(request.form.get("password", "")):
            login_user(user)
            flash(f"Selamat datang kembali, {user.name}. Anda berhasil masuk ke workspace.", "auth_success")
            next_url = request.args.get("next", "")
            target = urlparse(urljoin(request.host_url, next_url))
            if target.scheme in {"http", "https"} and target.netloc == request.host:
                return redirect(target.geturl())
            return redirect(url_for("main.dashboard"))
        flash("Email atau kata sandi belum cocok. Periksa kembali lalu coba lagi.", "auth_error")
    return render_template("auth/login.html", email=request.form.get("email", "").strip())


@auth.post("/logout")
@roles_required(*ROLES)
def logout():
    logout_user()
    flash("Anda telah keluar.", "success")
    return redirect(url_for("auth.login"))


@main.get("/")
def index():
    return redirect(url_for("main.dashboard")) if current_user.is_authenticated else redirect(url_for("auth.login"))


@main.get("/dashboard")
@roles_required(*ROLES)
def dashboard():
    role = current_user.role
    if role == "requester":
        requests_q = PurchaseRequest.query.filter_by(requester_id=current_user.id)
        stats = {status: requests_q.filter_by(status=status).count() for status in ["pending_approval", "approved", "rejected", "ordered", "completed"]}
        rows = requests_q.order_by(PurchaseRequest.created_at.desc()).limit(6).all()
    elif role == "approver":
        stats = {"pending_approval": PurchaseRequest.query.filter_by(status="pending_approval").count()}
        rows = PurchaseRequest.query.filter_by(status="pending_approval").order_by(PurchaseRequest.created_at).limit(8).all()
    elif role == "procurement":
        stats = {"ready_to_process": PurchaseRequest.query.filter(PurchaseRequest.status.in_(["approved", "in_procurement"])).count(), "quotations": VendorQuotation.query.count(), "active_pos": PurchaseOrder.query.filter(PurchaseOrder.status != "fully_received").count()}
        rows = PurchaseRequest.query.filter(PurchaseRequest.status.in_(["approved", "in_procurement"])).order_by(PurchaseRequest.created_at).limit(8).all()
    else:
        stats = {"issued": PurchaseOrder.query.filter_by(status="issued").count(), "partially_received": PurchaseOrder.query.filter_by(status="partially_received").count()}
        rows = PurchaseOrder.query.filter(PurchaseOrder.status != "fully_received").order_by(PurchaseOrder.issued_at).limit(8).all()
    return render_template("dashboard/index.html", role_label=ROLES[role], stats=stats, rows=rows)


def visible_request(pr_id):
    pr = db.session.get(PurchaseRequest, pr_id)
    if not pr:
        abort(404)
    if current_user.role == "requester" and pr.requester_id != current_user.id:
        abort(404)
    return pr


@main.route("/requests", methods=["GET", "POST"])
@roles_required("requester", "approver", "procurement")
def purchase_requests():
    if request.method == "POST":
        names = request.form.getlist("item_name[]")
        quantities = request.form.getlist("quantity[]")
        units = request.form.getlist("unit[]")
        prices = request.form.getlist("estimated_unit_price[]")
        title, description = request.form.get("title", "").strip(), request.form.get("description", "").strip()
        try:
            items = []
            for name, qty, unit, price in zip(names, quantities, units, prices):
                if not name.strip():
                    continue
                quantity, unit_price = Decimal(qty), Decimal(price or "0")
                if not quantity.is_finite() or not unit_price.is_finite() or quantity <= 0 or unit_price < 0 or not unit.strip():
                    raise ValueError
                items.append(PurchaseRequestItem(item_name=name.strip(), quantity=quantity, unit=unit.strip(), estimated_unit_price=unit_price))
            if not title or not description or not items:
                raise ValueError
            pr = PurchaseRequest(request_number=f"PR-{date.today():%Y%m%d}-{current_user.id}-{int(date.today().strftime('%j'))}{PurchaseRequest.query.count()+1:03d}", requester_id=current_user.id, title=title, description=description, status="pending_approval", items=items)
            db.session.add(pr)
            db.session.flush()
            log_action(current_user, "request_created", pr, f"Purchase request {pr.request_number} dibuat.")
            db.session.commit()
            flash("Purchase Request berhasil dibuat.", "success")
            return redirect(url_for("main.request_detail", pr_id=pr.id))
        except (InvalidOperation, ValueError):
            db.session.rollback()
            flash("Lengkapi judul, alasan, dan minimal satu item dengan kuantitas/harga valid.", "error")
        except IntegrityError:
            db.session.rollback()
            flash("Nomor PR bentrok. Coba kirim ulang.", "error")
    if current_user.role == "requester":
        query = PurchaseRequest.query.filter_by(requester_id=current_user.id)
    elif current_user.role == "approver":
        query = PurchaseRequest.query.filter_by(status="pending_approval")
    else:
        query = PurchaseRequest.query.filter(PurchaseRequest.status.in_(["approved", "ordered", "in_procurement", "completed"]))
    return render_template("purchase_requests/list.html", requests=query.order_by(PurchaseRequest.created_at.desc()).all(), can_create=current_user.role == "requester")


@main.get("/requests/<int:pr_id>")
@roles_required(*ROLES)
def request_detail(pr_id):
    pr = visible_request(pr_id)
    logs = ActivityLog.query.filter_by(entity_type="purchase_requests", entity_id=pr.id).order_by(ActivityLog.created_at.desc()).all()
    return render_template("purchase_requests/detail.html", pr=pr, logs=logs)


@main.post("/requests/<int:pr_id>/decision")
@roles_required("approver")
def decide_request(pr_id):
    pr = visible_request(pr_id)
    decision, reason = request.form.get("decision"), request.form.get("reason", "").strip()
    if pr.status != "pending_approval" or decision not in {"approved", "rejected"} or (decision == "rejected" and not reason):
        flash("Keputusan tidak valid; alasan wajib diisi untuk penolakan.", "error")
    else:
        pr.status, pr.approved_by, pr.approved_at, pr.approval_reason = decision, current_user.id, db.func.current_timestamp(), reason
        log_action(current_user, f"request_{decision}", pr, f"PR {pr.request_number} {decision}. {reason}")
        db.session.commit()
        flash(f"Purchase Request {decision}.", "success")
    return redirect(url_for("main.request_detail", pr_id=pr.id))


@main.route("/vendors", methods=["GET", "POST"])
@roles_required("procurement")
def vendors():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            vendor = Vendor(vendor_code=f"VEN-{Vendor.query.count()+1:04d}", name=name, contact_person=request.form.get("contact_person", "").strip(), email=request.form.get("email", "").strip(), phone=request.form.get("phone", "").strip(), address=request.form.get("address", "").strip())
            db.session.add(vendor)
            db.session.flush()
            log_action(current_user, "vendor_created", vendor, f"Vendor {vendor.name} ditambahkan.")
            db.session.commit()
            flash("Vendor berhasil ditambahkan.", "success")
            return redirect(url_for("main.vendors"))
        flash("Nama vendor wajib diisi.", "error")
    return render_template("vendors/list.html", vendors=Vendor.query.order_by(Vendor.name).all())


@main.post("/vendors/<int:vendor_id>")
@roles_required("procurement")
def vendor_update(vendor_id):
    vendor = db.session.get(Vendor, vendor_id)
    if not vendor:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nama vendor wajib diisi.", "error")
    else:
        vendor.name = name
        vendor.contact_person = request.form.get("contact_person", "").strip()
        vendor.email = request.form.get("email", "").strip()
        vendor.phone = request.form.get("phone", "").strip()
        vendor.address = request.form.get("address", "").strip()
        vendor.is_active = request.form.get("is_active") == "on"
        log_action(current_user, "vendor_updated", vendor, f"Data vendor {vendor.name} diperbarui.")
        db.session.commit()
        flash("Vendor berhasil diperbarui.", "success")
    return redirect(url_for("main.vendors"))


@main.route("/requests/<int:pr_id>/quotations/new", methods=["GET", "POST"])
@roles_required("procurement")
def quotation_new(pr_id):
    pr = visible_request(pr_id)
    if pr.status not in {"approved", "in_procurement"} or pr.purchase_order:
        abort(403)
    if request.method == "POST":
        try:
            vendor_id = int(request.form.get("vendor_id", "0"))
            vendor = db.session.get(Vendor, vendor_id)
            number = request.form.get("quotation_number", "").strip()
            if not vendor or not vendor.is_active or not number:
                raise ValueError("Vendor dan nomor quotation wajib diisi.")
            qitems = []
            for item in pr.items:
                price = Decimal(request.form.get(f"unit_price_{item.id}", ""))
                if not price.is_finite() or price < 0:
                    raise ValueError("Harga harus nol atau lebih.")
                qitems.append(VendorQuotationItem(purchase_request_item_id=item.id, item_name=item.item_name, quantity=item.quantity, unit=item.unit, unit_price=price))
            total = sum((x.quantity * x.unit_price for x in qitems), Decimal("0"))
            quotation_date = date.fromisoformat(request.form["quotation_date"]) if request.form.get("quotation_date") else None
            valid_until = date.fromisoformat(request.form["valid_until"]) if request.form.get("valid_until") else None
            delivery_days = int(request.form.get("delivery_days")) if request.form.get("delivery_days") else None
            if valid_until and quotation_date and valid_until < quotation_date:
                raise ValueError("Tanggal berlaku tidak boleh sebelum tanggal quotation.")
            if delivery_days is not None and delivery_days < 1:
                raise ValueError("Estimasi pengiriman minimal satu hari.")
            ocr_status = request.form.get("ocr_status", "not_requested")
            if ocr_status not in {"not_requested", "processed", "failed"}:
                raise ValueError("Status OCR tidak valid.")
            quotation = VendorQuotation(purchase_request_id=pr.id, vendor_id=vendor.id, quotation_number=number, quotation_date=quotation_date, valid_until=valid_until, delivery_days=delivery_days, total_price=total, currency="IDR", created_by=current_user.id, ocr_status=ocr_status, ocr_text=request.form.get("ocr_text") or None, items=qitems)
            document_name = request.form.get("document_name", "").strip()
            if document_name:
                candidate = Path(current_app.config["UPLOAD_FOLDER"]) / document_name
                if Path(document_name).name != document_name or not candidate.is_file():
                    raise ValueError("Dokumen OCR tidak valid. Unggah ulang dokumen quotation.")
                quotation.document_path = document_name
            db.session.add(quotation)
            db.session.flush()
            pr.status = "in_procurement"
            log_action(current_user, "quotation_created", quotation, f"Quotation {number} dicatat dari {vendor.name}.")
            db.session.commit()
            flash("Quotation berhasil disimpan.", "success")
            return redirect(url_for("main.request_detail", pr_id=pr.id))
        except (ValueError, InvalidOperation, KeyError) as exc:
            db.session.rollback()
            flash(str(exc) or "Data quotation tidak valid.", "error")
        except IntegrityError:
            db.session.rollback()
            flash("Nomor quotation tersebut sudah digunakan untuk vendor ini.", "error")
    return render_template("quotations/form.html", pr=pr, vendors=Vendor.query.filter_by(is_active=True).all(), quotation=None, extracted={}, ocr_text="", document_name="", ocr_status="not_requested")


@main.post("/ocr")
@roles_required("procurement")
def quotation_ocr():
    upload = request.files.get("document")
    pr = db.session.get(PurchaseRequest, request.form.get("pr_id", type=int))
    if not pr or pr.status not in {"approved", "in_procurement"} or pr.purchase_order:
        abort(404)
    if not upload or not upload.filename:
        flash("Pilih dokumen terlebih dahulu.", "error")
        return redirect(url_for("main.quotation_new", pr_id=pr.id))
    try:
        path, text, extracted = run_ocr(upload)
        flash("OCR selesai. Periksa dan koreksi hasil sebelum menyimpan quotation.", "success")
        return render_template("quotations/form.html", pr=pr, vendors=Vendor.query.filter_by(is_active=True).all(), quotation=None, extracted=extracted, ocr_text=text, document_name=Path(path).name, ocr_status="processed")
    except (ValueError, RuntimeError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("main.quotation_new", pr_id=pr.id))


@main.get("/private-documents/<path:filename>")
@roles_required("procurement")
def private_document(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@main.route("/requests/<int:pr_id>/purchase-order", methods=["GET", "POST"])
@roles_required("procurement")
def create_po(pr_id):
    pr = visible_request(pr_id)
    if pr.status not in {"approved", "in_procurement"} or pr.purchase_order:
        abort(403)
    if request.method == "POST":
        quotation = db.session.get(VendorQuotation, request.form.get("quotation_id", type=int))
        if not quotation:
            flash("Pilih quotation terlebih dahulu.", "error")
        else:
            try:
                po = create_purchase_order(pr, quotation, current_user)
                db.session.commit()
                flash("Purchase Order diterbitkan.", "success")
                return redirect(url_for("main.po_detail", po_id=po.id))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "error")
    quotes = VendorQuotation.query.filter_by(purchase_request_id=pr.id).all()
    return render_template("purchase_orders/create.html", pr=pr, quotations=quotes)


@main.get("/purchase-orders")
@roles_required("procurement", "receiver")
def purchase_orders():
    orders = PurchaseOrder.query.order_by(PurchaseOrder.issued_at.desc()).all()
    return render_template("purchase_orders/list.html", orders=orders)


@main.get("/purchase-orders/<int:po_id>")
@roles_required("procurement", "receiver")
def po_detail(po_id):
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        abort(404)
    return render_template("purchase_orders/detail.html", po=po)


@main.post("/purchase-orders/<int:po_id>/receipts")
@roles_required("receiver")
def receive_po(po_id):
    po = db.session.get(PurchaseOrder, po_id)
    if not po:
        abort(404)
    try:
        quantities = {str(item.id): request.form.get(f"quantity_{item.id}", "0") or "0" for item in po.items}
        conditions = {str(item.id): request.form.get(f"condition_{item.id}", "good") for item in po.items}
        receipt = receive_goods(po, quantities, conditions, request.form.get("notes", "").strip(), current_user)
        db.session.commit()
        flash(f"Penerimaan {receipt.receipt_number} berhasil dicatat.", "success")
    except (ValueError, InvalidOperation) as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("main.po_detail", po_id=po.id))


@main.get("/receipts/<int:receipt_id>")
@roles_required("receiver", "procurement")
def receipt_detail(receipt_id):
    receipt = db.session.get(GoodsReceipt, receipt_id)
    if not receipt:
        abort(404)
    return render_template("goods_receipts/detail.html", receipt=receipt)


@main.get("/activity")
@roles_required(*ROLES)
def activity():
    query = ActivityLog.query
    if current_user.role == "requester":
        own_ids = db.session.query(PurchaseRequest.id).filter_by(requester_id=current_user.id)
        query = query.filter((ActivityLog.entity_type == "purchase_requests") & ActivityLog.entity_id.in_(own_ids))
    elif current_user.role == "approver":
        query = query.filter(ActivityLog.action.in_(["request_approved", "request_rejected", "request_created"]))
    elif current_user.role == "receiver":
        query = query.filter(ActivityLog.action == "goods_received")
    logs = query.order_by(ActivityLog.created_at.desc()).limit(200).all()
    return render_template("activity/list.html", logs=logs)
