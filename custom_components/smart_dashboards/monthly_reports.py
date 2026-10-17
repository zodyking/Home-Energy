"""Monthly energy and presence PDFs.

Reports are written under the integration data directory and are never removed
by retention, cleanup, or regenerating a different month. Updating a month
replaces only that month's file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

REPORTS_DIRNAME = "monthly_reports"
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def reports_dir(data_dir: str) -> Path:
    path = Path(data_dir) / REPORTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def valid_month(month: str) -> str | None:
    text = str(month or "").strip()
    if not _MONTH_RE.match(text):
        return None
    return text


def month_title(month: str) -> str:
    year_s, mon_s = month.split("-", 1)
    mon = int(mon_s)
    name = _MONTH_NAMES[mon] if 1 <= mon <= 12 else month
    return f"{name} {year_s}"


def _safe(text: Any) -> str:
    """Core Helvetica is WinAnsi. Keep the report readable if a name is not Latin-1."""
    raw = str(text if text is not None else "")
    return raw.encode("latin-1", "replace").decode("latin-1")


def _hours(seconds: float) -> str:
    return f"{float(seconds or 0.0) / 3600.0:.2f}"


def _kwh(wh: float) -> str:
    return f"{float(wh or 0.0) / 1000.0:.3f}"


def fingerprint(days: dict[str, Any]) -> str:
    raw = json.dumps(days, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _state_summary(states: dict[str, Any], limit: int = 4) -> str:
    if not isinstance(states, dict) or not states:
        return "No state samples"
    ranked = sorted(
        ((str(k), float(v or 0.0)) for k, v in states.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    parts = [f"{name} {_hours(secs)} h" for name, secs in ranked[:limit] if secs > 0]
    return ", ".join(parts) if parts else "No state samples"


def render_month_pdf(month: str, days: dict[str, Any], generated_label: str) -> bytes:
    """Build one month's PDF from a durable day map. Returns PDF bytes."""
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_margins(14, 14, 14)
    pdf.set_title(_safe(f"Home Energy {month_title(month)}"))
    pdf.set_author("Home Energy")
    pdf.add_page()

    def heading(text: str, size: int = 16) -> None:
        pdf.set_text_color(3, 120, 170)
        pdf.set_font("helvetica", "B", size)
        pdf.multi_cell(w=0, h=8, text=_safe(text), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(20, 20, 20)

    def body(text: str, size: int = 10, style: str = "") -> None:
        pdf.set_text_color(20, 20, 20)
        pdf.set_font("helvetica", style, size)
        pdf.multi_cell(w=0, h=5, text=_safe(text), align="L", new_x="LMARGIN", new_y="NEXT")

    def rule() -> None:
        y = pdf.get_y() + 1
        pdf.set_draw_color(180, 200, 210)
        pdf.line(14, y, 196, y)
        pdf.set_y(y + 3)

    heading(f"Home Energy — {month_title(month)}")
    body(f"Generated {generated_label}")
    body(
        "Daily room energy and device-tracker presence from retained history. "
        "This file is kept permanently and is replaced only when this same month is updated."
    )
    rule()

    day_keys = sorted(k for k in days if isinstance(k, str) and k.startswith(month))
    if not day_keys:
        body("No daily records for this month yet.")
    else:
        heading("Daily energy by room", 13)
        for day in day_keys:
            bucket = days.get(day) if isinstance(days.get(day), dict) else {}
            rooms = bucket.get("rooms") if isinstance(bucket.get("rooms"), dict) else {}
            heading(day, 12)
            if not rooms:
                body("No room energy recorded.")
            else:
                for room_id in sorted(rooms, key=lambda rid: str((rooms[rid] or {}).get("name") or rid).lower()):
                    room = rooms[room_id] if isinstance(rooms[room_id], dict) else {}
                    room_name = room.get("name") or room_id
                    wh = float(room.get("wh") or 0.0)
                    extra = []
                    for key, label in (
                        ("warnings", "warnings"),
                        ("shutoffs", "shutoffs"),
                        ("power_cycles", "cycles"),
                    ):
                        n = int(room.get(key) or 0)
                        if n:
                            extra.append(f"{n} {label}")
                    suffix = f"  ({', '.join(extra)})" if extra else ""
                    body(f"{room_name}  —  {_kwh(wh)} kWh{suffix}", 11, "B")
                    devices = room.get("devices") if isinstance(room.get("devices"), list) else []
                    if not devices:
                        body("No per-device breakdown.")
                        continue
                    for device in devices:
                        if not isinstance(device, dict):
                            continue
                        part = str(device.get("part") or "").strip()
                        label = device.get("name") or "Device"
                        if part:
                            label = f"{label} ({part})"
                        body(f"    {label}: {_kwh(device.get('wh') or 0)} kWh")
            pdf.ln(1)

    heading("People and device trackers", 13)
    person_rollup: dict[str, dict[str, Any]] = {}
    for day in day_keys:
        bucket = days.get(day) if isinstance(days.get(day), dict) else {}
        persons = bucket.get("persons") if isinstance(bucket.get("persons"), dict) else {}
        for person_id, person in persons.items():
            if not isinstance(person, dict):
                continue
            roll = person_rollup.setdefault(
                str(person_id),
                {"name": person.get("name") or person_id, "trackers": {}},
            )
            if person.get("name"):
                roll["name"] = person.get("name")
            trackers = person.get("trackers") if isinstance(person.get("trackers"), dict) else {}
            for tracker_id, tracker in trackers.items():
                if not isinstance(tracker, dict):
                    continue
                slot = roll["trackers"].setdefault(
                    str(tracker_id),
                    {
                        "name": tracker.get("name") or tracker_id,
                        "seconds_home": 0.0,
                        "seconds_away": 0.0,
                        "days_home": 0,
                        "states": {},
                    },
                )
                if tracker.get("name"):
                    slot["name"] = tracker.get("name")
                home_secs = float(tracker.get("seconds_home") or 0.0)
                slot["seconds_home"] += home_secs
                slot["seconds_away"] += float(tracker.get("seconds_away") or 0.0)
                if home_secs > 0:
                    slot["days_home"] += 1
                states = tracker.get("states") if isinstance(tracker.get("states"), dict) else {}
                for state_name, secs in states.items():
                    slot["states"][str(state_name)] = float(slot["states"].get(str(state_name)) or 0.0) + float(secs or 0.0)

    if not person_rollup:
        body("No device-tracker presence recorded for this month.")
    else:
        for person_id in sorted(person_rollup, key=lambda pid: str(person_rollup[pid].get("name") or pid).lower()):
            person = person_rollup[person_id]
            body(str(person.get("name") or person_id), 12, "B")
            trackers = person.get("trackers") or {}
            if not trackers:
                body("No linked device trackers observed.")
                continue
            for tracker_id in sorted(trackers, key=lambda tid: str(trackers[tid].get("name") or tid).lower()):
                tracker = trackers[tracker_id]
                body(
                    f"{tracker.get('name') or tracker_id}",
                    11,
                    "B",
                )
                body(f"Entity: {tracker_id}")
                body(
                    f"Days home: {int(tracker.get('days_home') or 0)}    "
                    f"Hours home: {_hours(tracker.get('seconds_home') or 0)}    "
                    f"Hours away: {_hours(tracker.get('seconds_away') or 0)}"
                )
                body(f"Presence summary: {_state_summary(tracker.get('states') or {})}")

            heading(f"{person.get('name') or person_id} — daily presence", 11)
            for day in day_keys:
                bucket = days.get(day) if isinstance(days.get(day), dict) else {}
                persons = bucket.get("persons") if isinstance(bucket.get("persons"), dict) else {}
                person_day = persons.get(person_id)
                if not isinstance(person_day, dict):
                    continue
                bits = []
                day_trackers = person_day.get("trackers") if isinstance(person_day.get("trackers"), dict) else {}
                for tracker_id, tracker in day_trackers.items():
                    if not isinstance(tracker, dict):
                        continue
                    bits.append(
                        f"{tracker.get('name') or tracker_id}: {_hours(tracker.get('seconds_home') or 0)} h home"
                    )
                if bits:
                    body(f"{day}: " + "; ".join(bits))

    pdf.ln(2)
    body("End of report.", 9)
    raw = pdf.output()
    return bytes(raw)


def report_path(data_dir: str, month: str) -> Path | None:
    key = valid_month(month)
    if not key:
        return None
    return reports_dir(data_dir) / f"{key}.pdf"


def write_month_pdf(data_dir: str, month: str, days: dict[str, Any], generated_label: str) -> Path | None:
    """Write or replace one month. Other month files are left in place."""
    path = report_path(data_dir, month)
    if path is None:
        return None
    data = render_month_pdf(month, days, generated_label)
    tmp = path.with_suffix(".pdf.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as err:
        _LOGGER.warning("Monthly report write failed for %s: %s", month, err)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return path


def list_reports(data_dir: str) -> list[dict[str, Any]]:
    folder = reports_dir(data_dir)
    rows: list[dict[str, Any]] = []
    for path in folder.glob("*.pdf"):
        month = valid_month(path.stem)
        if month is None or path.name != f"{month}.pdf":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        generated = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
        rows.append(
            {
                "month": month,
                "title": month_title(month),
                "filename": path.name,
                "bytes": int(stat.st_size),
                "generated_at": generated,
            }
        )
    rows.sort(key=lambda row: row["month"], reverse=True)
    return rows


def read_report_bytes(data_dir: str, month: str) -> bytes | None:
    path = report_path(data_dir, month)
    if path is None or not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError as err:
        _LOGGER.warning("Monthly report read failed for %s: %s", month, err)
        return None
