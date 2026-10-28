"""Conservative PDF parser: never trust inferred invoice fields without confirmation.

Only text PDFs are supported. Untrusted PDFs MUST be parsed in an isolated worker
before any production deployment; these limits are not a resource sandbox.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_PAGES = 5
MAX_TEXT_CHARS = 30000


class PdfRejected(ValueError):
    """The uploaded document cannot be safely/meaningfully parsed as a text PDF."""


@dataclass(frozen=True)
class PdfDraft:
    invoice_number: str
    amount_rub: str
    bank_account: str
    issued_on: str
    warnings: list[str]


# Only explicit labels are trusted. A generic number/amount elsewhere in a PDF
# can belong to a bank, a product row, VAT, a contract or the counterparty.
_NUMBER_LABEL = re.compile(
    r"\b(?:сч[её]т(?:\s+на\s+оплату)?\s*(?:№|номер|#)"
    r"|invoice\s*(?:no\.?|number|№|#))\s*[:.\-\s]*"
    r"(?P<value>[\w][\w/\-]{0,63})(?![\w/\-])",
    re.IGNORECASE,
)
_TOTAL_LABEL = re.compile(
    r"\b(?:итого(?:\s+к\s+оплате)?|(?:всего|сумма)\s+к\s+оплате"
    r"|к\s+оплате|total(?:\s+due)?|amount(?:\s+due)?)"
    r"\s*[:=]?\s*(?P<value>\d[\d\s.,\u00a0\u202f]*)(?!\d)",
    re.IGNORECASE,
)
_BANK_LABEL = re.compile(
    r"(?:\b(?:расч[её]тный\s+сч[её]т|bank\s+account|iban)\b|(?<!\w)р/с)"
    r"\s*[:№#=\-]?\s*(?P<value>.*)",
    re.IGNORECASE,
)
_DATE_LABEL = re.compile(
    r"\b(?:дата(?:\s+выставления|\s+сч[её]та)?|invoice\s+date|date)\s*[:=\-]?\s*",
    re.IGNORECASE,
)
_DATE_VALUE = re.compile(
    r"(?<!\d)(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./]\d{1,2}[./]\d{4}"
    r"|\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+\d{4})(?!\d)",
    re.IGNORECASE,
)
_MONTHS = dict(zip(
    ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"),
    range(1, 13),
))


def _parse_money(raw: str) -> str | None:
    """Accept unambiguous thousands/decimal separators; never guess '1,234'."""
    raw = raw.strip().replace("\u00a0", " ").replace("\u202f", " ")
    if not raw or not re.fullmatch(r"[\d .,]+", raw):
        return None
    # Spaces must group digits by thousands; '12 34' is not a valid amount.
    if " " in raw:
        # Spaces around punctuation are not valid thousands groups.
        if not re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?", raw):
            return None
        raw = raw.replace(" ", "")
    if not re.fullmatch(r"\d[\d.,]*", raw):
        return None
    if "," in raw and "." in raw:
        sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands_sep = "." if sep == "," else ","
        head, decimals = raw.rsplit(sep, 1)
        if not (1 <= len(decimals) <= 2 and decimals.isdecimal()):
            return None
        if not re.fullmatch(rf"\d{{1,3}}(?:{re.escape(thousands_sep)}\d{{3}})+", head):
            return None
        normalized = head.replace(thousands_sep, "") + "." + decimals
    elif "," in raw or "." in raw:
        sep = "," if "," in raw else "."
        parts = raw.split(sep)
        if len(parts) == 2:
            before, after = parts
            if not before or not after:
                return None
            if 1 <= len(after) <= 2:
                normalized = before + "." + after
            else:
                # 1,234 could be 1234 or 1.234. Require explicit precision.
                return None
        elif all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            normalized = "".join(parts)
        elif (len(parts) > 2 and 1 <= len(parts[-1]) <= 2
              and all(len(p) == 3 for p in parts[1:-1]) and 1 <= len(parts[0]) <= 3):
            normalized = "".join(parts[:-1]) + "." + parts[-1]
        else:
            return None
    else:
        normalized = raw
    try:
        value = Decimal(normalized)
        if not value.is_finite() or value <= 0 or value > Decimal("999999999999.99"):
            return None
        return str(value.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(raw: str) -> str | None:
    try:
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", raw):
            year, month, day = (int(p) for p in raw.split("-"))
            return date(year, month, day).isoformat()
        if re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]\d{4}", raw):
            day, month, year = (int(p) for p in re.split(r"[./]", raw))
            return date(year, month, day).isoformat()
        match = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", raw.lower())
        if match:
            return date(int(match[3]), _MONTHS[match[2]], int(match[1])).isoformat()
    except (ValueError, KeyError):
        return None
    return None


def _parse_bank(raw: str) -> str | None:
    """Extract a single numeric 20-digit account or an IBAN (15..34 chars)."""
    value = raw.strip().upper()
    # Do not swallow unrelated columns after the account.
    numeric = re.match(r"((?:\d[ \u00a0\u202f-]*){20})(?![ \u00a0\u202f-]*\d)", value)
    if numeric:
        account = re.sub(r"[ \u00a0\u202f-]", "", numeric.group(1))
        if len(account) == 20:
            return account
    iban = re.match(r"([A-Z]{2}\d{2}[ \u00a0\u202f-]*(?:[A-Z0-9][ \u00a0\u202f-]*){11,30})(?![A-Z0-9])", value)
    if iban:
        account = re.sub(r"[ \u00a0\u202f-]", "", iban.group(1))
        if 15 <= len(account) <= 34:
            return account
    return None


def parse_invoice_text(text: str) -> PdfDraft:
    """Pure extraction function, deliberately separate from untrusted PDF decoding."""
    if len(text) > MAX_TEXT_CHARS:
        raise PdfRejected("Слишком много текста в PDF")
    text = unicodedata.normalize("NFC", text).replace("\r", "\n")
    if len(text) > MAX_TEXT_CHARS:
        raise PdfRejected("Слишком много текста в PDF")
    candidates: dict[str, set[str]] = {k: set() for k in ("number", "money", "account", "date")}
    invalid: set[str] = set()
    for original in text.splitlines():
        line = " ".join(original.split())
        if not line:
            continue
        for found in _NUMBER_LABEL.finditer(line):
            candidates["number"].add(found.group("value"))
        for found in _TOTAL_LABEL.finditer(line):
            money = _parse_money(found.group("value"))
            if money is None:
                invalid.add("money")
            else:
                candidates["money"].add(money)
        for found in _BANK_LABEL.finditer(line):
            account = _parse_bank(found.group("value"))
            if account is None:
                invalid.add("account")
            else:
                candidates["account"].add(account)
        dates: list[str] = []
        for found in _DATE_LABEL.finditer(line):
            date_found = _DATE_VALUE.search(line, pos=found.end())
            if date_found:
                dates.append(date_found.group())
            else:
                invalid.add("date")
        # Header convention: 'Счёт № 123 от 29 октября 2026'.
        if _NUMBER_LABEL.search(line):
            for date_found in re.finditer(r"\bот\s+(" + _DATE_VALUE.pattern + r")", line, re.I):
                dates.append(date_found.group(1))
        for date_text in dates:
            parsed = _parse_date(date_text)
            if parsed:
                candidates["date"].add(parsed)
            else:
                invalid.add("date")

    labels = {"number": "номер счёта", "money": "сумма", "account": "банковские реквизиты", "date": "дата"}
    warnings = ["Автоматическое извлечение не подтверждает правильность данных. Сверьте их с оригиналом PDF."]
    values: dict[str, str] = {}
    for field, label in labels.items():
        found = candidates[field]
        if len(found) > 1 or (found and field in invalid):
            values[field] = ""
            warnings.append(f"Неоднозначное поле «{label}»: найдены конфликтующие или повреждённые данные. Введите вручную.")
        elif len(found) == 1:
            values[field] = next(iter(found))
        else:
            values[field] = ""
            warnings.append(f"Не удалось уверенно распознать поле: {label}. Введите вручную.")
    return PdfDraft(values["number"], values["money"], values["account"], values["date"], warnings)


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
        parts: list[str] = []
        total_chars = 0
        for page in reader.pages:
            if "/Annots" in page:
                raise PdfRejected("PDF с аннотациями не поддерживается")
            part = page.extract_text() or ""
            total_chars += len(part)
            if total_chars > MAX_TEXT_CHARS:
                raise PdfRejected("Слишком много текста в PDF")
            parts.append(part)
    except PdfRejected:
        raise
    except Exception as exc:
        raise PdfRejected("PDF повреждён или не поддерживается") from exc
    text = "\n".join(parts)
    if not text.strip():
        raise PdfRejected("В PDF нет извлекаемого текста: сканы пока не поддерживаются")
    return parse_invoice_text(text)
