"""Conservative local PDF text extraction for manually verified invoice drafts.

Parsing arbitrary PDFs is risky: use a sandboxed worker in a production deployment.
No uploads or extracted texts are persisted here.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PAGES = 5
MAX_TEXT_CHARS = 30000


class PdfRejected(ValueError):
    pass


@dataclass(frozen=True)
class PdfDraft:
    invoice_number: str
    amount_rub: str
    bank_account: str
    issued_on: str
    warnings: list[str]


def extract_draft(content: bytes) -> PdfDraft:
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise PdfRejected("Размер PDF должен быть от 1 байта до 2 МиБ")
    if not content.startswith(b"%PDF-"):
        raise PdfRejected("Файл не имеет сигнатуры PDF")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise PdfRejected("Зашифрованные PDF не поддерживаются")
        if not (1 <= len(reader.pages) <= MAX_PAGES):
            raise PdfRejected("PDF должен содержать от 1 до 5 страниц")
        root = reader.trailer.get("/Root")
        if root and any(x in root for x in ("/OpenAction", "/AA", "/Names", "/AcroForm")):
            raise PdfRejected("PDF с активными элементами или формами не поддерживается")
        parts = []
        for page in reader.pages:
            if "/Annots" in page:
                raise PdfRejected("PDF с аннотациями не поддерживается")
            part = page.extract_text() or ""
            if sum(len(x) for x in parts) + len(part) > MAX_TEXT_CHARS:
                raise PdfRejected("Слишком много текста в PDF")
            parts.append(part)
    except PdfRejected:
        raise
    except Exception as exc:
        raise PdfRejected("PDF повреждён или не поддерживается") from exc
    text = "\n".join(parts)
    if not text.strip():
        raise PdfRejected("В PDF нет извлекаемого текста: сканы пока не поддерживаются")

    def match(pattern: str) -> str:
        found = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        return found.group(1).strip() if found else ""

    number = match(r"(?:сч[её]т\s*(?:№|#|номер)?|invoice\s*(?:no\.?|#|number)?)\s*[:№#-]?\s*([\w/-]{1,64})")
    money = match(r"(?:итого|к оплате|total|amount)\s*[:=]?\s*([\d\s.,]{1,24})\s*(?:₽|руб\.?|rub)?")
    account = match(r"(?:р/с|расч[её]тный сч[её]т|bank account|iban)\s*[:№#-]?\s*([A-Z]{2}\d{2}[A-Z0-9]{10,34}|\d{20})")
    date_text = match(r"(?:дата|date)\s*[:=]?\s*(\d{2}[.]\d{2}[.]\d{4}|\d{4}-\d{2}-\d{2})")
    warnings = ["Поля извлечены эвристически. Проверьте каждое поле по исходному документу перед сохранением."]
    if money:
        try:
            normalized = money.replace(" ", "").replace("\u00a0", "").replace(",", ".")
            value = Decimal(normalized)
            money = str(value) if value > 0 and value.as_tuple().exponent >= -2 else ""
        except InvalidOperation:
            money = ""
    if date_text:
        try:
            if "-" in date_text:
                date_text = date.fromisoformat(date_text).isoformat()
            else:
                date_text = datetime.strptime(date_text, "%d.%m.%Y").date().isoformat()
        except ValueError:
            date_text = ""
    account = re.sub(r"\s+", "", account).upper()
    for key, value in (("номер счёта", number), ("сумма", money), ("банковские реквизиты", account), ("дата", date_text)):
        if not value:
            warnings.append(f"Не удалось уверенно распознать поле: {key}")
    return PdfDraft(number, money, account, date_text, warnings)
