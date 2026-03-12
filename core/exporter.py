from __future__ import annotations

from io import BytesIO, StringIO
from pathlib import Path
import pandas as pd


def build_dataframes(parsed: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    df_tx = pd.DataFrame(parsed["transactions"])
    df_meta = pd.DataFrame([parsed["meta"]])
    df_val = pd.DataFrame([parsed["validation"]])
    return df_tx, df_meta, df_val


def export_to_excel(parsed: dict, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    excel_bytes = export_to_excel_bytes(parsed)

    with output_path.open("wb") as file:
        file.write(excel_bytes)


def export_to_excel_bytes(parsed: dict) -> bytes:
    df_tx, df_meta, df_val = build_dataframes(parsed)
    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_tx.to_excel(writer, sheet_name="Transacciones", index=False)
        df_meta.to_excel(writer, sheet_name="Meta", index=False)
        df_val.to_excel(writer, sheet_name="Validacion", index=False)

    return buffer.getvalue()


def export_to_csv(parsed: dict, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    csv_text = export_to_csv_text(parsed)
    output_path.write_text(csv_text, encoding="utf-8-sig")


def export_to_csv_text(parsed: dict) -> str:
    df_tx, _, _ = build_dataframes(parsed)
    buffer = StringIO()
    df_tx.to_csv(buffer, index=False)
    return buffer.getvalue()
