"""constrain roles and workflow states

Revision ID: a21b8c4ef910
Revises: 7c10636c6d78
Create Date: 2026-10-24

"""
from alembic import op


revision = "a21b8c4ef910"
down_revision = "7c10636c6d78"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint("ck_user_role_valid", "role IN ('requester','approver','procurement','receiver')")
    with op.batch_alter_table("vendors") as batch_op:
        batch_op.create_check_constraint("ck_vendor_rating_range", "rating IS NULL OR (rating >= 0 AND rating <= 5)")
    with op.batch_alter_table("purchase_requests") as batch_op:
        batch_op.create_check_constraint("ck_request_status_valid", "status IN ('pending_approval','approved','rejected','in_procurement','ordered','completed')")
    with op.batch_alter_table("vendor_quotations") as batch_op:
        batch_op.create_check_constraint("ck_quotation_ocr_status_valid", "ocr_status IN ('not_requested','processed','failed')")
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.create_check_constraint("ck_po_status_valid", "status IN ('issued','partially_received','fully_received')")
    with op.batch_alter_table("goods_receipt_items") as batch_op:
        batch_op.create_check_constraint("ck_receipt_condition_valid", "condition IN ('good','damaged','incomplete')")


def downgrade():
    with op.batch_alter_table("goods_receipt_items") as batch_op:
        batch_op.drop_constraint("ck_receipt_condition_valid", type_="check")
    with op.batch_alter_table("purchase_orders") as batch_op:
        batch_op.drop_constraint("ck_po_status_valid", type_="check")
    with op.batch_alter_table("vendor_quotations") as batch_op:
        batch_op.drop_constraint("ck_quotation_ocr_status_valid", type_="check")
    with op.batch_alter_table("purchase_requests") as batch_op:
        batch_op.drop_constraint("ck_request_status_valid", type_="check")
    with op.batch_alter_table("vendors") as batch_op:
        batch_op.drop_constraint("ck_vendor_rating_range", type_="check")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_user_role_valid", type_="check")
