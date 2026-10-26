"""Batch DOCX export for the *built-in* 50-row synthetic fixture only.

Only zero/one Gemini requests for the entire batch. Never writes PII to SQL
or to status CSV, never persists token maps, fails closed on unknown cases.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from time import perf_counter
from typing import Literal, Sequence
from zipfile import ZIP_DEFLATED, ZipFile

from models.case_schema import CaseRecord
from services.ai_drafting_service import (
    DraftingError, DraftResult, _trusted_preflight, _validate_response,
    generate_demo_draft,
)
from services.document_service import DocumentError, render_demo_docx
from services.privacy_service import prepare_demo_payload

BatchMode = Literal["offline", "gemini"]

# Fixed, manually authored, *synthetic-only* prose. No generative AI call.
OFFLINE_PARAGRAPH = (
    "W fikcyjnej sprawie [STRONA_1] nie uregulowała należności wynikającej "
    "z testowej faktury [DOKUMENT_1] w wyznaczonym terminie."
)
MAX_BATCH_SIZE = 50


class BatchError(ValueError):
    """Safe error messages, without user data or raw API responses."""


@dataclass(frozen=True)
class BatchRow:
    position: int
    status: Literal["CREATED", "REJECTED"]
    code: str
    filename: str = ""


@dataclass(frozen=True)
class BatchResult:
    zip_bytes: bytes = field(repr=False)
    rows: tuple[BatchRow, ...]
    mode: BatchMode
    api_calls: int
    duration_ms: int
    model_name: str | None = None
    total_tokens: int | None = None

    @property
    def created_count(self) -> int:
        return sum(r.status == "CREATED" for r in self.rows)

    @property
    def rejected_count(self) -> int:
        return sum(r.status == "REJECTED" for r in self.rows)


def _restore_for_case(case: CaseRecord, pseudo_paragraph: str) -> str:
    """Perform trusted preflight and response verification for EACH case."""
    check = prepare_demo_payload(case)
    _trusted_preflight(case, check)
    _validate_response(pseudo_paragraph, check)
    result = pseudo_paragraph
    for token in ("[STRONA_1]", "[DOKUMENT_1]"):
        result = result.replace(token, check.token_map[token])
    return result


def _report_csv(rows: Sequence[BatchRow]) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(("pozycja_poprawnego_rekordu", "status", "kod", "plik"))
    for r in rows:
        writer.writerow((r.position, r.status, r.code, r.filename))
    return buffer.getvalue().encode("utf-8-sig")


def generate_demo_batch(
    cases: Sequence[CaseRecord],
    *,
    mode: BatchMode = "offline",
    allow_api: bool = False,
    client=None,
) -> BatchResult:
    """Produce ZIP in RAM; Gemini mode uses at most one API request.

    Preflight checks ALL cases *before* the first outbound request. An
    untrusted case blocks the whole job rather than allowing mixed real data.
    """
    if mode not in ("offline", "gemini"):
        raise BatchError("Nieobsługiwany tryb generowania.")
    if not 1 <= len(cases) <= MAX_BATCH_SIZE:
        raise BatchError("Partia musi zawierać od 1 do 50 rekordów demo.")
    if mode == "gemini" and not allow_api:
        raise BatchError("Wywołanie API wymaga osobnego potwierdzenia.")

    # ALL-or-nothing outbound preflight. The API is never contacted if a
    # case isn't identical to one of the bundled synthetic records.
    for case in cases:
        check = prepare_demo_payload(case)
        try:
            _trusted_preflight(case, check)
        except DraftingError:
            raise BatchError("Wśród rekordów jest pozycja poza zatwierdzonym zestawem demo.") from None

    started = perf_counter()
    api_calls = 0
    model_name = None
    total_tokens = None
    pseudo = OFFLINE_PARAGRAPH

    if mode == "gemini":
        first_check = prepare_demo_payload(cases[0])
        # Exactly one network call, before rendering any documents.
        result: DraftResult = generate_demo_draft(cases[0], first_check, client=client)
        pseudo = result.pseudonymized_paragraph
        api_calls = 1
        model_name = result.model_name
        total_tokens = result.total_tokens

    rows: list[BatchRow] = []
    archive_buffer = BytesIO()
    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        for position, case in enumerate(cases, start=1):
            filename = f"wezwanie_demo_{position:04d}.docx"
            try:
                paragraph = _restore_for_case(case, pseudo)
                docx_bytes = render_demo_docx(case, paragraph)
                archive.writestr(filename, docx_bytes)
                rows.append(BatchRow(position, "CREATED", "OK", filename))
            except (DraftingError, DocumentError, ValueError):
                # Sanitized aggregate report: no PESEL, names or raw LLM text.
                rows.append(BatchRow(position, "REJECTED", "DOCUMENT_CHECK_FAILED"))
        archive.writestr("batch_report.csv", _report_csv(rows))
        archive.writestr("README.txt", (
            "LEGAL DOCUMENT ENGINE — SYNTETYCZNA DEMONSTRACJA\n"
            "Dokumenty stanowią projekty testowe; nie są przeznaczone do użycia w sprawach rzeczywistych.\n"
            "Dane stron i kwot to wartości fikcyjne. PESEL nie trafia do dokumentów.\n"
            "Raport CSV zawiera wyłącznie numery porządkowe i statusy.\n"
            "Wymagana ręczna kontrola treści i formatowania przed jakimkolwiek użyciem.\n"
        ).encode("utf-8"))
    return BatchResult(
        zip_bytes=archive_buffer.getvalue(),
        rows=tuple(rows), mode=mode, api_calls=api_calls,
        duration_ms=int((perf_counter() - started) * 1000),
        model_name=model_name, total_tokens=total_tokens,
    )
