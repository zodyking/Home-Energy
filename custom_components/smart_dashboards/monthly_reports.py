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
    """Editorial A4 energy statement. All dimensions are millimeters.

    The document deliberately separates the compact period overview from the
    complete day-by-day record. Long tables repeat their headings on new pages.
    """

    INK = (24, 46, 57)
    DEEP = (13, 38, 49)
    ACCENT = (12, 112, 128)
    SEA = (47, 146, 150)
    MUTED = (105, 117, 124)
    FAINT = (154, 165, 170)
    RULE = (223, 230, 231)
    PALE = (246, 249, 249)
    SOFT = (236, 244, 244)
    WHITE = (255, 255, 255)
    GOLD = (179, 120, 50)
    RED = (165, 41, 49)
    ROSE = (253, 243, 243)
    ROOM_COLORS = (
        (12, 112, 128), (45, 144, 148), (90, 160, 153),
        (145, 167, 163), (92, 129, 150), (141, 119, 153),
        (179, 145, 105), (101, 145, 113),
    )
    LEFT = 14.0
    RIGHT = 196.0
    WIDTH = 182.0

    def __init__(self, title: str, period: str = "") -> None:
        from fpdf import FPDF
        self.title = title
        self.period = period
        self.pdf = FPDF(format="A4", unit="mm")
        self.pdf.set_margins(14, 33, 14)
        self.pdf.set_auto_page_break(auto=True, margin=34)
        self.pdf.set_title(_safe(title))
        self.pdf.set_author("Home Energy")
        self.pdf.set_subject("Estimated electricity usage and connectivity record")
        self.pdf.alias_nb_pages()
        self.pdf.header = self._header  # type: ignore[method-assign]
        self.pdf.footer = self._footer  # type: ignore[method-assign]
        self._columns: list[tuple[float, str, str]] = []

    def font(self, size: float, bold: bool = False, color=None) -> None:
        self.pdf.set_font("helvetica", "B" if bold else "", size)
        self.pdf.set_text_color(*(color or self.INK))

    def _header(self) -> None:
        pdf = self.pdf
        pdf.set_fill_color(*self.ACCENT)
        pdf.rect(14, 12.1, 3.0, 8.0, "F")
        self.font(11.3, True, self.DEEP)
        pdf.set_xy(21.1, 12.2)
        pdf.cell(60, 5.7, "HOME ENERGY")
        self.font(7.0, False, self.MUTED)
        pdf.set_xy(21.2, 18.4)
        pdf.cell(80, 3.7, "RESIDENTIAL ENERGY RECORD")
        self.font(7.7, True, self.ACCENT)
        pdf.set_xy(125, 12.7)
        pdf.cell(71, 5, "PERIOD STATEMENT", align="R")
        self.font(7.3, False, self.MUTED)
        pdf.set_xy(120, 18.1)
        pdf.cell(76, 4, _safe("PAGE " + str(pdf.page_no()) + " OF {nb}"), align="R")
        pdf.set_draw_color(*self.RULE)
        pdf.set_line_width(0.24)
        pdf.line(14, 27.1, 196, 27.1)
        pdf.set_y(33)

    def _footer(self) -> None:
        pdf = self.pdf
        pdf.set_auto_page_break(auto=False)
        pdf.set_draw_color(*self.RULE)
        pdf.line(14, 262.7, 196, 262.7)
        pdf.set_fill_color(*self.ROSE)
        pdf.rect(14, 267.1, 182, 20.1, "F")
        pdf.set_fill_color(*self.RED)
        pdf.rect(14, 267.1, 1.4, 20.1, "F")
        pdf.set_xy(19, 269.1)
        self.font(8.1, True, self.RED)
        # There is room for the complete, legally important disclaimer.
        pdf.multi_cell(
            w=172, h=4.7, text=_safe(_DISCLAIMER), align="L",
            new_x="LMARGIN", new_y="NEXT",
        )
        pdf.set_auto_page_break(auto=True, margin=34)

    def need(self, height: float) -> None:
        if self.pdf.get_y() + height > self.pdf.page_break_trigger:
            self.pdf.add_page()

    def gap(self, mm: float) -> None:
        self.pdf.set_y(self.pdf.get_y() + mm)

    def rule(self, x1: float = 14, x2: float = 196, color=None) -> None:
        pdf = self.pdf
        pdf.set_draw_color(*(color or self.RULE))
        pdf.set_line_width(0.2)
        pdf.line(x1, pdf.get_y(), x2, pdf.get_y())

    def wrap(self, value: Any, width: float, size: float = 8.5,
             bold: bool = False) -> list[str]:
        """Return every printable line without truncating customer data."""
        pdf = self.pdf
        self.font(size, bold)
        text = _safe(value).replace("\r", "")
        if not text:
            return [""]
        output: list[str] = []
        for paragraph in text.split("\n"):
            if not paragraph.strip():
                output.append("")
                continue
            words = paragraph.split()
            line = ""
            for word in words:
                possible = (line + " " + word) if line else word
                if pdf.get_string_width(possible) <= width:
                    line = possible
                    continue
                if line:
                    output.append(line)
                    line = ""
                if pdf.get_string_width(word) <= width:
                    line = word
                    continue
                # Even uninterrupted tracker names, IDs and device labels wrap.
                piece = ""
                for char in word:
                    candidate = piece + char
                    if piece and pdf.get_string_width(candidate) > width:
                        output.append(piece)
                        piece = char
                    else:
                        piece = candidate
                line = piece
            output.append(line)
        return output or [""]

    def text(self, value: Any, size: float = 8.6, color=None,
             bold: bool = False, line_height: float = 4.6,
             width: float = 182, x: float = 14) -> None:
        lines = self.wrap(value, width - 1, size, bold)
        self.need(len(lines) * line_height)
        self.font(size, bold, color)
        for line in lines:
            self.pdf.set_x(x)
            self.pdf.cell(width, line_height, line, new_x="LMARGIN", new_y="NEXT")

    def section(self, number: str, title: str, note: str = "", reserve: float = 22) -> None:
        self.gap(3.4)
        self.need(reserve)
        pdf = self.pdf
        y = pdf.get_y()
        self.font(7.0, True, self.ACCENT)
        pdf.set_xy(14, y + 0.3)
        pdf.cell(13, 6.2, _safe(number))
        self.font(13.7, True, self.DEEP)
        pdf.set_xy(28.4, y)
        pdf.cell(152, 7.0, _safe(title))
        pdf.set_y(y + 9.1)
        self.rule()
        self.gap(3.2)
        if note:
            self.text(note, 8.15, self.MUTED, line_height=4.25)
            self.gap(2)

    def hero(self, start: str, end: str, generated: str,
             total_wh: float, days: int, recorded: int,
             missing: int, future: int, avg_wh: float,
             peak_day: str, peak_wh: float, connections: int) -> None:
        pdf = self.pdf
        y = pdf.get_y()
        self.font(7.7, True, self.ACCENT)
        pdf.set_xy(14, y)
        pdf.cell(102, 5, "YOUR ELECTRICITY, AT A GLANCE")
        self.font(23.5, True, self.DEEP)
        pdf.set_xy(13.6, y + 7)
        pdf.cell(118, 13, "Monthly statement")
        self.font(10.2, False, self.MUTED)
        pdf.set_xy(14, y + 21.1)
        pdf.cell(122, 6, _safe(period_label(self.period)))

        pdf.set_draw_color(*self.RULE)
        pdf.line(138.2, y + 5, 138.2, y + 33)
        self.font(7.6, True, self.MUTED)
        pdf.set_xy(143, y + 7.5)
        pdf.cell(53, 4, "ESTIMATED USAGE", align="R")
        amount = f"{_kwh(total_wh, 2)}"
        size = 20.5 if len(amount) <= 8 else 15
        self.font(size, True, self.DEEP)
        pdf.set_xy(143, y + 14)
        pdf.cell(53, 11, _safe(amount), align="R")
        self.font(9, False, self.ACCENT)
        pdf.set_xy(143, y + 25.3)
        pdf.cell(53, 5, "kWh / period", align="R")
        pdf.set_y(y + 38)
        self.rule()
        self.gap(5.0)

        # Metadata is printed as labelled document details, not miniature charts.
        yy = pdf.get_y()
        self.font(7.0, True, self.MUTED)
        pdf.set_xy(14, yy)
        pdf.cell(90, 4, "BILLING PERIOD")
        pdf.set_xy(112, yy)
        pdf.cell(84, 4, "PREPARED ON")
        self.font(9, True, self.INK)
        pdf.set_xy(14, yy + 4.5)
        pdf.cell(95, 6, _safe(_weekday_day(start) + " - " + _weekday_day(end)))
        self.font(9.0, False, self.INK)
        pdf.set_xy(112, yy + 4.5)
        pdf.cell(84, 6, _safe(_pretty_generated(generated)))
        pdf.set_y(yy + 14)

        yy = pdf.get_y()
        self.need(27)
        pdf.set_fill_color(*self.PALE)
        pdf.rect(14, yy, 182, 25.1, "F")
        blocks = [
            ("AVERAGE READING DAY", f"{_kwh(avg_wh, 2)} kWh", f"Across {recorded} recorded days"),
            ("HIGHEST READING", f"{_kwh(peak_wh, 2)} kWh" if peak_day else "None", _weekday_day(peak_day) if peak_day else "No readings yet"),
            ("CONNECTIVITY EVENTS", str(connections), "Disconnects and reconnects"),
        ]
        for i, (label, value, caption) in enumerate(blocks):
            x = 18 + i * 60.6
            if i:
                pdf.set_draw_color(*self.RULE)
                pdf.line(x - 4, yy + 4, x - 4, yy + 21)
            self.font(6.8, True, self.MUTED)
            pdf.set_xy(x, yy + 3.7)
            pdf.cell(55, 4, label)
            self.font(14.0, True, self.DEEP)
            pdf.set_xy(x, yy + 8.8)
            pdf.cell(55, 7.5, _safe(value))
            self.font(7.2, False, self.MUTED)
            pdf.set_xy(x, yy + 17.7)
            pdf.cell(56, 4, _safe(caption))
        pdf.set_y(yy + 29)

        yy = pdf.get_y()
        self.need(16)
        self.font(7.0, True, self.MUTED)
        pdf.set_xy(14, yy)
        pdf.cell(34, 4.8, "DATA COVERAGE")
        coverage = [
            (recorded, "recorded", self.ACCENT),
            (missing, "no reading", self.GOLD),
            (future, "not elapsed", self.MUTED),
        ]
        x = 51
        for count, name, tone in coverage:
            pdf.set_fill_color(*tone)
            pdf.circle(x + 1.7, yy + 2.3, 1.45, "F")
            self.font(8.2, True, self.INK)
            label = f"{count} {name}"
            pdf.set_xy(x + 5.3, yy)
            pdf.cell(46, 4.8, _safe(label))
            x += 48
        pdf.set_y(yy + 8.0)
        self.text(
            f"{days} calendar days in the period. Missing readings are not counted as zero usage. "
            "Connectivity changes are recorded only when a change is detected; earlier outages cannot be reconstructed.",
            7.9, self.MUTED, line_height=4.15,
        )

    def room_list(self, rows: list[tuple[str, float]], total: float) -> None:
        pdf = self.pdf
        self.font(7.0, True, self.MUTED)
        yy = pdf.get_y()
        pdf.set_xy(16, yy)
        pdf.cell(59, 5.5, "ROOM")
        pdf.set_xy(142, yy)
        pdf.cell(35, 5.5, "TOTAL (kWh)", align="R")
        pdf.set_xy(177, yy)
        pdf.cell(19, 5.5, "SHARE", align="R")
        pdf.set_y(yy + 6)
        self.rule()
        for i, (name, wh) in enumerate(rows):
            lines = self.wrap(name, 58, 8.55)
            height = max(9.5, 3.7 + 4.25 * len(lines))
            self.need(height)
            yy = pdf.get_y()
            if i % 2:
                pdf.set_fill_color(*self.PALE)
                pdf.rect(14, yy, 182, height, "F")
            self.font(8.55, True, self.INK)
            for j, line in enumerate(lines):
                pdf.set_xy(16.5, yy + 2.1 + j * 4.25)
                pdf.cell(58, 4.1, line)
            color = self.ROOM_COLORS[i % len(self.ROOM_COLORS)]
            frac = wh / total if total > 0 else 0
            pdf.set_fill_color(*self.SOFT)
            pdf.rect(79, yy + 3.6, 59, 2.8, "F")
            if frac > 0:
                pdf.set_fill_color(*color)
                pdf.rect(79, yy + 3.6, 59 * min(frac, 1), 2.8, "F")
            self.font(8.45, True, self.INK)
            pdf.set_xy(144, yy + 2.15)
            pdf.cell(33, 5.3, _kwh(wh, 2), align="R")
            self.font(8.0, False, self.MUTED)
            pdf.set_xy(177, yy + 2.15)
            share = f"{(wh / total * 100) if total > 0 else 0:.0f}%"
            pdf.cell(19, 5.3, share, align="R")
            pdf.set_y(yy + height)
            self.rule()
        self.need(9)
        yy = pdf.get_y()
        self.font(8.8, True, self.DEEP)
        pdf.set_xy(16.5, yy + 2)
        pdf.cell(102, 5.4, "WHOLE HOME")
        pdf.set_xy(141, yy + 2)
        pdf.cell(36, 5.4, _kwh(total, 2), align="R")
        pdf.set_xy(177, yy + 2)
        pdf.cell(19, 5.4, "100%" if total > 0 else "0%", align="R")
        pdf.set_y(yy + 10)

    def day_heading(self, day: str, status: str, kind: str) -> None:
        self.need(20)
        pdf = self.pdf
        y = pdf.get_y()
        pdf.set_fill_color(*(self.SOFT if kind == "recorded" else self.PALE))
        pdf.rect(14, y, 182, 9.2, "F")
        pdf.set_fill_color(*(
            self.ACCENT if kind == "recorded" else
            self.GOLD if kind == "missing" else self.FAINT
        ))
        pdf.rect(14, y, 1.45, 9.2, "F")
        self.font(9.7, True, self.DEEP)
        pdf.set_xy(18.5, y + 1.6)
        pdf.cell(102, 5.6, _safe(_weekday_day(day)))
        self.font(8.2, True, self.ACCENT if kind == "recorded" else self.MUTED)
        pdf.set_xy(123, y + 1.8)
        pdf.cell(69, 5.2, _safe(status), align="R")
        pdf.set_y(y + 10.6)

    def daily_room(self, label: str, energy_wh: float, total_wh: float) -> None:
        pdf = self.pdf
        lines = self.wrap(label, 110, 8.25)
        height = max(5.5, 1 + 4.3 * len(lines))
        self.need(height)
        y = pdf.get_y()
        self.font(8.25, False, self.INK)
        for i, line in enumerate(lines):
            pdf.set_xy(22, y + i * 4.3)
            pdf.cell(108, 4.3, line)
        self.font(8.35, True, self.INK)
        pdf.set_xy(134, y)
        pdf.cell(35, 4.3, f"{_kwh(energy_wh, 2)} kWh", align="R")
        share = f"{(energy_wh / total_wh * 100) if total_wh > 0 else 0:.0f}%"
        self.font(8.0, False, self.MUTED)
        pdf.set_xy(173, y)
        pdf.cell(20, 4.3, share, align="R")
        pdf.set_y(y + height)

    def daily_event(self, row: dict[str, Any]) -> None:
        pdf = self.pdf
        at = _clock(str(row.get("at") or ""))
        event = "Disconnected" if row.get("event") == "disconnected" else "Reconnected"
        detail = f"{row.get('room_name') or 'Room'} / {row.get('name') or 'Device'} / {row.get('part') or 'reading'}"
        label_lines = self.wrap(detail, 98, 8.0)
        time_lines = self.wrap(at, 34, 7.65)
        height = max(len(label_lines), len(time_lines), 1) * 4.35 + 1.5
        self.need(height)
        y = pdf.get_y()
        pdf.set_fill_color(*(self.RED if event == "Disconnected" else self.ACCENT))
        pdf.circle(23, y + 2.55, 1.1, "F")
        self.font(7.65, False, self.MUTED)
        for i, line in enumerate(time_lines):
            pdf.set_xy(27, y + i * 4.35)
            pdf.cell(35, 4.3, line)
        self.font(8.0, False, self.INK)
        for i, line in enumerate(label_lines):
            pdf.set_xy(62, y + i * 4.35)
            pdf.cell(98, 4.3, line)
        self.font(7.25, True, self.RED if event == "Disconnected" else self.ACCENT)
        pdf.set_xy(165.5, y)
        pdf.cell(27.5, 4.3, event.upper(), align="R")
        pdf.set_y(y + height)

    def table_header(self, columns: list[tuple[float, str, str]]) -> None:
        assert abs(sum(col[0] for col in columns) - 182) < 0.01, "Table must be 182 mm wide"
        self._columns = columns
        self.need(15)
        pdf = self.pdf
        yy = pdf.get_y()
        pdf.set_fill_color(*self.DEEP)
        pdf.rect(14, yy, 182, 8.4, "F")
        self.font(7.05, True, self.WHITE)
        x = 14
        for width, label, align in columns:
            pdf.set_xy(x + 2.3, yy + 2.1)
            pdf.cell(width - 4.6, 4, _safe(label.upper()), align=align)
            x += width
        pdf.set_y(yy + 8.4)

    def table_row(self, cells: list[str], *, fill: bool = False,
                  bold: bool = False, size: float = 8.2,
                  state: str = "") -> None:
        if not self._columns:
            raise RuntimeError("A table header must precede a table row")
        lines = [self.wrap(value, width - 5, size, bold) for
                 value, (width, _, _) in zip(cells, self._columns)]
        nlines = max((len(v) for v in lines), default=1)
        row_h = nlines * 4.3 + 4.3
        if self.pdf.get_y() + row_h > self.pdf.page_break_trigger:
            self.pdf.add_page()
            self.table_header(self._columns)
        pdf = self.pdf
        yy = pdf.get_y()
        if fill:
            pdf.set_fill_color(*self.PALE)
            pdf.rect(14, yy, 182, row_h, "F")
        x = 14
        for j, ((width, _, alignment), column_lines) in enumerate(zip(self._columns, lines)):
            color = self.INK
            if state and j == len(cells) - 1:
                color = self.RED if state == "disconnected" else self.ACCENT
            elif bold:
                color = self.DEEP
            self.font(size, bold or bool(state and j == len(cells) - 1), color)
            for k, part in enumerate(column_lines):
                pdf.set_xy(x + 2.3, yy + 2.3 + k * 4.3)
                pdf.cell(width - 4.6, 4.2, part, align=alignment)
            x += width
        pdf.set_y(yy + row_h)
        self.rule()

    def note_panel(self, heading: str, text: str) -> None:
        text_lines = self.wrap(text, 171, 8.1)
        height = 14 + 4.4 * len(text_lines)
        self.need(height + 3)
        pdf = self.pdf
        y = pdf.get_y()
        pdf.set_fill_color(*self.PALE)
        pdf.rect(14, y, 182, height, "F")
        pdf.set_fill_color(*self.ACCENT)
        pdf.rect(14, y, 1.1, height, "F")
        self.font(7.0, True, self.ACCENT)
        pdf.set_xy(19.0, y + 3)
        pdf.cell(170, 4.2, heading.upper())
        self.font(8.1, False, self.MUTED)
        for i, line in enumerate(text_lines):
            pdf.set_xy(19, y + 9 + i * 4.4)
            pdf.cell(171, 4.3, line)
        pdf.set_y(y + height + 2)

    @staticmethod
    def _nice_ceiling(value: float) -> float:
        if value <= 0:
            return 1.0
        magnitude = 10 ** math.floor(math.log10(value))
        for factor in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
            if value <= factor * magnitude:
                return factor * magnitude
        return 10 * magnitude


