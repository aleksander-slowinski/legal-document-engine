from datetime import date
from io import BytesIO
import pandas as pd
import pytest
from models.case_schema import CaseRecord, is_valid_pesel
from scripts.generate_demo_data import build_demo_rows, synthetic_pesel
from services.data_quality_service import load_case_table, validate_case_table

REFERENCE_DAY = date(2026, 10, 25)


def test_pesel_checksum():
    good = synthetic_pesel(1)
    assert is_valid_pesel(good)
    assert not is_valid_pesel(good[:-1] + str((int(good[-1]) + 1) % 10))


def test_pesel_invalid_birth_date():
    assert not is_valid_pesel("00999912345")
    assert not is_valid_pesel("00000000000")


def test_demo_50_cases_46_valid_4_rejected():
    report = validate_case_table(pd.DataFrame(build_demo_rows()), today=REFERENCE_DAY)
    assert (report.total_count, report.valid_count, report.rejected_count) == (50, 46, 4)
    assert [r.source_row for r in report.rejected_cases] == [8, 19, 33, 46]


def test_duplicate_signature_rejects_both_rows():
    rows = build_demo_rows()[:2]
    rows[1]["Sygnatura"] = rows[0]["Sygnatura"].lower()
    report = validate_case_table(pd.DataFrame(rows), today=REFERENCE_DAY)
    assert report.rejected_count == 2
    assert all("duplikat" in " ".join(r.reasons) for r in report.rejected_cases)


def test_future_due_date():
    rows = build_demo_rows()[:1]
    rows[0]["Data_Wymagalnosci"] = "2099-12-31"
    report = validate_case_table(pd.DataFrame(rows), today=REFERENCE_DAY)
    assert report.rejected_count == 1
    assert "jeszcze nie upłynął" in " ".join(report.rejected_cases[0].reasons)


def test_amount_comma_accepted():
    case = CaseRecord.model_validate(build_demo_rows()[0])
    assert str(case.kwota_roszczenia) == "1017.50"


def test_unknown_column_blocked():
    frame = pd.DataFrame(build_demo_rows()[:1])
    frame["Dodatkowe_PII"] = "test"
    with pytest.raises(ValueError, match="Niedozwolone"):
        validate_case_table(frame)


def test_missing_column_blocked():
    frame = pd.DataFrame(build_demo_rows()[:1]).drop(columns="PESEL")
    with pytest.raises(ValueError, match="Brak wymaganych"):
        validate_case_table(frame)


def test_csv_import_preserves_pe_sel_leading_zero():
    rows = build_demo_rows()[:1]
    rows[0]["PESEL"] = "02022900006"
    raw = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
    imported = load_case_table("test.csv", raw)
    assert imported.loc[0, "PESEL"] == "02022900006"


def test_xlsx_import_retains_text_columns():
    frame = pd.DataFrame(build_demo_rows()[:2])
    buf = BytesIO()
    frame.to_excel(buf, index=False, engine="openpyxl")
    imported = load_case_table("test.xlsx", buf.getvalue())
    assert imported.loc[0, "PESEL"] == frame.loc[0, "PESEL"]


def test_rejected_csv_has_error_reason():
    report = validate_case_table(pd.DataFrame(build_demo_rows()), today=REFERENCE_DAY)
    decoded = report.rejected_csv().decode("utf-8-sig")
    assert "Błędy" in decoded
    assert "PESEL" in decoded
