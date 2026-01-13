"""
Waifu Fight Manager (file-based JSON persistence)

This module is Discord-agnostic on purpose: it only manages game state and rules.
You can wire it to any interface later.

Key rules implemented:
- Each user can own exactly one waifu at a time.
- Creating a waifu assigns random stats:
  - Health, Agility, Mana, Recover, Damage: random 5..10
  - All stats cap at 30
- Max health equals Health stat (1:1). Current health starts at max.
- Dodge chance: up to 50% at Agility=30
- Special chance: up to 30% at Mana=30
- Special attack stuns the defender (they cannot attack until recovered again).
- Recover stat sets real-time cooldown between attacks: 60min (low) -> 30min (high)
- When a waifu reaches 0 health: it dies permanently, and its waifu name is globally banned forever.
- sleep: once per day, heals +8 up to max health
- On kill: attacker heals to full and earns 1 pending levelup
- levelup: consumes 1 pending levelup and gives +2 points to a random stat (capped at 30)
- Dev mode: removes cooldown/stun/sleep daily limitation (for debugging)
"""

import json
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional


SCHEMA_VERSION = 2
INCAP_SECONDS = 24 * 60 * 60  # 24 hours


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


@dataclass
class Stats:
    health: int
    agility: int
    mana: int
    recover: int
    damage: int

    def cap_all(self, cap: int = 30) -> None:
        for k in vars(self):
            setattr(self, k, _clamp(getattr(self, k), 0, cap))

    def hit_damage(self) -> int:
        if self.damage <= 12:
            return 1
        if self.damage <= 22:
            return 2
        return 3

    def dodge_chance(self) -> float:
        return (self.agility / 30.0) * 0.5

    def special_chance(self) -> float:
        return (self.mana / 30.0) * 0.3

    def cooldown_seconds(self) -> int:
        r = _clamp(self.recover, 0, 30)
        if r <= 5:
            return 60 * 60
        t = (r - 5) / 25
        return int((60 - 30 * t) * 60)


@dataclass
class Waifu:
    name: str
    image_url: Optional[str]
    special_name: str
    stats: Stats
    current_hp: int

    last_attack_at: Optional[datetime]
    stunned_until: Optional[datetime]
    incapacitated_until: Optional[datetime]

    last_sleep_date: Optional[str]
    pending_levelups: int

    def max_hp(self) -> int:
        return _clamp(self.stats.health, 1, 30)

    def heal_full(self) -> None:
        self.current_hp = self.max_hp()

    def heal(self, amount: int) -> None:
        self.current_hp = _clamp(self.current_hp + amount, 0, self.max_hp())

    def is_stunned(self, now: datetime) -> bool:
        return self.stunned_until and now < self.stunned_until

    def is_incapacitated(self, now: datetime) -> bool:
        return self.incapacitated_until and now < self.incapacitated_until

    def maybe_recover_from_incap(self, now: datetime) -> None:
        if self.incapacitated_until and now >= self.incapacitated_until:
            self.incapacitated_until = None
            self.heal_full()
    
    def is_stunned_now(self) -> bool:
        now = _utc_now()
        return self.is_stunned(now)


