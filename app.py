"""Legal Document Engine Sprint 2B: local DQ + strict demo PII gate + one AI draft."""

import hashlib
import streamlit as st

from services.ai_drafting_service import (
    DraftingError,
    SYSTEM_INSTRUCTION,
    build_demo_api_payload,
    generate_demo_draft,
)
from services.data_quality_service import load_case_table, validate_case_table
from services.privacy_service import privacy_gate_batch
from services.batch_service import BatchError, generate_demo_batch
from services.telemetry_service import log_batch_aggregate

st.set_page_config(page_title="Legal Document Engine", page_icon="⚖️", layout="wide")
st.title("Legal Document Engine")
st.caption("MVP v1.0 · Data Quality → Privacy Gate → AI Draft → DOCX Batch & ZIP")
st.warning(
    "DEMO — używaj wyłącznie dostarczonych danych syntetycznych. "
    "AI akceptuje tylko niezmienione rekordy z wbudowanego zestawu testowego. "
    "Privacy Gate nie jest ogólną anonimizacją ani gwarancją zgodności z RODO. "
    "Wygenerowany tekst jest szkicem do weryfikacji, nie poradą prawną."
)

uploaded = st.file_uploader("Załaduj CSV lub XLSX", type=["csv", "xlsx"])
if uploaded is not None:
    try:
        frame = load_case_table(uploaded.name, uploaded.getvalue())
        report = validate_case_table(frame)
    except (ValueError, TypeError, OSError) as exc:
        st.error(f"Nie udało się przetworzyć tabeli: {exc}")
    else:
        a, b, c = st.columns(3)
        a.metric("Wczytane", report.total_count)
        b.metric("Poprawne", report.valid_count)
        c.metric("Odrzucone", report.rejected_count)

        checks = privacy_gate_batch(report.valid_cases)
        ready_positions = [i for i, check in enumerate(checks) if check.ready]
        blocked_positions = [i for i, check in enumerate(checks) if not check.ready]

        data_tab, privacy_tab, ai_tab, batch_tab = st.tabs(
            ["Data Quality", "Privacy & Payload Inspector", "AI Draft — 1 rekord", "DOCX Batch & ZIP"]
        )
        with data_tab:
            st.subheader("Data Quality Report")
            if report.rejected_count:
                st.dataframe(report.issues_table(), hide_index=True, use_container_width=True)
                st.download_button(
                    "Pobierz odrzucone rekordy do korekty",
                    data=report.rejected_csv(),
                    file_name="odrzucone_rekordy.csv",
                    mime="text/csv",
                )
                st.caption("CSV zawiera pełne dane syntetyczne odrzuconych wierszy.")
            else:
                st.success("Wszystkie rekordy przeszły walidację.")

        with privacy_tab:
            st.subheader("Local Privacy Gate")
            left, right = st.columns(2)
            left.metric("READY — zgodne z wzorcem demo", len(ready_positions))
            right.metric("BLOCKED — brak dopuszczenia", len(blocked_positions))
            st.caption(
                "READY oznacza zgodność z ograniczonym wzorcem; nie oznacza, "
                "że dowolny rekord jest bezpieczny do przetwarzania przez API."
            )
            if blocked_positions:
                st.dataframe(
                    [
                        {"Rekord poprawny nr": i + 1, "Powód": "; ".join(checks[i].issues)}
                        for i in blocked_positions
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            if ready_positions:
                selected = st.selectbox(
                    "Podgląd rekordu READY",
                    ready_positions,
                    format_func=lambda i: f"Rekord poprawny nr {i + 1}",
                    key="privacy_preview",
                )
                st.code(checks[selected].api_text or "", language="text")
                st.info("To lokalny podgląd. Nie wykonuje wywołania API.")

        with ai_tab:
            st.subheader("Gemini — formalizacja pojedynczego zdania testowego")
            st.caption(
                "W tym sprincie wysyłamy tylko jeden wybrany rekord po osobnym "
                "kliknięciu. Nie ma masowego przetwarzania ani eksportu DOCX."
            )
            if not ready_positions:
                st.info("Brak rekordów READY.")
            else:
                index = st.selectbox(
                    "Wybierz rekord demo",
                    ready_positions,
                    format_func=lambda i: f"Rekord poprawny nr {i + 1}",
                    key="ai_selection",
                )
                case = report.valid_cases[index]
                check = checks[index]
                try:
                    payload = build_demo_api_payload(case, check)
                except DraftingError:
                    st.error("Wybrany rekord nie należy do zatwierdzonego zestawu demo.")
                else:
                    st.markdown("**Dokładna treść przekazywana jako `contents` do Gemini:**")
                    st.code(payload, language="text")
                    with st.expander("Pokaż również system_instruction"):
                        st.code(SYSTEM_INSTRUCTION, language="text")

                    consent = st.checkbox(
                        "Potwierdzam, że to wyłącznie dane syntetyczne i chcę "
                        "wykonać jedno wywołanie zewnętrznego Gemini API.",
                        key="confirm_ai_call",
                    )
                    if st.button(
                        "Wygeneruj akapit (1 żądanie API)",
                        disabled=not consent,
                        type="primary",
                    ):
                        try:
                            with st.spinner("Generowanie i weryfikacja tokenów..."):
                                result = generate_demo_draft(case, check)
                        except DraftingError as exc:
                            st.error(str(exc))
                        else:
                            st.success("Wynik zaakceptowany przez lokalny walidator.")
                            st.markdown("**Odpowiedź Gemini — z tokenami:**")
                            st.code(result.pseudonymized_paragraph, language="text")
                            st.markdown("**Lokalnie przywrócone dane demo:**")
                            st.write(result.restored_paragraph)
                            st.caption(
                                f"Model: {result.model_name} · Tokens in: {result.prompt_tokens} "
                                f"· out: {result.output_tokens} · total: {result.total_tokens}"
                            )
                            st.warning(
                                "Weryfikacja tokenów nie gwarantuje prawdziwości treści. "
                                "Projekt pisma musi zostać sprawdzony przez człowieka."
                            )

        with batch_tab:
            st.subheader("Masowy eksport DOCX — fikcyjne wezwania")
            st.caption(
                "Generowanie w RAM. Archiwum zawiera wyłącznie projekty dokumentów demo "
                "oraz raport bez identyfikatorów osobowych."
            )
            if not ready_positions:
                st.info("Brak rekordów dopuszczonych do generowania.")
            else:
                st.write(f"Dane do demonstracji: **{len(ready_positions)} rekordów READY**")
                batch_mode = st.radio(
                    "Wybierz sposób przygotowania akapitu",
                    options=["offline", "gemini"],
                    format_func=lambda value: (
                        "Offline — gotowy, zweryfikowany tekst testowy (0 wywołań API)"
                        if value == "offline" else
                        "Gemini — 1 wywołanie API dla całej partii"
                    ),
                    key="batch_mode",
                )
                st.info(
                    "Wszystkie rekordy muszą należeć do niezmienionego, "
                    "wbudowanego zestawu syntetycznego. "
                    "Nie jest to system do autentycznych spraw."
                )
                confirmed = st.checkbox(
                    "Potwierdzam wyłącznie syntetyczne dane demonstracyjne "
                    "i rozumiem ograniczenia projektu.",
                    key="batch_demo_confirm",
                )
                if batch_mode == "gemini":
                    api_confirmed = st.checkbox(
                        "Potwierdzam świadomie jedno zewnętrzne żądanie Gemini API.",
                        key="batch_api_confirm",
                    )
                else:
                    api_confirmed = False

                # Hash is ephemeral. Never store file bytes or names in telemetry.
                upload_key = hashlib.sha256(uploaded.getvalue()).hexdigest()
                previous = st.session_state.get("batch_export")
                if previous and previous["upload_key"] != upload_key:
                    st.session_state.pop("batch_export", None)

                enabled = confirmed and (batch_mode != "gemini" or api_confirmed)
                if st.button("Utwórz paczkę dokumentów ZIP", disabled=not enabled, type="primary"):
                    st.session_state.pop("batch_export", None)
                    try:
                        with st.spinner("Weryfikacja i generowanie DOCX..."):
                            result = generate_demo_batch(
                                report.valid_cases,
                                mode=batch_mode,
                                allow_api=api_confirmed,
                            )
                    except (BatchError, DraftingError) as exc:
                        st.error(str(exc))
                    else:
                        was_logged = log_batch_aggregate(result)
                        st.session_state["batch_export"] = {
                            "upload_key": upload_key,
                            "mode": batch_mode,
                            "result": result,
                            "sql_logged": was_logged,
                        }
                export = st.session_state.get("batch_export")
                if export and export["upload_key"] == upload_key and export["mode"] == batch_mode:
                    result = export["result"]
                    x, y, z = st.columns(3)
                    x.metric("Gotowe DOCX", result.created_count)
                    y.metric("Odrzucone", result.rejected_count)
                    z.metric("Wywołania API", result.api_calls)
                    st.caption(
                        f"Czas: {result.duration_ms} ms · "
                        f"Tokeny łącznie: {result.total_tokens if result.total_tokens is not None else 'nie dotyczy'} · "
                        f"Zapis SQL: {'TAK' if export['sql_logged'] else 'WYŁĄCZONY / NIEDOSTĘPNY'}"
                    )
                    st.download_button(
                        "Pobierz ZIP z projektami DOCX",
                        data=result.zip_bytes,
                        file_name="LegalDocumentEngine_demo_batch.zip",
                        mime="application/zip",
                        key="download_batch_zip",
                    )
                    st.warning(
                        "Dokumenty zostały wygenerowane do celów demonstracyjnych. "
                        "Nie należy ich wykorzystywać jako pism w rzeczywistych sprawach."
                    )
