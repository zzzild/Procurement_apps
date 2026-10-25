from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

from .extensions import db
from .models import ActivityLog, GoodsReceipt, GoodsReceiptItem, PurchaseOrder, PurchaseOrderItem, PurchaseRequest, PurchaseRequestItem, VendorQuotation, VendorQuotationItem


def log_action(user, action, entity, description):
    db.session.add(ActivityLog(user_id=user.id, action=action, entity_type=entity.__tablename__, entity_id=entity.id, description=description))


def extract_quotation_fields(text):
    """Conservative field parser: only returns values supported by explicit labels."""
    patterns = {
        "vendor_name": r"(?im)^\s*(?:vendor|supplier|perusahaan)\s*[:\-]\s*(.+?)\s*$",
        "quotation_number": r"(?im)\b(?:quotation(?:\s*(?:no|number))?|no\.?\s*(?:quotation|penawaran))\s*[:#\-]\s*([\w./-]+)",
        "item_name": r"(?im)^\s*(?:item(?:\s*name|\s*description)?|nama\s*item|description)\s*[:\-]\s*(.+?)\s*$",
        "quantity": r"(?im)^\s*(?:qty|quantity|kuantitas|jumlah)\s*[:\-]\s*([\d.,]+)",
        "unit": r"(?im)^\s*(?:unit|satuan)\s*[:\-]\s*([\w-]+)",
        "unit_price": r"(?im)^\s*(?:unit\s*price|price\s*per\s*unit|harga\s*satuan)\s*[:\-]\s*(?:IDR\s*)?([\d.,]+)",
        "total_price": r"(?im)^\s*(?:grand\s*total|total\s*(?:harga|price|penawaran))\s*[:\-]?\s*(?:(?:IDR|RP)\s*)?([\d.,]+)",
        "delivery_days": r"(?im)^\s*(?:delivery(?:\s*time)?|lead\s*time|waktu\s*(?:pengiriman|kirim))\s*[:\-]?\s*(\d+)\s*(?:days?|hari)?",
        "quotation_date": r"(?im)\b(?:quotation\s*date|tanggal(?:\s*quotation)?)\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})",
        "valid_until": r"(?im)^\s*(?:valid\s*until|berlaku\s*sampai)\s*[:\-]?\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})",
    }
    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text or "")
        if match:
            value = match.group(1).strip()
            if key in {"total_price", "unit_price"}:
                value = _normalize_ocr_amount(value)
                if value is None:
                    continue
            elif key in {"quotation_date", "valid_until"}:
                value = _normalize_ocr_date(value)
                if value is None:
                    continue
            result[key] = value

    # OCR engines often return a quotation table row as text, not as labeled fields.
    item_row = re.search(
        r"(?im)^\s*\d+\s+(.+?)\s+(\d+(?:[.,]\d+)?)\s+([A-Za-z][\w./-]*)\s+(?:IDR\s*)?([\d.,]+)\s+(?:IDR\s*)?[\d.,]+\s*$",
        text or "",
    )
    if item_row:
        result.setdefault("item_name", item_row.group(1).strip())
        result.setdefault("quantity", item_row.group(2).replace(",", "."))
        result.setdefault("unit", item_row.group(3).lower())
        unit_price = _normalize_ocr_amount(item_row.group(4))
        if unit_price is not None:
            result.setdefault("unit_price", unit_price)

    estimated_delivery = re.search(r"(?i)\bestimasi(?:\s+(?:pengiriman|delivery))?\s+(\d+)\s+(?:hari|days?)\b", text or "")
    if estimated_delivery:
        result.setdefault("delivery_days", estimated_delivery.group(1))

    # Supplier names are sometimes printed as the first line without a field label.
    if "vendor_name" not in result:
        nonempty_lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        first_line = nonempty_lines[0] if nonempty_lines else ""
        if re.match(r"^(?:PT|CV|UD)\.?\s+", first_line, re.IGNORECASE):
            vendor_name = re.sub(r"\s+QUOTATION\s*$", "", first_line, flags=re.IGNORECASE).strip()
            if len(nonempty_lines) > 1 and "QUOTATION" in first_line.upper():
                suffix_line = re.sub(r"\s+(?:PENAWARAN\s+HARGA|QUOTATION)\s*$", "", nonempty_lines[1], flags=re.IGNORECASE).strip()
                if suffix_line and re.fullmatch(r"[A-Z][A-Z\s.-]+", suffix_line):
                    vendor_name = f"{vendor_name} {suffix_line}"
            result["vendor_name"] = vendor_name
    return result