def render_period_pdf(
    key: str,
    days: dict[str, Any],
    generated_label: str,
    events: list[dict[str, Any]] | None = None,
) -> bytes:
    """Render a complete printable energy statement from the existing rollup."""
    rng = key_range(key)
    if not rng:
        raise ValueError(f"Invalid report key {key!r}")
    start, end = rng
    roll = _rollup(start, end, days)
    doc = _ReportPdf(report_display_title(key), key)
    pdf = doc.pdf
    pdf.add_page()

    calendar = roll["calendar"]
    recorded = roll["recorded"]
    total_wh = float(roll["total_wh"])
    n_recorded = len(recorded)
    avg_wh = total_wh / n_recorded if n_recorded else 0.0
    peak_day = roll["peak_day"]
    peak_wh = float(roll["daily_total"].get(peak_day, 0)) if peak_day else 0.0
    log = [row for row in (events or []) if isinstance(row, dict)]
    log.sort(key=lambda row: str(row.get("at") or ""))
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in log:
        by_day.setdefault(str(row.get("at") or "")[:10], []).append(row)
    as_of = _parse_day(str(generated_label or "")[:10])
    elapsed = [d for d in calendar if as_of is None or d <= as_of.isoformat()]
    missing = [d for d in elapsed if d not in roll["daily_total"]]
    future = len(calendar) - len(elapsed)

    # PAGE 1: the concise reading of the period, with clear source coverage.
    doc.hero(
        start, end, generated_label, total_wh, len(calendar), n_recorded,
        len(missing), future, avg_wh, peak_day, peak_wh, len(log),
    )
    rooms = roll["rooms"]
    ordered_room_ids = sorted(rooms, key=lambda k: float(rooms[k]["wh"]), reverse=True)
    doc.section("01", "Usage by room",
                "Estimated energy totals across the billing period.", reserve=24)
    if not ordered_room_ids:
        doc.text("No room energy was recorded in this period.", 8.6, doc.MUTED)
    else:
        doc.room_list(
            [(str(rooms[rid]["name"]), float(rooms[rid]["wh"]))
             for rid in ordered_room_ids], total_wh,
        )

    # The detailed device register stays with the period summary on page one.
    devices = roll["devices"]
    doc.section("02", "Appliances and outlets",
                "Each device with a stored energy reading, sorted by estimated usage.", reserve=28)
    if not devices:
        doc.text("No device energy was recorded in this period.", 8.5, doc.MUTED)
    else:
        doc.table_header([(77, "Device", "L"), (55, "Room", "L"),
                          (27, "kWh", "R"), (23, "Share", "R")])
        ordered_devices = sorted(devices.values(), key=lambda item: item["wh"], reverse=True)
        for i, device in enumerate(ordered_devices):
            wh = float(device["wh"])
            room = rooms.get(device["room_id"], {})
            share = (wh / total_wh * 100.0) if total_wh > 0 else 0.0
            doc.table_row([
                str(device["name"]), str(room.get("name") or device["room_id"]),
                _kwh(wh, 2), f"{share:.0f}%",
            ], fill=i % 2 == 1)


    # The daily ledger always starts cleanly, never as an orphaned page heading.
    pdf.add_page()
    doc.section("03", "Day-by-day record",
                "Every calendar day is included. Room energy and each detected connection change appear under the day they occurred.",
                reserve=33)
    for day in calendar:
        day_events = by_day.get(day, [])
        if as_of is not None and day > as_of.isoformat():
            doc.day_heading(day, "NOT YET ELAPSED", "future")
            doc.text("Not yet elapsed. No energy or connectivity record exists for this day.",
                     8.2, doc.MUTED, width=173, x=19)
            # Defensive handling for provided events with a future date.
            for row in day_events:
                doc.daily_event(row)
            doc.gap(2.1)
            continue
        total = roll["daily_total"].get(day)
        if total is None:
            doc.day_heading(day, "NO ENERGY READING", "missing")
            doc.text("No energy reading was recorded.", 8.3, doc.MUTED,
                     width=173, x=19)
        else:
            doc.day_heading(day, f"{_kwh(float(total), 2)} kWh", "recorded")
            day_rooms = roll["daily_rooms"].get(day) or {}
            ranked = sorted(
                ((rid, float(value)) for rid, value in day_rooms.items()
                 if float(value) > 0),
                key=lambda pair: pair[1], reverse=True,
            )
            if ranked:
                for room_id, wh in ranked:
                    room_name = str(rooms.get(room_id, {}).get("name") or room_id)
                    doc.daily_room(room_name, wh, float(total))
            else:
                doc.text(f"Energy total {_kwh(float(total), 2)} kWh. No room breakdown was stored.",
                         8.3, doc.MUTED, width=173, x=19)
        if day_events:
            doc.gap(1)
            for row in day_events:
                doc.daily_event(row)
        else:
            doc.text("No disconnect or reconnect recorded.", 7.8, doc.MUTED,
                     width=173, x=19)
        doc.gap(2.1)

    persons = roll["persons"]
    doc.section("04", "Time spent at home",
                "For multiple trackers, the longest daily at-home reading is used to avoid double counting.",
                reserve=27)
    if not persons:
        doc.text("No one was tracked at home in this period.", 8.5, doc.MUTED)
    else:
        doc.table_header([(71, "Person", "L"), (34, "Days home", "R"),
                          (39, "Hours home", "R"), (38, "Hours / day", "R")])
        ordered_people = sorted(persons.values(), key=lambda p: str(p["name"]).lower())
        for i, person in enumerate(ordered_people):
            days_seen = int(person["days_seen"])
            home_hours = float(person["seconds_home"]) / 3600.0
            doc.table_row([
                str(person["name"]), str(int(person["days_home"])),
                f"{home_hours:.1f}", f"{(home_hours / days_seen if days_seen else 0):.1f}",
            ], fill=i % 2 == 1)

    doc.section("05", "Connectivity event history",
                "All recorded disconnect and reconnect events, oldest first. Each also appears in the daily record.",
                reserve=28)
    if not log:
        doc.text("No disconnect or reconnect was stored in this period.", 8.5, doc.MUTED)
    else:
        doc.table_header([(38, "When", "L"), (37, "Room", "L"),
                          (44, "Device", "L"), (31, "Reading", "L"),
                          (32, "Event", "L")])
        for i, row in enumerate(log):
            state = "disconnected" if row.get("event") == "disconnected" else "reconnected"
            doc.table_row([
                _clock(str(row.get("at") or "")), str(row.get("room_name") or ""),
                str(row.get("name") or ""), str(row.get("part") or ""),
                "Disconnected" if state == "disconnected" else "Reconnected",
            ], fill=i % 2 == 1, state=state, size=7.8)

    return bytes(pdf.output())


# --------------------------------------------------------------------------- files


def write_period_pdf(
    data_dir: str,
    key: str,
    days: dict[str, Any],
    generated_label: str,
    events: list[dict[str, Any]] | None = None,
) -> Path | None:
    """Write or replace one billing period. Other files are left in place."""
    path = report_path(data_dir, key)
    if path is None:
        return None
    try:
        data = render_period_pdf(path.stem, days, generated_label, events or [])
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
