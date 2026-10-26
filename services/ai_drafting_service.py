"""Controlled Gemini drafting for the built-in synthetic demo only.

Fail-closed design:
- accept ONLY an unchanged record from the generated demo fixture,
- recompute the privacy check locally, never trust supplied token_map,
- send only the deterministic, approved pseudonymized sentence,
- reject changed/missing/extra tokens and raw identifiers in AI output,
- perform re-identification only after successful checks.

This is NOT a general-purpose PII scrubber or legal document review service.
"""

from __future__ import annotations

import os
import re
from datetime import date
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from models.case_schema import CaseRecord
from scripts.generate_demo_data import build_demo_rows
from services.privacy_service import PrivacyCheck, prepare_demo_payload, APPROVED_PAYLOAD

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)

MODEL_DEFAULT = "gemini-3.8-flash"
EXPECTED_TOKENS = ("[STRONA_1]", "[DOKUMENT_1]")

SYSTEM_INSTRUCTION = (
    "Jesteś redaktorem tekstów demonstracyjnych w języku polskim. "
    "Przeredaguj WYŁĄCZNIE podane zdanie o fikcyjnej fakturze na krótki, "
    "formalny akapit. Nie dodawaj faktów, dat, kwot, nazwisk, adresów, "
    "podstaw prawnych ani informacji o sądzie. "
    "Każdy token [STRONA_1] i [DOKUMENT_1] musi wystąpić dokładnie raz, "
    "w niezmienionej postaci. Nie dodawaj żadnych innych tokenów. "
    'Zwróć wyłącznie obiekt JSON z pojedynczym polem "akapit" typu string. '
    "To wyłącznie fikcyjny scenariusz demonstracyjny."
)


class DraftingError(ValueError):
    """Non-sensitive failure message suitable for the Streamlit UI."""


class DraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    akapit: str = Field(min_length=30, max_length=800)


@dataclass(frozen=True)
class DraftResult:
    pseudonymized_paragraph: str
    restored_paragraph: str = field(repr=False)
    model_name: str = ""
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@lru_cache(maxsize=1)
def _allowed_cases() -> frozenset[str]:
    """Match normalized complete records to bundled synthetic fixture."""
    results: set[str] = set()
    for raw in build_demo_rows():
        try:
            record = CaseRecord.model_validate(raw)
        except ValidationError:
            continue
        results.add(record.model_dump_json(by_alias=True))
    return frozenset(results)


def _trusted_preflight(case: CaseRecord, check: PrivacyCheck) -> str:
    if case.model_dump_json(by_alias=True) not in _allowed_cases():
        raise DraftingError("API jest dostępne wyłącznie dla oryginalnych danych demo.")

    if case.data_wymagalnosci > date.today():
        raise DraftingError("Rekord nie przeszedł kontroli daty wymagalności.")

    current = prepare_demo_payload(case)
    if not current.ready or current.api_text is None:
        raise DraftingError("Privacy Gate zablokował rekord.")

    # Never use an untrusted caller-supplied map/payload for a network request.
    if not check.ready or check.api_text != current.api_text or check.token_map != current.token_map:
        raise DraftingError("Kontrola integralności danych Privacy Gate nie powiodła się.")

    if not APPROVED_PAYLOAD.fullmatch(current.api_text):
        raise DraftingError("Payload nie spełnia dozwolonego wzorca.")

    if set(current.token_map) != set(EXPECTED_TOKENS):
        raise DraftingError("Wymagane tokeny demonstracyjne są niekompletne.")

    return current.api_text


def build_demo_api_payload(case: CaseRecord, check: PrivacyCheck) -> str:
    """Exactly the `contents` sent to Gemini; safe to show in payload inspector."""
    approved = _trusted_preflight(case, check)
    return "Zredaguj poniższy fikcyjny opis.\n\n" + approved


