from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.auth import router as auth_router
from routes.scan import router as scan_router
from routes.dashboard import router as dashboard_router
from routes.products import router as products_router
from routes.reports import router as reports_router
from routes.ecommerce import router as ecommerce_router
from routes.pdf_report import router as pdf_report_router
from routes.docx_report import router as docx_report_router
from routes.batch_scan import router as batch_scan_router


app = FastAPI(title="Legal Metrology Compliance Checker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(scan_router)
app.include_router(dashboard_router)
app.include_router(products_router)
app.include_router(reports_router)
app.include_router(ecommerce_router)
app.include_router(pdf_report_router)
app.include_router(docx_report_router)
app.include_router(batch_scan_router)

@app.get("/")
def root():
    return {"status": "ok", "message": "Legal Metrology Compliance Checker API is running"}

@app.get("/api/health")
def health():
    return {"status": "healthy"}
