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


def _clock(label: str) -> str:
    """ASCII time such as 'Oct 18, 8:14 AM'."""
    text = str(label or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text[:16]
    hour = parsed.strftime("%I").lstrip("0") or "12"
    return f"{parsed.strftime('%b')} {parsed.day}, {hour}:{parsed.strftime('%M %p')}"


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
                dtype = str(device.get("type") or "").strip().lower()
                dslot = devices.setdefault(dkey, {"room_id": str(room_id), "name": label, "wh": 0.0, "type": dtype})
                if dtype:
                    dslot["type"] = dtype
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
    """Premium editorial A4 statement. All positioning is in millimeters."""

    INK = (28, 46, 78)
    DARK = (18, 35, 70)
    ACCENT = (38, 96, 196)
    TEAL = (82, 133, 224)
    MINT = (228, 238, 252)
    MUTED = (103, 116, 142)
    DIM = (149, 160, 181)
    LINE = (219, 227, 240)
    PALE = (247, 250, 255)
    WHITE = (255, 255, 255)
    AMBER = (179, 115, 44)
    AMBER_PALE = (252, 246, 236)
    RED = (164, 45, 57)
    RED_PALE = (252, 242, 242)
    NAVY_PALE = (235, 243, 243)
    LEFT = 14.0
    RIGHT = 196.0
    WIDTH = 182.0
    ROOM_COLORS = (
        (38, 96, 196), (82, 133, 224), (115, 154, 231),
        (73, 113, 191), (119, 136, 202), (97, 122, 171),
        (146, 167, 223), (92, 126, 211),
    )

    def __init__(self, title: str, period: str = "") -> None:
        from fpdf import FPDF
        self.title, self.period = title, period
        self.pdf = FPDF(format="A4", unit="mm")
        self.pdf.set_margins(14, 33, 14)
        self.pdf.set_auto_page_break(auto=True, margin=34)
        self.pdf.alias_nb_pages()
        self.pdf.set_title(_safe(title))
        self.pdf.set_author("Home Energy")
        self.pdf.set_subject("Estimated household energy statement")
        self.pdf.header = self._header  # type: ignore[method-assign]
        self.pdf.footer = self._footer  # type: ignore[method-assign]
        self._columns: list[tuple[float, str, str]] = []
        self._table_title: str = ""

    def font(self, size: float = 8.5, bold: bool = False, color=None) -> None:
        self.pdf.set_font("helvetica", "B" if bold else "", size)
        self.pdf.set_text_color(*(color or self.INK))

    def _header(self) -> None:
        p = self.pdf
        p.set_fill_color(*self.ACCENT)
        p.rect(14, 11.2, 3, 11, "F")
        p.set_fill_color(*self.DARK)
        p.rect(14, 11.2, 3, 2, "F")
        self.font(10.7, True, self.DARK)
        p.set_xy(21, 11.3)
        p.cell(82, 6.0, "Home Energy")
        self.font(7.1, False, self.MUTED)
        p.set_xy(21, 17.5)
        p.cell(96, 4.1, "Residential Energy Intelligence")
        self.font(8, True, self.ACCENT)
        p.set_xy(128, 12)
        p.cell(68, 4.6, "Period Statement", align="R")
        self.font(7.3, False, self.MUTED)
        p.set_xy(128, 18.1)
        p.cell(68, 4.0, f"Page {p.page_no()} / {{nb}}", align="R")
        p.set_draw_color(*self.LINE)
        p.set_line_width(0.25)
        p.line(14, 27.5, 196, 27.5)
        p.set_y(33)

    def _footer(self) -> None:
        p = self.pdf
        p.set_auto_page_break(auto=False)
        p.set_draw_color(*self.LINE)
        p.set_line_width(0.2)
        p.line(14, 263.0, 196, 263.0)
        p.set_fill_color(*self.RED_PALE)
        p.rect(14, 268.4, 182, 18.3, "F")
        p.set_fill_color(*self.RED)
        p.rect(14, 268.4, 1.3, 18.3, "F")
        self.font(7.8, True, self.RED)
        p.set_xy(18.7, 270)
        p.multi_cell(w=172.4, h=4.5, text=_safe(_DISCLAIMER), align="L",
                     new_x="LMARGIN", new_y="NEXT")
        p.set_auto_page_break(auto=True, margin=34)

    def need(self, height: float) -> None:
        if self.pdf.get_y() + height > self.pdf.page_break_trigger:
            self.pdf.add_page()

    def space(self, mm: float) -> None:
        self.pdf.set_y(self.pdf.get_y() + mm)

    def rule(self, y: float | None = None, color=None) -> None:
        p = self.pdf
        at = p.get_y() if y is None else y
        p.set_draw_color(*(color or self.LINE))
        p.set_line_width(0.2)
        p.line(14, at, 196, at)

    def fit(self, value: Any, width: float, size: float = 8.2,
            bold: bool = False) -> str:
        """For static labels only. Customer data uses wrapped row cells."""
        self.pdf.set_font("helvetica", "B" if bold else "", size)
        p = self.pdf
        v = _safe(value)
        if p.get_string_width(v) <= width:
            return v
        while v and p.get_string_width(v + "...") > width:
            v = v[:-1]
        return v + "..." if v else ""

    def wrap(self, value: Any, width: float, size: float = 8.0,
             bold: bool = False) -> list[str]:
        self.font(size, bold)
        p = self.pdf
        result: list[str] = []
        for para in _safe(value).replace("\r", "").split("\n"):
            if not para.strip():
                result.append("")
                continue
            current = ""
            for word in para.split():
                attempt = (current + " " + word).strip()
                if p.get_string_width(attempt) <= width:
                    current = attempt
                    continue
                if current:
                    result.append(current)
                current = ""
                if p.get_string_width(word) <= width:
                    current = word
                    continue
                part = ""
                for c in word:
                    if part and p.get_string_width(part + c) > width:
                        result.append(part)
                        part = c
                    else:
                        part += c
                current = part
            result.append(current)
        return result or [""]

    def paragraph(self, value: str, size: float = 8.2, color=None,
                  x: float = 14, w: float = 182, line_height: float = 4.4,
                  bold: bool = False) -> None:
        lines = self.wrap(value, w - 1, size, bold)
        self.need(len(lines) * line_height)
        self.font(size, bold, color)
        for line in lines:
            self.pdf.set_x(x)
            self.pdf.cell(w, line_height, line, new_x="LMARGIN", new_y="NEXT")

    def section(self, number: str, title: str, subtitle: str = "",
                reserve: float = 20) -> None:
        self.space(2.0)
        self.need(reserve)
        p = self.pdf
        y = p.get_y()
        self.font(7.3, True, self.ACCENT)
        p.set_xy(14, y + 1.1)
        p.cell(13, 5.2, number)
        self.font(11.9, True, self.DARK)
        p.set_xy(28, y)
        p.cell(168, 6.2, self.fit(title, 165, 11.9, True))
        p.set_y(y + 7.2)
        self.rule()
        self.space(1.2)
        if subtitle:
            self.paragraph(subtitle, 7.2, self.MUTED, line_height=3.8)
            self.space(0.5)

    def hero(self, key: str, start: str, end: str, generated: str,
             total_wh: float) -> None:
        p = self.pdf
        y = p.get_y()
        p.set_fill_color(*self.DARK)
        p.rect(14, y, 182, 31.5, "F")
        p.set_fill_color(*self.TEAL)
        p.rect(14, y, 1.5, 31.5, "F")
        p.set_fill_color(42, 82, 166)
        p.rect(144, y, 52, 31.5, "F")
        self.font(7.6, True, (147, 212, 203))
        p.set_xy(21, y + 3.1)
        p.cell(110, 5, "Your Monthly Energy Record")
        self.font(17.2, True, self.WHITE)
        p.set_xy(21, y + 8.2)
        p.cell(116, 10.8, "Electricity Statement")
        self.font(10.1, False, (209, 226, 227))
        p.set_xy(21, y + 21.0)
        p.cell(118, 6.1, self.fit(period_label(key), 115, 10.1))
        self.font(7.5, True, (182, 212, 210))
        p.set_xy(148.5, y + 3.2)
        p.cell(42, 5, "Total Estimate", align="R")
        amount = _kwh(total_wh, 2)
        amount_font = 21.0 if len(amount) < 9 else 16.0
        self.font(amount_font, True, self.WHITE)
        p.set_xy(148, y + 11.5)
        p.cell(43, 13, amount, align="R")
        self.font(10.0, False, (167, 222, 210))
        p.set_xy(149, y + 25.2)
        p.cell(42, 5, "kWh", align="R")
        p.set_y(y + 34.5)
        self.font(7.1, True, self.MUTED)
        p.set_xy(14, p.get_y())
        p.cell(32, 4.2, "Billing Window")
        p.set_xy(104, p.get_y())
        p.cell(92, 4.2, "Statement Prepared")
        yy = p.get_y() + 4.2
        self.font(8.7, True, self.INK)
        p.set_xy(14, yy)
        p.cell(88, 5.2, self.fit(f"{_weekday_day(start)}  -  {_weekday_day(end)}", 87, 8.7, True))
        self.font(8.6, False, self.INK)
        p.set_xy(104, yy)
        p.cell(92, 5.2, self.fit(_pretty_generated(generated), 90, 8.6))
        p.set_y(yy + 6.0)

    def metrics(self, avg: float, peak_day: str, peak: float,
                low_day: str, low: float, outages: int) -> None:
        p = self.pdf
        y = p.get_y()
        self.need(17.8)
        data = [
            ("Recorded-Day Avg", f"{_kwh(avg, 2)} kWh", "Average with a reading"),
            ("Highest Day", f"{_kwh(peak, 2)} kWh" if peak_day else "-", _weekday_day(peak_day) if peak_day else "No reading"),
            ("Lowest Day", f"{_kwh(low, 2)} kWh" if low_day else "-", _weekday_day(low_day) if low_day else "No reading"),
            ("Outage Episodes", str(outages), "Collapsed connection log"),
        ]
        width = 44.75
        for idx, (label, value, desc) in enumerate(data):
            x = 14 + idx * 45.75
            p.set_fill_color(*self.PALE)
            p.rect(x, y, width, 16.4, "F")
            p.set_fill_color(*self.ACCENT)
            p.rect(x, y, 0.9, 16.4, "F")
            self.font(6.4, True, self.MUTED)
            p.set_xy(x + 3.0, y + 1.4)
            p.cell(width - 6.6, 4, self.fit(label, width - 6.6, 6.7, True))
            self.font(11.8 if len(value) < 13 else 9.8, True, self.DARK)
            p.set_xy(x + 3.0, y + 4.6)
            p.cell(width - 6.0, 6.6, self.fit(value, width - 6.0, 11.8 if len(value) < 13 else 9.8, True))
            self.font(6.4, False, self.MUTED)
            p.set_xy(x + 3.0, y + 11.7)
            p.cell(width - 6.6, 4, self.fit(desc, width - 6.6, 6.8))
        p.set_y(y + 18.1)

    def coverage(self, recorded: int, missing: int, future: int,
                 total: int) -> None:
        self.need(14)
        p = self.pdf
        y = p.get_y()
        self.font(7.2, True, self.DARK)
        p.set_xy(14, y)
        p.cell(91, 4.2, "Reading Completeness")
        self.font(7.2, False, self.MUTED)
        p.set_xy(100, y)
        p.cell(96, 5, f"{recorded} of {total} calendar days recorded", align="R")
        y += 5
        p.set_fill_color(*self.LINE)
        p.rect(14, y, 182, 4.1, "F")
        cur = 14.0
        if total:
            for n, color in ((recorded, self.ACCENT), (missing, self.AMBER), (future, (185, 195, 196))):
                if n:
                    w = 182 * n / total
                    p.set_fill_color(*color)
                    p.rect(cur, y, w, 4.1, "F")
                    cur += w
        y += 5
        labels = [(recorded, "READINGS", self.ACCENT),
                  (missing, "UNAVAILABLE", self.AMBER),
                  (future, "UPCOMING", self.MUTED)]
        for i, (num, label, color) in enumerate(labels):
            x = 14 + i * 61
            p.set_fill_color(*color)
            p.rect(x, y + 0.9, 2.3, 2.3, "F")
            self.font(7.0, True, self.INK)
            p.set_xy(x + 4.3, y)
            p.cell(54, 3.7, f"{num} {label.title()}")
        p.set_y(y + 4.8)

    def trend(self, calendar: list[str], daily: dict[str, float],
              as_of: date | None, avg: float) -> None:
        self.need(43)
        p = self.pdf
        y0 = p.get_y()
        self.font(8.2, True, self.DARK)
        p.set_xy(14, y0)
        p.cell(100, 4.4, "Energy Trend")
        self.font(7.3, False, self.MUTED)
        p.set_xy(100, y0)
        p.cell(96, 4.4, "kWh Per Calendar Day", align="R")
        top = y0 + 8
        bottom = top + 20.8
        left = 29.0
        chart_w = 167.0
        peak = max([float(v) for v in daily.values()] or [0.0])
        maximum = self.nice(max(peak, avg) / 1000.0)
        self.font(6.7, False, self.MUTED)
        p.set_draw_color(*self.LINE)
        for step in range(4):
            level = maximum * step / 3
            gy = bottom - 20.8 * step / 3
            p.set_line_width(0.17)
            p.line(left, gy, left + chart_w, gy)
            p.set_xy(14, gy - 1.9)
            p.cell(12, 4, f"{level:.2f}".rstrip("0").rstrip("."), align="R")
        n = len(calendar)
        if n:
            slot = chart_w / n
            bw = min(7.4, max(0.25, slot * 0.61))
            label_step = max(1, math.ceil(n / 10))
            for i, day in enumerate(calendar):
                value = daily.get(day)
                center = left + (i + 0.5) * slot
                x = center - bw / 2
                if value is not None:
                    h = 20.8 * (max(0, float(value)) / 1000.0) / maximum
                    h = min(20.8, h)
                    p.set_fill_color(*self.ACCENT)
                    if h > 0:
                        p.rect(x, bottom - h, bw, h, "F")
                    else:
                        p.circle(center, bottom - 1.2, 0.7, "F")
                elif as_of is not None and day > as_of.isoformat():
                    p.set_draw_color(187, 199, 200)
                    p.set_line_width(0.5)
                    p.line(x, bottom - 1.6, x + bw, bottom - 1.6)
                else:
                    p.set_fill_color(*self.AMBER)
                    p.rect(x, bottom - 1.9, bw, 1.9, "F")
                if i % label_step == 0 or i == n - 1:
                    label = _short_day(day) if n <= 12 else str(_parse_day(day).day if _parse_day(day) else day)
                    self.font(6.4, False, self.MUTED)
                    p.set_xy(center - 10, bottom + 1.1)
                    p.cell(20, 4, _safe(label), align="C")
        if avg > 0:
            line_y = bottom - min(20.8, (avg / 1000.0) / maximum * 20.8)
            p.set_draw_color(*self.DARK)
            p.set_line_width(0.23)
            p.set_dash_pattern(dash=1.6, gap=1.4)
            p.line(left, line_y, left + chart_w, line_y)
            p.set_dash_pattern()
            self.font(6.4, True, self.DARK)
            caption = f"AVG {_kwh(avg, 2)}"
            w = p.get_string_width(caption) + 4
            p.set_fill_color(*self.WHITE)
            p.rect(196 - w, top - 3.5, w, 4.1, "F")
            p.set_xy(196 - w, top - 3.5)
            p.cell(w, 4.1, caption, align="R")
        p.set_y(bottom + 5.6)
        self.font(7, False, self.MUTED)
        p.cell(182, 4, "Solid: Recorded    Orange: Unavailable Reading    Grey: Future Day    Dashed: Recorded-Day Average",
               new_x="LMARGIN", new_y="NEXT")

    @staticmethod
    def nice(value: float) -> float:
        if value <= 0:
            return 1.0
        unit = 10 ** math.floor(math.log10(value))
        for k in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
            if value <= k * unit:
                return k * unit
        return unit * 10

    def room_rows(self, rows: list[tuple[str, float]], total: float) -> None:
        p = self.pdf
        if not rows:
            self.paragraph("No room energy was recorded.", color=self.MUTED)
            return
        self.need(15)
        y = p.get_y()
        cursor = 14.0
        for i, (_, value) in enumerate(rows):
            w = 182 * value / total if total > 0 else 0
            if w > 0:
                p.set_fill_color(*self.ROOM_COLORS[i % len(self.ROOM_COLORS)])
                p.rect(cursor, y, w, 3.8, "F")
                cursor += w
        if total <= 0:
            p.set_fill_color(*self.LINE)
            p.rect(14, y, 182, 3.8, "F")
        p.set_y(y + 5.7)
        self.font(6.3, True, self.MUTED)
        yy = p.get_y()
        p.set_xy(14, yy)
        p.cell(109, 3.9, "Room")
        p.set_xy(127, yy)
        p.cell(43, 3.9, "Energy", align="R")
        p.set_xy(173, yy)
        p.cell(23, 3.9, "Share", align="R")
        p.set_y(yy + 4.4)
        self.rule()
        for index, (name, wh) in enumerate(rows):
            lines = self.wrap(name, 103, 7.8)
            h = max(5.8, 1.5 + 3.6 * len(lines))
            self.need(h)
            y = p.get_y()
            self.font(7.8, False, self.INK)
            p.set_fill_color(*self.ROOM_COLORS[index % len(self.ROOM_COLORS)])
            p.rect(14, y + 1.8, 2.0, 2.0, "F")
            for j, part in enumerate(lines):
                p.set_xy(18.0, y + 0.9 + j * 3.6)
                p.cell(103, 3.5, part)
            self.font(7.9, True, self.DARK)
            p.set_xy(126, y + 0.8)
            p.cell(44, 3.8, f"{_kwh(wh, 2)} kWh", align="R")
            self.font(7.6, False, self.MUTED)
            p.set_xy(173, y + 0.8)
            p.cell(23, 3.8, f"{(wh / total * 100) if total else 0:.0f}%", align="R")
            p.set_y(y + h)
            self.rule()
        self.need(8)
        y = p.get_y()
        self.font(8.2, True, self.DARK)
        p.set_xy(14, y + 1.1)
        p.cell(110, 5.2, "Total Household")
        p.set_xy(122, y + 1.1)
        p.cell(48, 5.2, f"{_kwh(total, 2)} kWh", align="R")
        p.set_xy(173, y + 0.8)
        p.cell(23, 5.2, "100%" if total > 0 else "0%", align="R")
        p.set_y(y + 6.2)

    def table_header(self, columns: list[tuple[float, str, str]],
                     title: str = "") -> None:
        if abs(sum(c[0] for c in columns) - 182.0) > .001:
            raise AssertionError("All tables must be exactly 182 mm wide")
        self._columns = columns
        if title:
            self._table_title = title
        self.need(11.2)
        p = self.pdf
        y = p.get_y()
        p.set_fill_color(*self.DARK)
        p.rect(14, y, 182, 6.4, "F")
        self.font(6.6, True, self.WHITE)
        x = 14
        for width, label, align in columns:
            p.set_xy(x + 2.0, y + 1.35)
            p.cell(width - 4, 3.9, self.fit(label, width - 4, 6.6, True), align=align)
            x += width
        p.set_y(y + 6.4)

    def table_row(self, cells: list[Any], index: int = 0,
                  bold: bool = False, size: float = 8.0,
                  state: str = "") -> None:
        if not self._columns or len(cells) != len(self._columns):
            raise ValueError("A table header with matching columns is required")
        texts = [self.wrap(val, width - 4.6, size, bold) for val, (width, _, _) in zip(cells, self._columns)]
        nlines = max(len(parts) for parts in texts)
        h = 2.8 + 3.8 * nlines
        if self.pdf.get_y() + h > self.pdf.page_break_trigger:
            self.pdf.add_page()
            self.table_header(self._columns)
        p = self.pdf
        y = p.get_y()
        if index % 2:
            p.set_fill_color(*self.PALE)
            p.rect(14, y, 182, h, "F")
        x = 14
        for j, (width, _, align) in enumerate(self._columns):
            color = self.RED if state == "offline" and j == len(texts) - 1 else self.DARK if bold else self.INK
            self.font(size, bold or (state == "offline" and j == len(texts) - 1), color)
            for li, line in enumerate(texts[j]):
                p.set_xy(x + 2, y + 1.0 + li * 3.8)
                p.cell(width - 4, 3.6, line, align=align)
            x += width
        p.set_y(y + h)
        self.rule()

    def insight_cards(self, groups: list[tuple[str, str, str]]) -> None:
        """Two columns; each value is derived from the existing rollup only."""
        p = self.pdf
        card_w = 89.3
        for idx in range(0, len(groups), 2):
            self.need(19)
            y = p.get_y()
            for column, (label, value, detail) in enumerate(groups[idx:idx + 2]):
                x = 14 + column * 92.7
                p.set_fill_color(*self.PALE)
                p.rect(x, y, card_w, 17.0, "F")
                p.set_fill_color(*self.ACCENT)
                p.rect(x, y, 1, 17.0, "F")
                self.font(7, True, self.MUTED)
                p.set_xy(x + 4, y + 1.6)
                p.cell(81, 3.9, self.fit(label, 80, 7, True))
                self.font(11.3, True, self.DARK)
                p.set_xy(x + 4, y + 5.4)
                p.cell(81, 5.2, self.fit(value, 80, 10.7, True))
                self.font(7.0, False, self.MUTED)
                p.set_xy(x + 4, y + 11.2)
                p.cell(81, 4.0, self.fit(detail, 80, 7))
            p.set_y(y + 18.8)

    def daily_card(self, day: str, state: str, total_wh: float | None,
                   room_list: list[tuple[str, float]], avg: float,
                   home_line: str) -> None:
        p = self.pdf
        if state == "future":
            self.need(11.2)
            y = p.get_y()
            p.set_fill_color(*self.PALE)
            p.rect(14, y, 182, 9.5, "F")
            p.set_fill_color(*(178, 193, 192))
            p.rect(14, y, 1.5, 9.5, "F")
            self.font(8.5, True, self.INK)
            p.set_xy(18.7, y + 2.0)
            p.cell(94, 4.8, _weekday_day(day))
            self.font(7.4, True, self.MUTED)
            p.set_xy(114, y + 2.1)
            p.cell(78, 4.4, "NOT YET ELAPSED", align="R")
            p.set_y(y + 11.4)
            return
        if state == "missing":
            self.need(11.2)
            y = p.get_y()
            p.set_fill_color(*self.AMBER_PALE)
            p.rect(14, y, 182, 9.5, "F")
            p.set_fill_color(*self.AMBER)
            p.rect(14, y, 1.5, 9.5, "F")
            self.font(8.5, True, self.INK)
            p.set_xy(18.7, y + 2)
            p.cell(96, 4.8, _weekday_day(day))
            self.font(7.3, True, self.AMBER)
            p.set_xy(116, y + 2)
            p.cell(76, 4.8, "NO READING STORED", align="R")
            p.set_y(y + 11.4)
            return
        # For a recorded day, keep all room rows and presence together when feasible.
        count = max(1, len(room_list))
        height = 10.5 + count * 5.0 + (4.6 if avg > 0 else 0) + (4.4 if home_line else 0) + 3.0
        if height <= 105:
            self.need(height + 2)
        else:
            self.need(22)
        y = p.get_y()
        p.set_fill_color(*self.NAVY_PALE)
        p.rect(14, y, 182, 9.6, "F")
        p.set_fill_color(*self.ACCENT)
        p.rect(14, y, 1.55, 9.6, "F")
        self.font(8.6, True, self.DARK)
        p.set_xy(18.7, y + 1.8)
        p.cell(97, 5.2, _weekday_day(day))
        self.font(9.2, True, self.ACCENT)
        p.set_xy(116, y + 1.7)
        p.cell(76, 5.4, f"{_kwh(total_wh or 0, 2)} kWh", align="R")
        p.set_y(y + 10.8)
        if room_list:
            for room_name, wh in room_list:
                lines = self.wrap(room_name, 90, 7.9)
                h = max(4.9, 4.1 * len(lines) + 0.8)
                self.need(h)
                yy = p.get_y()
                self.font(7.9, False, self.INK)
                for line_i, line in enumerate(lines):
                    p.set_xy(20, yy + line_i * 4.1)
                    p.cell(89, 4.0, line)
                share = wh / total_wh if total_wh and total_wh > 0 else 0
                p.set_fill_color(*self.LINE)
                p.rect(111, yy + 1.4, 36, 2.3, "F")
                if share > 0:
                    p.set_fill_color(*self.TEAL)
                    p.rect(111, yy + 1.4, 36 * min(share, 1), 2.3, "F")
                self.font(7.8, True, self.INK)
                p.set_xy(149, yy)
                p.cell(29, 4.4, f"{_kwh(wh, 2)} kWh", align="R")
                self.font(7.6, False, self.MUTED)
                p.set_xy(179, yy)
                p.cell(14, 4.4, f"{share * 100:.0f}%", align="R")
                p.set_y(yy + h)
        else:
            self.paragraph("No positive room-level usage was stored.", 7.8, self.MUTED, x=20, w=173, line_height=4.5)
        if avg > 0:
            compared = _vs_typical(float(total_wh or 0), avg)
            if compared:
                self.paragraph(compared, 7.3, self.MUTED, x=20, w=172, line_height=4.3)
        if home_line:
            self.paragraph(home_line, 7.3, self.ACCENT, x=20, w=172, line_height=4.2)
        self.space(3)

    def note(self, heading: str, text: str, tint: str = "neutral") -> None:
        bg = self.AMBER_PALE if tint == "amber" else self.PALE
        tone = self.AMBER if tint == "amber" else self.ACCENT
        lines = self.wrap(text, 171, 7.7)
        height = 9 + len(lines) * 4.2
        self.need(height + 2)
        p = self.pdf
        y = p.get_y()
        p.set_fill_color(*bg)
        p.rect(14, y, 182, height, "F")
        p.set_fill_color(*tone)
        p.rect(14, y, 1.2, height, "F")
        self.font(7.0, True, tone)
        p.set_xy(19, y + 2.5)
        p.cell(171, 4.0, heading.upper())
        self.font(7.7, False, self.MUTED)
        for i, line in enumerate(lines):
            p.set_xy(19, y + 7 + i * 4.2)
            p.cell(171, 4.1, line)
        p.set_y(y + height + 2)


def _vs_typical(total: float, avg: float) -> str:
    if avg <= 0:
        return ""
    delta = float(total) - avg
    if abs(delta) < 5:
        return f"In line with a typical day ({_kwh(avg, 2)} kWh)."
    word = "above" if delta > 0 else "below"
    return f"{_kwh(abs(delta), 2)} kWh {word} a typical day ({_kwh(avg, 2)} kWh)."


def _home_line(roll: dict[str, Any], day: str) -> str:
    people = (roll.get("daily_home") or {}).get(day) or {}
    persons = roll.get("persons") or {}
    bits: list[str] = []
    ranked = sorted(people.items(), key=lambda item: float(item[1] or 0.0), reverse=True)
    for person_id, seconds in ranked:
        seconds = float(seconds or 0.0)
        if seconds <= 0:
            continue
        name = str((persons.get(person_id) or {}).get("name") or person_id)
        bits.append(f"{name} {seconds / 3600.0:.1f} h")
    if not bits:
        return ""
    return "At home: " + ", ".join(bits[:4])


def _span_label(start: str, end: str) -> str:
    try:
        opened = datetime.fromisoformat(str(start or "").strip())
        closed = datetime.fromisoformat(str(end or "").strip())
        seconds = int((closed - opened).total_seconds())
    except (TypeError, ValueError):
        return ""
    if seconds < 60:
        return "under 1 min"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {mins} min" if mins else f"{hours} h"
    days, rem = divmod(hours, 24)
    return f"{days} d {rem} h" if rem else f"{days} d"


def _insight_lines(roll: dict[str, Any]) -> list[str]:
    """Short energy comparisons. Missing days are left out of every average."""
    daily = roll["daily_total"]
    n = len(daily)
    total = float(roll["total_wh"])
    if n == 0:
        return ["No energy readings were stored in this period."]
    avg = total / n
    peak_day = str(roll["peak_day"] or "")
    low_day = str(roll["low_day"] or "")
    peak_wh = float(daily.get(peak_day, 0.0))
    low_wh = float(daily.get(low_day, 0.0))
    lines = [f"Typical recorded day: {_kwh(avg, 2)} kWh across {n} days with a reading."]
    if n == 1:
        lines.append(
            f"Only {_weekday_day(peak_day)} has a reading, {_kwh(peak_wh, 2)} kWh. "
            "Comparisons need at least two recorded days."
        )
    else:
        lines.append(
            f"Busiest day was {_weekday_day(peak_day)} at {_kwh(peak_wh, 2)} kWh, "
            f"{_kwh(max(peak_wh - avg, 0.0), 2)} kWh above a typical day."
        )
        if low_day and low_day != peak_day:
            lines.append(
                f"Quietest day was {_weekday_day(low_day)} at {_kwh(low_wh, 2)} kWh, "
                f"{_kwh(max(avg - low_wh, 0.0), 2)} kWh below a typical day."
            )
        weekday: list[float] = []
        weekend: list[float] = []
        for day, wh in daily.items():
            parsed = _parse_day(str(day))
            if parsed is None:
                continue
            (weekday if parsed.weekday() < 5 else weekend).append(float(wh))
        if weekday and weekend:
            lines.append(
                f"Weekdays averaged {_kwh(sum(weekday) / len(weekday), 2)} kWh. "
                f"Weekends averaged {_kwh(sum(weekend) / len(weekend), 2)} kWh."
            )
    rooms = roll["rooms"]
    ordered = sorted(rooms, key=lambda rid: float(rooms[rid]["wh"]), reverse=True)
    if ordered:
        top = rooms[ordered[0]]
        share = (float(top["wh"]) / total * 100.0) if total > 0 else 0.0
        if len(ordered) > 1:
            second = rooms[ordered[1]]
            diff = max(float(top["wh"]) - float(second["wh"]), 0.0)
            lines.append(
                f"{top['name']} used the most, {_kwh(top['wh'], 2)} kWh ({share:.0f}%). "
                f"That is {_kwh(diff, 2)} kWh more than {second['name']}."
            )
        else:
            lines.append(f"{top['name']} was the only room with stored energy, {_kwh(top['wh'], 2)} kWh.")
    devices = list(roll["devices"].values())
    if devices:
        device = max(devices, key=lambda item: float(item["wh"]))
        room_name = str(rooms.get(device["room_id"], {}).get("name") or device["room_id"])
        share = (float(device["wh"]) / total * 100.0) if total > 0 else 0.0
        lines.append(
            f"{device['name']} in {room_name} was the largest device at {_kwh(device['wh'], 2)} kWh ({share:.0f}%)."
        )
    warnings = sum(int(room.get("warnings") or 0) for room in rooms.values())
    shutoffs = sum(int(room.get("shutoffs") or 0) for room in rooms.values())
    cycles = sum(int(room.get("power_cycles") or 0) for room in rooms.values())
    activity = []
    if warnings:
        activity.append(f"{warnings} warning" if warnings == 1 else f"{warnings} warnings")
    if shutoffs:
        activity.append(f"{shutoffs} shutoff" if shutoffs == 1 else f"{shutoffs} shutoffs")
    if cycles:
        activity.append(f"{cycles} power cycle" if cycles == 1 else f"{cycles} power cycles")
    if activity:
        lines.append("Threshold activity this period: " + ", ".join(activity) + ".")
    if roll["persons"]:
        home_totals: list[float] = []
        away_totals: list[float] = []
        for day, wh in daily.items():
            present = any(float(seconds or 0) > 0 for seconds in (roll["daily_home"].get(day) or {}).values())
            (home_totals if present else away_totals).append(float(wh))
        if home_totals and away_totals:
            lines.append(
                f"Days with someone home averaged {_kwh(sum(home_totals) / len(home_totals), 2)} kWh. "
                f"Days with no one tracked at home averaged {_kwh(sum(away_totals) / len(away_totals), 2)} kWh."
            )
    return lines


def _alert_label(event: dict[str, Any]) -> str:
    if event.get("door_reminder"):
        return "Reminder"
    kind = str(event.get("type") or "")
    return {
        "warning": "Warning",
        "shutoff": "Shutoff",
        "power_cycle": "Power cycle",
        "phase_change": "Phase change",
    }.get(kind, "Alert")


def _alert_detail(event: dict[str, Any]) -> str:
    parts: list[str] = []
    outlet = str(event.get("outlet_name") or "").strip()
    if outlet:
        parts.append(outlet)
    if event.get("from_phase") is not None and event.get("to_phase") is not None:
        parts.append(f"Phase {event.get('from_phase')} to {event.get('to_phase')}")
    if event.get("room_watts") is not None:
        parts.append(f"Room {event.get('room_watts')} W")
    if event.get("room_threshold") not in (None, ""):
        parts.append(f"Room limit {event.get('room_threshold')} W")
    if event.get("outlet_watts") is not None:
        parts.append(f"Outlet {event.get('outlet_watts')} W")
    if event.get("outlet_threshold") not in (None, ""):
        parts.append(f"Outlet limit {event.get('outlet_threshold')} W")
    if event.get("kwh_limit") not in (None, ""):
        parts.append(f"{event.get('kwh_limit')} kWh mark")
    if event.get("alert_kind") == "room_kwh":
        parts.append("Daily room energy alert")
    elif event.get("alert_kind") == "home_kwh":
        parts.append("Daily home energy alert")
    reminder = str(event.get("door_reminder") or "").replace("_", " ").strip()
    if reminder:
        parts.append(reminder)
    if event.get("outlets_cycled") not in (None, ""):
        parts.append(f"{event.get('outlets_cycled')} outlets cycled")
    return ", ".join(parts) if parts else "Logged alert"


def _alert_was_spoken(event: dict[str, Any]) -> bool:
    """A row belongs on the statement only when an announcement was spoken."""
    if event.get("tts_succeeded") is False:
        return False
    return bool(str(event.get("tts_message") or "").strip())


def _alert_spoken(event: dict[str, Any]) -> str:
    return str(event.get("tts_message") or "").strip()


def _alert_counts(alerts: list[dict[str, Any]] | None) -> tuple[int, int, int, list[dict[str, Any]]]:
    """Warnings exclude reminders that are stored as warnings but not counted."""
    warnings = shutoffs = cycles = 0
    rows: list[dict[str, Any]] = []
    for event in alerts or []:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("type") or "")
        if kind == "warning" and not event.get("door_reminder") and event.get("counted_as_warning") is not False:
            warnings += 1
        elif kind == "shutoff":
            shutoffs += 1
        elif kind == "power_cycle":
            cycles += 1
        if kind in ("warning", "phase_change", "shutoff", "power_cycle") and _alert_was_spoken(event):
            rows.append(event)
    rows.sort(key=lambda event: str(event.get("ts") or ""))
    return warnings, shutoffs, cycles, rows


