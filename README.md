# Legal Metrology Compliance Checker — Backend

A FastAPI REST API for scanning product labels, extracting compliance fields via OCR (Gemini AI + RapidOCR), and validating against Indian legal metrology rules.

## Features

- **JWT Authentication** — Register/login with token-based auth
- **Image Scan** — Upload product labels for OCR + compliance validation
- **Realtime Scan** — Base64 image scanning via Gemini AI
- **Batch Scan** — Process multiple labels in one request
- **Violation Management** — Track, assign, and resolve compliance violations
- **Reports** — Generate PDF, DOCX, and CSV compliance reports
- **E-commerce Comparison** — Cross-platform product compliance comparison
- **Dashboard API** — Stats, trends, and recent scan data

## Tech Stack

| Technology | Purpose |
|------------|---------|
| FastAPI 0.14 | Web framework |
| Uvicorn 0.24 | ASGI server |
| MongoDB (PyMongo 4.6) | Database |
| Google Gemini AI | OCR + field extraction |
| RapidOCR (ONNX) | Fallback OCR engine (used when Gemini unavailable) |
| OpenCV | Image preprocessing |
| Regex Field Extractor | Extracts MRP, dates, batch, manufacturer, etc. from OCR text |
| ReportLab | PDF generation |
| python-docx | DOCX generation |

## Getting Started

### Prerequisites

- Python 3.10+
- MongoDB Atlas account (or local MongoDB)
- Google Gemini API key

### Setup

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Create environment file
cp .env.example .env
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MONGODB_URI` | Yes | MongoDB connection string |
| `JWT_SECRET` | Yes | Secret key for JWT signing |
| `GEMINI_API_KEY` | Yes | Google Gemini API key |

### Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API available at [http://localhost:8000](http://localhost:8000).
Swagger docs at [http://localhost:8000/docs](http://localhost:8000/docs).

## API Endpoints

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register a new user |
| POST | `/api/auth/login` | Login and get JWT token |
| GET | `/api/auth/me` | Get current user profile |

### Scan
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/scan/upload` | Upload image for scanning |
| POST | `/api/scan/realtime` | Scan base64 image |
| POST | `/api/scan/batch` | Batch scan multiple images |
| GET | `/api/scan` | List all scans |
| GET | `/api/scan/{id}` | Get scan details with violations |
| DELETE | `/api/scan/{id}` | Delete a scan |
| PATCH | `/api/scan/{scan_id}/violations/{violation_id}` | Update violation resolution |

### Reports
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scan/{id}/report/pdf` | Download PDF report |
| GET | `/api/scan/{id}/report/docx` | Download DOCX report |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard/stats` | Overview statistics |
| GET | `/api/dashboard/recent` | Recent scans |

## Project Structure

```
backend/
├── main.py                 # FastAPI app entry point
├── db.py                   # MongoDB connection
├── auth_utils.py           # JWT + password hashing
├── requirements.txt
├── .env.example
├── models/
│   └── user.py             # Pydantic user models
├── routes/
│   ├── auth.py             # Authentication endpoints
│   ├── scan.py             # Scan CRUD + OCR pipeline
│   ├── batch_scan.py       # Batch scanning
│   ├── dashboard.py        # Dashboard stats
│   ├── products.py         # Product listing
│   ├── reports.py          # CSV/PDF/XLSX exports
│   ├── ecommerce.py        # E-commerce comparison
│   ├── pdf_report.py       # PDF report generation
│   └── docx_report.py      # DOCX report generation
├── services/
│   ├── gemini_scanner.py   # Gemini AI OCR
│   ├── ocr_service.py      # OCR routing (Gemini → RapidOCR)
│   ├── image_preprocessor.py # Image cleanup
│   ├── field_extractor.py  # Regex field extraction
│   ├── rule_engine.py      # Compliance rule validation
│   ├── font_analyzer.py    # Font size compliance
│   ├── box_mapper.py       # Bounding box mapping
│   └── geocoding.py        # Address lookup
├── rules/
│   ├── rules.json          # 14 compliance rules (LM Act 2009)
│   └── font_size_table.json # Font size requirements
└── uploads/                # Uploaded scan images (gitignored)
```

## Compliance Rules

The rule engine validates against 14 rules from the Legal Metrology Act, 2009:

| Severity | Rules |
|----------|-------|
| Critical | Net quantity declaration, MRP declaration |
| Major | Commodity name, manufacturer details, dates, addresses, importer details |
| Minor | Misleading quantity words |
| Needs Review | Font size, Country of origin |

Products with **90%+ pass rate** (13/14 rules) are marked as **compliant**.
