# leaderboard.py

from tinydb import TinyDB, Query
from typing import Optional, List, Dict
from pathlib import Path
from datetime import datetime


def generate_date(dt: Optional[datetime] = None) -> str:
    """
    Generate a formatted date string.

    Format:
        YYYY-MM-DD HH:MM
    """
    if dt is None:
        dt = datetime.now()

    return dt.strftime("%Y-%m-%d %H:%M")


class Leaderboard:
    """
    Leaderboard manager backed by TinyDB.

    Uses TinyDB doc_id as the record unique identifier.
    """

    def __init__(self, db_path: str = "leaderboard.json"):
        self.db_path = Path(db_path)
        self.db = TinyDB(self.db_path)
        self.records = self.db.table("records")

    # ---------- INSERT ---------- #

    def add_record(
        self,
        user_id: int,
        username: str,
        record_time: float,
        created_at: str,
        tag: Optional[str] = None,
    ) -> int:
        """
        Add a new time record.

        Returns:
            int: Record ID (doc_id)
        """
        doc_id = self.records.insert(
            {
                "user_id": user_id,
                "username": username,
                "record_time": round(record_time, 4),
                "created_at": created_at,
                "tag": tag,
            }
        )
        return doc_id

    # ---------- GETTERS ---------- #

    def _attach_id(self, doc) -> Dict:
        """
        Attach TinyDB doc_id to the record dict.
        """
        data = dict(doc)
        data["id"] = doc.doc_id
        return data

    def get_all_records(self) -> List[Dict]:
        return [self._attach_id(d) for d in self.records]

    def get_records_by_user(self, user_id: int) -> List[Dict]:
        Record = Query()
        return [
            self._attach_id(d) for d in self.records.search(Record.user_id == user_id)
        ]

    def get_records_by_tag(self, tag: str) -> List[Dict]:
        Record = Query()
        return [self._attach_id(d) for d in self.records.search(Record.tag == tag)]

    def get_record_by_id(self, record_id: int) -> Optional[Dict]:
        doc = self.records.get(doc_id=record_id)
        return self._attach_id(doc) if doc else None

    def get_best_record(self) -> Optional[Dict]:
        docs = list(self.records)
        if not docs:
            return None
        best = min(docs, key=lambda d: d["record_time"])
        return self._attach_id(best)

    def get_top_n(self, n: int = 10) -> List[Dict]:
        docs = sorted(self.records, key=lambda d: d["record_time"])
        return [self._attach_id(d) for d in docs[:n]]

    # ---------- DELETE ---------- #

    def delete_record_by_id(self, record_id: int) -> bool:
        """
        Delete a record by its ID.

        Returns:
            bool: True if deleted, False if not found.
        """
        if self.records.contains(doc_id=record_id):
            self.records.remove(doc_ids=[record_id])
            return True
        return False

    # ---------- MAINTENANCE ---------- #

    def clear(self) -> None:
        self.records.truncate()
