"""Offline, zero API calls. SDK client is injected and intercepted."""

import json
from types import SimpleNamespace

import pytest

from models.case_schema import CaseRecord
from scripts.generate_demo_data import build_demo_rows
from services.ai_drafting_service import (
    DraftingError,
    SYSTEM_INSTRUCTION,
    build_demo_api_payload,
    generate_demo_draft,
)
from services.privacy_service import PrivacyCheck, prepare_demo_payload


OK_PARAGRAPH = (
    "W ramach fikcyjnej sprawy [STRONA_1] nie dokonała zapłaty "
    "za testową fakturę [DOKUMENT_1] w uzgodnionym terminie."
)


def demo_case():
    return CaseRecord.model_validate(build_demo_rows()[0])


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response
        self.error = error
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        payload = {"akapit": self.response if self.response is not None else OK_PARAGRAPH}
        return SimpleNamespace(
            text=json.dumps(payload, ensure_ascii=False),
            usage_metadata=SimpleNamespace(
                prompt_token_count=36,
                candidates_token_count=40,
                total_token_count=76,
            ),
        )


def test_single_call_contains_only_pseudonymized_demo_text():
    case = demo_case()
    check = prepare_demo_payload(case)
    client = FakeClient()
    result = generate_demo_draft(case, check, client=client, model_name="model-test")
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["contents"] == build_demo_api_payload(case, check)
    assert call["config"]["system_instruction"] == SYSTEM_INSTRUCTION
    assert call["config"]["response_mime_type"] == "application/json"
    outbound = call["contents"] + call["config"]["system_instruction"]
    for prohibited in (case.imie_nazwisko, case.pesel, case.sygnatura, "FV/001/2024"):
        assert prohibited not in outbound
    assert result.pseudonymized_paragraph == OK_PARAGRAPH
    assert case.imie_nazwisko in result.restored_paragraph
    assert "FV/001/2024" in result.restored_paragraph
    assert result.total_tokens == 76


def test_blocked_record_never_contacts_client():
    raw = build_demo_rows()[0].copy()
    raw["Opis_Stanu_Faktycznego"] += " Świadek Adam Nowak."
    case = CaseRecord.model_validate(raw)
    check = prepare_demo_payload(case)
    client = FakeClient()
    with pytest.raises(DraftingError, match="oryginalnych danych demo"):
        generate_demo_draft(case, check, client=client)
    assert client.calls == []


def test_changed_amount_blocks_despite_approved_narrative():
    raw = build_demo_rows()[0].copy()
    raw["Kwota_Roszczenia"] = "123456,78"
    case = CaseRecord.model_validate(raw)
    check = prepare_demo_payload(case)
    assert check.ready
    client = FakeClient()
    with pytest.raises(DraftingError, match="oryginalnych danych demo"):
        generate_demo_draft(case, check, client=client)
    assert client.calls == []


def test_modified_check_map_blocks_before_call():
    case = demo_case()
    check = prepare_demo_payload(case)
    forged = PrivacyCheck(status="READY", api_text=check.api_text,
                          token_map={"[STRONA_1]": "inna osoba", "[DOKUMENT_1]": "X"})
    client = FakeClient()
    with pytest.raises(DraftingError, match="integralności"):
        generate_demo_draft(case, forged, client=client)
    assert not client.calls


@pytest.mark.parametrize("response", [
    "Zapisano brak płatności za [DOKUMENT_1] w fikcyjnej sprawie.",
    "[STRONA_1] oraz [STRONA_1] nie zapłaciła za [DOKUMENT_1] w terminie.",
    "[STRONA_1] nie zapłaciła za [DOKUMENT_1], więc wniosek [PESEL_1] uznano za zasadny.",
    "[STRONA_1] nie zapłaciła za [DOKUMENT_1] w dniu 12.02.2025.",
    "[STRONA_1] nie zapłaciła za FV/001/2024 oraz [DOKUMENT_1] w terminie.",
    "[STRONA_1] nie zapłaciła za [DOKUMENT_1], jak twierdzi Jan Kowalski.",
])
def test_unsafe_ai_output_rejected(response):
    case = demo_case()
    check = prepare_demo_payload(case)
    with pytest.raises(DraftingError, match="nie przeszła walidacji"):
        generate_demo_draft(case, check, client=FakeClient(response=response))


def test_api_failure_does_not_echo_exception_contents():
    case = demo_case()
    check = prepare_demo_payload(case)
    client = FakeClient(error=RuntimeError("SECRET: " + case.pesel))
    with pytest.raises(DraftingError) as exc:
        generate_demo_draft(case, check, client=client)
    assert case.pesel not in str(exc.value)
    assert "SECRET" not in str(exc.value)


def test_invalid_json_response_rejected():
    case = demo_case()
    check = prepare_demo_payload(case)

    class BadJsonClient(FakeClient):
        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text="NOT JSON")

    with pytest.raises(DraftingError, match="nie przeszła walidacji"):
        generate_demo_draft(case, check, client=BadJsonClient())


def test_unknown_extra_json_field_rejected():
    case = demo_case()
    check = prepare_demo_payload(case)

    class ExtraJsonClient(FakeClient):
        def generate_content(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(text=json.dumps({"akapit": OK_PARAGRAPH, "pesel": "not allowed"}))

    with pytest.raises(DraftingError, match="nie przeszła walidacji"):
        generate_demo_draft(case, check, client=ExtraJsonClient())
