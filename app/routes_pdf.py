"""Authenticated PDF preview; no original documents are stored."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import Identity, require_web_user, verify_csrf
from app.database import get_db
from app.services.invoices import list_suppliers
from app.services.pdf_import import MAX_UPLOAD_BYTES, PdfRejected, extract_draft

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory="app/templates")


@router.get("/pdf-import", response_class=HTMLResponse)
def upload_page(request: Request, identity: Identity = Depends(require_web_user), db: Session = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="pdf_import.html", context={
        "csrf_token": identity.session.csrf_token, "suppliers": list_suppliers(db),
        "draft": None, "error": None,
    })


@router.post("/pdf-import", response_class=HTMLResponse)
async def preview_pdf(request: Request, file: UploadFile = File(...), csrf_token: str = Form(""),
                      identity: Identity = Depends(require_web_user), db: Session = Depends(get_db)):
    verify_csrf(identity, csrf_token)
    # Content-Type and filename are untrusted; validate both in addition to magic bytes.
    if not file.filename or not file.filename.lower().endswith(".pdf") or file.content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Допускаются только файлы .pdf")
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        draft = extract_draft(content)
        error = None
    except PdfRejected as exc:
        draft = None
        error = str(exc)
    finally:
        await file.close()
    return templates.TemplateResponse(request=request, name="pdf_import.html", context={
        "csrf_token": identity.session.csrf_token, "suppliers": list_suppliers(db),
        "draft": draft, "error": error,
    }, status_code=422 if error else 200)
