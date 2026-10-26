"""Strict privacy gate for *synthetic demo cases only*.

No network calls, no persistence, no claim of arbitrary PII de-identification.
Only an approved, deterministic narrative is marked READY for the future API.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from models.case_schema import CaseRecord


APPROVED_PAYLOAD = re.compile(
    r"^W fikcyjnej sprawie \[STRONA_1\] nie uregulowała "
    r"testowej faktury \[DOKUMENT_1\] w wyznaczonym terminie\.$"
)
INVOICE_ID = re.compile(r"\bFV/[A-Za-z0-9]+/[A-Za-z0-9]+\b", re.IGNORECASE)


@dataclass(frozen=True)
class PrivacyCheck:
    status: Literal["READY", "BLOCKED"]
    api_text: str | None
    issues: tuple[str, ...] = ()
    # Purely in-memory mapping, explicitly excluded from Streamlit display/logs.
    token_map: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def ready(self) -> bool:
        return self.status == "READY"


def prepare_demo_payload(case: CaseRecord) -> PrivacyCheck:
    """Pseudonymize known fields, then allow ONLY the known demo narrative.

    Fail closed: arbitrary descriptions cannot be sent via this MVP gate.
    """
    original = case.opis_stanu_faktycznego
    text = original
    token_map: dict[str, str] = {}

    name = case.imie_nazwisko
    if name:
        name_pattern = re.compile(re.escape(name), flags=re.IGNORECASE)
        if name_pattern.search(text):
            text = name_pattern.sub("[STRONA_1]", text)
            token_map["[STRONA_1]"] = name

    # When these identifiers appear in the narrative, replace them locally.
    pesel_pattern = re.compile(re.escape(case.pesel))
    if pesel_pattern.search(text):
        text = pesel_pattern.sub("[PESEL_1]", text)
        token_map["[PESEL_1]"] = case.pesel

    signature_pattern = re.compile(re.escape(case.sygnatura), re.IGNORECASE)
    if signature_pattern.search(text):
        text = signature_pattern.sub("[SYGNATURA_1]", text)
        token_map["[SYGNATURA_1]"] = case.sygnatura

    document_ids = list(dict.fromkeys(match.group(0) for match in INVOICE_ID.finditer(text)))
    for idx, identifier in enumerate(document_ids, start=1):
        token = f"[DOKUMENT_{idx}]"
        text = re.sub(re.escape(identifier), lambda _: token, text, flags=re.IGNORECASE)
        token_map[token] = identifier

    if not APPROVED_PAYLOAD.fullmatch(text):
        return PrivacyCheck(
            status="BLOCKED",
            api_text=None,
            issues=(
                "Opis nie odpowiada zatwierdzonemu wzorcowi syntetycznemu. "
                "Nie przekazuj rekordu do API; wymaga osobnej reguły i testów.",
            ),
            token_map={},
        )

    # No source row, PESEL, name, monetary amount or case signature is sent.
    return PrivacyCheck(status="READY", api_text=text, token_map=token_map)


def privacy_gate_batch(cases: tuple[CaseRecord, ...]) -> tuple[PrivacyCheck, ...]:
    return tuple(prepare_demo_payload(case) for case in cases)
