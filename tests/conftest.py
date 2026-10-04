"""
Shared fixtures. Tests build tiny synthetic Base Layer / Opportunities files in a temp folder,
so they need none of the real (confidential) data and none of the OCR dependencies.
"""
import csv
import datetime as dt
import io

import openpyxl
import pytest

from future_week_adjustment import app as app_module

WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
SUNDAY = dt.date(2026, 9, 27)  # a real Sunday; asserted below so the fixtures can't silently drift

OPPORTUNITY_HEADERS = [
    "Workgroup(s)", "Opportunity Start Date-Time", "Opportunity End Date-Time",
    "Headcount", "Reason", "Notes",
]


def opportunity(workgroup, weekday, start, end, headcount="1", reason="", notes="keep me", end_next_day=False):
    """One Opportunities row. `start`/`end` are 'HH:MM'; the date is derived from `weekday`.
    `end_next_day=True` makes an overnight shift that ends the following day."""
    assert SUNDAY.strftime("%A") == "Sunday"
    day = SUNDAY + dt.timedelta(days=WEEKDAYS.index(weekday))
    end_day = day + dt.timedelta(days=1) if end_next_day else day
    return {
        "Workgroup(s)": workgroup,
        "Opportunity Start Date-Time": f"{day.isoformat()}T{start}",
        "Opportunity End Date-Time": f"{end_day.isoformat()}T{end}",
        "Headcount": headcount,
        "Reason": reason,
        "Notes": notes,
    }


# Inbound has two shifts in the source (06:00-16:00 -> 10..16 per day, 14:00-23:00 -> 20..26).
# Outbound is absent from the source, so its row must stay "no source match".
DEFAULT_OPPORTUNITIES = [
    opportunity("Inbound", "Sunday", "06:00", "16:00", "1", "old reason A"),
    opportunity("Inbound", "Sunday", "06:10", "16:10", "1", "old reason B"),   # near match (10 min off)
    opportunity("Inbound", "Sunday", "14:00", "23:00", "1"),
    opportunity("Inbound", "Monday", "06:00", "16:00", "1"),
    opportunity("Outbound", "Sunday", "06:00", "16:00", "7", "old reason C"),  # no source match
]


def make_base_layer(path, min_hours=None, headcount_overrides=None, tail_shift=False):
    """
    Write a minimal Base Layer workbook the parser understands: weekday header row, a
    'Shift / Start Time / End Time' header row carrying the workgroup per day column, then one
    row per shift. `min_hours` adds a 'Minimum Hours' cell under the block.
    `headcount_overrides` maps (shift_name, weekday) -> headcount.
    """
    overrides = headcount_overrides or {}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Baselayer"
    first_day_col = 4
    for i, wd in enumerate(WEEKDAYS):
        ws.cell(1, first_day_col + i, wd)
        ws.cell(2, first_day_col + i, "Inbound")
    ws.cell(2, 1, "Shift")
    ws.cell(2, 2, "Start Time")
    ws.cell(2, 3, "End Time")

    shifts = [("Day", "06:00", "16:00", 10), ("Late", "14:00", "23:00", 20)]
    if tail_shift:
        shifts.append(("Tail", "02:45", "06:00", 30))  # starts before the first shift -> belongs to next day
    row = 3
    for name, start, end, base in shifts:
        ws.cell(row, 1, name)
        ws.cell(row, 2, start)
        ws.cell(row, 3, end)
        for i, wd in enumerate(WEEKDAYS):
            ws.cell(row, first_day_col + i, overrides.get((name, wd), base + i))
        row += 1
    if min_hours is not None:
        ws.cell(row + 1, 2, 1000)           # block total hours, one row above Minimum Hours
        ws.cell(row + 2, 2, min_hours)
        ws.cell(row + 2, 3, "Minimum Hours")
    wb.save(path)


def make_opportunities_csv(path, rows=None):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OPPORTUNITY_HEADERS)
        writer.writeheader()
        writer.writerows(rows if rows is not None else DEFAULT_OPPORTUNITIES)


def make_opportunities_xlsx(path, rows=None, blank_row_after=None):
    """`blank_row_after=N` inserts an empty worksheet row after the Nth data row."""
    rows = rows if rows is not None else DEFAULT_OPPORTUNITIES
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(OPPORTUNITY_HEADERS)
    for i, r in enumerate(rows, start=1):
        ws.append([r[h] for h in OPPORTUNITY_HEADERS])
        if blank_row_after == i:
            ws.append([None] * len(OPPORTUNITY_HEADERS))
    wb.save(path)


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def upload(client, endpoint, path):
    data = {"file": (io.BytesIO(path.read_bytes()), path.name)}
    return client.post(endpoint, data=data, content_type="multipart/form-data")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client whose upload/output/data folders all live in a throwaway temp dir."""
    for attr in ("UPLOAD_DIR", "OUTPUT_DIR", "DATA_DIR"):
        folder = tmp_path / attr.lower()
        folder.mkdir()
        monkeypatch.setattr(app_module, attr, str(folder))
    app_module.SESSIONS.clear()
    app_module.app.config.update(TESTING=True)
    return app_module.app.test_client()


@pytest.fixture
def output_dir():
    from pathlib import Path
    return Path(app_module.OUTPUT_DIR)
