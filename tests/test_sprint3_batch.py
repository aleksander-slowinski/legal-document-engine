"""Sprint 3: offline DOCX/ZIP regression tests, no network or SQL required."""
import csv
from datetime import date
from io import BytesIO, StringIO
from types import SimpleNamespace
from zipfile import ZipFile
import json

from docx import Document
import pandas as pd
import pytest

from models.case_schema import CaseRecord
from scripts.generate_demo_data import build_demo_rows
from services.data_quality_service import validate_case_table
from services.batch_service import (
    BatchError, OFFLINE_PARAGRAPH, generate_demo_batch,
)
from services.document_service import (
    ALLOWED_FIELDS, DocumentError, document_context, render_demo_docx,
)
from services.telemetry_service import log_batch_aggregate


def demo_cases():
    report = validate_case_table(pd.DataFrame(build_demo_rows()), today=date(2026, 10, 25))
    assert (report.total_count, report.valid_count, report.rejected_count) == (50, 46, 4)
    return report.valid_cases


def all_doc_text(docx_bytes):
    doc = Document(BytesIO(docx_bytes))
    body = '\n'.join(p.text for p in doc.paragraphs)
    tables = '\n'.join(cell.text for t in doc.tables for row in t.rows for cell in row.cells)
    return body + '\n' + tables


class FakeGemini:
    def __init__(self):
        self.calls = []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            text=json.dumps({'akapit': OFFLINE_PARAGRAPH}, ensure_ascii=False),
            usage_metadata=SimpleNamespace(
                prompt_token_count=100, candidates_token_count=50, total_token_count=200,
            ),
        )


def test_context_excludes_pesel():
    case = demo_cases()[0]
    context = document_context(
        case,
        'W fikcyjnej sprawie Osoba Testowa 001 nie zapłaciła za FV/001/2024.',
        issued_on=date(2026, 10, 25),
    )
    assert set(context) == ALLOWED_FIELDS
    assert case.pesel not in repr(context)
    assert context['amount'] == '1 017,50 zł'
    assert context['issue_date'] == '25.10.2026'


def test_single_word_document_contains_demo_marker():
    case = demo_cases()[0]
    paragraph = 'W fikcyjnej sprawie Osoba Testowa 001 nie uregulowała testowej faktury FV/001/2024.'
    output = render_demo_docx(case, paragraph)
    assert output[:2] == b'PK'
    result = all_doc_text(output)
    assert 'WEZWANIE DO ZAPŁATY' in result
    assert 'Osoba Testowa 001' in result
    assert '1 017,50 zł' in result
    assert 'FV/001/2024' in result
    assert 'PROJEKT DEMONSTRACYJNY' in result
    assert '{{' not in result
    assert '[STRONA_1]' not in result
    assert case.pesel not in result


def test_unresolved_placeholder_in_document_rejected():
    case = demo_cases()[0]
    with pytest.raises(DocumentError, match='nierozwiązane tokeny'):
        render_demo_docx(case, 'Test [STRONA_1]')


def test_offline_batch_creates_46_word_docs_and_non_identifying_manifest():
    cases = demo_cases()
    result = generate_demo_batch(cases, mode='offline')
    assert result.created_count == 46
    assert result.rejected_count == 0
    assert result.api_calls == 0
    assert result.total_tokens is None
    with ZipFile(BytesIO(result.zip_bytes)) as archive:
        names = archive.namelist()
        docx_names = [n for n in names if n.endswith('.docx')]
        assert len(docx_names) == 46
        assert len(names) == 48  # docs + CSV + README
        assert names[0] == 'wezwanie_demo_0001.docx'
        assert names[45] == 'wezwanie_demo_0046.docx'
        assert 'Osoba Testowa 001' in all_doc_text(archive.read(docx_names[0]))
        assert cases[-1].imie_nazwisko in all_doc_text(archive.read(docx_names[-1]))
        csv_report = archive.read('batch_report.csv').decode('utf-8-sig')
        assert len(list(csv.DictReader(StringIO(csv_report)))) == 46
        assert 'PESEL' not in csv_report
        for case in cases:
            assert case.pesel not in csv_report
            assert case.imie_nazwisko not in csv_report
            assert case.sygnatura not in csv_report


def test_gemini_batch_calls_api_exactly_once_and_reuses_tokenized_text():
    client = FakeGemini()
    result = generate_demo_batch(demo_cases(), mode='gemini', allow_api=True, client=client)
    assert len(client.calls) == result.api_calls == 1
    assert result.created_count == 46
    assert result.total_tokens == 200
    sent = client.calls[0]['contents']
    assert '[STRONA_1]' in sent and '[DOKUMENT_1]' in sent
    assert 'Osoba Testowa' not in sent
    with ZipFile(BytesIO(result.zip_bytes)) as archive:
        first = all_doc_text(archive.read('wezwanie_demo_0001.docx'))
        last = all_doc_text(archive.read('wezwanie_demo_0046.docx'))
    assert 'Osoba Testowa 001' in first
    assert demo_cases()[-1].imie_nazwisko in last


def test_gemini_mode_requires_explicit_confirmation():
    client = FakeGemini()
    with pytest.raises(BatchError, match='potwierdzenia'):
        generate_demo_batch(demo_cases(), mode='gemini', client=client)
    assert client.calls == []


def test_modified_case_blocks_whole_batch_before_api_call():
    cases = list(demo_cases())
    modified = cases[-1].model_copy(update={'kwota_roszczenia': cases[-1].kwota_roszczenia + 5})
    cases[-1] = modified
    client = FakeGemini()
    with pytest.raises(BatchError, match='poza zatwierdzonym'):
        generate_demo_batch(cases, mode='gemini', allow_api=True, client=client)
    assert client.calls == []


def test_one_doc_failure_isolated_and_report_sanitized(monkeypatch):
    from services import batch_service
    original_render = batch_service.render_demo_docx

    def broken_render(case, paragraph):
        if case.imie_nazwisko == 'Osoba Testowa 005':
            raise DocumentError('FAKE PRIVATE DETAIL MUST NOT BE LOGGED')
        return original_render(case, paragraph)

    monkeypatch.setattr(batch_service, 'render_demo_docx', broken_render)
    result = generate_demo_batch(demo_cases(), mode='offline')
    assert result.created_count == 45
    assert result.rejected_count == 1
    with ZipFile(BytesIO(result.zip_bytes)) as archive:
        report = archive.read('batch_report.csv').decode('utf-8-sig')
        assert 'FAKE PRIVATE DETAIL' not in report
        assert 'Osoba Testowa' not in report
        assert 'DOCUMENT_CHECK_FAILED' in report
        assert not 'wezwanie_demo_0005.docx' in archive.namelist()


def test_invalid_batch_size_and_mode():
    with pytest.raises(BatchError):
        generate_demo_batch((), mode='offline')
    with pytest.raises(BatchError):
        generate_demo_batch(demo_cases(), mode='other')
    with pytest.raises(BatchError):
        generate_demo_batch(demo_cases() * 2, mode='offline')


def test_sql_telemetry_default_off(monkeypatch):
    monkeypatch.delenv('SQL_LOGGING_ENABLED', raising=False)
    result = generate_demo_batch(demo_cases()[:1])
    assert log_batch_aggregate(result) is False


def test_sql_telemetry_unavailable_does_not_crash(monkeypatch):
    monkeypatch.setenv('SQL_LOGGING_ENABLED', 'true')
    monkeypatch.setenv('SQL_DRIVER', 'NoSuchDriver')
    result = generate_demo_batch(demo_cases()[:1])
    assert log_batch_aggregate(result) is False
