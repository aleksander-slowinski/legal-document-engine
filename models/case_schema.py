"""Schemat pojedynczego, syntetycznego rekordu roszczenia."""
from datetime import date, datetime
from decimal import Decimal
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

REQUIRED_COLUMNS = (
    "Sygnatura", "Imie_Nazwisko", "PESEL", "Kwota_Roszczenia",
    "Data_Wymagalnosci", "Opis_Stanu_Faktycznego",
)
PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def is_valid_pesel(value: str) -> bool:
    """Sprawdza format, datę urodzenia i sumę kontrolną PESEL."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{11}", value):
        return False
    year, encoded_month, day = int(value[:2]), int(value[2:4]), int(value[4:6])
    periods = ((1, 12, 1900, 0), (21, 32, 2000, 20),
               (41, 52, 2100, 40), (61, 72, 2200, 60),
               (81, 92, 1800, 80))
    try:
        _, _, century, offset = next(p for p in periods if p[0] <= encoded_month <= p[1])
        date(century + year, encoded_month - offset, day)
    except (StopIteration, ValueError):
        return False
    checksum = (10 - sum(int(n) * w for n, w in zip(value[:10], PESEL_WEIGHTS)) % 10) % 10
    return checksum == int(value[10])


class CaseRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    sygnatura: str = Field(alias="Sygnatura", min_length=1, max_length=100)
    imie_nazwisko: str = Field(alias="Imie_Nazwisko", min_length=3, max_length=150)
    pesel: str = Field(alias="PESEL")
    kwota_roszczenia: Decimal = Field(alias="Kwota_Roszczenia", gt=0)
    data_wymagalnosci: date = Field(alias="Data_Wymagalnosci")
    opis_stanu_faktycznego: str = Field(alias="Opis_Stanu_Faktycznego", min_length=10, max_length=10000)

    @field_validator("pesel")
    @classmethod
    def validate_pesel(cls, value: str) -> str:
        if not is_valid_pesel(value):
            raise ValueError("Niepoprawny PESEL (format, data lub suma kontrolna)")
        return value

    @field_validator("kwota_roszczenia", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal:
        if isinstance(value, bool):
            raise ValueError("Kwota musi być liczbą")
        amount = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", amount):
            raise ValueError("Kwota: dodatnia liczba, maksymalnie dwa miejsca po przecinku")
        return Decimal(amount)

    @field_validator("data_wymagalnosci", mode="before")
    @classmethod
    def parse_due_date(cls, value: object) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        text = str(value).strip()
        try:
            return date.fromisoformat(text)
        except ValueError:
            try:
                return datetime.fromisoformat(text).date()
            except ValueError as exc:
                raise ValueError("Data musi być w formacie YYYY-MM-DD") from exc
