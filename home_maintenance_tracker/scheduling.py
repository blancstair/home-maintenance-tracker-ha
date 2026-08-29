"""Maintenance due-state, escalation, and usage forecasting calculations."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from math import ceil
from typing import Any


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def add_months(base: date, months: int) -> date:
    target_month = base.month - 1 + months
    year = base.year + target_month // 12
    month = target_month % 12 + 1
    return date(year, month, min(base.day, monthrange(year, month)[1]))


def add_interval(base: date, value: float, unit: str) -> date:
    if unit == "days":
        return base + timedelta(days=value)
    if unit == "weeks":
        return base + timedelta(weeks=value)
    if unit == "months":
        whole = int(value)
        result = add_months(base, whole)
        fraction = value - whole
        if fraction:
            result += timedelta(days=round(30.4375 * fraction))
        return result
    if unit == "years":
        return add_months(base, int(round(value * 12)))
    raise ValueError(f"Unsupported calendar unit: {unit}")


def current_meter(db, meter_id: str | None) -> dict[str, Any] | None:
    if not meter_id:
        return None
    row = db.execute(
        "SELECT mr.reading,mr.recorded_at,m.name,m.unit,m.kind "
        "FROM meters m LEFT JOIN meter_readings mr ON mr.id=("
        "SELECT id FROM meter_readings WHERE meter_id=m.id ORDER BY recorded_at DESC LIMIT 1) "
        "WHERE m.id=?",
        (meter_id,),
    ).fetchone()
    return dict(row) if row and row["reading"] is not None else None


def usage_forecast(db, meter_id: str | None, target: float | None) -> dict[str, Any] | None:
    if not meter_id or target is None:
        return None
    rows = db.execute(
        "SELECT reading,recorded_at FROM meter_readings WHERE meter_id=? ORDER BY recorded_at DESC LIMIT 12",
        (meter_id,),
    ).fetchall()
    if not rows:
        return None
    current = float(rows[0]["reading"])
    remaining = target - current
    result = {"current": current, "remaining": max(0, remaining), "estimated_date": None, "daily_rate": None}
    if len(rows) < 2:
        return result
    newest_time = parse_datetime(rows[0]["recorded_at"])
    oldest_time = parse_datetime(rows[-1]["recorded_at"])
    elapsed_days = (newest_time - oldest_time).total_seconds() / 86400 if newest_time and oldest_time else 0
    usage = current - float(rows[-1]["reading"])
    if elapsed_days <= 0 or usage <= 0:
        return result
    daily_rate = usage / elapsed_days
    result["daily_rate"] = round(daily_rate, 3)
    if remaining > 0:
        result["estimated_date"] = (date.today() + timedelta(days=remaining / daily_rate)).isoformat()
    else:
        result["estimated_date"] = date.today().isoformat()
    return result


def _calendar_dates(task: dict[str, Any], today: date) -> tuple[date | None, date | None]:
    schedule_type = task["schedule_type"]
    start = parse_date(task.get("start_date"))
    last = parse_date(task.get("last_completed_date"))
    value = task.get("calendar_value")
    unit = task.get("calendar_unit")

    if schedule_type == "one_time":
        due = start
        return due, due

    if schedule_type in ("pattern", "seasonal") and start:
        # Pattern and seasonal tasks stay anchored to scheduled occurrences,
        # never the date on which work happened early or late.
        month = task.get("fixed_month") or start.month
        day = task.get("fixed_day") or start.day
        anchor = date(start.year, month, min(day, monthrange(start.year, month)[1]))
        interval_value = float(value or 1)
        interval_unit = unit or "years"
        previous_due = parse_date(task.get("last_scheduled_due"))
        if previous_due:
            due = add_interval(previous_due, interval_value, interval_unit)
        else:
            due = anchor
            # Legacy/sample rows may have completion history from before the
            # explicit scheduled-occurrence field existed.
            while last and due <= last:
                next_due = add_interval(due, interval_value, interval_unit)
                if next_due <= due:
                    break
                due = next_due
        period_days = max(1, (add_interval(due, interval_value, interval_unit) - due).days)
        return due, due + timedelta(days=ceil(period_days * 0.5))

    if value and unit:
        base = last or start
        if not base:
            return None, None
        due = add_interval(base, float(value), unit)
        interval_days = max(1, (due - base).days)
        # Date-only records escalate on the first full calendar day beyond 1.5×.
        red = base + timedelta(days=ceil(interval_days * 1.5))
        return due, red
    return None, None


def enrich_task(db, raw_task: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    task = dict(raw_task)
    calendar_due, calendar_red = _calendar_dates(task, today)
    meter = current_meter(db, task.get("meter_id"))
    meter_due = None
    meter_red = None
    if task.get("meter_interval") is not None:
        base = task.get("last_completed_reading")
        if base is None:
            base = 0
        meter_due = float(base) + float(task["meter_interval"])
        meter_red = float(base) + 1.5 * float(task["meter_interval"])

    calendar_overdue = calendar_due is not None and today > calendar_due
    calendar_is_red = calendar_red is not None and today >= calendar_red
    meter_overdue = meter_due is not None and meter is not None and float(meter["reading"]) >= meter_due
    meter_is_red = meter_red is not None and meter is not None and float(meter["reading"]) >= meter_red

    stype = task["schedule_type"]
    if stype == "combined":
        if task.get("combination_rule") == "last":
            overdue = calendar_overdue and meter_overdue
            red = calendar_is_red and meter_is_red
        else:
            overdue = calendar_overdue or meter_overdue
            red = calendar_is_red or meter_is_red
    elif stype == "meter":
        overdue, red = meter_overdue, meter_is_red
    elif stype == "condition":
        overdue = bool(task.get("manual_due"))
        red = False
    else:
        overdue, red = calendar_overdue, calendar_is_red

    snoozed_until = parse_date(task.get("snoozed_until"))
    snoozed = bool(snoozed_until and today <= snoozed_until and not red)
    effective_overdue = overdue and not snoozed
    due_soon = bool(calendar_due and today <= calendar_due <= today + timedelta(days=30))
    forecast = usage_forecast(db, task.get("meter_id"), meter_due)
    projected_due = forecast.get("estimated_date") if forecast else None

    if red:
        state = "red"
    elif effective_overdue:
        state = "overdue"
    elif snoozed:
        state = "snoozed"
    elif due_soon or (projected_due and today.isoformat() <= projected_due <= (today + timedelta(days=30)).isoformat()):
        state = "upcoming"
    else:
        state = "normal"

    task.update({
        "calendar_due": calendar_due.isoformat() if calendar_due else None,
        "calendar_red": calendar_red.isoformat() if calendar_red else None,
        "meter": meter,
        "meter_due": meter_due,
        "meter_red": meter_red,
        "meter_forecast": forecast,
        "overdue": bool(overdue),
        "red": bool(red),
        "snoozed": snoozed,
        "state": state,
    })
    return task


def reminder_days(task: dict[str, Any]) -> int:
    """Approved overdue cadence: daily, weekly, fortnightly, or monthly."""
    if task["schedule_type"] == "one_time":
        return 1
    value = task.get("calendar_value")
    unit = task.get("calendar_unit")
    projected_days = None
    if value and unit:
        base = date.today()
        projected_days = max(1, (add_interval(base, float(value), unit) - base).days)
    elif task.get("meter_forecast") and task["meter_forecast"].get("daily_rate") and task.get("meter_interval"):
        projected_days = float(task["meter_interval"]) / task["meter_forecast"]["daily_rate"]
    if projected_days is None:
        return 7
    if projected_days <= 7:
        return 1
    if projected_days <= 92:
        return 7
    if projected_days <= 274:
        return 14
    return 30
