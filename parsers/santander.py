from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import List, Optional

import fitz

from parsers.base import BaseBankParser


DATE_FOLIO_RE = re.compile(r"^(\d{2}-[A-Z]{3}-\d{4})\s+([A-Z0-9]+)\s+(.*)$")
MONEY_ONLY_RE = re.compile(r"^\$?[\d,]+\.\d{2}$")

MONTHS = {
    "ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AGO": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12",
}


@dataclass
class Transaction:
    page: int
    date: str
    folio: str
    description: str
    amount_pdf: Decimal
    movement_type: str
    deposit: Optional[Decimal]
    withdrawal: Optional[Decimal]
    balance: Decimal


@dataclass
class StatementMeta:
    bank: str
    account: Optional[str]
    clabe: Optional[str]
    period_start: Optional[str]
    period_end: Optional[str]
    opening_balance: Decimal
    total_deposits_pdf: Decimal
    total_withdrawals_pdf: Decimal
    closing_balance: Decimal
    currency: Optional[str]
    layout_version: str


def parse_money(text: str) -> Decimal:
    clean = text.replace("$", "").replace(",", "").strip()
    return Decimal(clean).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_date_santander(text: str) -> str:
    dd, mon, yyyy = text.split("-")
    return f"{yyyy}-{MONTHS[mon]}-{dd}"


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def decimal_to_float(value):
    return float(value) if value is not None else None


