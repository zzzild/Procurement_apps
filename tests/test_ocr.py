from app.services import extract_quotation_fields


def test_parser_extracts_labeled_values_only():
    result = extract_quotation_fields("""Vendor: PT Contoh
Quotation No: QT-2026-9
Quotation Date: 2026-05-01
Valid Until: 2026-05-31
Total Price: IDR 1.500.000
Delivery: 7 days""")
    assert result["vendor_name"] == "PT Contoh"
    assert result["quotation_number"] == "QT-2026-9"
    assert result["total_price"] == "1500000"
    assert result["delivery_days"] == "7"
