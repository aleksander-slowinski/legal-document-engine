"""Import CSV/XLSX i lokalny audyt jakości danych (bez API)."""
from collections import Counter
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
import pandas as pd
from pydantic import ValidationError
from models.case_schema import CaseRecord, REQUIRED_COLUMNS

MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_ROWS = 500

@dataclass(frozen=True)
class RejectedCase:
    source_row: int
    reasons: tuple[str, ...]
    original: dict[str, str]

@dataclass(frozen=True)
class DataQualityReport:
    total_count: int
    valid_cases: tuple[CaseRecord, ...]
    rejected_cases: tuple[RejectedCase, ...]

    @property
    def valid_count(self) -> int:
        return len(self.valid_cases)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected_cases)

    def issues_table(self) -> pd.DataFrame:
        """Minimalny widok błędów bez ujawniania nazwisk i PESEL."""
        return pd.DataFrame([
            {"Wiersz": c.source_row, "Sygnatura": c.original.get("Sygnatura", ""),
             "Błędy": "; ".join(c.reasons)}
            for c in self.rejected_cases
        ], columns=["Wiersz", "Sygnatura", "Błędy"])

    def rejected_csv(self) -> bytes:
        """Do korekty lokalnej: UWAGA, pełne dane odrzuconych wierszy."""
        rows = [{**c.original, "Wiersz": c.source_row,
                 "Błędy": "; ".join(c.reasons)} for c in self.rejected_cases]
        return pd.DataFrame(rows, columns=[*REQUIRED_COLUMNS, "Wiersz", "Błędy"]).to_csv(
            index=False
        ).encode("utf-8-sig")


def load_case_table(filename: str, content: bytes) -> pd.DataFrame:
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("Plik przekracza 5 MB")
    if not content:
        raise ValueError("Plik jest pusty")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        try:
            frame = pd.read_csv(
                BytesIO(content), dtype=str, keep_default_na=False,
                encoding="utf-8-sig", sep=None, engine="python",
            )
        except UnicodeDecodeError as exc:
            raise ValueError("CSV musi mieć kodowanie UTF-8") from exc
    elif suffix == ".xlsx":
        frame = pd.read_excel(BytesIO(content), dtype=str,
                              keep_default_na=False, engine="openpyxl")
    else:
        raise ValueError("Obsługiwane formaty: CSV lub XLSX")
    frame.columns = [str(col).strip() for col in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError("Powtarzające się nazwy kolumn")
    if frame.empty:
        raise ValueError("Brak rekordów")
    if len(frame) > MAX_ROWS:
        raise ValueError(f"Maksymalna liczba rekordów: {MAX_ROWS}")
    return frame.fillna("")


def validate_case_table(frame: pd.DataFrame, *, today: date | None = None) -> DataQualityReport:
    missing = [col for col in REQUIRED_COLUMNS if col not in frame.columns]
    extra = [col for col in frame.columns if col not in REQUIRED_COLUMNS]
    if missing:
        raise ValueError("Brak wymaganych kolumn: " + ", ".join(missing))
    if extra:
        raise ValueError("Niedozwolone dodatkowe kolumny: " + ", ".join(extra))
    if frame.empty:
        raise ValueError("Brak rekordów")
    if len(frame) > MAX_ROWS:
        raise ValueError(f"Maksymalna liczba rekordów: {MAX_ROWS}")

    reference_date = today or date.today()
    records = frame.loc[:, list(REQUIRED_COLUMNS)].fillna("").reset_index(drop=True)
    signatures = [str(s).strip().casefold() for s in records["Sygnatura"]]
    counts = Counter(s for s in signatures if s)
    valid: list[CaseRecord] = []
    rejected: list[RejectedCase] = []

    for index, row in records.iterrows():
        raw = {key: str(row[key]).strip() for key in REQUIRED_COLUMNS}
        problems: list[str] = []
        parsed: CaseRecord | None = None
        try:
            parsed = CaseRecord.model_validate(raw)
        except ValidationError as exc:
            for err in exc.errors():
                name = str(err["loc"][0]) if err["loc"] else "Rekord"
                problems.append(f"{name}: {err['msg']}")
        if parsed is not None and parsed.data_wymagalnosci > reference_date:
            problems.append("Data_Wymagalnosci: termin jeszcze nie upłynął")
        if signatures[index] and counts[signatures[index]] > 1:
            problems.append("Sygnatura: duplikat w pliku")
        if problems:
            rejected.append(RejectedCase(
                source_row=index + 2, reasons=tuple(problems), original=raw
            ))
        else:
            assert parsed is not None
            valid.append(parsed)
    return DataQualityReport(len(records), tuple(valid), tuple(rejected))