def _draw_alert_counts(doc: _ReportPdf, warnings: int, shutoffs: int, cycles: int) -> None:
    blocks = (
        ("Warnings", warnings, "A spoken alert when a room or outlet goes over a limit you set. The outlet keeps running."),
        ("Shutoffs", shutoffs, "A short automatic pause of one outlet that crossed a limit you set. That outlet turns back on after the pause."),
        ("Power cycles", cycles, "An automatic off, then on, of the room outlets after repeated warnings, using the enforcement phase you configured."),
    )
    for label, count, explanation in blocks:
        doc.need(12)
        y = doc.pdf.get_y()
        doc.font(8, True, doc.MUTED)
        doc.pdf.set_xy(14, y)
        doc.pdf.cell(130, 5.2, label)
        doc.font(12, True, doc.DARK)
        doc.pdf.set_xy(144, y)
        doc.pdf.cell(52, 5.2, str(int(count)), align="R")
        doc.pdf.set_y(y + 6.2)
        doc.paragraph(explanation, 8.0, doc.INK, line_height=4.2)
        doc.space(1.4)


_TYPE_WORD = {
    "outlet": "outlet",
    "single_outlet": "outlet",
    "light": "light",
    "vent": "vent",
    "wall_heater": "heater",
    "minisplit": "minisplit",
    "stove": "stove",
    "microwave": "microwave",
    "fridge": "fridge",
    "door": "door",
    "window": "window",
}


