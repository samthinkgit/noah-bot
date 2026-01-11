# steallist.py

from tinydb import TinyDB, Query
from typing import Optional, List, Dict
from pathlib import Path
from datetime import datetime
import discord


def generate_date(dt: Optional[datetime] = None) -> str:
    """
    Generate a formatted date string.

    Format:
        YYYY-MM-DD HH:MM
    """
    if dt is None:
        dt = datetime.now()

    return dt.strftime("%Y-%m-%d %H:%M")


class StealList:
    """
    StealList manager backed by TinyDB.

    Handles both persistence and Discord rendering.
    """

    def __init__(self, db_path: str = "steallist.json"):
        self.db_path = Path(db_path)
        self.db = TinyDB(self.db_path)
        self.records = self.db.table("steals")

    # ---------- INSERT ---------- #

    def add_waifu(
        self,
        owner_id: int,
        owner_name: str,
        target_id: int,
        target_name: str,
        waifu_name: str,
    ) -> int:
        return self.records.insert(
            {
                "owner_id": owner_id,
                "owner_name": owner_name,
                "target_id": target_id,
                "target_name": target_name,
                "waifu_name": waifu_name,
                "created_at": generate_date(),
            }
        )

    # ---------- INTERNAL ---------- #

    def _attach_id(self, doc) -> Dict:
        data = dict(doc)
        data["id"] = doc.doc_id
        return data

    # ---------- GETTERS ---------- #

    def get_by_owner(self, owner_id: int) -> List[Dict]:
        Steal = Query()
        return [
            self._attach_id(d) for d in self.records.search(Steal.owner_id == owner_id)
        ]

    def get_by_target(self, target_id: int) -> List[Dict]:
        Steal = Query()
        return [
            self._attach_id(d)
            for d in self.records.search(Steal.target_id == target_id)
        ]

    def get_by_id(self, record_id: int) -> Optional[Dict]:
        doc = self.records.get(doc_id=record_id)
        return self._attach_id(doc) if doc else None

    # ---------- DELETE ---------- #

    def remove_by_id(self, record_id: int) -> bool:
        if self.records.contains(doc_id=record_id):
            self.records.remove(doc_ids=[record_id])
            return True
        return False

    def clear_owner(self, owner_id: int) -> int:
        Steal = Query()
        to_delete = self.records.search(Steal.owner_id == owner_id)
        ids = [d.doc_id for d in to_delete]

        if ids:
            self.records.remove(doc_ids=ids)

        return len(ids)

    # ---------- DISCORD RENDER ---------- #

    def render_embed(
        self,
        records: List[Dict],
        title: str,
        subtitle: str,
    ) -> discord.Embed:
        """
        Render a Discord embed that looks like a table.
        """

        embed = discord.Embed(
            title=title,
            description=subtitle,
            color=discord.Color.dark_purple(),
        )

        if not records:
            embed.description += "\n\n_No waifus found._"
            return embed

        ids = []
        waifus = []
        from_users = []

        for r in records:
            ids.append(str(r["id"]))
            waifus.append(r["waifu_name"])
            from_users.append(r["target_name"])

        embed.add_field(name="ID", value="\n".join(ids), inline=True)
        embed.add_field(name="Waifu", value="\n".join(waifus), inline=True)
        embed.add_field(name="From", value="\n".join(from_users), inline=True)

        embed.set_footer(text=f"Total: {len(records)} waifus")

        return embed