def _normalize_ocr_amount(value):
    """Normalize common comma/dot thousands and decimal separators."""
    try:
        if "." in value and "," in value:
            decimal_mark = "." if value.rfind(".") > value.rfind(",") else ","
            thousands_mark = "," if decimal_mark == "." else "."
            normalized = value.replace(thousands_mark, "").replace(decimal_mark, ".")
        elif "," in value:
            normalized = value.replace(",", "") if len(value.rsplit(",", 1)[-1]) == 3 else value.replace(",", ".")
        elif "." in value:
            normalized = value.replace(".", "") if len(value.rsplit(".", 1)[-1]) == 3 else value
        else:
            normalized = value
        amount = Decimal(normalized)
        return str(amount) if amount.is_finite() else None
    except InvalidOperation:
        return None


def _normalize_ocr_date(value):
    """Return ISO dates for common English quotation date formats."""
    for date_format in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    month_names = {
        "januari": 1, "februari": 2, "maret": 3, "april": 4,
        "mei": 5, "juni": 6, "juli": 7, "agustus": 8,
        "september": 9, "oktober": 10, "november": 11, "desember": 12,
    }
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value)
    if match and match.group(2).lower() in month_names:
        try:
            return date(int(match.group(3)), month_names[match.group(2).lower()], int(match.group(1))).isoformat()
        except ValueError:
            return None
    return None