def smart_device_name(name: Any, appliance_type: Any) -> str:
    """Append the appliance type once when the user's name does not already say it."""
    label = str(name or "").strip() or "Device"
    word = _TYPE_WORD.get(str(appliance_type or "").strip().lower(), "")
    if not word or word in label.lower():
        return label
    return f"{label} {word}"


def _fits(doc: _ReportPdf, height: float) -> bool:
    return doc.pdf.get_y() + height <= doc.pdf.page_break_trigger - 1


def _write_capped(doc: _ReportPdf, text: str, size: float = 8.2, color=None,
                  line_height: float = 4.3, bold: bool = False) -> None:
    """Write wrapped lines, and stop rather than open another page."""
    lines = doc.wrap(text, 180, size, bold)
    doc.font(size, bold, color or doc.INK)
    for line in lines:
        if not _fits(doc, line_height):
            return
        doc.pdf.set_x(14)
        doc.pdf.cell(182, line_height, line, new_x="LMARGIN", new_y="NEXT")


def _gap(doc: _ReportPdf, mm: float) -> None:
    if _fits(doc, mm):
        doc.space(mm)


def _draw_recorded_bars(doc: _ReportPdf, calendar: list[str], daily: dict[str, float],
                        as_of: date | None, avg: float) -> None:
    """Small daily bars in the same rect and line style as the cover trend."""
    if not calendar or not _fits(doc, 42):
        return
    p = doc.pdf
    y0 = p.get_y()
    doc.font(8.2, True, doc.DARK)
    p.set_xy(14, y0)
    p.cell(100, 4.4, "Recorded days")
    doc.font(7.3, False, doc.MUTED)
    p.set_xy(100, y0)
    p.cell(96, 4.4, "kWh", align="R")
    top = y0 + 7
    plot_h = 18.0
    bottom = top + plot_h
    left = 29.0
    chart_w = 167.0
    peak = max([float(v) for v in daily.values()] or [0.0])
    maximum = doc.nice(max(peak, avg) / 1000.0)
    doc.font(6.5, False, doc.MUTED)
    p.set_draw_color(*doc.LINE)
    for step in range(3):
        level = maximum * step / 2
        gy = bottom - plot_h * step / 2
        p.set_line_width(0.17)
        p.line(left, gy, left + chart_w, gy)
        p.set_xy(14, gy - 1.8)
        p.cell(12, 3.6, f"{level:.2f}".rstrip("0").rstrip("."), align="R")
    slot = chart_w / len(calendar)
    bw = min(6.0, max(0.4, slot * 0.62))
    label_step = max(1, math.ceil(len(calendar) / 8))
    for i, day in enumerate(calendar):
        value = daily.get(day)
        center = left + (i + 0.5) * slot
        x = center - bw / 2
        if value is not None:
            height = plot_h * (max(0.0, float(value)) / 1000.0) / maximum if maximum else 0
            height = min(plot_h, max(0.4, height))
            p.set_fill_color(*doc.ACCENT)
            p.rect(x, bottom - height, bw, height, "F")
        elif as_of is not None and day > as_of.isoformat():
            p.set_draw_color(187, 199, 200)
            p.set_line_width(0.45)
            p.line(x, bottom - 1.2, x + bw, bottom - 1.2)
        else:
            p.set_fill_color(*doc.AMBER)
            p.rect(x, bottom - 1.6, bw, 1.6, "F")
        if i % label_step == 0 or i == len(calendar) - 1:
            parsed = _parse_day(day)
            label = str(parsed.day) if parsed else ""
            doc.font(6.2, False, doc.MUTED)
            p.set_xy(center - 6, bottom + 0.8)
            p.cell(12, 3.4, label, align="C")
    if avg > 0 and maximum:
        line_y = bottom - min(plot_h, (avg / 1000.0) / maximum * plot_h)
        p.set_draw_color(*doc.DARK)
        p.set_line_width(0.23)
        p.set_dash_pattern(dash=1.5, gap=1.2)
        p.line(left, line_y, left + chart_w, line_y)
        p.set_dash_pattern()
    p.set_y(bottom + 5.2)
    _write_capped(
        doc,
        "Blue bars are recorded days. Orange marks a day with no reading. A grey line marks a future day. The dashed line is the average recorded day.",
        size=7.0,
        color=doc.MUTED,
        line_height=3.6,
    )


