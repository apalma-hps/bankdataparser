from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseBankParser(ABC):
    bank_code: str
    bank_name: str
    layout_version: str

    @abstractmethod
    def parse(self, pdf_path: str | Path) -> dict:
        raise NotImplementedError