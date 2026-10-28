"""Validated API input and output types."""
import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_bank_account(value: str) -> str:
    if isinstance(value, str):
        return re.sub(r"\s+", "", value).upper()
    return value


class SupplierCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    bank_account: str = Field(min_length=5, max_length=64)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Название должно содержать минимум 2 символа")
        return value

    @field_validator("bank_account", mode="before")
    @classmethod
    def clean_bank_account(cls, value: str) -> str:
        return _normalize_bank_account(value)


class InvoiceCreate(BaseModel):
    supplier_id: int = Field(gt=0)
    invoice_number: str = Field(min_length=1, max_length=64)
    amount_rub: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    bank_account: str = Field(min_length=5, max_length=64)
    issued_on: date

    @field_validator("invoice_number")
    @classmethod
    def clean_invoice_number(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Номер счёта не может быть пустым")
        return value

    @field_validator("bank_account", mode="before")
    @classmethod
    def clean_bank_account(cls, value: str) -> str:
        return _normalize_bank_account(value)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    bank_account: str
    created_at: datetime


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    supplier_id: int
    invoice_number: str
    amount_rub: Decimal
    bank_account: str
    issued_on: date
    risk_score: int
    risk_level: str
    findings: list[dict]
    created_at: datetime


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    action: str
    entity_type: str
    entity_id: int
    details: str
    created_at: datetime