def _validate_response(paragraph: str, check: PrivacyCheck) -> None:
    for token in EXPECTED_TOKENS:
        if paragraph.count(token) != 1:
            raise DraftingError("Odpowiedź AI zmieniła liczbę wymaganych tokenów.")

    # No unknown placeholders or newly invented numeric references.
    without_tokens = paragraph
    for token in EXPECTED_TOKENS:
        without_tokens = without_tokens.replace(token, "")
    if "[" in without_tokens or "]" in without_tokens:
        raise DraftingError("Odpowiedź AI zawiera nieznane tokeny.")
    if re.search(r"\d", without_tokens):
        raise DraftingError("Odpowiedź AI dopisała liczby lub identyfikatory.")
    if "\n" in paragraph or "\r" in paragraph:
        raise DraftingError("Odpowiedź AI nie jest pojedynczym akapitem.")

    # Do not permit accidental reintroduction of local values before local restoration.
    for original in check.token_map.values():
        if original.casefold() in paragraph.casefold():
            raise DraftingError("Odpowiedź AI zawiera nieprzywrócony identyfikator.")
    if re.search(r"\b[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\b", without_tokens):
        # Conservative heuristic: block new full names, including possible false positives.
        raise DraftingError("Odpowiedź AI zawiera możliwy nowy identyfikator osobowy.")
    if "@" in without_tokens or "http" in without_tokens.casefold():
        raise DraftingError("Odpowiedź AI zawiera niedozwolone dane kontaktowe.")


def generate_demo_draft(
    case: CaseRecord,
    check: PrivacyCheck,
    *,
    client=None,
    model_name: str | None = None,
) -> DraftResult:
    """Single API call for exactly one known synthetic case.

    Client injection allows unit tests without API keys, network access or cost.
    Exceptions never include the raw response or the unredacted case.
    """
    contents = build_demo_api_payload(case, check)
    selected_model = model_name or os.getenv("GEMINI_MODEL", MODEL_DEFAULT)
    if not selected_model or not selected_model.strip():
        raise DraftingError("Nie skonfigurowano modelu Gemini.")

    owns_client = client is None
    if owns_client:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise DraftingError("Brak GEMINI_API_KEY w pliku .env.")
        from google import genai  # lazy import; offline tests need no SDK
        client = genai.Client(api_key=key)

    try:
        # We send only a fixed instruction and approved pseudonymized contents.
        response = client.models.generate_content(
            model=selected_model.strip(),
            contents=contents,
            config={
                "system_instruction": SYSTEM_INSTRUCTION,
                "response_mime_type": "application/json",
                "max_output_tokens": 4096,
                "temperature": 0.2,
            },
        )
    except Exception as exc:
        # Show only a numeric HTTP status or exception class.
        # Never display the SDK message: it can contain request/response details.
        code = getattr(exc, "code", None)
        if type(code) is int and 400 <= code <= 599:
            raise DraftingError(f"Gemini API zwróciło HTTP {code}.") from None
        raise DraftingError(
            f"Wywołanie Gemini nie powiodło się (typ: {type(exc).__name__})."
        ) from None
    finally:
        if owns_client:
            client.close()

    try:
        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise DraftingError("Gemini nie zwróciło tekstu odpowiedzi.")
        parsed = DraftResponse.model_validate_json(text)
        _validate_response(parsed.akapit, check)
    except (ValidationError, DraftingError):
        # No raw LLM text in errors or logging.
        raise DraftingError("Odpowiedź AI nie przeszła walidacji struktury lub tokenów.") from None

    paragraph = parsed.akapit
    restored = paragraph
    for token in EXPECTED_TOKENS:
        restored = restored.replace(token, check.token_map[token])

    usage = getattr(response, "usage_metadata", None)
    return DraftResult(
        pseudonymized_paragraph=paragraph,
        restored_paragraph=restored,
        model_name=selected_model.strip(),
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        total_tokens=getattr(usage, "total_token_count", None),
    )
