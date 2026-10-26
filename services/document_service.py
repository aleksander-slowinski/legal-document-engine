"""Local DOCX creation from the bundled, visibly marked demo template.

The Word file is generated on the same host as Streamlit. Never accepts an
untrusted template or runs an LLM during rendering.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from models.case_schema import CaseRecord

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "wezwanie_demo.docx"
ALLOWED_FIELDS = frozenset({
    "issue_date", "case_reference", "debtor", "amount", "due_date",
    "invoice", "narrative",
})


class DocumentError(ValueError):
    """Safe, non-sensitive document-rendering error."""


def _format_pln(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " zł"


def document_context(case: CaseRecord, paragraph: str, *, issued_on: date | None = None) -> dict[str, str]:
    """Only the explicitly approved fields are passed to Word rendering.

    Deliberately excludes PESEL (even checksum-valid test identifiers can
    accidentally coincide with real numbers). Does not infer legal facts.
    """
    if not isinstance(paragraph, str) or not paragraph.strip():
        raise DocumentError("Brak zweryfikowanego akapitu.")
    if "[" in paragraph or "]" in paragraph:
        raise DocumentError("W tekście pozostały nierozwiązane tokeny.")
    # The fixed demo text includes exactly one fictitious invoice identifier.
    return {
        "issue_date": (issued_on or date.today()).strftime("%d.%m.%Y"),
        "case_reference": case.sygnatura,
        "debtor": case.imie_nazwisko,
        "amount": _format_pln(case.kwota_roszczenia),
        "due_date": case.data_wymagalnosci.strftime("%d.%m.%Y"),
        "invoice": _invoice_from_demo_case(case),
        "narrative": paragraph.strip(),
    }


def _invoice_from_demo_case(case: CaseRecord) -> str:
    """Extracts fixture invoice; no regex parsing from arbitrary legal data."""
    import re
    match = re.search(r"\bFV/[0-9]{3}/2024\b", case.opis_stanu_faktycznego)
    if not match:
        raise DocumentError("Brak oczekiwanego oznaczenia fikcyjnej faktury.")
    return match.group(0)


def _render_with_python_docx_fallback(template_path: Path, context: dict[str, str]) -> bytes:
    """Narrow offline fallback for placeholders occupying their own runs.

    The primary renderer is docxtpl. This fallback permits offline testing
    in environments without docxtpl and supports *only* this fixture.
    """
    doc = Document(str(template_path))
    seen: set[str] = set()
    containers = [*doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                containers.extend(cell.paragraphs)
    for sec in doc.sections:
        containers.extend(sec.header.paragraphs)
        containers.extend(sec.footer.paragraphs)
    for paragraph in containers:
        for run in paragraph.runs:
            for key, value in context.items():
                marker = "{{ " + key + " }}"
                if marker in run.text:
                    run.text = run.text.replace(marker, value)
                    seen.add(key)
    if not set(context).issubset(seen):
        raise DocumentError("Szablon DOCX ma niekompletne pola.")
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def render_demo_docx(
    case: CaseRecord,
    paragraph: str,
    *,
    template_path: Path | None = None,
    issued_on: date | None = None,
) -> bytes:
    """Creates one DOCX entirely locally; does not write a temporary file."""
    path = template_path or TEMPLATE_PATH
    if not path.is_file():
        raise DocumentError("Brak szablonu DOCX.")
    context = document_context(case, paragraph, issued_on=issued_on)
    if set(context) != ALLOWED_FIELDS:
        raise DocumentError("Nieoczekiwane dane przekazane do szablonu.")
    try:
        from docxtpl import DocxTemplate
    except ImportError:
        # Intentionally very limited. No user-supplied templates or expressions.
        return _render_with_python_docx_fallback(path, context)
    try:
        template = DocxTemplate(str(path))
        template.render(context, autoescape=True)
        output = BytesIO()
        template.save(output)
        return output.getvalue()
    except (OSError, ValueError, PackageNotFoundError) as exc:
        raise DocumentError("Nie udało się utworzyć dokumentu DOCX.") from None
