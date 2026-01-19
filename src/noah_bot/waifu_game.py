import json
import os
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional


SCHEMA_VERSION = 2
INCAP_SECONDS = 12 * 60 * 60  # 12h incapacitated
STUN_SECONDS = 3 * 60 * 60  # 3h stun
PEACEFUL_INCAP_SECONDS = 365 * 24 * 60 * 60  # 1 year
DOJO_CHARGE_SECONDS = 30 * 60  # 30 minutes of training


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _from_iso(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


# ---------------- STATS ---------------- #


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


# ---------------- WAIFU ---------------- #


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
    received_hits: Dict[str, int]

    last_daily_date: Optional[str]
    last_sleep_date: Optional[str]
    pending_levelups: int
    embed_color: Optional[int]  # <-- NEW

    def max_hp(self) -> int:
        return _clamp(self.stats.health, 1, 30)

    def heal_full(self) -> None:
        self.current_hp = self.max_hp()

    def heal_half(self) -> None:
        self.current_hp = _clamp(self.current_hp + self.max_hp() // 2, 0, self.max_hp())

    def heal(self, amount: int) -> None:
        self.current_hp = _clamp(self.current_hp + amount, 0, self.max_hp())

    def is_stunned(self, now: datetime) -> bool:
        return self.stunned_until is not None and now < self.stunned_until

    def is_stunned_now(self) -> bool:
        return self.is_stunned(_utc_now())

    def is_incapacitated(self, now: datetime) -> bool:
        return self.incapacitated_until is not None and now < self.incapacitated_until

    def maybe_recover_from_incap(self, now: datetime) -> None:
        if self.incapacitated_until and now >= self.incapacitated_until:
            self.incapacitated_until = None
            self.heal_full()

    def can_sleep(self, now: datetime) -> bool:
        today = now.date().isoformat()
        return self.last_sleep_date != today

    def level(self) -> int:
        return (
            self.stats.health
            + self.stats.agility
            + self.stats.mana
            + self.stats.recover
            + self.stats.damage
        )

    def now(self) -> datetime:
        return _utc_now()


# ---------------- MANAGER ---------------- #


class WaifuGameManager:
    def __init__(self, json_path: str, rng: Optional[random.Random] = None) -> None:
        self.json_path = json_path
        self.rng = rng or random.Random()
        self._state = {
            "schema_version": SCHEMA_VERSION,
            "devmode": False,
            "users": {},
            "players": [],
            "dojo": None,
            "next_dojo_at": None,
        }
        self._load()

    # ---------- Persistence ---------- #

    def _load(self) -> None:
        if not os.path.exists(self.json_path):
            self._save()
            return
        with open(self.json_path, "r", encoding="utf-8") as f:
            self._state = json.load(f)
        # Backwards compatibility: older files may not have "players" key
        if "players" not in self._state:
            self._state["players"] = []
        if "dojo" not in self._state:
            self._state["dojo"] = None
        if "next_dojo_at" not in self._state:
            self._state["next_dojo_at"] = None

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.json_path) or ".", exist_ok=True)
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    @property
    def devmode(self) -> bool:
        return bool(self._state.get("devmode", False))

    def set_devmode(self, enabled: bool):
        self._state["devmode"] = bool(enabled)
        self._save()

    def waifu_set_image(self, user_id: str, image_url: str):
        w = self.get_waifu(user_id)
        if not w:
            return {"ok": False, "message": "No waifu."}

        w.image_url = image_url
        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()
        return {"ok": True, "waifu": self._public_view(w)}

    # ---------- Helpers ---------- #

    def get_waifu(self, user_id: str) -> Optional[Waifu]:
        raw = self._state["users"].get(str(user_id))
        if not raw:
            return None
        return self._deserialize_waifu(raw)

    def set_players(self, player_ids):
        """Set the list of tracked player IDs (as strings)."""
        self._state["players"] = [str(pid) for pid in player_ids]
        self._save()

    def get_players(self):
        """Return the list of tracked player IDs (strings)."""
        return list(self._state.get("players", []))

    # ---------- Dojo helpers ---------- #

    @property
    def dojo(self) -> Optional[Dict[str, Any]]:
        return self._state.get("dojo")

    def _set_dojo(self, dojo: Optional[Dict[str, Any]]) -> None:
        self._state["dojo"] = dojo
        self._save()

    def _random_next_dojo_time(self, now: Optional[datetime] = None) -> datetime:
        now = now or _utc_now()
        hours = self.rng.randint(10, 20)
        return now + timedelta(hours=hours)

    def _weighted_sample_two_players(self, now: Optional[datetime] = None):
        """Return up to two player IDs (strings) weighted by inverse level.

        Lower-level waifus have higher probability of being selected.
        Only players with an existing waifu are considered.
        """

        now = now or _utc_now()
        players = self.get_players()
        candidates = []  # list of (user_id, weight)

        for pid in players:
            w = self.get_waifu(str(pid))
            if not w:
                continue
            level = max(1, w.level())
            # Simple inverse weighting: lower level -> higher weight
            weight = 1.0 / float(level)
            candidates.append((str(pid), weight))

        if len(candidates) < 2:
            return []

        def _weighted_choice(items):
            total = sum(w for _, w in items)
            r = self.rng.random() * total
            upto = 0.0
            for uid, w in items:
                upto += w
                if upto >= r:
                    return uid
            # Fallback
            return items[-1][0]

        first = _weighted_choice(candidates)
        remaining = [(uid, w) for uid, w in candidates if uid != first]
        if not remaining:
            return [first]
        second = _weighted_choice(remaining)
        return [first, second]

    def _ensure_dojo(self, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Ensure there is an active dojo, spawning one if time has come.

        Returns the active dojo dict or None if none can be created.
        """

        now = now or _utc_now()

        if self.dojo is not None:
            return self.dojo

        next_at_raw = self._state.get("next_dojo_at")
        next_at = _from_iso(next_at_raw) if next_at_raw else None

        if next_at is not None and now < next_at:
            return None

        # Time to spawn a new dojo
        result = self.spawn_dojo(force=False, now=now)
        if result.get("ok"):
            return result["dojo"]
        return None

    def spawn_dojo(
        self, force: bool = False, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Spawn a new dojo and select two players.

        If force is False and there is already an active dojo, it will fail.
        """

        now = now or _utc_now()

        if self.dojo is not None and not force:
            return {"ok": False, "message": "There is already an active dojo."}

        selected_players = self._weighted_sample_two_players(now=now)
        if len(selected_players) < 2:
            # Schedule the next attempt even if we failed to create one
            self._state["next_dojo_at"] = _to_iso(self._random_next_dojo_time(now))
            self._save()
            return {
                "ok": False,
                "message": "Not enough eligible players to spawn a dojo.",
            }

        # Placeholder dojo definitions; fill with real names and images externally
        dojo_templates = [
            {
                "id": 0,
                "name": "Eternal Waifu Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo1.jpeg",
            },
            {
                "id": 1,
                "name": "Phantom Waifu Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/replicate-prediction-jy70t2acdsrmr0cvtw9arezw6c.jpeg",
            },
            {
                "id": 2,
                "name": "Waifu Battle Room",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo3.jpeg",
            },
            {
                "id": 3,
                "name": "Celestial Waifu Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo4.jpeg",
            },
            {
                "id": 4,
                "name": "Shadow Waifu Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo5.jpeg",
            },
            {
                "id": 5,
                "name": "Weightless Waifu Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo6.jpeg",
            },
            {
                "id": 6,
                "name": "Arcane Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo7.jpeg",
            },
            {
                "id": 7,
                "name": "The First Flame Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo8.jpeg",
            },
            {
                "id": 8,
                "name": "Lightning Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo9.jpeg",
            },
            {
                "id": 9,
                "name": "Montadito's VII Dojo",
                "image_url": "https://welcome.materiacore.com/wp-content/uploads/2026/01/dojo10.jpeg",
            },
        ]
        template = self.rng.choice(dojo_templates)

        dojo = {
            "id": template["id"],
            "name": template["name"],
            "image_url": template.get("image_url"),
            "spawned_at": _to_iso(now),
            "selected_players": selected_players,
            "training": {
                uid: {"started_at": None, "completed": False}
                for uid in selected_players
            },
        }

        self._state["dojo"] = dojo
        self._state["next_dojo_at"] = _to_iso(self._random_next_dojo_time(now))
        self._save()

        return {"ok": True, "dojo": dojo}

    def dojo_training_action(
        self, user_id: str, now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Start/continue/finish dojo training for a given user.

        Returns a dict with a small "code" describing the state.
        """

        now = now or _utc_now()
        dojo = self._ensure_dojo(now=now)

        if dojo is None:
            return {"ok": False, "code": "no_dojo", "message": "No active dojo."}

        uid = str(user_id)
        if uid not in dojo.get("selected_players", []):
            return {
                "ok": False,
                "code": "not_selected",
                "message": "You were not selected for this dojo.",
                "dojo": dojo,
            }

        training = dojo["training"].get(uid)
        if training is None:
            return {
                "ok": False,
                "code": "internal_error",
                "message": "No training slot found for this user.",
            }

        if training.get("completed"):
            return {
                "ok": False,
                "code": "already_completed",
                "message": "You already finished your dojo training.",
                "dojo": dojo,
            }

        if training.get("started_at") is None:
            training["started_at"] = _to_iso(now)
            self._save()
            return {
                "ok": True,
                "code": "started",
                "message": "Dojo training started.",
                "remaining_seconds": DOJO_CHARGE_SECONDS,
                "dojo": dojo,
            }

        started_at = _from_iso(training["started_at"])
        if not started_at:
            training["started_at"] = _to_iso(now)
            self._save()
            return {
                "ok": True,
                "code": "started",
                "message": "Dojo training started.",
                "remaining_seconds": DOJO_CHARGE_SECONDS,
                "dojo": dojo,
            }

        elapsed = (now - started_at).total_seconds()
        if elapsed < DOJO_CHARGE_SECONDS:
            remaining = int(DOJO_CHARGE_SECONDS - elapsed)
            return {
                "ok": True,
                "code": "charging",
                "message": "Dojo training in progress.",
                "remaining_seconds": remaining,
                "dojo": dojo,
            }

        # Training complete: grant 3 pending levelups
        w = self.get_waifu(uid)
        if not w:
            return {
                "ok": False,
                "code": "no_waifu",
                "message": "No waifu found for this user.",
                "dojo": dojo,
            }

        w.pending_levelups += 3
        training["completed"] = True

        self._state["users"][uid] = self._serialize_waifu(w)

        # If all selected players are done, close the dojo
        if all(t["completed"] for t in dojo["training"].values()):
            self._state["dojo"] = None

        self._save()

        return {
            "ok": True,
            "code": "completed",
            "message": "Dojo training completed.",
            "gained_levelups": 3,
            "dojo": dojo,
            "pending_levelups": w.pending_levelups,
        }

    # ---------- Core Actions ---------- #

    def waifu_set_color(self, user_id: str, color: int):
        w = self.get_waifu(user_id)
        if not w:
            return {"ok": False, "message": "No waifu."}

        w.embed_color = color
        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {"ok": True, "color": color}

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
            last_daily_date=None,
            last_sleep_date=None,
            pending_levelups=0,
            received_hits={},
            embed_color=None,
        )

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()
        return {"ok": True, "waifu": self._public_view(w)}

    def waifu_attack(self, attacker_id: str, defender_id: str, now=None):
        now = now or _utc_now()
        a = self.get_waifu(attacker_id)
        d = self.get_waifu(defender_id)

        if not a or not d:
            return {"ok": False, "message": "Missing waifu."}

        a.maybe_recover_from_incap(now)
        d.maybe_recover_from_incap(now)

        if not self.devmode:
            if a.is_incapacitated(now):
                return {"ok": False, "message": "Your waifu is incapacitated."}
            if a.is_stunned(now):
                return {"ok": False, "message": "Your waifu is stunned."}
            if d.is_incapacitated(now):
                return {"ok": False, "message": "Target waifu is incapacitated."}

        def _add_pending_levelups(target_user_id: str, amount: int) -> None:
            """
            Adds pending levelups without being overwritten later by stale objects.
            If the target is the current attacker, mutate `a` directly.
            """
            nonlocal a
            if str(target_user_id) == str(attacker_id):
                a.pending_levelups += amount
                return

            w = self.get_waifu(str(target_user_id))
            if not w:
                return
            w.pending_levelups += amount
            self._state["users"][str(target_user_id)] = self._serialize_waifu(w)

        # Dodge
        if self.rng.random() < d.stats.dodge_chance():
            # In normal mode, dodges should still consume cooldown
            if not self.devmode:
                a.last_attack_at = now

            # Persist state if we changed attacker cooldown
            self._state["users"][str(attacker_id)] = self._serialize_waifu(a)
            self._state["users"][str(defender_id)] = self._serialize_waifu(d)
            self._save()

            return {
                "ok": True,
                "dodged": True,
                "special": False,
                "damage": 0,
                "defender_hp_after": d.current_hp,
                "killed": False,
                "stunned_applied": False,
            }

        special = self.rng.random() < a.stats.special_chance()
        damage = a.stats.hit_damage()
        d.current_hp -= damage

        d.received_hits[str(attacker_id)] = (
            d.received_hits.get(str(attacker_id), 0) + damage
        )

        stunned_applied = False
        if special and not self.devmode:
            d.stunned_until = now + timedelta(seconds=STUN_SECONDS)
            stunned_applied = True

        killed = False
        defender_hp_after = d.current_hp

        if d.current_hp <= 0:
            killed = True

            # Rank attackers by total damage dealt since last death
            ranking = sorted(d.received_hits.items(), key=lambda x: x[1], reverse=True)

            if len(ranking) >= 1:
                top1_id, _ = ranking[0]
                _add_pending_levelups(top1_id, 2)

            if len(ranking) >= 2:
                top2_id, _ = ranking[1]
                _add_pending_levelups(top2_id, 1)

            # Reset defender state
            d.received_hits = {}
            d.heal_full()
            d.incapacitated_until = now + timedelta(seconds=INCAP_SECONDS)

            # Reward attacker with full heal (your original rule)
            a.heal_half()

            # What do we report as hp_after? (keep it consistent for UI)
            defender_hp_after = 0  # shows the kill correctly

        if not self.devmode:
            a.last_attack_at = now

        self._state["users"][str(attacker_id)] = self._serialize_waifu(a)
        self._state["users"][str(defender_id)] = self._serialize_waifu(d)
        self._save()

        return {
            "ok": True,
            "dodged": False,
            "special": special,
            "special_name": a.special_name if special else None,
            "damage": damage,
            "defender_hp_after": defender_hp_after,
            "stunned_applied": stunned_applied,
            "killed": killed,
        }

    def waifu_peaceful_kill(self, attacker_id: str, target_id: str, now=None):
        now = now or _utc_now()

        attacker = self.get_waifu(attacker_id)
        target = self.get_waifu(target_id)

        if not attacker or not target:
            return {"ok": False, "message": "Missing waifu."}

        if not self.devmode:
            if attacker.is_incapacitated(now) or attacker.is_stunned(now):
                return {"ok": False, "message": "Your waifu cannot act right now."}

        # Instant kill
        target.current_hp = 0
        target.received_hits = {}
        target.stunned_until = None
        target.incapacitated_until = now + timedelta(seconds=PEACEFUL_INCAP_SECONDS)

        # Consume cooldown
        if not self.devmode:
            attacker.last_attack_at = now

        self._state["users"][str(attacker_id)] = self._serialize_waifu(attacker)
        self._state["users"][str(target_id)] = self._serialize_waifu(target)
        self._save()

        return {
            "ok": True,
            "target_name": target.name,
            "revive_at": target.incapacitated_until.isoformat(),
        }

    def waifu_sleep(self, user_id: str, now=None):
        now = now or _utc_now()
        w = self.get_waifu(user_id)

        if not w:
            return {"ok": False, "message": "No waifu."}

        w.maybe_recover_from_incap(now)

        if not self.devmode:
            if w.is_incapacitated(now):
                return {"ok": False, "message": "Waifu is incapacitated."}
            if w.is_stunned(now):
                return {"ok": False, "message": "Waifu is stunned."}

        today = now.date().isoformat()
        if not self.devmode and w.last_sleep_date == today:
            return {"ok": False, "message": "Already slept today."}

        before = w.current_hp
        w.heal(8)
        w.last_sleep_date = today

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {
            "ok": True,
            "hp_before": before,
            "hp_after": w.current_hp,
            "healed": w.current_hp - before,
        }

    def waifu_levelup(self, user_id: str):
        w = self.get_waifu(user_id)
        now = _utc_now()

        if not w:
            return {"ok": False, "message": "No waifu."}
        if not self.devmode and w.is_stunned(now):
            return {"ok": False, "message": "Waifu is stunned."}
        if w.pending_levelups <= 0:
            return {"ok": False, "message": "No pending levelups."}

        stat = self.rng.choice(list(vars(w.stats).keys()))
        setattr(w.stats, stat, _clamp(getattr(w.stats, stat) + 1, 0, 30))
        w.pending_levelups -= 1

        self._state["users"][str(user_id)] = self._serialize_waifu(w)
        self._save()

        return {
            "ok": True,
            "chosen_stat": stat,
            "pending_levelups_left": w.pending_levelups,
        }

    # ---------- Serialization ---------- #

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
            "last_daily_date": w.last_daily_date,
            "last_sleep_date": w.last_sleep_date,
            "pending_levelups": w.pending_levelups,
            "received_hits": w.received_hits,
            "embed_color": w.embed_color,
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
            last_attack_at=_from_iso(raw.get("last_attack_at")),
            stunned_until=_from_iso(raw.get("stunned_until")),
            incapacitated_until=_from_iso(raw.get("incapacitated_until")),
            last_sleep_date=raw.get("last_sleep_date"),
            pending_levelups=raw.get("pending_levelups", 0),
            last_daily_date=raw.get("last_daily_date"),
            received_hits=raw.get("received_hits", {}),
            embed_color=raw.get("embed_color", None),
        )

        w.current_hp = _clamp(w.current_hp, 0, w.max_hp())
        return w

    def _public_view(self, w: Waifu) -> Dict[str, Any]:
        return {
            "name": w.name,
            "special_name": w.special_name,
            "hp": w.current_hp,
            "max_hp": w.max_hp(),
            "stats": {
                "health": w.stats.health,
                "agility": w.stats.agility,
                "mana": w.stats.mana,
                "recover": w.stats.recover,
                "hit_damage": w.stats.hit_damage(),
                "cooldown_seconds": w.stats.cooldown_seconds(),
                "dodge_chance": w.stats.dodge_chance(),
                "special_chance": w.stats.special_chance(),
            },
            "pending_levelups": w.pending_levelups,
        }
