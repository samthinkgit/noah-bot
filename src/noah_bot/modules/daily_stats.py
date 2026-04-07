import json
from datetime import datetime
from pathlib import Path
from typing import Any


def local_now() -> datetime:
    return datetime.now().astimezone()


def current_day_key(now: datetime | None = None) -> str:
    current = now or local_now()
    return current.date().isoformat()


def _seconds_since_local_midnight(moment: datetime) -> int:
    local_moment = moment.astimezone()
    start_of_day = local_moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, int((local_moment - start_of_day).total_seconds()))


def overlap_seconds_for_current_day(
    started_at_iso: str | None,
    ended_at_iso: str | None = None,
) -> int:
    if not started_at_iso:
        return 0

    try:
        started_at = datetime.fromisoformat(started_at_iso)
    except ValueError:
        return 0

    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=local_now().tzinfo)

    if ended_at_iso:
        try:
            ended_at = datetime.fromisoformat(ended_at_iso)
        except ValueError:
            ended_at = local_now()
    else:
        ended_at = local_now()

    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=local_now().tzinfo)

    ended_local = ended_at.astimezone()
    started_local = started_at.astimezone(ended_local.tzinfo)
    start_of_day = ended_local.replace(hour=0, minute=0, second=0, microsecond=0)
    overlap_start = max(started_local, start_of_day)
    overlap_end = ended_local

    if overlap_end <= overlap_start:
        return 0

    overlap_seconds = int((overlap_end - overlap_start).total_seconds())
    return min(overlap_seconds, _seconds_since_local_midnight(ended_local))


class DailyStatsManager:
    def __init__(self, json_path: str = "daily_stats.json"):
        self.json_path = Path(json_path)
        self._state = self._load()
        self._guilds: dict[str, dict[str, Any]] = self._state["guilds"]

    def _default_state(self) -> dict[str, Any]:
        return {
            "date": current_day_key(),
            "guilds": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.json_path.exists():
            return self._default_state()

        try:
            with self.json_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError):
            return self._default_state()

        if not isinstance(payload, dict):
            return self._default_state()

        date_value = payload.get("date")
        guilds = payload.get("guilds")
        return {
            "date": date_value if isinstance(date_value, str) and date_value else current_day_key(),
            "guilds": guilds if isinstance(guilds, dict) else {},
        }

    def _save(self) -> None:
        with self.json_path.open("w", encoding="utf-8") as file:
            json.dump(self._state, file, indent=2, ensure_ascii=False)

    def _ensure_current_day(self) -> None:
        today = current_day_key()
        if self._state.get("date") == today:
            return

        self._state = self._default_state()
        self._guilds = self._state["guilds"]
        self._save()

    def _guild_key(self, guild_id: int) -> str:
        return str(guild_id)

    def _user_key(self, user_id: int) -> str:
        return str(user_id)

    def _ensure_guild(self, guild_id: int, guild_name: str) -> dict[str, Any]:
        self._ensure_current_day()
        guild = self._guilds.setdefault(
            self._guild_key(guild_id),
            {
                "guild_id": guild_id,
                "guild_name": guild_name,
                "users": {},
                "updated_at": None,
            },
        )
        guild["guild_name"] = guild_name
        guild["updated_at"] = local_now().isoformat()
        return guild

    def _ensure_user(
        self,
        guild_id: int,
        guild_name: str,
        user_id: int,
        display_name: str,
    ) -> dict[str, Any]:
        guild = self._ensure_guild(guild_id, guild_name)
        users = guild["users"]
        user = users.setdefault(
            self._user_key(user_id),
            {
                "user_id": user_id,
                "display_name": display_name,
                "messages": 0,
                "vc_seconds": 0,
                "waifu_claims": 0,
                "autogami_uses": 0,
                "updated_at": None,
            },
        )
        user["display_name"] = display_name
        return user

    def increment_messages(
        self,
        guild_id: int,
        guild_name: str,
        user_id: int,
        display_name: str,
        amount: int = 1,
    ) -> None:
        if amount <= 0:
            return

        user = self._ensure_user(guild_id, guild_name, user_id, display_name)
        user["messages"] = int(user.get("messages", 0)) + amount
        user["updated_at"] = local_now().isoformat()
        self._save()

    def add_vc_seconds(
        self,
        guild_id: int,
        guild_name: str,
        user_id: int,
        display_name: str,
        seconds: int,
    ) -> None:
        if seconds <= 0:
            return

        user = self._ensure_user(guild_id, guild_name, user_id, display_name)
        user["vc_seconds"] = int(user.get("vc_seconds", 0)) + int(seconds)
        user["updated_at"] = local_now().isoformat()
        self._save()

    def increment_waifu_claims(
        self,
        guild_id: int,
        guild_name: str,
        user_id: int,
        display_name: str,
        amount: int = 1,
    ) -> None:
        if amount <= 0:
            return

        user = self._ensure_user(guild_id, guild_name, user_id, display_name)
        user["waifu_claims"] = int(user.get("waifu_claims", 0)) + amount
        user["updated_at"] = local_now().isoformat()
        self._save()

    def increment_autogami_uses(
        self,
        guild_id: int,
        guild_name: str,
        user_id: int,
        display_name: str,
        amount: int = 1,
    ) -> None:
        if amount <= 0:
            return

        user = self._ensure_user(guild_id, guild_name, user_id, display_name)
        user["autogami_uses"] = int(user.get("autogami_uses", 0)) + amount
        user["updated_at"] = local_now().isoformat()
        self._save()

    def get_guild_user_stats(self, guild_id: int) -> dict[int, dict[str, Any]]:
        self._ensure_current_day()
        guild = self._guilds.get(self._guild_key(guild_id))
        if not isinstance(guild, dict):
            return {}

        users = guild.get("users")
        if not isinstance(users, dict):
            return {}

        output: dict[int, dict[str, Any]] = {}
        for raw_user_id, payload in users.items():
            if not isinstance(payload, dict):
                continue

            try:
                user_id = int(raw_user_id)
            except ValueError:
                continue

            output[user_id] = dict(payload)

        return output

    def get_user_stats(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        guild_users = self.get_guild_user_stats(guild_id)
        user_stats = guild_users.get(user_id)
        if user_stats is None:
            return None
        return dict(user_stats)

    def get_current_date(self) -> str:
        self._ensure_current_day()
        return str(self._state.get("date") or current_day_key())
