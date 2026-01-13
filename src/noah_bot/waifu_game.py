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

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


SCHEMA_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # datetime.fromisoformat supports "+00:00" offsets
    return datetime.fromisoformat(s)


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


@dataclass
class Stats:
    health: int  # also max HP
    agility: int  # dodge chance (up to 50%)
    mana: int  # special chance (up to 30%)
    recover: int  # cooldown (60 -> 30 min)
    damage: int  # determines hit damage (1..3 derived)

    def cap_all(self, cap: int = 30) -> None:
        self.health = _clamp(self.health, 0, cap)
        self.agility = _clamp(self.agility, 0, cap)
        self.mana = _clamp(self.mana, 0, cap)
        self.recover = _clamp(self.recover, 0, cap)
        self.damage = _clamp(self.damage, 0, cap)

    def hit_damage(self) -> int:
        """
        Convert damage points (0..30) into actual damage per hit.
        - Around 5..10 => 1
        - Mid => 2
        - High (near 30) => 3
        """
        if self.damage <= 12:
            return 1
        if self.damage <= 22:
            return 2
        return 3

    def dodge_chance(self) -> float:
        # 0..30 => 0..0.5
        return (_clamp(self.agility, 0, 30) / 30.0) * 0.5

    def special_chance(self) -> float:
        # 0..30 => 0..0.3
        return (_clamp(self.mana, 0, 30) / 30.0) * 0.3

    def cooldown_seconds(self) -> int:
        """
        Recover points map to cooldown in minutes between 60 (worst) and 30 (best).
        Linear mapping for 5..30.
        """
        r = _clamp(self.recover, 0, 30)
        # If recover is very low, treat as worst.
        if r <= 5:
            minutes = 60
        else:
            # r=5 -> 60, r=30 -> 30
            t = (r - 5) / (30 - 5)
            minutes = int(round(60 - (30 * t)))
            minutes = _clamp(minutes, 30, 60)
        return minutes * 60


@dataclass
class Waifu:
    name: str
    image_url: Optional[str]
    special_name: str
    stats: Stats
    current_hp: int
    alive: bool

    # Timers / cooldowns
    last_attack_at: Optional[datetime]
    stunned_until: Optional[datetime]

    # Daily action
    last_sleep_date: Optional[str]  # YYYY-MM-DD

    # Rewards
    pending_levelups: int

    def max_hp(self) -> int:
        return _clamp(self.stats.health, 1, 30)

    def heal_full(self) -> None:
        self.current_hp = self.max_hp()

    def heal(self, amount: int) -> None:
        self.current_hp = _clamp(self.current_hp + amount, 0, self.max_hp())

    def is_stunned(self, now: datetime) -> bool:
        if not self.stunned_until:
            return False
        return now < self.stunned_until

    def is_stunned_now(self) -> bool:
        return self.is_stunned(_utc_now())


