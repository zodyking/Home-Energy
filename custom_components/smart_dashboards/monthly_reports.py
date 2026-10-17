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


def report_display_title(month: str) -> str:
    return f"Home-Energy ({month_title(month)})"


_DISCLAIMER = (
    "Calculations are not accurate but an estimated value pulled from power readings "
    "in your home, subject to connectivity errors. Refer to Con Edison for accurate readings."
)


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


def _pretty_day(day: str) -> str:
    try:
        parsed = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return day
    return f"{parsed.strftime('%a')}, {parsed.strftime('%b')} {parsed.day}"


def _event_note(room: dict[str, Any]) -> str:
    bits = []
    for key, label in (("warnings", "warning"), ("shutoffs", "shutoff"), ("power_cycles", "cycle")):
        count = int(room.get(key) or 0)
        if count:
            bits.append(f"{count} {label}{'' if count == 1 else 's'}")
    return ", ".join(bits)


def _pretty_generated(label: str) -> str:
    text = str(label or "").strip()
    if not text:
        return "Not recorded"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    hour = parsed.strftime("%I").lstrip("0") or "12"
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} {hour}:{parsed.strftime('%M %p')}"


class _MonthlyPdf:
    """A4 report with a repeating title bar and a bold red estimate notice."""

    def __init__(self, title: str) -> None:
        from fpdf import FPDF

        self._title = title
        self.pdf = FPDF(format="A4", unit="mm")
        self.pdf.set_auto_page_break(auto=True, margin=34)
        self.pdf.set_margins(14, 22, 14)
        self.pdf.set_title(_safe(title))
        self.pdf.set_author("Home-Energy")
        self.pdf.alias_nb_pages()
        self.pdf.header = self._header  # type: ignore[method-assign]
        self.pdf.footer = self._footer  # type: ignore[method-assign]
        self._columns: list[tuple[float, str]] | None = None

    def _header(self) -> None:
        pdf = self.pdf
        pdf.set_fill_color(12, 42, 58)
        pdf.rect(0, 0, 210, 16, "F")
        pdf.set_xy(14, 4)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(140, 8, _safe(self._title), align="L")
        pdf.set_font("helvetica", "", 9)
        pdf.set_xy(140, 4)
        pdf.cell(56, 8, _safe(f"Page {pdf.page_no()}/{{nb}}"), align="R")
        pdf.set_text_color(28, 32, 36)
        pdf.set_y(22)

    def _footer(self) -> None:
        pdf = self.pdf
        pdf.set_auto_page_break(auto=False)
        pdf.set_fill_color(255, 236, 236)
        pdf.rect(12, 270, 186, 20, "F")
        pdf.set_xy(15, 271.5)
        pdf.set_text_color(176, 28, 28)
        pdf.set_font("helvetica", "B", 8)
        pdf.multi_cell(w=180, h=3.8, text=_safe(_DISCLAIMER), align="C")
        pdf.set_text_color(28, 32, 36)
        pdf.set_auto_page_break(auto=True, margin=34)

    def _fit(self, text: Any, width: float, style: str = "", size: int = 8) -> str:
        pdf = self.pdf
        pdf.set_font("helvetica", style, size)
        raw = _safe(text)
        if pdf.get_string_width(raw) <= width - 2.4:
            return raw
        trimmed = raw
        while trimmed and pdf.get_string_width(trimmed + "...") > width - 2.4:
            trimmed = trimmed[:-1]
        return f"{trimmed}..." if trimmed else ""

    def _section(self, title: str) -> None:
        pdf = self.pdf
        pdf.ln(3)
        if pdf.get_y() > 248:
            pdf.add_page()
        pdf.set_fill_color(3, 120, 170)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(182, 8, _safe(f"  {title}"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)
        pdf.set_text_color(28, 32, 36)

    def _muted(self, text: str) -> None:
        pdf = self.pdf
        pdf.set_text_color(90, 98, 106)
        pdf.set_font("helvetica", "", 9)
        pdf.multi_cell(w=182, h=4.5, text=_safe(text), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(28, 32, 36)

    def _tiles(self, tiles: list[tuple[str, str]]) -> None:
        pdf = self.pdf
        if not tiles:
            return
        width = 182 / len(tiles)
        y = pdf.get_y() + 1
        for index, (label, value) in enumerate(tiles):
            x = 14 + index * width
            pdf.set_fill_color(244, 248, 250)
            pdf.rect(x + 1, y, width - 2, 16, "F")
            pdf.set_xy(x + 3, y + 2)
            pdf.set_font("helvetica", "", 7)
            pdf.set_text_color(90, 98, 106)
            pdf.cell(width - 6, 4, self._fit(label, width - 6, size=7))
            pdf.set_xy(x + 3, y + 7.5)
            pdf.set_font("helvetica", "B", 12)
            pdf.set_text_color(12, 42, 58)
            pdf.cell(width - 6, 6, self._fit(value, width - 6, style="B", size=12))
        pdf.set_xy(14, y + 19)
        pdf.set_text_color(28, 32, 36)

    def _table_header(self, columns: list[tuple[float, str]]) -> None:
        pdf = self.pdf
        self._columns = columns
        if pdf.get_y() + 14 > pdf.page_break_trigger:
            pdf.add_page()
        pdf.set_fill_color(12, 42, 58)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", "B", 8)
        for width, label in columns:
            align = "R" if label in {"kWh", "Days home", "Hours home", "Hours away"} else "L"
            pdf.cell(width, 7, self._fit(label, width, style="B", size=8), fill=True, align=align)
        pdf.ln(7)
        pdf.set_text_color(28, 32, 36)

    def _table_row(
        self,
        columns: list[tuple[float, str, str]],
        *,
        fill: bool,
        bold: bool = False,
        size: int = 8,
    ) -> None:
        pdf = self.pdf
        height = 6.4
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page()
            if self._columns:
                saved = self._columns
                self._table_header(saved)
        pdf.set_fill_color(244, 248, 250) if fill else pdf.set_fill_color(255, 255, 255)
        style = "B" if bold else ""
        pdf.set_font("helvetica", style, size)
        if bold:
            pdf.set_text_color(12, 42, 58)
        else:
            pdf.set_text_color(28, 32, 36)
        for width, text, align in columns:
            pdf.cell(
                width,
                height,
                self._fit(text, width, style=style, size=size),
                fill=True,
                align=align,
            )
        pdf.ln(height)
        pdf.set_draw_color(226, 232, 236)
        y = pdf.get_y()
        pdf.line(14, y, 196, y)


def render_month_pdf(month: str, days: dict[str, Any], generated_label: str) -> bytes:
    """Build one month's PDF from a durable day map. Returns PDF bytes."""
    title = report_display_title(month)
    doc = _MonthlyPdf(title)
    pdf = doc.pdf
    pdf.add_page()

    doc._muted(
        f"Generated {_pretty_generated(generated_label)}. "
        "Daily room energy and device-tracker presence from retained history."
    )
    pdf.ln(1)

    day_keys = sorted(k for k in days if isinstance(k, str) and k.startswith(month))
    total_wh = 0.0
    person_ids: set[str] = set()
    for day in day_keys:
        bucket = days.get(day) if isinstance(days.get(day), dict) else {}
        rooms = bucket.get("rooms") if isinstance(bucket.get("rooms"), dict) else {}
        for room in rooms.values():
            if isinstance(room, dict):
                total_wh += float(room.get("wh") or 0.0)
        persons = bucket.get("persons") if isinstance(bucket.get("persons"), dict) else {}
        person_ids.update(str(pid) for pid in persons)

    doc._tiles(
        [
            ("Days recorded", str(len(day_keys))),
            ("Estimated energy", f"{_kwh(total_wh)} kWh"),
            ("People tracked", str(len(person_ids))),
        ]
    )

    energy_cols = [(36, "Date"), (48, "Room"), (66, "Device"), (32, "kWh")]
    doc._section("Daily energy by room")
    if not day_keys:
        doc._muted("No daily records for this month yet.")
    else:
        doc._table_header(energy_cols)
        stripe = False
        for day in day_keys:
            bucket = days.get(day) if isinstance(days.get(day), dict) else {}
            rooms = bucket.get("rooms") if isinstance(bucket.get("rooms"), dict) else {}
            label = _pretty_day(day)
            if not rooms:
                doc._table_row(
                    [(36, label, "L"), (48, "—", "L"), (66, "No room energy recorded", "L"), (32, "—", "R")],
                    fill=stripe,
                )
                stripe = not stripe
                continue
            ordered = sorted(rooms, key=lambda rid: str((rooms[rid] or {}).get("name") or rid).lower())
            for room_id in ordered:
                room = rooms[room_id] if isinstance(rooms[room_id], dict) else {}
                room_name = str(room.get("name") or room_id)
                note = _event_note(room)
                devices = [d for d in (room.get("devices") or []) if isinstance(d, dict)]
                if not devices:
                    device_label = note or "No device breakdown"
                    doc._table_row(
                        [
                            (36, label, "L"),
                            (48, room_name, "L"),
                            (66, device_label, "L"),
                            (32, _kwh(room.get("wh") or 0), "R"),
                        ],
                        fill=stripe,
                        bold=True,
                    )
                    stripe = not stripe
                    continue
                for index, device in enumerate(devices):
                    part = str(device.get("part") or "").strip()
                    device_name = str(device.get("name") or "Device")
                    if part:
                        device_name = f"{device_name} ({part})"
                    if index == 0 and note:
                        device_name = f"{device_name} · {note}"
                    doc._table_row(
                        [
                            (36, label if index == 0 else "", "L"),
                            (48, room_name if index == 0 else "", "L"),
                            (66, device_name, "L"),
                            (32, _kwh(device.get("wh") or 0), "R"),
                        ],
                        fill=stripe,
                        bold=index == 0,
                    )
                    stripe = not stripe

    doc._section("People and device trackers")
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

    summary_cols = [(36, "Person"), (50, "Device"), (24, "Days home"), (36, "Hours home"), (36, "Hours away")]
    if not person_rollup:
        doc._muted("No device-tracker presence recorded for this month.")
    else:
        doc._table_header(summary_cols)
        stripe = False
        for person_id in sorted(person_rollup, key=lambda pid: str(person_rollup[pid].get("name") or pid).lower()):
            person = person_rollup[person_id]
            person_name = str(person.get("name") or person_id)
            trackers = person.get("trackers") or {}
            if not trackers:
                doc._table_row(
                    [
                        (36, person_name, "L"),
                        (50, "No tracker observed", "L"),
                        (24, "—", "R"),
                        (36, "—", "R"),
                        (36, "—", "R"),
                    ],
                    fill=stripe,
                )
                stripe = not stripe
                continue
            first = True
            for tracker_id in sorted(trackers, key=lambda tid: str(trackers[tid].get("name") or tid).lower()):
                tracker = trackers[tracker_id]
                device = str(tracker.get("name") or tracker_id)
                doc._table_row(
                    [
                        (36, person_name if first else "", "L"),
                        (50, device, "L"),
                        (24, str(int(tracker.get("days_home") or 0)), "R"),
                        (36, _hours(tracker.get("seconds_home") or 0), "R"),
                        (36, _hours(tracker.get("seconds_away") or 0), "R"),
                    ],
                    fill=stripe,
                    bold=first,
                )
                stripe = not stripe
                first = False
                summary = _state_summary(tracker.get("states") or {})
                if summary and summary != "No state samples":
                    doc._table_row(
                        [
                            (36, "", "L"),
                            (50, summary, "L"),
                            (24, "", "L"),
                            (36, "", "L"),
                            (36, tracker_id, "R"),
                        ],
                        fill=stripe,
                        size=7,
                    )
                    stripe = not stripe

        doc._section("Daily presence log")
        daily_cols = [(36, "Date"), (40, "Person"), (70, "Device"), (36, "Hours home")]
        doc._table_header(daily_cols)
        stripe = False
        wrote_daily = False
        for day in day_keys:
            bucket = days.get(day) if isinstance(days.get(day), dict) else {}
            persons = bucket.get("persons") if isinstance(bucket.get("persons"), dict) else {}
            for person_id in sorted(persons, key=lambda pid: str((persons[pid] or {}).get("name") or pid).lower()):
                person_day = persons.get(person_id)
                if not isinstance(person_day, dict):
                    continue
                person_name = str(person_day.get("name") or person_id)
                day_trackers = person_day.get("trackers") if isinstance(person_day.get("trackers"), dict) else {}
                first = True
                for tracker_id in sorted(day_trackers, key=lambda tid: str(day_trackers[tid].get("name") or tid).lower()):
                    tracker = day_trackers[tracker_id]
                    if not isinstance(tracker, dict):
                        continue
                    wrote_daily = True
                    doc._table_row(
                        [
                            (36, _pretty_day(day) if first else "", "L"),
                            (40, person_name if first else "", "L"),
                            (70, str(tracker.get("name") or tracker_id), "L"),
                            (36, _hours(tracker.get("seconds_home") or 0), "R"),
                        ],
                        fill=stripe,
                    )
                    stripe = not stripe
                    first = False
        if not wrote_daily:
            doc._muted("No daily presence rows for this month.")

    return bytes(pdf.output())


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
                "title": report_display_title(month),
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
