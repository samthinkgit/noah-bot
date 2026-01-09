from typing import List
import json
from pathlib import Path
from typing import Optional


class DiscordChart:
    """
    Utility class to generate Discord-friendly tables using code blocks.
    """

    def __init__(self, headers: List[str]):
        self.headers = headers
        self.rows: List[List[str]] = []

    def add_row(self, row: List[str]) -> None:
        """
        Add a row to the table.

        Args:
            row (List[str]): Row values as strings.
        """
        self.rows.append(row)

    def _column_widths(self) -> List[int]:
        """
        Calculate max width for each column.
        """
        widths = [len(h) for h in self.headers]

        for row in self.rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        return widths

    def render(self) -> str:
        """
        Render the table as a Discord code block.

        Returns:
            str: Formatted table.
        """
        widths = self._column_widths()

        def format_row(row: List[str]) -> str:
            return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

        header = format_row(self.headers)
        separator = "-+-".join("-" * w for w in widths)
        body = "\n".join(format_row(r) for r in self.rows)

        table = f"{header}\n{separator}\n{body}"

        return f"```{table}```"


class UserEmojiManager:
    """
    Manages per-user emojis stored in a JSON file.
    """

    def __init__(self, file_path: str = "user_emojis.json"):
        self.file_path = Path(file_path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.file_path.exists():
            return {}

        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def _save(self) -> None:
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def set_emoji(self, user_id: int, emoji: str) -> None:
        """
        Assign an emoji to a user.
        """
        self._data[str(user_id)] = emoji
        self._save()

    def get_emoji(self, user_id: int) -> Optional[str]:
        """
        Retrieve the emoji for a user.
        """
        return self._data.get(str(user_id))

    def remove_emoji(self, user_id: int) -> bool:
        """
        Remove the emoji assigned to a user.
        """
        key = str(user_id)
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False
