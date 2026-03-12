from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import streamlit as st

from core.exporter import build_dataframes, export_to_csv_text, export_to_excel_bytes
from core.registry import PARSER_REGISTRY


BANK_LABELS = {
    "bbva": "BBVA",
    "santander": "Santander",
}


def bank_label(bank_code: str) -> str:
    return BANK_LABELS.get(bank_code, bank_code.upper())


def metric_label(value: bool) -> str:
    return "OK" if value else "Error"


def parse_uploaded_pdf(bank_code: str, uploaded_file) -> dict:
    suffix = Path(uploaded_file.name).suffix or ".pdf"

    with NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(uploaded_file.getbuffer())
        temp_path = Path(temp_file.name)

    try:
        return PARSER_REGISTRY[bank_code].parse(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def main() -> None:
    st.set_page_config(
        page_title="Bank Statement Parser",
        page_icon=":material/account_balance:",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(203, 226, 255, 0.55), transparent 28%),
                radial-gradient(circle at top right, rgba(255, 226, 204, 0.55), transparent 24%),
                linear-gradient(180deg, #f8f6f1 0%, #f3efe7 100%);
        }
        .hero {
            background: rgba(255, 252, 247, 0.82);
            border: 1px solid rgba(30, 41, 59, 0.08);
            border-radius: 20px;
            padding: 1.4rem 1.6rem;
            box-shadow: 0 22px 60px rgba(60, 54, 44, 0.08);
            margin-bottom: 1rem;
        }
        .hero h1 {
            font-family: "Iowan Old Style", "Palatino Linotype", serif;
            letter-spacing: -0.02em;
            margin: 0;
            color: #102a43;
        }
        .hero p {
            margin: 0.35rem 0 0 0;
            color: #486581;
            font-size: 1rem;
        }
        .status-pill {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            background: #e6fffa;
            color: #0f766e;
            font-size: 0.85rem;
            margin-top: 0.75rem;
        }
        </style>
        <div class="hero">
            <h1>Bank Statement Parser</h1>
            <p>Sube un PDF, procesa el estado de cuenta y descarga transacciones, meta y validaciones.</p>
            <div class="status-pill">BBVA y Santander listos para Streamlit</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.subheader("Entrada")
        bank_code = st.selectbox(
            "Banco",
            options=list(PARSER_REGISTRY.keys()),
            format_func=bank_label,
        )
        uploaded_file = st.file_uploader(
            "Estado de cuenta en PDF",
            type=["pdf"],
            help="Sube un PDF emitido por el banco seleccionado.",
        )
        run_parser = st.button("Procesar estado de cuenta", type="primary", use_container_width=True)

        st.caption("Los archivos solo se usan durante la sesion actual.")

    if not uploaded_file:
        st.info("Carga un PDF para iniciar el procesamiento.")
        return

    upload_key = f"{bank_code}:{uploaded_file.name}:{uploaded_file.size}"

    if run_parser:
        with st.spinner("Procesando PDF..."):
            try:
                st.session_state["parsed_result"] = parse_uploaded_pdf(bank_code, uploaded_file)
                st.session_state["parsed_upload_key"] = upload_key
            except Exception as exc:
                st.error(f"No se pudo procesar el archivo: {exc}")
                return

    if st.session_state.get("parsed_upload_key") != upload_key:
        st.info("Selecciona el banco y presiona Procesar estado de cuenta.")
        return

    parsed = st.session_state["parsed_result"]

    df_tx, df_meta, df_val = build_dataframes(parsed)
    validation = parsed["validation"]
    csv_bytes = export_to_csv_text(parsed).encode("utf-8-sig")
    excel_bytes = export_to_excel_bytes(parsed)
    stem = Path(uploaded_file.name).stem.replace(" ", "_")

    top_left, top_right = st.columns([1.3, 1])

    with top_left:
        st.success(f"Procesamiento completado para {bank_label(bank_code)}.")
        st.dataframe(df_meta, use_container_width=True, hide_index=True)

    with top_right:
        st.metric("Movimientos", validation.get("transaction_count", 0))
        st.metric("Depositos", metric_label(validation.get("deposits_match", False)))
        st.metric("Retiros", metric_label(validation.get("withdrawals_match", False)))
        st.metric("Saldo final", metric_label(validation.get("closing_match", False)))

    download_col1, download_col2 = st.columns(2)
    with download_col1:
        st.download_button(
            "Descargar CSV",
            data=csv_bytes,
            file_name=f"{bank_code}_{stem}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with download_col2:
        st.download_button(
            "Descargar Excel",
            data=excel_bytes,
            file_name=f"{bank_code}_{stem}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    tab_transactions, tab_validation, tab_meta = st.tabs(
        ["Transacciones", "Validacion", "Meta"]
    )

    with tab_transactions:
        st.dataframe(df_tx, use_container_width=True, hide_index=True)

    with tab_validation:
        st.dataframe(df_val, use_container_width=True, hide_index=True)

    with tab_meta:
        st.json(parsed["meta"], expanded=True)


if __name__ == "__main__":
    main()
