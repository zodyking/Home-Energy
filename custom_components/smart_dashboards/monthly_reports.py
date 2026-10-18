"""One monthly energy and presence PDF.

The statement covers the billing range from the statistics billing sensors.
Each day inside that month is broken down by room. When those sensors are not
set, the statement is the calendar month instead. Extra day or cycle files are
not kept.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

REPORTS_DIRNAME = "monthly_reports"
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_KEY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$")
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

_DISCLAIMER = (
    "Calculations are not accurate but an estimated value pulled from power readings "
    "in your home, subject to connectivity errors. Refer to Con Edison for accurate readings."
)

_NAVY = (12, 42, 58)
_TEAL = (3, 120, 170)
_INK = (28, 32, 36)
_MUTED = (90, 98, 106)
_PANEL = (244, 248, 250)
_GRID = (226, 232, 236)
_ROOM_COLORS = (
    (3, 120, 170),
    (0, 150, 136),
    (255, 152, 0),
    (121, 85, 72),
    (156, 39, 176),
    (76, 175, 80),
    (233, 30, 99),
    (63, 81, 181),
    (255, 193, 7),
    (96, 125, 139),
)


# --------------------------------------------------------------------------- keys


def reports_dir(data_dir: str) -> Path:
    path = Path(data_dir) / REPORTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def valid_month(month: str) -> str | None:
    text = str(month or "").strip()
    return text if _MONTH_RE.match(text) else None


def _parse_day(text: str) -> date | None:
    try:
        return datetime.strptime(str(text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def period_key(start: str, end: str) -> str | None:
    """Key for one billing period: YYYY-MM-DD_YYYY-MM-DD."""
    a, b = _parse_day(start), _parse_day(end)
    if a is None or b is None or a > b:
        return None
    return f"{a.isoformat()}_{b.isoformat()}"


def valid_key(key: str) -> str | None:
    """Accept a billing-period key or a legacy YYYY-MM month key."""
    text = str(key or "").strip()
    match = _KEY_RE.match(text)
    if match:
        return period_key(match.group(1), match.group(2))
    return valid_month(text)


def key_range(key: str) -> tuple[str, str] | None:
    """Inclusive (start, end) days for a period or legacy month key."""
    text = valid_key(key)
    if not text:
        return None
    match = _KEY_RE.match(text)
    if match:
        return match.group(1), match.group(2)
    year, month = (int(part) for part in text.split("-"))
    first = date(year, month, 1)
    nxt = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()


def month_title(month: str) -> str:
    year_s, mon_s = month.split("-", 1)
    mon = int(mon_s)
    name = _MONTH_NAMES[mon] if 1 <= mon <= 12 else month
    return f"{name} {year_s}"


def period_label(key: str) -> str:
    """Human label such as 'Sep 16 - Oct 15, 2026'."""
    text = valid_key(key)
    if not text:
        return str(key or "")
    if _MONTH_RE.match(text):
        return month_title(text)
    rng = key_range(text)
    if not rng:
        return text
    a, b = _parse_day(rng[0]), _parse_day(rng[1])
    if a is None or b is None:
        return text
    if a.year == b.year:
        return f"{a.strftime('%b')} {a.day} - {b.strftime('%b')} {b.day}, {b.year}"
    return f"{a.strftime('%b')} {a.day}, {a.year} - {b.strftime('%b')} {b.day}, {b.year}"


def report_display_title(key: str) -> str:
    return f"Home-Energy ({period_label(key)})"


def report_path(data_dir: str, key: str) -> Path | None:
    text = valid_key(key)
    if not text:
        return None
    return reports_dir(data_dir) / f"{text}.pdf"


def fingerprint(days: dict[str, Any]) -> str:
    raw = json.dumps(days, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- text


def _safe(text: Any) -> str:
    """Core Helvetica is WinAnsi. Keep the report readable if a name is not Latin-1."""
    raw = str(text if text is not None else "")
    return raw.encode("latin-1", "replace").decode("latin-1")


def _hours(seconds: float) -> str:
    return f"{float(seconds or 0.0) / 3600.0:.1f}"


def _kwh(wh: float, digits: int = 2) -> str:
    return f"{float(wh or 0.0) / 1000.0:.{digits}f}"


def _short_day(day: str) -> str:
    parsed = _parse_day(day)
    if parsed is None:
        return day
    return f"{parsed.strftime('%b')} {parsed.day}"


def _weekday_day(day: str) -> str:
    parsed = _parse_day(day)
    if parsed is None:
        return day
    return f"{parsed.strftime('%a')} {parsed.strftime('%b')} {parsed.day}"


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


# --------------------------------------------------------------------------- rollup


def _period_days(start: str, end: str) -> list[str]:
    a, b = _parse_day(start), _parse_day(end)
    if a is None or b is None or a > b:
        return []
    out = []
    cur = a
    while cur <= b and len(out) < 400:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _rollup(start: str, end: str, days: dict[str, Any]) -> dict[str, Any]:
    """Collapse daily summaries into one billing-period picture."""
    calendar = _period_days(start, end)
    recorded = [d for d in calendar if isinstance(days.get(d), dict)]
    daily_total: dict[str, float] = {}
    daily_rooms: dict[str, dict[str, float]] = {}
    rooms: dict[str, dict[str, Any]] = {}
    devices: dict[tuple[str, str], dict[str, Any]] = {}
    persons: dict[str, dict[str, Any]] = {}
    daily_home: dict[str, dict[str, float]] = {}

    for day in recorded:
        bucket = days[day]
        rooms_day = bucket.get("rooms") if isinstance(bucket.get("rooms"), dict) else {}
        total = 0.0
        daily_rooms[day] = {}
        for room_id, room in rooms_day.items():
            if not isinstance(room, dict):
                continue
            wh = float(room.get("wh") or 0.0)
            total += wh
            daily_rooms[day][str(room_id)] = wh
            slot = rooms.setdefault(
                str(room_id),
                {"name": room.get("name") or room_id, "wh": 0.0, "days": 0, "warnings": 0, "shutoffs": 0, "power_cycles": 0, "peak_day": "", "peak_wh": 0.0},
            )
            if room.get("name"):
                slot["name"] = room.get("name")
            slot["wh"] += wh
            slot["days"] += 1
            for key in ("warnings", "shutoffs", "power_cycles"):
                slot[key] += int(room.get(key) or 0)
            if wh > slot["peak_wh"]:
                slot["peak_wh"] = wh
                slot["peak_day"] = day
            for device in room.get("devices") or []:
                if not isinstance(device, dict):
                    continue
                part = str(device.get("part") or "").strip()
                label = str(device.get("name") or "Device")
                if part and part not in ("Power", "Configured wattage", "Light"):
                    label = f"{label} ({part})"
                dkey = (str(room_id), label)
                dslot = devices.setdefault(dkey, {"room_id": str(room_id), "name": label, "wh": 0.0})
                dslot["wh"] += float(device.get("wh") or 0.0)
        daily_total[day] = total

        persons_day = bucket.get("persons") if isinstance(bucket.get("persons"), dict) else {}
        daily_home[day] = {}
        for person_id, person in persons_day.items():
            if not isinstance(person, dict):
                continue
            pslot = persons.setdefault(
                str(person_id),
                {"name": person.get("name") or person_id, "seconds_home": 0.0, "seconds_away": 0.0, "days_home": 0, "days_seen": 0, "trackers": {}},
            )
            if person.get("name"):
                pslot["name"] = person.get("name")
            trackers = person.get("trackers") if isinstance(person.get("trackers"), dict) else {}
            best_home = 0.0
            seen = False
            for tracker_id, tracker in trackers.items():
                if not isinstance(tracker, dict):
                    continue
                seen = True
                home = float(tracker.get("seconds_home") or 0.0)
                away = float(tracker.get("seconds_away") or 0.0)
                best_home = max(best_home, home)
                tslot = pslot["trackers"].setdefault(
                    str(tracker_id),
                    {"name": tracker.get("name") or tracker_id, "seconds_home": 0.0, "seconds_away": 0.0, "days_home": 0},
                )
                if tracker.get("name"):
                    tslot["name"] = tracker.get("name")
                tslot["seconds_home"] += home
                tslot["seconds_away"] += away
                if home > 0:
                    tslot["days_home"] += 1
            if seen:
                pslot["days_seen"] += 1
                pslot["seconds_home"] += best_home
                if best_home > 0:
                    pslot["days_home"] += 1
            daily_home[day][str(person_id)] = best_home

    total_wh = sum(daily_total.values())
    peak_day = max(daily_total, key=daily_total.get) if daily_total else ""
    low_day = min(daily_total, key=daily_total.get) if daily_total else ""
    return {
        "calendar": calendar,
        "recorded": recorded,
        "daily_total": daily_total,
        "daily_rooms": daily_rooms,
        "rooms": rooms,
        "devices": devices,
        "persons": persons,
        "daily_home": daily_home,
        "total_wh": total_wh,
        "peak_day": peak_day,
        "low_day": low_day,
    }


# --------------------------------------------------------------------------- pdf


class _ReportPdf:
    """A4 statement with a repeating title bar and a bold red estimate notice."""

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
        self._columns: list[tuple[float, str, str]] | None = None

    # chrome -------------------------------------------------------------

    def _header(self) -> None:
        pdf = self.pdf
        pdf.set_fill_color(*_NAVY)
        pdf.rect(0, 0, 210, 16, "F")
        pdf.set_xy(14, 4)
        pdf.set_font("helvetica", "B", 12)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(140, 8, self.fit(self._title, 138, style="B", size=12), align="L")
        pdf.set_font("helvetica", "", 9)
        pdf.set_xy(140, 4)
        pdf.cell(56, 8, _safe(f"Page {pdf.page_no()}/{{nb}}"), align="R")
        pdf.set_text_color(*_INK)
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
        pdf.set_text_color(*_INK)
        pdf.set_auto_page_break(auto=True, margin=34)

    def need(self, height: float) -> None:
        if self.pdf.get_y() + height > self.pdf.page_break_trigger:
            self.pdf.add_page()

    # text ---------------------------------------------------------------

    def fit(self, text: Any, width: float, style: str = "", size: int = 8) -> str:
        pdf = self.pdf
        pdf.set_font("helvetica", style, size)
        raw = _safe(text)
        if pdf.get_string_width(raw) <= width - 2.4:
            return raw
        trimmed = raw
        while trimmed and pdf.get_string_width(trimmed + "...") > width - 2.4:
            trimmed = trimmed[:-1]
        return f"{trimmed}..." if trimmed else ""

    def section(self, title: str, note: str = "") -> None:
        pdf = self.pdf
        pdf.ln(3)
        self.need(24)
        pdf.set_fill_color(*_TEAL)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(182, 8, _safe(f"  {title}"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)
        if note:
            pdf.ln(1)
            self.muted(note)
        pdf.ln(1.5)

    def day_line(self, heading: str, detail: str) -> None:
        """One recorded day: a heading bar and a single room sentence under it."""
        pdf = self.pdf
        self.need(16)
        pdf.set_fill_color(*_PANEL)
        pdf.set_text_color(*_NAVY)
        pdf.set_font("helvetica", "B", 9)
        pdf.cell(182, 7, self.fit(f"  {heading}", 180, style="B", size=9), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)
        pdf.set_font("helvetica", "", 9)
        pdf.multi_cell(w=182, h=5, text=_safe(detail), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)

    def muted(self, text: str, size: int = 9) -> None:
        pdf = self.pdf
        pdf.set_text_color(*_MUTED)
        pdf.set_font("helvetica", "", size)
        pdf.multi_cell(w=182, h=4.5, text=_safe(text), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)

    def tiles(self, tiles: list[tuple[str, str, str]]) -> None:
        """(label, value, caption) tiles across the page."""
        pdf = self.pdf
        if not tiles:
            return
        self.need(26)
        width = 182 / len(tiles)
        y = pdf.get_y() + 1
        for index, (label, value, caption) in enumerate(tiles):
            x = 14 + index * width
            pdf.set_fill_color(*_PANEL)
            pdf.rect(x + 1, y, width - 2, 22, "F")
            pdf.set_fill_color(*_TEAL)
            pdf.rect(x + 1, y, 1.2, 22, "F")
            pdf.set_xy(x + 4, y + 2)
            pdf.set_font("helvetica", "", 7)
            pdf.set_text_color(*_MUTED)
            pdf.cell(width - 7, 4, self.fit(label, width - 7, size=7))
            pdf.set_xy(x + 4, y + 7)
            pdf.set_font("helvetica", "B", 13)
            pdf.set_text_color(*_NAVY)
            pdf.cell(width - 7, 7, self.fit(value, width - 7, style="B", size=13))
            pdf.set_xy(x + 4, y + 15)
            pdf.set_font("helvetica", "", 7)
            pdf.set_text_color(*_MUTED)
            pdf.cell(width - 7, 4, self.fit(caption, width - 7, size=7))
        pdf.set_xy(14, y + 25)
        pdf.set_text_color(*_INK)

    # tables -------------------------------------------------------------

    def table_header(self, columns: list[tuple[float, str, str]]) -> None:
        pdf = self.pdf
        self._columns = columns
        self.need(14)
        pdf.set_fill_color(*_NAVY)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", "B", 8)
        for width, label, align in columns:
            pdf.cell(width, 7, self.fit(label, width, style="B", size=8), fill=True, align=align)
        pdf.ln(7)
        pdf.set_text_color(*_INK)

    def table_row(self, cells: list[str], *, fill: bool, bold: bool = False, size: int = 8, swatch: tuple[int, int, int] | None = None) -> None:
        pdf = self.pdf
        if not self._columns:
            return
        height = 6.4
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page()
            self.table_header(self._columns)
        pdf.set_fill_color(*(_PANEL if fill else (255, 255, 255)))
        style = "B" if bold else ""
        pdf.set_font("helvetica", style, size)
        pdf.set_text_color(*(_NAVY if bold else _INK))
        x0 = pdf.get_x()
        y0 = pdf.get_y()
        for (width, _label, align), text in zip(self._columns, cells):
            pdf.cell(width, height, self.fit(text, width, style=style, size=size), fill=True, align=align)
        if swatch is not None:
            pdf.set_fill_color(*swatch)
            pdf.rect(x0 + 1.4, y0 + 1.9, 2.6, 2.6, "F")
        pdf.ln(height)
        pdf.set_draw_color(*_GRID)
        y = pdf.get_y()
        pdf.line(14, y, 196, y)

    # charts -------------------------------------------------------------

    def bar_chart(
        self,
        labels: list[str],
        values: list[float],
        *,
        height: float = 52.0,
        unit: str = "kWh",
        color: tuple[int, int, int] = _TEAL,
        highlight: int | None = None,
        average: float | None = None,
        scale: float = 1000.0,
    ) -> None:
        """Vertical bars across the full content width. Values are raw (Wh or seconds)."""
        pdf = self.pdf
        n = len(values)
        self.need(height + 22)
        top = pdf.get_y() + 7
        left = 26.0
        width = 170.0
        bottom = top + height
        peak = max(values) if values else 0.0
        if peak <= 0:
            peak = scale
        nice = self._nice_ceiling(peak / scale)
        pdf.set_draw_color(*_GRID)
        pdf.set_font("helvetica", "", 6.5)
        pdf.set_text_color(*_MUTED)
        for step in range(5):
            y = bottom - height * step / 4
            pdf.line(left, y, left + width, y)
            pdf.set_xy(14, y - 2)
            pdf.cell(10.5, 4, _safe(f"{nice * step / 4:g}"), align="R")
        pdf.set_xy(14, top - 5.5)
        pdf.cell(10.5, 4, _safe(unit), align="R")
        if n:
            slot = width / n
            bar_w = max(1.2, slot * 0.68)
            label_every = max(1, math.ceil(n / 14))
            for index, value in enumerate(values):
                x = left + index * slot + (slot - bar_w) / 2
                h = 0.0 if nice <= 0 else min(height, height * (value / scale) / nice)
                fill = (229, 57, 53) if highlight == index else color
                pdf.set_fill_color(*fill)
                if h > 0:
                    pdf.rect(x, bottom - h, bar_w, h, "F")
                else:
                    pdf.set_fill_color(*_GRID)
                    pdf.rect(x, bottom - 0.6, bar_w, 0.6, "F")
                if index % label_every == 0 or index == n - 1:
                    pdf.set_xy(x - 6 + bar_w / 2, bottom + 1)
                    pdf.set_text_color(*_MUTED)
                    pdf.set_font("helvetica", "", 6.5)
                    pdf.cell(12, 4, _safe(labels[index]), align="C")
        if average is not None and nice > 0 and average > 0:
            y = bottom - min(height, height * (average / scale) / nice)
            pdf.set_draw_color(*_NAVY)
            pdf.set_line_width(0.4)
            pdf.dashed_line(left, y, left + width, y, dash_length=1.6, space_length=1.2)
            pdf.set_line_width(0.2)
            pdf.set_font("helvetica", "B", 6.5)
            label = _safe(f"avg {average / scale:.1f} {unit}/day")
            label_w = pdf.get_string_width(label) + 3
            label_y = top - 5.5
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(left + width - label_w, label_y, label_w, 4, "F")
            pdf.set_xy(left + width - label_w, label_y)
            pdf.set_text_color(*_NAVY)
            pdf.cell(label_w, 4, label, align="R")
        pdf.set_draw_color(*_GRID)
        pdf.set_xy(14, bottom + 7)
        pdf.set_text_color(*_INK)

    def share_bars(self, rows: list[tuple[str, float, tuple[int, int, int]]], total: float, unit_fmt) -> None:
        """Horizontal share bars. rows: (label, value, color)."""
        pdf = self.pdf
        if not rows:
            return
        label_w = 48.0
        value_w = 36.0
        bar_left = 14 + label_w
        bar_w = 182 - label_w - value_w
        peak = max(value for _, value, _ in rows) or 1.0
        for label, value, color in rows:
            self.need(8)
            y = pdf.get_y()
            pdf.set_fill_color(*color)
            pdf.rect(14, y + 1.5, 3, 3.6, "F")
            pdf.set_xy(18.5, y)
            pdf.set_font("helvetica", "", 8.5)
            pdf.set_text_color(*_INK)
            pdf.cell(label_w - 5, 6.5, self.fit(label, label_w - 5, size=8.5))
            pdf.set_fill_color(*_PANEL)
            pdf.rect(bar_left, y + 1, bar_w, 4.6, "F")
            w = bar_w * (value / peak) if peak > 0 else 0
            if w > 0:
                pdf.set_fill_color(*color)
                pdf.rect(bar_left, y + 1, w, 4.6, "F")
            share = (value / total * 100.0) if total > 0 else 0.0
            pdf.set_xy(bar_left + bar_w + 1, y)
            pdf.set_font("helvetica", "B", 8)
            pdf.set_text_color(*_NAVY)
            pdf.cell(value_w - 1, 6.5, self.fit(f"{unit_fmt(value)} {share:.0f}%", value_w - 1, style="B", size=8), align="R")
            pdf.ln(6.8)
        pdf.set_text_color(*_INK)

    @staticmethod
    def _nice_ceiling(value: float) -> float:
        if value <= 0:
            return 1.0
        magnitude = 10 ** math.floor(math.log10(value))
        for mult in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
            if value <= mult * magnitude:
                return mult * magnitude
        return 10 * magnitude


def render_period_pdf(key: str, days: dict[str, Any], generated_label: str) -> bytes:
    """Build one billing-period statement from durable daily summaries."""
    rng = key_range(key)
    if not rng:
        raise ValueError(f"Invalid report key {key!r}")
    start, end = rng
    roll = _rollup(start, end, days)
    doc = _ReportPdf(report_display_title(key))
    pdf = doc.pdf
    pdf.add_page()

    calendar = roll["calendar"]
    recorded = roll["recorded"]
    total_wh = roll["total_wh"]
    n_rec = len(recorded)
    avg_wh = total_wh / n_rec if n_rec else 0.0
    peak_day = roll["peak_day"]
    peak_wh = roll["daily_total"].get(peak_day, 0.0) if peak_day else 0.0

    shown = [day for day in calendar if not recorded or day <= recorded[-1]]

    pdf.set_font("helvetica", "B", 18)
    pdf.set_text_color(*_NAVY)
    pdf.cell(182, 9, _safe("Monthly statement"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(
        w=182,
        h=5.5,
        text=_safe(
            f"{_weekday_day(start)} through {_weekday_day(end)}. "
            f"{n_rec} of {len(calendar)} days recorded. "
            f"Prepared {_pretty_generated(generated_label)}."
        ),
        align="L",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(2)
    doc.tiles(
        [
            ("Total", f"{_kwh(total_wh, 1)} kWh", "estimated for this period"),
            ("Typical day", f"{_kwh(avg_wh, 2)} kWh", "average of recorded days"),
            ("Busiest day", f"{_kwh(peak_wh, 2)} kWh" if peak_day else "-", _weekday_day(peak_day) if peak_day else "no readings yet"),
            ("People", str(len(roll["persons"])), "tracked at home"),
        ]
    )

    doc.section("Usage by day", "Each bar is one recorded day for the whole home. The red bar is the busiest day. The dashed line is the average. Days after the latest reading are left off this chart.")
    if not recorded:
        doc.muted("No daily summaries have been recorded in this period yet.")
    else:
        labels = [_short_day(day) for day in shown]
        values = [float(roll["daily_total"].get(day, 0.0)) for day in shown]
        highlight = shown.index(peak_day) if peak_day in shown else None
        doc.bar_chart(labels, values, highlight=highlight, average=avg_wh)

    rooms = roll["rooms"]
    ordered_rooms = sorted(rooms, key=lambda rid: rooms[rid]["wh"], reverse=True)
    palette = {rid: _ROOM_COLORS[i % len(_ROOM_COLORS)] for i, rid in enumerate(ordered_rooms)}
    doc.section("Usage by room", "Where this period's energy went. The longest bar is the room that used the most.")
    if not ordered_rooms:
        doc.muted("No room energy was recorded in this period.")
    else:
        doc.share_bars(
            [(str(rooms[rid]["name"]), float(rooms[rid]["wh"]), palette[rid]) for rid in ordered_rooms],
            total_wh,
            lambda wh: f"{_kwh(wh, 1)} kWh",
        )
        pdf.ln(2)
        doc.table_header([(100, "Room", "L"), (42, "kWh", "R"), (40, "Share", "R")])
        for index, rid in enumerate(ordered_rooms):
            room = rooms[rid]
            wh = float(room["wh"])
            share = (wh / total_wh * 100.0) if total_wh > 0 else 0.0
            doc.table_row([str(room["name"]), _kwh(wh, 2), f"{share:.0f}%"], fill=index % 2 == 1)
        doc.table_row(["Whole home", _kwh(total_wh, 2), "100%"], fill=False, bold=True)

    doc.section("Each day by room", "One block per day, from the start of the period through the latest reading. The line under the date is that day's rooms, largest first.")
    if not recorded:
        doc.muted("No daily summaries have been recorded in this period yet.")
    else:
        for day in shown:
            total = roll["daily_total"].get(day)
            if total is None:
                doc.day_line(_weekday_day(day), "No reading this day.")
                continue
            ranked = sorted(
                (
                    (rid, float(wh))
                    for rid, wh in (roll["daily_rooms"].get(day) or {}).items()
                    if float(wh) > 0
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            heading = f"{_weekday_day(day)}  -  {_kwh(float(total), 2)} kWh"
            if not ranked:
                doc.day_line(heading, "No room usage recorded.")
                continue
            parts = []
            for rid, wh in ranked:
                name = str(rooms.get(rid, {}).get("name") or rid)
                share = (wh / float(total) * 100.0) if float(total) > 0 else 0.0
                parts.append(f"{name} {_kwh(wh, 2)} kWh ({share:.0f}%)")
            doc.day_line(heading, ", ".join(parts))

    devices = roll["devices"]
    if devices:
        ordered_devices = sorted(devices.values(), key=lambda item: item["wh"], reverse=True)[:12]
        doc.section("Largest appliances", "The twelve devices that used the most energy in this period.")
        doc.table_header([(78, "Device", "L"), (52, "Room", "L"), (26, "kWh", "R"), (26, "Share", "R")])
        for index, device in enumerate(ordered_devices):
            wh = float(device["wh"])
            room = rooms.get(device["room_id"], {})
            share = (wh / total_wh * 100.0) if total_wh > 0 else 0.0
            doc.table_row(
                [str(device["name"]), str(room.get("name") or device["room_id"]), _kwh(wh, 2), f"{share:.0f}%"],
                fill=index % 2 == 1,
            )
        hidden = len(roll["devices"]) - len(ordered_devices)
        if hidden > 0:
            doc.muted(f"{hidden} smaller devices are not listed.")

    persons = roll["persons"]
    doc.section("People at home", "Hours at home for this period. When someone has more than one tracker, the longer reading for each day is used so they are not counted twice.")
    if not persons:
        doc.muted("No one was tracked at home in this period.")
    else:
        doc.table_header([(70, "Person", "L"), (36, "Days home", "R"), (40, "Hours home", "R"), (36, "Hours / day", "R")])
        ordered_people = sorted(persons.values(), key=lambda person: str(person["name"]).lower())
        for index, person in enumerate(ordered_people):
            days_seen = int(person["days_seen"])
            hours_home = float(person["seconds_home"]) / 3600.0
            avg_hours = hours_home / days_seen if days_seen else 0.0
            doc.table_row(
                [str(person["name"]), str(int(person["days_home"])), f"{hours_home:.1f}", f"{avg_hours:.1f}"],
                fill=index % 2 == 1,
            )

    return bytes(pdf.output())


# --------------------------------------------------------------------------- files


def write_period_pdf(data_dir: str, key: str, days: dict[str, Any], generated_label: str) -> Path | None:
    """Write or replace one billing period. Other files are left in place."""
    path = report_path(data_dir, key)
    if path is None:
        return None
    try:
        data = render_period_pdf(path.stem, days, generated_label)
    except Exception as err:  # noqa: BLE001 - never let a report crash the monitor
        _LOGGER.warning("Report render failed for %s: %s", key, err)
        return None
    tmp = path.with_suffix(".pdf.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as err:
        _LOGGER.warning("Report write failed for %s: %s", key, err)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None
    return path


def prune_reports(data_dir: str, keep_keys: set[str]) -> bool:
    """Delete statement files that are not the current monthly PDF. Returns True if any were removed."""
    folder = Path(data_dir) / REPORTS_DIRNAME
    if not folder.is_dir():
        return False
    removed = False
    for path in folder.glob("*.pdf"):
        key = valid_key(path.stem)
        if key is None or key not in keep_keys:
            try:
                path.unlink()
                removed = True
            except OSError as err:
                _LOGGER.warning("Could not remove extra report %s: %s", path.name, err)
    return removed


def list_reports(data_dir: str) -> list[dict[str, Any]]:
    folder = reports_dir(data_dir)
    rows: list[dict[str, Any]] = []
    for path in folder.glob("*.pdf"):
        key = valid_key(path.stem)
        if key is None or path.name != f"{key}.pdf":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rng = key_range(key) or ("", "")
        generated = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
        rows.append(
            {
                "key": key,
                "month": key,
                "start": rng[0],
                "end": rng[1],
                "title": report_display_title(key),
                "label": period_label(key),
                "filename": path.name,
                "bytes": int(stat.st_size),
                "generated_at": generated,
            }
        )
    rows.sort(key=lambda row: (row["start"], row["end"]), reverse=True)
    return rows


def read_report_bytes(data_dir: str, key: str) -> bytes | None:
    path = report_path(data_dir, key)
    if path is None or not path.is_file():
        return None
    try:
        return path.read_bytes()
    except OSError as err:
        _LOGGER.warning("Report read failed for %s: %s", key, err)
        return None