class WaifuGameManager:
    def __init__(self, json_path: str, rng: Optional[random.Random] = None) -> None:
        self.json_path = json_path
        self.rng = rng or random.Random()
        self._state: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "devmode": False,
            "banned_names": [],  # list[str] lowercased
            "users": {},  # user_id(str) -> waifu dict
        }
        self._load()

    # -----------------------
    # Persistence
    # -----------------------
    def _load(self) -> None:
        if not os.path.exists(self.json_path):
            self._save()
            return
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Minimal migration support
        if data.get("schema_version") != SCHEMA_VERSION:
            # You can extend migrations later; for now just accept if missing.
            data["schema_version"] = SCHEMA_VERSION
        data.setdefault("devmode", False)
        data.setdefault("banned_names", [])
        data.setdefault("users", {})
        self._state = data

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.json_path) or ".", exist_ok=True)
        tmp_path = self.json_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.json_path)

    # -----------------------
    # Public helpers
    # -----------------------
    def set_devmode(self, enabled: bool) -> Dict[str, Any]:
        self._state["devmode"] = bool(enabled)
        self._save()
        return {"ok": True, "devmode": self.devmode}

    @property
    def devmode(self) -> bool:
        return bool(self._state.get("devmode", False))

    def banned_names(self) -> set[str]:
        return set(self._state.get("banned_names", []))

    def get_waifu(self, user_id: str) -> Optional[Waifu]:
        raw = self._state["users"].get(str(user_id))
        if not raw:
            return None
        return self._deserialize_waifu(raw)

    def get_state_snapshot(self) -> Dict[str, Any]:
        """
        Returns the raw JSON-friendly state (safe to show in debug/admin UIs).
        """
        return json.loads(json.dumps(self._state))

    # -----------------------
    # Core actions
    # -----------------------
    def waifu_set(
        self,
        user_id: str,
        waifu_name: str,
        special_name: str,
        image_url=None,
    ) -> Dict[str, Any]:
        """
        Create / overwrite user's waifu (if their previous waifu was alive, it gets replaced).
        Waifu name is globally banned if it has ever died.
        """
        waifu_name = waifu_name.strip()
        special_name = special_name.strip()

        if not waifu_name:
            return {
                "ok": False,
                "error": "INVALID_NAME",
                "message": "Waifu name cannot be empty.",
            }
        if not special_name:
            return {
                "ok": False,
                "error": "INVALID_SPECIAL",
                "message": "Special name cannot be empty.",
            }

        name_key = waifu_name.lower()
        if name_key in self.banned_names():
            return {
                "ok": False,
                "error": "NAME_BANNED",
                "message": "That waifu name is permanently banned because it died before.",
            }

        stats = Stats(
            health=self.rng.randint(5, 10),
            agility=self.rng.randint(5, 10),
            mana=self.rng.randint(5, 10),
            recover=self.rng.randint(5, 10),
            damage=self.rng.randint(5, 10),
        )
        stats.cap_all(30)

        waifu = Waifu(
            name=waifu_name,
            special_name=special_name,
            stats=stats,
            current_hp=_clamp(stats.health, 1, 30),
            alive=True,
            last_attack_at=None,
            stunned_until=None,
            last_sleep_date=None,
            pending_levelups=0,
            image_url=image_url,
        )

        self._state["users"][str(user_id)] = self._serialize_waifu(waifu)
        self._save()

        return {
            "ok": True,
            "user_id": str(user_id),
            "waifu": self._public_waifu_view(waifu),
        }

    def waifu_attack(
        self, attacker_id: str, defender_id: str, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Attack another user's waifu.
        Enforces:
        - both must exist and be alive
        - attacker must not be stunned (unless devmode)
        - attacker must be off cooldown (unless devmode)
        - defender may dodge based on agility
        - special may trigger based on mana, stunning defender
        - killing bans defender waifu name forever and heals attacker to full and gives a pending levelup
        """
        now = now or _utc_now()
        attacker = self.get_waifu(attacker_id)
        defender = self.get_waifu(defender_id)

        if not attacker:
            return {
                "ok": False,
                "error": "NO_ATTACKER",
                "message": "Attacker has no waifu.",
            }
        if not defender:
            return {
                "ok": False,
                "error": "NO_DEFENDER",
                "message": "Defender has no waifu.",
            }
        if not attacker.alive:
            return {
                "ok": False,
                "error": "ATTACKER_DEAD",
                "message": "Attacker waifu is dead.",
            }
        if not defender.alive:
            return {
                "ok": False,
                "error": "DEFENDER_DEAD",
                "message": "Defender waifu is dead.",
            }

        if not self.devmode:
            if attacker.is_stunned(now):
                return {
                    "ok": False,
                    "error": "ATTACKER_STUNNED",
                    "message": "Attacker is stunned and cannot attack yet.",
                    "stunned_until": _to_iso(attacker.stunned_until),
                }

            can_attack, wait_seconds = self._can_attack(attacker, now)
            if not can_attack:
                return {
                    "ok": False,
                    "error": "ON_COOLDOWN",
                    "message": "Attacker is still recovering and cannot attack yet.",
                    "retry_after_seconds": wait_seconds,
                    "cooldown_seconds": attacker.stats.cooldown_seconds(),
                }

        # Defender dodge
        dodged = False
        roll = self.rng.random()
        if roll < defender.stats.dodge_chance():
            dodged = True

        special = False
        damage = 0
        killed = False
        stunned_applied = False

        if not dodged:
            # Special roll (attacker mana)
            if self.rng.random() < attacker.stats.special_chance():
                special = True

            damage = attacker.stats.hit_damage()
            defender.current_hp = _clamp(
                defender.current_hp - damage, 0, defender.max_hp()
            )

            if special and not self.devmode:
                # Special stuns the defender for one defender cooldown cycle (based on defender recover).
                stun_seconds = defender.stats.cooldown_seconds()
                defender.stunned_until = now + _seconds(stun_seconds)
                stunned_applied = True

            if defender.current_hp <= 0:
                defender.alive = False
                killed = True
                self._ban_name(defender.name)

                # Rewards to attacker
                attacker.heal_full()
                attacker.pending_levelups += 1

        # Update attacker cooldown
        if not self.devmode:
            attacker.last_attack_at = now

        # Persist
        self._state["users"][str(attacker_id)] = self._serialize_waifu(attacker)
        self._state["users"][str(defender_id)] = self._serialize_waifu(defender)
        self._save()

        return {
            "ok": True,
            "timestamp": _to_iso(now),
            "attacker_id": str(attacker_id),
            "defender_id": str(defender_id),
            "dodged": dodged,
            "special": special,
            "special_name": attacker.special_name if special else None,
            "damage": damage,
            "defender_hp_after": defender.current_hp,
            "defender_alive_after": defender.alive,
            "stunned_applied": stunned_applied,
            "defender_stunned_until": _to_iso(defender.stunned_until),
            "killed": killed,
            "attacker_pending_levelups": attacker.pending_levelups,
            "attacker_hp_after": attacker.current_hp,
        }

    def waifu_sleep(
        self, user_id: str, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Once per day (unless devmode), heal +8 HP up to max.
        """
        now = now or _utc_now()
        w = self.get_waifu(user_id)
        if not w:
            return {"ok": False, "error": "NO_WAIFU", "message": "User has no waifu."}
        if not w.alive:
            return {"ok": False, "error": "DEAD", "message": "Waifu is dead."}

        today = now.date().isoformat()

        if not self.devmode and w.last_sleep_date == today:
            return {
                "ok": False,
                "error": "ALREADY_SLEPT",
                "message": "Sleep can be used once per day.",
            }

        before = w.current_hp
        w.heal(8)
        w.last_sleep_date = today

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {
            "ok": True,
            "healed": w.current_hp - before,
            "hp_before": before,
            "hp_after": w.current_hp,
            "max_hp": w.max_hp(),
            "date": today,
        }

    def waifu_levelup(self, user_id: str) -> Dict[str, Any]:
        """
        Consume 1 pending levelup and add +2 points to a random stat (capped at 30).
        If health increases, max HP increases; current HP stays the same unless it exceeds new max.
        """
        w = self.get_waifu(user_id)
        if not w:
            return {"ok": False, "error": "NO_WAIFU", "message": "User has no waifu."}
        if not w.alive:
            return {"ok": False, "error": "DEAD", "message": "Waifu is dead."}
        if w.pending_levelups <= 0:
            return {
                "ok": False,
                "error": "NO_LEVELUP",
                "message": "No pending levelup available.",
            }

        stat_names = ["health", "agility", "mana", "recover", "damage"]
        chosen = self.rng.choice(stat_names)

        before_stats = asdict(w.stats)
        before_max_hp = w.max_hp()

        # Apply +2
        val = getattr(w.stats, chosen)
        setattr(w.stats, chosen, _clamp(val + 2, 0, 30))
        w.stats.cap_all(30)

        # Adjust current hp if needed (only if it exceeds max)
        after_max_hp = w.max_hp()
        if w.current_hp > after_max_hp:
            w.current_hp = after_max_hp

        w.pending_levelups -= 1

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {
            "ok": True,
            "chosen_stat": chosen,
            "stats_before": before_stats,
            "stats_after": asdict(w.stats),
            "max_hp_before": before_max_hp,
            "max_hp_after": after_max_hp,
            "current_hp_after": w.current_hp,
            "pending_levelups_left": w.pending_levelups,
        }

    # -----------------------
    # Internal logic
    # -----------------------
    def _can_attack(self, attacker: Waifu, now: datetime) -> Tuple[bool, int]:
        cd = attacker.stats.cooldown_seconds()
        if not attacker.last_attack_at:
            return True, 0
        elapsed = (now - attacker.last_attack_at).total_seconds()
        remaining = int(cd - elapsed)
        return (remaining <= 0), max(0, remaining)

    def _ban_name(self, waifu_name: str) -> None:
        key = waifu_name.strip().lower()
        if not key:
            return
        banned = set(self._state.get("banned_names", []))
        if key not in banned:
            banned.add(key)
            self._state["banned_names"] = sorted(banned)

    def _public_waifu_view(self, w: Waifu) -> Dict[str, Any]:
        return {
            "name": w.name,
            "special_name": w.special_name,
            "alive": w.alive,
            "hp": w.current_hp,
            "max_hp": w.max_hp(),
            "stats": {
                "health": w.stats.health,
                "agility": w.stats.agility,
                "mana": w.stats.mana,
                "recover": w.stats.recover,
                "damage_points": w.stats.damage,
                "hit_damage": w.stats.hit_damage(),
                "cooldown_seconds": w.stats.cooldown_seconds(),
                "dodge_chance": w.stats.dodge_chance(),
                "special_chance": w.stats.special_chance(),
            },
            "last_attack_at": _to_iso(w.last_attack_at),
            "stunned_until": _to_iso(w.stunned_until),
            "pending_levelups": w.pending_levelups,
            "last_sleep_date": w.last_sleep_date,
        }

    def _serialize_waifu(self, w: Waifu) -> Dict[str, Any]:
        return {
            "name": w.name,
            "special_name": w.special_name,
            "stats": asdict(w.stats),
            "current_hp": w.current_hp,
            "alive": w.alive,
            "last_attack_at": _to_iso(w.last_attack_at),
            "stunned_until": _to_iso(w.stunned_until),
            "last_sleep_date": w.last_sleep_date,
            "pending_levelups": w.pending_levelups,
            "image_url": w.image_url,
        }

    def waifu_set_image(self, user_id: str, image_url: str) -> dict:
        w = self.get_waifu(user_id)

        if not w:
            return {"ok": False, "message": "User has no waifu."}
        if not w.alive:
            return {"ok": False, "message": "Waifu is dead."}

        w.image_url = image_url
        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {"ok": True, "image_url": image_url}

    def _deserialize_waifu(self, raw: Dict[str, Any]) -> Waifu:
        stats_raw = raw.get("stats", {})
        stats = Stats(
            health=int(stats_raw.get("health", 5)),
            agility=int(stats_raw.get("agility", 5)),
            mana=int(stats_raw.get("mana", 5)),
            recover=int(stats_raw.get("recover", 5)),
            damage=int(stats_raw.get("damage", 5)),
        )
        stats.cap_all(30)

        w = Waifu(
            name=str(raw.get("name", "Unnamed")),
            special_name=str(raw.get("special_name", "Special")),
            stats=stats,
            current_hp=int(raw.get("current_hp", _clamp(stats.health, 1, 30))),
            alive=bool(raw.get("alive", True)),
            last_attack_at=_from_iso(raw.get("last_attack_at")),
            stunned_until=_from_iso(raw.get("stunned_until")),
            last_sleep_date=raw.get("last_sleep_date"),
            pending_levelups=int(raw.get("pending_levelups", 0)),
            image_url=raw.get("image_url"),
        )

        # Ensure current hp is within bounds
        w.current_hp = _clamp(w.current_hp, 0, w.max_hp())
        return w


def _seconds(n: int):
    # Small helper to avoid importing timedelta in multiple places
    from datetime import timedelta

    return timedelta(seconds=n)
