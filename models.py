from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass
class JobRow:
    excel_row: int
    start_date: str
    task_name: str
    quantity: str
    source_deadline: str
    description: str

@dataclass
class AccountJob:
    username: str
    password: str
    excel_path: Path
    status: str = "Chưa chạy"
    error: Optional[str] = None
