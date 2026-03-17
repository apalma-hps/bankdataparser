from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional, List

import fitz

from parsers.base import BaseBankParser


# =========================================================
# REGEX
# =========================================================

DATE_ONLY_RE = re.compile(r"^\d{2}/[A-Z]{3}$")
SECOND_LINE_RE = re.compile(r"^(\d{2}/[A-Z]{3})\s+([A-Z0-9]{2,4})\s+(.*)$")
AMOUNT_RE = re.compile(r"[\d,]+\.\d{2}")


# =========================================================
# MODELOS
# =========================================================

@dataclass
class Transaction:
    page: int
    oper_date: str
    liq_date: str
    code: str
    description: str
    reference: str
    movement_type: str
    amount: Decimal
    charge: Optional[Decimal]
    credit: Optional[Decimal]
    operation_balance: Optional[Decimal]
    liquidation_balance: Optional[Decimal]


@dataclass
class StatementMeta:
    bank: str
    account: Optional[str]
    client_number: Optional[str]
    clabe: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    opening_balance: Decimal
    total_deposits_pdf: Decimal
    total_withdrawals_pdf: Decimal
    closing_balance: Decimal
    currency: Optional[str]
    product_name: Optional[str]
    layout_version: str


# =========================================================
# HELPERS
# =========================================================

