"""Con Edison payee balance hold: cap a person's room, quietly, until the balance drops."""
from __future__ import annotations

import json
import os
from typing import Any

CONED_NOTICE = "Check the Con Edison app"

_BALANCE_KEYS = (
    "current_balance",
    "balance",
    "amount_owed",
    "remaining_balance",
    "remaining",
)
_NAME_KEYS = ("name", "payee_name", "payee")
_LIST_KEYS = ("payees", "payee_summaries", "payee_summary", "summary")


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _money(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_payees(attributes: Any, state: Any = None) -> list[dict[str, Any]]:
    """Read payee name and current balance from the Con Edison sensor."""
    attrs = attributes if isinstance(attributes, dict) else {}
    rows: list = []
    for key in _LIST_KEYS:
        rows.extend(_as_list(attrs.get(key)))
    for key in ("latest", "bill", "data"):
        block = attrs.get(key)
        if isinstance(block, dict):
            for inner in ("payees", "payee_summaries"):
                rows.extend(_as_list(block.get(inner)))
    if not rows:
        rows.extend(_as_list(state))

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = ""
        for key in _NAME_KEYS:
            if row.get(key):
                name = str(row.get(key)).strip()
                break
        if not name:
            continue
        balance = None
        for key in _BALANCE_KEYS:
            if key in row:
                balance = _money(row.get(key))
                if balance is not None:
                    break
        if balance is None:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append({"name": name, "balance": round(balance, 2)})
    return found


def normalize_coned_config(raw: Any) -> dict[str, Any]:
    """Keep the Integrations settings in a stable shape."""
    src = raw if isinstance(raw, dict) else {}
    sensor = str(src.get("payee_sensor") or "sensor.coned_payee_summary").strip()
    if not sensor.startswith("sensor."):
        sensor = "sensor.coned_payee_summary"
    payees: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in src.get("payees") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("payee_name") or "").strip()
        person = str(row.get("person_entity") or "").strip()
        if not name or not person.startswith("person."):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            amount = float(row.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        try:
            hours = int(row.get("hours", 24) or 24)
        except (TypeError, ValueError):
            hours = 24
        try:
            watts = int(row.get("watt_limit", 300) or 300)
        except (TypeError, ValueError):
            watts = 300
        payees.append(
            {
                "payee_name": name[:80],
                "person_entity": person,
                "amount": round(max(0.0, min(100000.0, amount)), 2),
                "hours": max(1, min(720, hours)),
                "watt_limit": max(50, min(5000, watts)),
            }
        )
    return {
        "enabled": bool(src.get("enabled", False)),
        "payee_sensor": sensor,
        "payees": payees,
    }


def update_balance_timers(
    rules: list[dict[str, Any]],
    payees: list[dict[str, Any]],
    now: float,
    since: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Start, keep, or clear the clock for each payee whose balance is high enough."""
    balances = {str(row.get("name") or "").strip().lower(): float(row.get("balance") or 0) for row in payees}
    kept: dict[str, float] = {}
    active: list[dict[str, Any]] = []
    for rule in rules:
        name = str(rule.get("payee_name") or "").strip().lower()
        if not name:
            continue
        if name not in balances:
            if name in since:
                kept[name] = float(since[name])
            continue
        if balances[name] + 0.001 < float(rule.get("amount") or 0):
            continue
        started = float(since.get(name) or now)
        kept[name] = started
        hours = max(1, int(rule.get("hours") or 1))
        if now - started >= hours * 3600:
            active.append(rule)
    return active, kept


def _room_id(room: dict) -> str:
    rid = room.get("id")
    if rid is not None and str(rid).strip():
        return str(rid).strip()
    return str(room.get("name") or "").strip().lower().replace(" ", "_")


def _room_person(room: dict) -> str:
    person = str(room.get("presence_person_entity") or "").strip()
    return person if person.startswith("person.") else ""


def room_caps(
    rooms: list[dict],
    active_rules: list[dict[str, Any]],
    home_persons: list[str],
) -> dict[str, dict[str, Any]]:
    """Map room id to watt cap. The message is only on the payee's own rooms."""
    caps: dict[str, dict[str, Any]] = {}
    alone = home_persons[0] if len(home_persons) == 1 else ""

    def apply(room_id: str, watts: int, notice: str | None) -> None:
        current = caps.get(room_id)
        if current is None or watts < int(current["watt_limit"]):
            caps[room_id] = {"watt_limit": watts, "notice": notice}
        elif notice and not current.get("notice"):
            current["notice"] = notice

    for rule in active_rules:
        person = str(rule.get("person_entity") or "").strip()
        watts = int(rule.get("watt_limit") or 300)
        if not person.startswith("person."):
            continue
        for room in rooms or []:
            if not isinstance(room, dict):
                continue
            rid = _room_id(room)
            if not rid:
                continue
            attached = _room_person(room)
            if attached == person:
                apply(rid, watts, CONED_NOTICE)
            elif not attached and alone == person:
                apply(rid, watts, None)
    return caps


def controllable_switches(room: dict) -> list[str]:
    """Outlet and appliance switches that can be turned off for the watt cap."""
    found: list[str] = []
    seen: set[str] = set()
    for outlet in room.get("outlets") or []:
        if not isinstance(outlet, dict):
            continue
        if str(outlet.get("type") or "") in {"stove", "microwave", "smoke_alarm", "door", "window"}:
            continue
        for key in ("plug1_switch", "plug2_switch", "switch_entity", "diffuser_switch"):
            eid = str(outlet.get(key) or "").strip()
            if not eid.startswith(("switch.", "fan.")):
                continue
            if eid in seen:
                continue
            seen.add(eid)
            found.append(eid)
    return found


def load_since(path: str) -> dict[str, float]:
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, TypeError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def save_since(path: str, since: dict[str, float]) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({key: value for key, value in since.items()}, handle)


def persons_home(rooms: list[dict], person_states: dict[str, str]) -> list[str]:
    """Configured presence people whose state is exactly home. Each person once."""
    home: list[str] = []
    seen: set[str] = set()
    for room in rooms or []:
        if not isinstance(room, dict):
            continue
        person = _room_person(room)
        if not person or person in seen:
            continue
        seen.add(person)
        if str(person_states.get(person) or "").strip().lower() == "home":
            home.append(person)
    return home
