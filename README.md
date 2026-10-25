# Procura — Procurement Management System

Procura is a server-rendered Flask application for managing purchase requests through approval, supplier quotations, purchase orders, and goods receipt. It focuses on a demonstrable internal procurement workflow; stock, payment, and accounting are out of scope.

## Workflow

`Requester creates PR → Approver approves/rejects → Procurement records vendor quotations → Procurement selects a quote and issues one PO → Receiver records one or more deliveries → PO/PR become fully received/completed`

Purchase requests use `pending_approval`, `approved`, `rejected`, `ordered`, `in_procurement`, and `completed`. Purchase orders use `issued`, `partially_received`, and `fully_received`. The service layer validates state transitions and quantity ceilings; database constraints enforce positive quantities, nonnegative prices, unique references, and one PO per PR.

## Technology and structure

- Python 3.11+ / Flask 3.1, Jinja2, Tailwind CDN (prototype/development styling), and small server-rendered forms.
- SQLAlchemy 2.1.6 with PostgreSQL through psycopg 3.2.13; SQLite is the local fallback when `DATABASE_URL` is unset.
- Flask-Migrate/Alembic, Flask-Login, Flask-WTF CSRF, Werkzeug password hashing, pytest.
- OCR uses the installed Tesseract engine through pytesseract and Pillow; PDF OCR optionally uses pdf2image and Poppler. It is an assistive extraction feature, not a trained model.

```text
app/
  extensions.py       Flask extension setup
  models.py           relational entities and constraints
  permissions.py      backend role guard
  routes.py           auth and server-rendered workflow endpoints
  services.py         audit, OCR parsing, PO and goods receipt rules
  templates/          role-aware Jinja pages
scripts/seed_demo_data.py  idempotent demo data
tests/                auth, access, workflow and OCR parser tests
migrations/           Flask-Migrate Alembic revisions (created below)
```

## Roles

| Role | Main access |
| --- | --- |
| Requester | Create and view only own PRs, track status and activity |
| Approver | View pending PRs and approve/reject with a rejection reason |
| Procurement Staff | Manage vendors, add quotations, compare offers, issue PO |
| Receiver | View issued orders and record partial/final receipts |

Each route checks roles on the server. Request detail also checks requester ownership. Forms use CSRF tokens. Important actions write to `activity_logs`.

## Data model

`users` owns `purchase_requests`; each request has `purchase_request_items` and `vendor_quotations`. A quotation belongs to one vendor and request and has `vendor_quotation_items` mapped to the requested items. One request can have at most one `purchase_order`; that order copies item quantities/prices to `purchase_order_items` and can have multiple `goods_receipts`, each with `goods_receipt_items`. `activity_logs` associates each key event with its actor and entity. Monetary values use SQL `Numeric`/Python `Decimal`.

## Setup

Prerequisites: Python 3.11 or newer and PostgreSQL 14+ for the intended database setup. (SQLite can be used for a quick local demo.)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with a random `SECRET_KEY` and a PostgreSQL connection URL, for example `postgresql+psycopg://procurement:...@localhost:5432/procurement`. Create that database first. The app loads `.env` through python-dotenv; variables set in the shell take precedence.

```powershell
$env:SECRET_KEY = "your-long-random-secret"
$env:DATABASE_URL = "postgresql+psycopg://procurement:password@localhost:5432/procurement"
flask --app run.py db upgrade
python scripts/seed_demo_data.py
flask --app run.py run
```

Open http://127.0.0.1:5000. For SQLite quick start, leave `DATABASE_URL` unset and run the migration commands; the local database file is under `instance/`.

## Demo accounts

Every account uses the fictional password `ProcuraDemo2026!`:

| Email | Role |
| --- | --- |
| `requester@procura.test` | Requester |
| `approver@procura.test` | Approver |
| `procurement@procura.test` | Procurement Staff |
| `receiver@procura.test` | Receiver |

The seed creates one pending request, one approved request with competing quotations, one rejected request, and one partial-receipt PO. Running it again preserves existing demo records and avoids duplicates.

## OCR setup and use

Manual quotations work without OCR dependencies. For OCR, install Tesseract OCR and ensure `tesseract` is on `PATH` (or configure `pytesseract.pytesseract.tesseract_cmd` before deployment). PDF OCR also needs Poppler available to pdf2image. On Windows, install Tesseract and Poppler separately and add their `bin` directories to PATH, or set `POPPLER_PATH` in `.env` to the folder containing `pdfinfo.exe` and `pdftoppm.exe`. In the quotation form choose a PNG/JPG/TIFF/PDF file (8 MB maximum), run OCR, inspect the recognized text and extracted fields, then enter or correct values before saving. A heuristic parser recognizes labeled fields, common English and Indonesian dates, and simple quotation table rows; layout variations, tables, and OCR errors still need human review. Uploaded files are stored under private `instance/private_uploads`, outside static assets.

## Verification

```powershell
python -m pytest -q
```

The tests cover authentication, backend role/ownership guards, request creation, PO eligibility/creation, over-receipt rejection, partial/full receipt state, and labeled OCR parsing. OCR execution against actual Tesseract/Poppler binaries is an environment-dependent manual check.

## Current scope notes

This take-home implementation provides a multi-item request form, add/list vendor management, manual quotation comparison, image/PDF OCR draft extraction, a single issued PO per PR, and repeatable receipt entry. Tailwind is loaded from CDN for rapid prototype setup. Authentication, workflow, and role boundaries are implemented server-side. Before production use, configure HTTPS and secure cookie deployment settings, add CI coverage for PostgreSQL migrations, deploy-specific Tesseract/Poppler paths, and antivirus scanning for uploaded documents. Alembic revision files are included in this repository; run `flask db migrate` only after changing models, then commit the new revision.