def parse_money(text: str) -> Decimal:
    clean = text.replace("$", "").replace(",", "").strip()
    return Decimal(clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_date_bbva_short(text: str, year: str = "2026") -> str:
    months = {
        "ENE": "01",
        "FEB": "02",
        "MAR": "03",
        "ABR": "04",
        "MAY": "05",
        "JUN": "06",
        "JUL": "07",
        "AGO": "08",
        "SEP": "09",
        "OCT": "10",
        "NOV": "11",
        "DIC": "12",
    }
    dd, mon = text.split("/")
    return f"{year}-{months[mon]}-{dd}"


def parse_date_bbva_full(text: str) -> str:
    dd, mm, yyyy = text.split("/")
    return f"{yyyy}-{mm}-{dd}"


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def decimal_to_float(value):
    return float(value) if value is not None else None


# =========================================================
# PARSER
# =========================================================

class BBVAParserV1(BaseBankParser):
    bank_code = "bbva"
    bank_name = "BBVA"
    layout_version = "bbva_maestra_pyme_v1"

    def parse(self, pdf_path: str | Path) -> dict:
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            raise FileNotFoundError(f"No existe el archivo: {pdf_path}")

        doc = fitz.open(pdf_path)
        pages_lines = self._extract_pages_lines(doc)
        full_text = "\n".join(
            "\n".join(line["text"] for line in lines)
            for _, lines, _ in pages_lines
        )

        meta = self._extract_meta(full_text)
        year = meta.period_start[:4] if meta.period_start else "2026"
        transactions = self._extract_transactions(pages_lines, year)
        validation = self._validate(meta, transactions)

        return {
            "meta": asdict(meta),
            "transactions": [self._tx_to_dict(tx) for tx in transactions],
            "validation": validation,
        }

    # =====================================================
    # EXTRACCIÓN GENERAL
    # =====================================================

    def _extract_pages_lines(self, doc) -> List[tuple[int, List[dict], dict]]:
        pages_lines = []

        for page_num, page in enumerate(doc, start=1):
            lines_by_position = defaultdict(list)

            for x0, y0, x1, y1, text, block_no, line_no, word_no in page.get_text("words"):
                lines_by_position[(block_no, line_no)].append(
                    {
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "y1": y1,
                        "text": text,
                        "word_no": word_no,
                    }
                )

            line_items = []
            for _, words in sorted(
                lines_by_position.items(),
                key=lambda item: (
                    min(word["y0"] for word in item[1]),
                    min(word["x0"] for word in item[1]),
                ),
            ):
                words = sorted(words, key=lambda word: word["word_no"])
                text = normalize_spaces(" ".join(word["text"] for word in words))
                if not text:
                    continue
                line_items.append({"text": text, "words": words})

            pages_lines.append((page_num, line_items, self._extract_columns(line_items)))

        return pages_lines

    def _extract_columns(self, line_items: List[dict]) -> dict:
        headers = {}

        for line in line_items:
            token = line["text"].upper()
            if token not in {"CARGOS", "ABONOS", "OPERACIÓN", "LIQUIDACIÓN"}:
                continue

            word = line["words"][0]
            headers.setdefault(token, (word["x0"] + word["x1"]) / 2)

        return {
            "charge": headers.get("CARGOS"),
            "credit": headers.get("ABONOS"),
            "operation_balance": headers.get("OPERACIÓN"),
            "liquidation_balance": headers.get("LIQUIDACIÓN"),
        }

    def _extract_meta(self, full_text: str) -> StatementMeta:
        period_match = re.search(
            r"Periodo\s+DEL (\d{2}/\d{2}/\d{4})\s+AL (\d{2}/\d{2}/\d{4})",
            full_text
        )
        account_match = re.search(r"No\.\s+de Cuenta\s+(\d+)", full_text)
        client_match = re.search(r"No\.\s+de Cliente\s+([A-Z0-9]+)", full_text)
        clabe_match = re.search(r"No\.\s+Cuenta CLABE\s+(\d+)", full_text)
        product_match = re.search(
            r"(MAESTRA PYME BBVA|MAESTRA [A-ZÁÉÍÓÚ ]+ BBVA)",
            full_text
        )
        currency_match = re.search(
            r"(Moneda Nacional|MONEDA NACIONAL|DOLARES)",
            full_text
        )

        opening_match = re.search(
            r"Saldo de Liquidación Inicial\s+([\d,]+\.\d{2})",
            full_text
        )
        deposits_match = re.search(
            r"Depósitos / Abonos \(\+\)\s+\d+\s+([\d,]+\.\d{2})",
            full_text
        )
        withdrawals_match = re.search(
            r"Retiros / Cargos \(-\)\s+\d+\s+([\d,]+\.\d{2})",
            full_text
        )
        closing_match = re.search(
            r"Saldo Final \(\+\)\s+([\d,]+\.\d{2})",
            full_text
        )

        if not all([opening_match, deposits_match, withdrawals_match, closing_match]):
            raise ValueError("No pude extraer el resumen principal de BBVA.")

        return StatementMeta(
            bank=self.bank_name,
            account=account_match.group(1) if account_match else None,
            client_number=client_match.group(1) if client_match else None,
            clabe=clabe_match.group(1) if clabe_match else None,
            period_start=parse_date_bbva_full(period_match.group(1)) if period_match else None,
            period_end=parse_date_bbva_full(period_match.group(2)) if period_match else None,
            opening_balance=parse_money(opening_match.group(1)),
            total_deposits_pdf=parse_money(deposits_match.group(1)),
            total_withdrawals_pdf=parse_money(withdrawals_match.group(1)),
            closing_balance=parse_money(closing_match.group(1)),
            currency=currency_match.group(1) if currency_match else None,
            product_name=product_match.group(1) if product_match else None,
            layout_version=self.layout_version,
        )

    # =====================================================
    # DETALLE DE MOVIMIENTOS
    # =====================================================

    def _extract_transactions(
        self,
        pages_lines: List[tuple[int, List[dict], dict]],
        year: str
    ) -> List[Transaction]:
        in_detail = False
        raw_blocks: List[Transaction] = []

        current = None

        def flush_current():
            nonlocal current
            if current is None:
                return

            parsed = self._finalize_block(current, year)
            if parsed:
                raw_blocks.append(parsed)

            current = None

        for page_num, lines, columns in pages_lines:
            idx = 0

            while idx < len(lines):
                line_item = lines[idx]
                line = line_item["text"]

                if "Detalle de Movimientos Realizados" in line:
                    in_detail = True
                    idx += 1
                    continue

                if not in_detail:
                    idx += 1
                    continue

                if line.startswith("Total de Movimientos"):
                    flush_current()
                    in_detail = False
                    idx += 1
                    continue

                if self._is_noise(line):
                    idx += 1
                    continue

                # Detecta inicio real de movimiento BBVA:
                # Línea 1: solo fecha oper, ej. 02/FEB
                # Línea 2: fecha liq + código + descripción inicial
                if DATE_ONLY_RE.match(line):
                    if idx + 1 < len(lines):
                        next_line_item = lines[idx + 1]
                        next_line = next_line_item["text"]

                        if not self._is_noise(next_line):
                            m2 = SECOND_LINE_RE.match(next_line)
                            if m2:
                                flush_current()

                                trimmed_words = next_line_item["words"][2:]
                                trimmed_text = normalize_spaces(
                                    " ".join(word["text"] for word in trimmed_words)
                                )

                                current = {
                                    "page": page_num,
                                    "columns": columns,
                                    "oper_date_raw": line,
                                    "liq_date_raw": m2.group(1),
                                    "code": m2.group(2),
                                    "lines": [trimmed_text],
                                    "line_items": [
                                        {
                                            "text": trimmed_text,
                                            "words": trimmed_words,
                                        }
                                    ],
                                }

                                idx += 2
                                continue

                if current is not None:
                    current["lines"].append(line)
                    current["line_items"].append(line_item)

                idx += 1

        flush_current()
        return raw_blocks

    def _finalize_block(self, block: dict, year: str) -> Optional[Transaction]:
        text = " ".join(block["lines"])
        text = normalize_spaces(text)

        amount_entries = self._extract_amount_entries(
            block["line_items"],
            block["columns"],
        )
        if not amount_entries:
            return None

        charge_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] == "charge"
        ]
        credit_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] == "credit"
        ]
        operation_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] == "operation_balance"
        ]
        liquidation_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] == "liquidation_balance"
        ]
        unclassified_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] is None
        ]

        charge = charge_entries[0] if charge_entries else None
        credit = credit_entries[0] if credit_entries else None
        amount = charge or credit or (unclassified_entries[0] if unclassified_entries else None)
        op_balance = operation_entries[-1] if operation_entries else None
        liq_balance = liquidation_entries[-1] if liquidation_entries else None

        if amount is None:
            return None

        if credit is not None and charge is None:
            movement_type = "deposit"
        elif charge is not None and credit is None:
            movement_type = "withdrawal"
        else:
            movement_type = self._infer_type(block["code"], text)

        cleaned_words = []
        for line_item in block["line_items"]:
            for word in line_item["words"]:
                if AMOUNT_RE.fullmatch(word["text"]):
                    continue
                cleaned_words.append(word["text"])
        cleaned_text = normalize_spaces(" ".join(cleaned_words))

        reference = self._extract_reference(cleaned_text)

        return Transaction(
            page=block["page"],
            oper_date=parse_date_bbva_short(block["oper_date_raw"], year),
            liq_date=parse_date_bbva_short(block["liq_date_raw"], year),
            code=block["code"],
            description=cleaned_text,
            reference=reference,
            movement_type=movement_type,
            amount=amount,
            charge=charge,
            credit=credit,
            operation_balance=op_balance,
            liquidation_balance=liq_balance,
        )

    def _extract_amount_entries(self, line_items: List[dict], columns: dict) -> List[dict]:
        amount_entries = []

        for line_item in line_items:
            for word in line_item["words"]:
                if not AMOUNT_RE.fullmatch(word["text"]):
                    continue

                x_center = (word["x0"] + word["x1"]) / 2
                amount_entries.append(
                    {
                        "text": word["text"],
                        "column": self._classify_amount_column(x_center, columns),
                    }
                )

        return amount_entries

    def _classify_amount_column(self, x_center: float, columns: dict) -> Optional[str]:
        candidates = [
            (abs(x_center - column_x), column_name)
            for column_name, column_x in columns.items()
            if column_x is not None
        ]

        if not candidates:
            return None

        return min(candidates)[1]

    # =====================================================
    # HEURÍSTICAS
    # =====================================================

    def _infer_type(self, code: str, text: str) -> str:
        deposit_codes = {"T20", "P14"}
        withdrawal_codes = {"T17", "X01", "A15", "G30", "S39", "S40", "P31"}

        upper = text.upper()

        if code in deposit_codes:
            return "deposit"

        if code in withdrawal_codes:
            return "withdrawal"

        if "RECIBIDO" in upper or "ABONO" in upper:
            return "deposit"

        if "ENVIADO" in upper or "PAGO" in upper or "IVA" in upper:
            return "withdrawal"

        return "unknown"

    def _extract_reference(self, text: str) -> str:
        m = re.search(r"(Ref\.\s*[A-Z0-9*]+)", text, re.IGNORECASE)
        return m.group(1) if m else ""

    def _is_noise(self, line: str) -> bool:
        fixed_noise = {
            "( - )",
            "( + )",
            "FECHA",
            "SALDO",
            "OPER",
            "LIQ",
            "COD. DESCRIPCIÓN",
            "REFERENCIA",
            "CARGOS",
            "ABONOS",
            "OPERACIÓN",
            "LIQUIDACIÓN",
            "Información Financiera",
            "MONEDA NACIONAL",
            "DOMICILIO FISCAL",
        }

        noise_starts = (
            "No. Cuenta",
            "No. Cliente",
            "Estado de Cuenta",
            "PAGINA",
            "MAESTRA PYME BBVA",
            "BBVA MEXICO",
            "Av. Paseo de la Reforma",
            "La GAT Real",
            "CALLE ",
            "POLANCO ",
            "MIGUEL HIDALGO",
            "CIUDAD DE MEXICO",
            "SUCURSAL:",
            "DIRECCION:",
            "Tiene 90 días naturales",
            "Estimado Cliente",
            "Su Estado de Cuenta ha sido modificado",
            "También le informamos que",
            "el cual puede consultarlo",
            "Con BBVA adelante.",
            "100 %",
        )

        if line in fixed_noise:
            return True

        return any(line.startswith(prefix) for prefix in noise_starts)

    # =====================================================
    # VALIDACIÓN
    # =====================================================

    def _validate(self, meta: StatementMeta, transactions: List[Transaction]) -> dict:
        deposits_calc = sum(
            (tx.credit or Decimal("0.00") for tx in transactions),
            Decimal("0.00")
        ).quantize(Decimal("0.01"))

        withdrawals_calc = sum(
            (tx.charge or Decimal("0.00") for tx in transactions),
            Decimal("0.00")
        ).quantize(Decimal("0.01"))

        closing_candidates = [
            tx.liquidation_balance
            for tx in transactions
            if tx.liquidation_balance is not None
        ]
        closing_calc = closing_candidates[-1] if closing_candidates else meta.opening_balance

        unknown_count = sum(1 for tx in transactions if tx.movement_type == "unknown")

        return {
            "transaction_count": len(transactions),
            "unknown_type_count": unknown_count,
            "calculated_deposits": float(deposits_calc),
            "pdf_deposits": float(meta.total_deposits_pdf),
            "deposits_match": deposits_calc == meta.total_deposits_pdf,
            "calculated_withdrawals": float(withdrawals_calc),
            "pdf_withdrawals": float(meta.total_withdrawals_pdf),
            "withdrawals_match": withdrawals_calc == meta.total_withdrawals_pdf,
            "calculated_closing_balance": float(closing_calc),
            "pdf_closing_balance": float(meta.closing_balance),
            "closing_match": closing_calc == meta.closing_balance,
            "all_ok": (
                deposits_calc == meta.total_deposits_pdf
                and withdrawals_calc == meta.total_withdrawals_pdf
                and closing_calc == meta.closing_balance
                and unknown_count == 0
            ),
        }

    # =====================================================
    # SERIALIZACIÓN
    # =====================================================

    def _tx_to_dict(self, tx: Transaction) -> dict:
        return {
            "page": tx.page,
            "oper_date": tx.oper_date,
            "liq_date": tx.liq_date,
            "code": tx.code,
            "description": tx.description,
            "reference": tx.reference,
            "movement_type": tx.movement_type,
            "amount": decimal_to_float(tx.amount),
            "charge": decimal_to_float(tx.charge),
            "credit": decimal_to_float(tx.credit),
            "operation_balance": decimal_to_float(tx.operation_balance),
            "liquidation_balance": decimal_to_float(tx.liquidation_balance),
        }