class WaifuGameManager:
    def __init__(self, json_path: str, rng: Optional[random.Random] = None) -> None:
        self.json_path = json_path
        self.rng = rng or random.Random()
        self._state = {
            "schema_version": SCHEMA_VERSION,
            "devmode": False,
            "users": {},
        }
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.json_path):
            self._save()
            return
        with open(self.json_path, "r", encoding="utf-8") as f:
            self._state = json.load(f)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.json_path) or ".", exist_ok=True)
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    @property
    def devmode(self) -> bool:
        return bool(self._state.get("devmode", False))

    def get_waifu(self, user_id: str) -> Optional[Waifu]:
        raw = self._state["users"].get(str(user_id))
        if not raw:
            return None
        return self._deserialize_waifu(raw)

    def waifu_set(
        self, user_id: str, waifu_name: str, special_name: str, image_url=None
    ):
        stats = Stats(*(self.rng.randint(5, 10) for _ in range(5)))
        stats.cap_all()

        w = Waifu(
            name=waifu_name.strip(),
            special_name=special_name.strip(),
            image_url=image_url,
            stats=stats,
            current_hp=stats.health,
            last_attack_at=None,
            stunned_until=None,
            incapacitated_until=None,
            last_sleep_date=None,
            pending_levelups=0,
        )

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()
        return {"ok": True}

    def waifu_attack(self, attacker_id: str, defender_id: str, now=None):
        now = now or _utc_now()
        a = self.get_waifu(attacker_id)
        d = self.get_waifu(defender_id)

        if not a or not d:
            return {"ok": False, "error": "MISSING_WAIFU"}

        a.maybe_recover_from_incap(now)
        d.maybe_recover_from_incap(now)

        if not self.devmode:
            if a.is_incapacitated(now):
                return {"ok": False, "error": "ATTACKER_INCAPACITATED"}
            if a.is_stunned(now):
                return {"ok": False, "error": "ATTACKER_STUNNED"}

        if self.rng.random() < d.stats.dodge_chance():
            return {"ok": True, "dodged": True}

        special = self.rng.random() < a.stats.special_chance()
        damage = a.stats.hit_damage()
        d.current_hp -= damage

        if special and not self.devmode:
            d.stunned_until = now + timedelta(seconds=d.stats.cooldown_seconds())

        incapacitated = False
        if d.current_hp <= 0:
            d.current_hp = 0
            d.incapacitated_until = now + timedelta(seconds=INCAP_SECONDS)
            incapacitated = True

            a.heal_full()
            a.pending_levelups += 1

        if not self.devmode:
            a.last_attack_at = now

        self._state["users"][str(attacker_id)] = self._serialize_waifu(a)
        self._state["users"][str(defender_id)] = self._serialize_waifu(d)
        self._save()

        return {
            "ok": True,
            "damage": damage,
            "special": special,
            "incapacitated": incapacitated,
            "defender_hp": d.current_hp,
            "defender_incapacitated_until": _to_iso(d.incapacitated_until),
        }

    def waifu_sleep(self, user_id: str, now=None):
        now = now or _utc_now()
        w = self.get_waifu(user_id)

        if not w:
            return {"ok": False}

        w.maybe_recover_from_incap(now)

        if not self.devmode and w.is_incapacitated(now):
            return {"ok": False, "error": "INCAPACITATED"}

        today = now.date().isoformat()
        if not self.devmode and w.last_sleep_date == today:
            return {"ok": False, "error": "ALREADY_SLEPT"}

        w.heal(8)
        w.last_sleep_date = today

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {"ok": True, "hp": w.current_hp}

    def waifu_levelup(self, user_id: str):
        w = self.get_waifu(user_id)
        if not w or w.pending_levelups <= 0:
            return {"ok": False}

        stat = self.rng.choice(list(vars(w.stats).keys()))
        setattr(w.stats, stat, _clamp(getattr(w.stats, stat) + 2, 0, 30))
        w.pending_levelups -= 1

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {"ok": True, "stat": stat}

    def _serialize_waifu(self, w: Waifu) -> Dict[str, Any]:
        return {
            "name": w.name,
            "special_name": w.special_name,
            "image_url": w.image_url,
            "stats": asdict(w.stats),
            "current_hp": w.current_hp,
            "last_attack_at": _to_iso(w.last_attack_at),
            "stunned_until": _to_iso(w.stunned_until),
            "incapacitated_until": _to_iso(w.incapacitated_until),
            "last_sleep_date": w.last_sleep_date,
            "pending_levelups": w.pending_levelups,
        }

    def _deserialize_waifu(self, raw: Dict[str, Any]) -> Waifu:
        stats = Stats(**raw["stats"])
        stats.cap_all()

        w = Waifu(
            name=raw["name"],
            special_name=raw["special_name"],
            image_url=raw.get("image_url"),
            stats=stats,
            current_hp=raw["current_hp"],
            last_attack_at=_from_iso(raw["last_attack_at"]),
            stunned_until=_from_iso(raw["stunned_until"]),
            incapacitated_until=_from_iso(raw.get("incapacitated_until")),
            last_sleep_date=raw.get("last_sleep_date"),
            pending_levelups=raw.get("pending_levelups", 0),
        )
        w.current_hp = _clamp(w.current_hp, 0, w.max_hp())
        return w
