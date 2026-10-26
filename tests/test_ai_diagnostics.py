import pytest
from models.case_schema import CaseRecord
from scripts.generate_demo_data import build_demo_rows
from services.ai_drafting_service import DraftingError, generate_demo_draft
from services.privacy_service import prepare_demo_payload


class FakeApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class FakeClient:
    def __init__(self, exception):
        self.models = self
        self.exception = exception

    def generate_content(self, **kwargs):
        raise self.exception


@pytest.mark.parametrize("code", [400, 403, 404, 429, 503])
def test_error_displays_only_http_code(code):
    case = CaseRecord.model_validate(build_demo_rows()[0])
    check = prepare_demo_payload(case)
    client = FakeClient(FakeApiError(code, "SECRET: " + case.pesel))
    with pytest.raises(DraftingError) as exc:
        generate_demo_draft(case, check, client=client)
    assert f"HTTP {code}" in str(exc.value)
    assert case.pesel not in str(exc.value)
    assert "SECRET" not in str(exc.value)
