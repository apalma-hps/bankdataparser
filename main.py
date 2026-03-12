from __future__ import annotations

import argparse
from pathlib import Path

from core.exporter import export_to_csv, export_to_excel
from core.registry import PARSER_REGISTRY


def main():
    parser = argparse.ArgumentParser(description="Conversor de estados de cuenta por banco")
    parser.add_argument(
        "--bank",
        required=True,
        choices=PARSER_REGISTRY.keys(),
        help="Banco a procesar"
    )
    parser.add_argument(
        "--pdf",
        required=True,
        help="Ruta del PDF"
    )
    parser.add_argument(
        "--excel",
        default=None,
        help="Ruta de salida Excel"
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Ruta de salida CSV"
    )

    args = parser.parse_args()

    bank = args.bank.lower()
    pdf_path = Path(args.pdf)

    parser_impl = PARSER_REGISTRY[bank]
    parsed = parser_impl.parse(pdf_path)

    default_stem = pdf_path.stem.replace(" ", "_")
    excel_path = args.excel or f"output/{bank}_{default_stem}.xlsx"
    csv_path = args.csv or f"output/{bank}_{default_stem}.csv"

    export_to_excel(parsed, excel_path)
    export_to_csv(parsed, csv_path)

    print("\n=== META ===")
    for k, v in parsed["meta"].items():
        print(f"{k}: {v}")

    print("\n=== VALIDACIÓN ===")
    for k, v in parsed["validation"].items():
        print(f"{k}: {v}")

    print(f"\nExcel generado en: {excel_path}")
    print(f"CSV generado en:   {csv_path}")


if __name__ == "__main__":
    main()