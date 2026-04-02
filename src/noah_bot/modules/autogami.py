import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTOGAMI_PASSWORD = "autogami"
PBKDF2_ITERATIONS = 200_000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _xor_bytes(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=32,
    )


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0

    while len(output) < length:
        block = hashlib.sha256(
            key + nonce + counter.to_bytes(8, byteorder="big")
        ).digest()
        output.extend(block)
        counter += 1

    return bytes(output[:length])


def _encrypt_payload(data: dict[str, Any], password: str) -> dict[str, str | int]:
    plaintext = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = _derive_key(password, salt)
    ciphertext = _xor_bytes(plaintext, _keystream(key, nonce, len(plaintext)))
    mac = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()

    return {
        "version": 1,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "mac": base64.b64encode(mac).decode("ascii"),
    }


def _decrypt_payload(payload: dict[str, Any], password: str) -> dict[str, Any]:
    salt = base64.b64decode(payload["salt"])
    nonce = base64.b64decode(payload["nonce"])
    ciphertext = base64.b64decode(payload["ciphertext"])
    received_mac = base64.b64decode(payload["mac"])
    key = _derive_key(password, salt)
    expected_mac = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()

    if not hmac.compare_digest(received_mac, expected_mac):
        raise ValueError("Autogami token store integrity check failed.")

    plaintext = _xor_bytes(ciphertext, _keystream(key, nonce, len(ciphertext)))
    data = json.loads(plaintext.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Autogami token store has an invalid format.")
    return data


class AutogamiTokenStore:
    def __init__(
        self,
        json_path: str = "autogami_tokens.json",
        password: str = AUTOGAMI_PASSWORD,
    ):
        self.json_path = Path(json_path)
        self.password = password
        self._state = self._load()
        self._users: dict[str, dict[str, Any]] = self._state["users"]

    def _default_state(self) -> dict[str, dict[str, Any]]:
        return {"users": {}}

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.json_path.exists():
            return self._default_state()

        try:
            with self.json_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, json.JSONDecodeError):
            return self._default_state()

        try:
            state = _decrypt_payload(payload, self.password)
        except (KeyError, ValueError, TypeError):
            return self._default_state()

        users = state.get("users")
        return {"users": users if isinstance(users, dict) else {}}

    def _save(self) -> None:
        payload = _encrypt_payload(self._state, self.password)
        with self.json_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)

    def _user_key(self, user_id: int) -> str:
        return str(user_id)

    def set_token(self, user_id: int, token: str, username: str | None = None) -> None:
        user_data = self._users.get(self._user_key(user_id), {})
        user_data["token"] = token
        user_data["updated_at"] = _utc_now_iso()
        if username:
            user_data["username"] = username
        self._users[self._user_key(user_id)] = user_data
        self._save()

    def get_token(self, user_id: int) -> str | None:
        user_data = self._users.get(self._user_key(user_id))
        if not isinstance(user_data, dict):
            return None

        token = user_data.get("token")
        if not isinstance(token, str) or not token.strip():
            return None
        return token