def run_ocr(file_storage):
    allowed = {"png", "jpg", "jpeg", "tif", "tiff", "pdf"}
    filename = secure_filename(file_storage.filename or "")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in allowed:
        raise ValueError("Gunakan dokumen PNG, JPG, TIFF, atau PDF.")
    # PIL verifies image contents. PDFs are converted only when Poppler is installed.
    upload_dir = Path(current_app.config["UPLOAD_FOLDER"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"{uuid.uuid4().hex}.{suffix}"
    file_storage.save(stored)
    try:
        import pytesseract
        if current_app.config.get("TESSERACT_CMD"):
            pytesseract.pytesseract.tesseract_cmd = current_app.config["TESSERACT_CMD"]
        if suffix == "pdf":
            if stored.read_bytes()[:5] != b"%PDF-":
                raise ValueError("File PDF tidak valid.")
            from pdf2image import convert_from_path
            try:
                pages = convert_from_path(
                    str(stored),
                    first_page=1,
                    last_page=5,
                    poppler_path=current_app.config.get("POPPLER_PATH"),
                )
            except Exception as exc:
                if type(exc).__name__ == "PDFInfoNotInstalledError":
                    raise RuntimeError("Poppler belum ditemukan. Atur POPPLER_PATH ke folder yang berisi pdfinfo.exe dan pdftoppm.exe, lalu restart Flask.") from exc
                if type(exc).__name__ == "PDFPageCountError":
                    raise ValueError("PDF valid sebagai file, tetapi halaman tidak bisa dibaca. Coba simpan ulang sebagai PDF standar.") from exc
                raise RuntimeError("Gagal mengubah halaman PDF menjadi gambar. Periksa Poppler dan izin membaca file PDF.") from exc
            text = "\n".join(pytesseract.image_to_string(page) for page in pages)
        else:
            from PIL import Image, UnidentifiedImageError
            try:
                with Image.open(stored) as image:
                    image.verify()
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError("File gambar tidak valid.") from exc
            try:
                with Image.open(stored) as image:
                    text = pytesseract.image_to_string(image)
            except Exception as exc:
                if type(exc).__name__ == "TesseractNotFoundError":
                    raise RuntimeError("File gambar valid, tetapi engine Tesseract belum terinstal atau belum masuk PATH. Pasang Tesseract OCR, mulai ulang terminal/server, lalu coba lagi.") from exc
                raise RuntimeError("Gambar valid, tetapi proses OCR gagal. Periksa instalasi Tesseract dan konfigurasi bahasanya.") from exc
    except (ImportError, OSError) as exc:
        stored.unlink(missing_ok=True)
        raise RuntimeError("OCR belum siap. Pasang pytesseract dan Tesseract; PDF juga memerlukan Poppler. Input quotation manual tetap tersedia.") from exc
    except ValueError:
        stored.unlink(missing_ok=True)
        raise
    except RuntimeError:
        stored.unlink(missing_ok=True)
        raise
    except Exception as exc:
        stored.unlink(missing_ok=True)
        raise RuntimeError("Dokumen gagal diproses OCR. Periksa format file, Tesseract, dan Poppler untuk PDF.") from exc
    return str(stored), text, extract_quotation_fields(text)


def create_purchase_order(request, quotation, user):
    if request.status not in {"approved", "in_procurement"} or request.purchase_order:
        raise ValueError("PR harus disetujui dan belum memiliki PO.")
    if quotation.purchase_request_id != request.id or not quotation.items:
        raise ValueError("Quotation harus terkait PR ini dan memiliki rincian item.")
    qitems = {item.purchase_request_item_id: item for item in quotation.items}
    if any(item.id not in qitems for item in request.items):
        raise ValueError("Quotation harus mencakup seluruh item PR.")
    for item in request.items:
        if qitems[item.id].quantity != item.quantity:
            raise ValueError("Kuantitas quotation harus sama dengan kuantitas PR.")
    po = PurchaseOrder(po_number=f"PO-{date.today():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}", purchase_request=request, vendor_id=quotation.vendor_id, quotation=quotation, created_by=user.id, status="issued")
    db.session.add(po)
    db.session.flush()
    for item in request.items:
        quote_item = qitems[item.id]
        db.session.add(PurchaseOrderItem(purchase_order_id=po.id, request_item_id=item.id, item_name=item.item_name, quantity_ordered=item.quantity, unit=item.unit, unit_price=quote_item.unit_price))
    request.status = "ordered"
    log_action(user, "po_issued", po, f"PO {po.po_number} diterbitkan dari {request.request_number}.")
    return po


def receive_goods(po, quantities, conditions, notes, user):
    if po.status not in {"issued", "partially_received"}:
        raise ValueError("PO tidak menerima pencatatan penerimaan baru.")
    receipt = GoodsReceipt(receipt_number=f"GR-{date.today():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}", purchase_order_id=po.id, received_by=user.id, notes=notes)
    db.session.add(receipt)
    db.session.flush()
    for item in po.items:
        qty = Decimal(str(quantities.get(str(item.id), "0")))
        received_to_date = sum((line.quantity_received for old in po.receipts for line in old.items if line.purchase_order_item_id == item.id), Decimal("0"))
        if qty < 0 or received_to_date + qty > item.quantity_ordered:
            raise ValueError(f"Jumlah penerimaan {item.item_name} melebihi sisa pesanan.")
        if qty:
            condition = conditions.get(str(item.id), "good")
            if condition not in {"good", "damaged", "incomplete"}:
                raise ValueError("Kondisi barang tidak valid.")
            receipt.items.append(GoodsReceiptItem(purchase_order_item_id=item.id, quantity_received=qty, condition=condition))
    db.session.flush()
    if not receipt.items:
        raise ValueError("Masukkan kuantitas penerimaan untuk setidaknya satu item.")
    db.session.flush()
    complete = all(sum((line.quantity_received for rec in [*po.receipts, receipt] for line in rec.items if line.purchase_order_item_id == item.id), Decimal("0")) >= item.quantity_ordered for item in po.items)
    po.status = "fully_received" if complete else "partially_received"
    po.purchase_request.status = "completed" if complete else "ordered"
    log_action(user, "goods_received", receipt, f"Penerimaan {receipt.receipt_number} dicatat untuk {po.po_number}.")
    return receipt