class SantanderParserV1(BaseBankParser):
    bank_code = "santander"
    bank_name = "Santander"
    layout_version = "santander_pyme_v1"

    def parse(self, pdf_path: str | Path) -> dict:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"No existe el archivo: {pdf_path}")

        doc = fitz.open(pdf_path)
        pages_text = self._extract_pages_text(doc)
        pages_lines = self._extract_pages_lines(doc)

        meta = self._extract_meta(pages_text)
        transactions = self._extract_transactions(pages_lines, meta.opening_balance)
        validation = self._validate(meta, transactions)

        return {
            "meta": asdict(meta),
            "transactions": [self._tx_to_dict(tx) for tx in transactions],
            "validation": validation,
        }

    def _extract_pages_text(self, doc):
        return [
            (page_num, page.get_text("text"))
            for page_num, page in enumerate(doc, start=1)
        ]

    def _extract_pages_lines(self, doc):
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

    def _extract_columns(self, line_items):
        headers = {}

        for line in line_items:
            token = line["text"].upper()
            if token not in {"DEPOSITO", "RETIRO", "SALDO"}:
                continue

            word = line["words"][0]
            headers.setdefault(token, (word["x0"] + word["x1"]) / 2)

        return {
            "deposit": headers.get("DEPOSITO"),
            "withdrawal": headers.get("RETIRO"),
            "balance": headers.get("SALDO"),
        }

    def _extract_meta(self, pages_text):
        full_text = "\n".join(text for _, text in pages_text)

        account_match = re.search(r"CUENTA SANTANDER PYME\s+(\d{2}-\d+-\d)", full_text)
        clabe_match = re.search(r"CUENTA CLABE:\s*(\d+)", full_text)
        period_match = re.search(r"DEL (\d{2}-[A-Z]{3}-\d{4})\s+AL\s+(\d{2}-[A-Z]{3}-\d{4})", full_text)

        summary_match = re.search(
            r"Saldo inicial\s*\+Depósitos\s*- Retiros\s*= Saldo final\s*"
            r"([\d,]+\.\d{2})\s*"
            r"([\d,]+\.\d{2})\s*"
            r"([\d,]+\.\d{2})\s*"
            r"([\d,]+\.\d{2})",
            full_text,
            re.DOTALL
        )

        if not summary_match:
            raise ValueError("No pude extraer el resumen principal de Santander.")

        return StatementMeta(
            bank=self.bank_name,
            account=account_match.group(1) if account_match else None,
            clabe=clabe_match.group(1) if clabe_match else None,
            period_start=parse_date_santander(period_match.group(1)) if period_match else None,
            period_end=parse_date_santander(period_match.group(2)) if period_match else None,
            opening_balance=parse_money(summary_match.group(1)),
            total_deposits_pdf=parse_money(summary_match.group(2)),
            total_withdrawals_pdf=parse_money(summary_match.group(3)),
            closing_balance=parse_money(summary_match.group(4)),
            currency="MXN",
            layout_version=self.layout_version,
        )

    def _extract_transactions(self, pages_lines, opening_balance):
        in_section = False
        current = None
        raw_transactions = []

        def flush_current():
            nonlocal current
            if current is None:
                return
            raw_transactions.append(self._finalize_transaction(current))
            current = None

        for page_num, lines, columns in pages_lines:
            for line_item in lines:
                line = line_item["text"]
                if line == "Detalle de movimientos cuenta de cheques.":
                    in_section = True
                    continue

                if not in_section:
                    continue

                if line.startswith("Detalles de movimientos Dinero Creciente Santander.") or line.startswith("Información fiscal."):
                    flush_current()
                    in_section = False
                    continue

                if line in {"FECHA", "FOLIO", "DESCRIPCION", "DEPOSITO", "RETIRO", "SALDO"}:
                    continue

                if line.startswith("SALDO FINAL DEL PERIODO ANTERIOR"):
                    continue

                if MONEY_ONLY_RE.match(line) and current is None:
                    continue

                if line == "TOTAL":
                    flush_current()
                    continue

                m = DATE_FOLIO_RE.match(line)
                if m:
                    flush_current()
                    current = {
                        "page": page_num,
                        "columns": columns,
                        "date_raw": m.group(1),
                        "folio": m.group(2),
                        "desc_lines": [m.group(3)],
                        "line_items": [],
                    }
                    continue

                if current is None:
                    continue

                current["line_items"].append(line_item)
                if not MONEY_ONLY_RE.match(line):
                    current["desc_lines"].append(line)

        flush_current()

        transactions = []
        prev_balance = opening_balance

        for item in raw_transactions:
            current_balance = item["balance"]
            delta = (current_balance - prev_balance).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            movement_type = item["movement_type"]
            deposit = item["deposit"]
            withdrawal = item["withdrawal"]

            expected_delta = deposit or Decimal("0.00")
            if withdrawal is not None:
                expected_delta = -withdrawal

            if delta != expected_delta:
                raise ValueError(
                    "Monto inconsistente Santander en "
                    f"página {item['page']}, folio {item['folio']}: "
                    f"monto={item['amount_pdf']} {movement_type}, delta_saldo={delta}"
                )

            transactions.append(Transaction(
                page=item["page"],
                date=parse_date_santander(item["date_raw"]),
                folio=item["folio"],
                description=item["description"],
                amount_pdf=item["amount_pdf"],
                movement_type=movement_type,
                deposit=deposit,
                withdrawal=withdrawal,
                balance=current_balance,
            ))
            prev_balance = current_balance

        return transactions

    def _finalize_transaction(self, current):
        amount_entries = self._extract_amount_entries(current["line_items"], current["columns"])

        deposit_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] == "deposit"
        ]
        withdrawal_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] == "withdrawal"
        ]
        balance_entries = [
            parse_money(entry["text"])
            for entry in amount_entries
            if entry["column"] == "balance"
        ]

        if not balance_entries:
            raise ValueError(
                f"Movimiento sin saldo Santander en página {current['page']}, "
                f"folio {current['folio']}"
            )

        if deposit_entries and withdrawal_entries:
            raise ValueError(
                f"Movimiento ambiguo Santander en página {current['page']}, "
                f"folio {current['folio']}: detecté depósito y retiro"
            )

        if deposit_entries:
            amount_pdf = deposit_entries[0]
            movement_type = "deposit"
            deposit = amount_pdf
            withdrawal = None
        elif withdrawal_entries:
            amount_pdf = withdrawal_entries[0]
            movement_type = "withdrawal"
            deposit = None
            withdrawal = amount_pdf
        else:
            raise ValueError(
                f"Movimiento sin monto clasificado Santander en página {current['page']}, "
                f"folio {current['folio']}"
            )

        return {
            "page": current["page"],
            "date_raw": current["date_raw"],
            "folio": current["folio"],
            "description": normalize_spaces(" ".join(current["desc_lines"])),
            "amount_pdf": amount_pdf,
            "movement_type": movement_type,
            "deposit": deposit,
            "withdrawal": withdrawal,
            "balance": balance_entries[-1],
        }

    def _extract_amount_entries(self, line_items, columns):
        amount_entries = []

        for line_item in line_items:
            for word in line_item["words"]:
                if not MONEY_ONLY_RE.fullmatch(word["text"]):
                    continue

                x_center = (word["x0"] + word["x1"]) / 2
                amount_entries.append(
                    {
                        "text": word["text"],
                        "column": self._classify_amount_column(x_center, columns),
                    }
                )

        return amount_entries

    def _classify_amount_column(self, x_center, columns):
        candidates = [
            (abs(x_center - column_x), column_name)
            for column_name, column_x in columns.items()
            if column_x is not None
        ]

        if not candidates:
            return None

        return min(candidates)[1]

    def _validate(self, meta, transactions):
        deposits_calc = sum((tx.deposit or Decimal("0.00")) for tx in transactions).quantize(Decimal("0.01"))
        withdrawals_calc = sum((tx.withdrawal or Decimal("0.00")) for tx in transactions).quantize(Decimal("0.01"))
        closing_calc = (transactions[-1].balance if transactions else meta.opening_balance).quantize(Decimal("0.01"))

        return {
            "transaction_count": len(transactions),
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
            ),
        }

    def _tx_to_dict(self, tx):
        return {
            "page": tx.page,
            "date": tx.date,
            "folio": tx.folio,
            "description": tx.description,
            "amount_pdf": decimal_to_float(tx.amount_pdf),
            "movement_type": tx.movement_type,
            "deposit": decimal_to_float(tx.deposit),
            "withdrawal": decimal_to_float(tx.withdrawal),
            "balance": decimal_to_float(tx.balance),
        }