def _draw_bill_analysis(
    doc: _ReportPdf,
    roll: dict[str, Any],
    as_of: date | None,
    avg_wh: float,
    total_wh: float,
    n_recorded: int,
    missing: int,
    rooms: dict[str, Any],
    ordered_rids: list[str],
    devices: list[dict[str, Any]],
) -> None:
    """One page. Stops early instead of flowing onto a second analysis page."""
    doc.section(
        " ",
        "Bill Analysis",
        "Why recorded use looks like this, which loads are largest, and how that sits with the people, rooms, and devices that were stored.",
        reserve=22,
    )
    daily = roll["daily_total"]
    if n_recorded <= 0 or total_wh <= 0:
        _write_capped(
            doc,
            "No energy readings were stored for this period, so there is no usage to explain and no efficiency figure to compute.",
            color=doc.MUTED,
        )
        return
    peak_day = str(roll.get("peak_day") or "")
    peak_wh = float(daily.get(peak_day, 0) or 0)
    why = (
        f"Stored readings cover {n_recorded} day{'s' if n_recorded != 1 else ''} and {_kwh(total_wh, 2)} kWh. "
        f"The highest recorded day was {_weekday_day(peak_day)} at {_kwh(peak_wh, 2)} kWh, "
        f"against {_kwh(avg_wh, 2)} kWh on an average recorded day."
    )
    if missing:
        why += (
            f" {missing} elapsed day{'s' if missing != 1 else ''} had no reading, "
            "so those days are not counted as zero."
        )
    home_totals: list[float] = []
    away_totals: list[float] = []
    for day, wh in daily.items():
        present = any(float(seconds or 0) > 0 for seconds in (roll["daily_home"].get(day) or {}).values())
        (home_totals if present else away_totals).append(float(wh))
    if home_totals and away_totals:
        why += (
            f" Days with someone tracked at home averaged {_kwh(sum(home_totals) / len(home_totals), 2)} kWh. "
            f"Days with nobody tracked at home averaged {_kwh(sum(away_totals) / len(away_totals), 2)} kWh."
        )
    _write_capped(doc, why)
    _gap(doc, 1.4)
    _draw_recorded_bars(doc, roll["calendar"], daily, as_of, avg_wh)
    _gap(doc, 1.6)
    _write_capped(doc, "Largest loads", size=8.6, bold=True, color=doc.DARK)
    shown_rooms = 0
    for rid in ordered_rids:
        wh = float(rooms[rid]["wh"])
        if wh <= 0:
            continue
        if shown_rooms >= 4:
            break
        share = wh / total_wh * 100 if total_wh else 0
        _write_capped(doc, f"{rooms[rid]['name']}: {_kwh(wh, 2)} kWh, {share:.0f} percent of recorded energy.", size=8.0)
        shown_rooms += 1
    shown_devices = 0
    for device in devices:
        wh = float(device["wh"])
        if wh <= 0:
            continue
        if shown_devices >= 4:
            break
        share = wh / total_wh * 100 if total_wh else 0
        label = smart_device_name(device.get("name"), device.get("type"))
        room_name = str(rooms.get(device["room_id"], {}).get("name") or device.get("room_id") or "")
        _write_capped(doc, f"{label} in {room_name}: {_kwh(wh, 2)} kWh, {share:.0f} percent.", size=8.0)
        shown_devices += 1
    people = [person for person in roll["persons"].values() if float(person.get("seconds_home") or 0) > 0]
    active_rooms = [room for room in rooms.values() if float(room.get("wh") or 0) > 0]
    active_devices = [device for device in devices if float(device.get("wh") or 0) > 0]
    person_days = sum(int(person.get("days_home") or 0) for person in people)
    top_room = rooms[ordered_rids[0]] if ordered_rids else None
    top_device = devices[0] if devices else None
    top_room_share = (float(top_room["wh"]) / total_wh * 100) if top_room and total_wh else 0
    top_device_share = (float(top_device["wh"]) / total_wh * 100) if top_device and total_wh else 0
    if top_device_share >= 45 and top_device:
        spread = (
            f"Use is concentrated in {smart_device_name(top_device.get('name'), top_device.get('type'))}, "
            f"at {top_device_share:.0f} percent of recorded energy."
        )
    elif top_room_share >= 50 and top_room:
        spread = f"Use is concentrated in {top_room['name']}, at {top_room_share:.0f} percent of recorded energy."
    else:
        spread = "Use is spread across the rooms and devices that recorded energy, rather than sitting in one place."
    who = (
        f"{len(people)} {'person was' if len(people) == 1 else 'people were'} tracked at home"
        if people else "nobody was tracked at home"
    )
    per_person = ""
    if people and person_days > 0:
        per_person = (
            f" That is {_kwh(total_wh / person_days, 2)} kWh for each tracked day someone was home."
        )
    _gap(doc, 1.2)
    _write_capped(
        doc,
        "No rate, dollar amount, or weather value is stored, so none is estimated here. "
        f"Against this home's own readings, {who}, across {len(active_rooms)} "
        f"{'room' if len(active_rooms) == 1 else 'rooms'} and {len(active_devices)} "
        f"{'device' if len(active_devices) == 1 else 'devices'} with stored energy. "
        f"The average recorded day was {_kwh(avg_wh, 2)} kWh. {spread}{per_person}",
    )


def render_period_pdf(
    key: str,
    days: dict[str, Any],
    generated_label: str,
    events: list[dict[str, Any]] | None = None,
    alerts: list[dict[str, Any]] | None = None,
) -> bytes:
    """Generate an editorial statement using the unmodified energy rollup."""
    from .durable_records import collapse_connectivity_events

    rng = key_range(key)
    if not rng:
        raise ValueError(f"Invalid report key {key!r}")
    start, end = rng
    roll = _rollup(start, end, days)
    doc = _ReportPdf(report_display_title(key), key)
    p = doc.pdf
    p.add_page()

    calendar = roll["calendar"]
    daily = roll["daily_total"]
    n_recorded = len(roll["recorded"])
    total_wh = float(roll["total_wh"])
    avg_wh = total_wh / n_recorded if n_recorded else 0.0
    max_day = roll["peak_day"]
    min_day = roll["low_day"]
    peak_wh = float(daily.get(max_day, 0)) if max_day else 0.0
    low_wh = float(daily.get(min_day, 0)) if min_day else 0.0
    as_of = _parse_day(str(generated_label or "")[:10])
    elapsed = [day for day in calendar if as_of is None or day <= as_of.isoformat()]
    missing = len([day for day in elapsed if day not in daily])
    future = len(calendar) - len(elapsed)
    episodes = collapse_connectivity_events(events)
    rooms = roll["rooms"]
    ordered_rids = sorted(rooms, key=lambda rid: float(rooms[rid]["wh"]), reverse=True)
    devices = sorted(roll["devices"].values(), key=lambda row: float(row["wh"]), reverse=True)

    # FIRST PAGE: summary, sample coverage, chronological plot, complete room register.
    doc.hero(key, start, end, generated_label, total_wh)
    doc.metrics(avg_wh, max_day, peak_wh, min_day, low_wh, len(episodes))
    doc.coverage(n_recorded, missing, future, len(calendar))
    doc.trend(calendar, daily, as_of, avg_wh)
    doc.section("01", "Energy By Room", "Period totals, with each room's share of estimated household energy.", reserve=26)
    doc.room_rows([(str(rooms[rid]["name"]), float(rooms[rid]["wh"])) for rid in ordered_rids], total_wh)

    # Presence is promoted to page one so the household context is visible with the main period summary.
    doc.section("02", "Household Presence", "At-home hours are deduplicated by the longest tracker reading each day.", reserve=24)
    persons = roll["persons"]
    if persons:
        doc.table_header([(71, "Person", "L"), (34, "Days Home", "R"),
                          (39, "Hours Home", "R"), (38, "Hours / Day", "R")])
        for i, person in enumerate(sorted(persons.values(), key=lambda a: str(a["name"]).lower())):
            seen = int(person["days_seen"])
            hours = float(person["seconds_home"]) / 3600.0
            doc.table_row([str(person["name"]), str(int(person["days_home"])),
                           f"{hours:.1f}", f"{hours / seen if seen else 0:.1f}"], index=i)
    else:
        doc.paragraph("No household presence history was stored for this period.", color=doc.MUTED)

    p.add_page()
    _draw_bill_analysis(
        doc, roll, as_of, avg_wh, total_wh, n_recorded, missing,
        rooms, ordered_rids, devices,
    )

    # All appliances remain in the report; large device lists get continued pages.
    p.add_page()
    doc.section("03", "Device Consumption", "Every device with stored energy, ordered from highest to lowest.", reserve=24)
    if devices:
        doc.table_header([(78, "Device", "L"), (57, "Room", "L"),
                          (25, "kWh", "R"), (22, "Share", "R")])
        for i, device in enumerate(devices):
            wh = float(device["wh"])
            room = rooms.get(device["room_id"], {})
            share = (wh / total_wh * 100) if total_wh > 0 else 0.0
            doc.table_row([
                smart_device_name(device.get("name"), device.get("type")),
                str(room.get("name") or device["room_id"]),
                _kwh(wh, 2), f"{share:.0f}%",
            ], index=i, size=8)
    else:
        doc.paragraph("No device energy was recorded in this period.", color=doc.MUTED)

    # Highlights sit at the top of the same page as the daily ledger.
    p.add_page()
    doc.section("04", "Highlights And Comparisons", "All comparisons use days with readings.", reserve=24)
    weekdays = [(d, float(v)) for d, v in daily.items() if _parse_day(d) and _parse_day(d).weekday() < 5]
    weekends = [(d, float(v)) for d, v in daily.items() if _parse_day(d) and _parse_day(d).weekday() >= 5]
    insights = []
    if weekdays:
        insights.append(("Weekday average", f"{_kwh(sum(v for _, v in weekdays) / len(weekdays), 2)} kWh", f"{len(weekdays)} recorded weekday" + ("s" if len(weekdays) != 1 else "")))
    if weekends:
        insights.append(("Weekend average", f"{_kwh(sum(v for _, v in weekends) / len(weekends), 2)} kWh", f"{len(weekends)} recorded weekend " + ("days" if len(weekends) != 1 else "day")))
    if insights:
        doc.insight_cards(insights)
    else:
        doc.paragraph("No weekday or weekend reading was available to compare.", color=doc.MUTED)
    warnings = sum(int(row.get("warnings") or 0) for row in rooms.values())
    shutoffs = sum(int(row.get("shutoffs") or 0) for row in rooms.values())
    cycles = sum(int(row.get("power_cycles") or 0) for row in rooms.values())
    notes = []
    if ordered_rids and devices:
        room_item = rooms[ordered_rids[0]]
        device_label = smart_device_name(devices[0].get("name"), devices[0].get("type"))
        notes.append(f"Largest sources: {room_item['name']} ({_kwh(room_item['wh'], 2)} kWh) and {device_label} ({_kwh(devices[0]['wh'], 2)} kWh).")
    if warnings or shutoffs or cycles:
        notes.append(f"Threshold activity: {warnings} warning{'s' if warnings != 1 else ''}, "
                     f"{shutoffs} shutoff{'s' if shutoffs != 1 else ''}, "
                     f"{cycles} power cycle{'s' if cycles != 1 else ''}.")
    if notes:
        doc.space(1.1)
        doc.paragraph(" ".join(notes), size=7.6, color=doc.MUTED, line_height=4.3)

    # EVERY DAY, without implying missing equals zero. Presence stays tied to that day.
    doc.section("05", "Daily Activity Ledger", "Every day in the billing window, including unavailable and future days.", reserve=24)
    for day in calendar:
        if as_of is not None and day > as_of.isoformat():
            doc.daily_card(day, "future", None, [], avg_wh, "")
            continue
        if day not in daily:
            doc.daily_card(day, "missing", None, [], avg_wh, "")
            continue
        wh = float(daily[day])
        room_values = roll["daily_rooms"].get(day) or {}
        day_rooms = sorted([(str(rooms.get(rid, {}).get("name") or rid), float(v))
                            for rid, v in room_values.items() if float(v) > 0],
                           key=lambda item: item[1], reverse=True)
        doc.daily_card(day, "recorded", wh, day_rooms, avg_wh if n_recorded > 1 else 0,
                       _home_line(roll, day))

    # Alerts start on their own page, ahead of connectivity.
    p.add_page()
    doc.section(
        " ",
        "Warnings And Phase Changes",
        "Only announcements that were spoken out loud are listed.",
        reserve=28,
    )
    doc.paragraph(
        "These are alerts and automatic pauses you configured in Home Energy. Each one applies only to the room or outlet named in the row.",
        size=8.2,
        line_height=4.3,
    )
    doc.space(1.2)
    warning_count, shutoff_count, cycle_count, alert_rows = _alert_counts(alerts)
    _draw_alert_counts(doc, warning_count, shutoff_count, cycle_count)
    doc.space(1.0)
    if alert_rows:
        doc.table_header([
            (34, "When", "L"),
            (32, "Room", "L"),
            (28, "Event", "L"),
            (44, "Detail", "L"),
            (44, "Spoken", "L"),
        ])
        for i, event in enumerate(alert_rows):
            doc.table_row([
                _clock(str(event.get("ts") or "")),
                str(event.get("room_name") or ""),
                _alert_label(event),
                _alert_detail(event),
                _alert_spoken(event),
            ], index=i, size=7.2)
    else:
        doc.paragraph("No spoken announcements were logged for this period.", color=doc.MUTED)

    # Exactly one row per collapsed outage; no duplicate day-by-day connection logs.
    p.add_page()
    doc.section("06", "Connectivity Incidents",
                "One row per outage; short reconnects may be stitched together. Episodes before logging began are not reconstructed.", reserve=26)
    if episodes:
        doc.table_header([(40, "Offline From", "L"), (33, "Room", "L"),
                          (43, "Device", "L"), (40, "Back Online", "L"), (26, "Duration", "R")])
        for i, episode in enumerate(episodes):
            restored = bool(episode.get("online_at"))
            back = _clock(str(episode.get("online_at") or "")) if restored else "Still offline"
            duration = _span_label(str(episode.get("offline_at") or ""), str(episode.get("online_at") or "")) if restored else "Ongoing"
            doc.table_row([
                _clock(str(episode.get("offline_at") or "")),
                str(episode.get("room_name") or ""),
                smart_device_name(episode.get("name"), episode.get("appliance_type")),
                back, duration,
            ], index=i, size=7.6, state="" if restored else "offline")
    else:
        doc.paragraph("No connectivity outage episode was logged for this period.", color=doc.MUTED)
    return bytes(p.output())


# --------------------------------------------------------------------------- files


def write_period_pdf(
    data_dir: str,
    key: str,
    days: dict[str, Any],
    generated_label: str,
    events: list[dict[str, Any]] | None = None,
    alerts: list[dict[str, Any]] | None = None,
) -> Path | None:
    """Write or replace one billing period. Other files are left in place."""
    path = report_path(data_dir, key)
    if path is None:
        return None
    try:
        data = render_period_pdf(path.stem, days, generated_label, events or [], alerts or [])
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
