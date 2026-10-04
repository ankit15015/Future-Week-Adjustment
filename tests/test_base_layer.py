import datetime as dt

import pytest

from conftest import make_base_layer
from future_week_adjustment import base_layer


def test_normalize_workgroup_ignores_case_spacing_and_order():
    assert base_layer.normalize_workgroup("Pack - Batch, Pack - Flow, Sort") == \
        base_layer.normalize_workgroup("sort,  pack - flow ,Pack - Batch")


@pytest.mark.parametrize("raw, expected", [
    ("Sunday", "Sunday"), (" mon ", "Monday"), ("TUES", "Tuesday"), ("xyz", None), (None, None),
])
def test_normalize_weekday(raw, expected):
    assert base_layer.normalize_weekday(raw) == expected


def test_to_time_handles_excel_floats_strings_and_blanks():
    assert base_layer.to_time(0.25) == dt.time(6, 0)
    assert base_layer.to_time("14:30") == dt.time(14, 30)
    assert base_layer.to_time(dt.time(9, 5)) == dt.time(9, 5)
    assert base_layer.to_time("") is None
    assert base_layer.to_time(None) is None


def test_parse_source_reads_every_shift_and_day(tmp_path):
    path = tmp_path / "base.xlsx"
    make_base_layer(path)
    records, warnings, min_hours, total_hours = base_layer.parse_source(str(path))

    assert len(records) == 14  # 2 shifts x 7 days
    sunday_day = next(r for r in records if r["weekday"] == "Sunday" and r["shift_name"] == "Day")
    assert (sunday_day["workgroup"], sunday_day["start_time"], sunday_day["end_time"], sunday_day["headcount"]) \
        == ("Inbound", "06:00", "16:00", 10.0)
    assert min_hours == {} and total_hours == {}


def test_parse_source_reads_minimum_hours(tmp_path):
    path = tmp_path / "base.xlsx"
    make_base_layer(path, min_hours=700)
    _, _, min_hours, total_hours = base_layer.parse_source(str(path))
    assert min_hours == {"Inbound": 700.0}
    assert total_hours == {"Inbound": 1000.0}


def test_early_morning_tail_shift_counts_toward_the_next_day(tmp_path):
    """A shift starting before the block's first shift (e.g. 02:45) belongs to the day AFTER its column."""
    path = tmp_path / "base.xlsx"
    make_base_layer(path, tail_shift=True)
    records, _, _, _ = base_layer.parse_source(str(path))
    tail = {r["weekday"]: r["headcount"] for r in records if r["shift_name"] == "Tail"}
    # Column "Sunday" holds 30, which must land on Monday; "Saturday" (36) wraps to Sunday.
    assert tail["Monday"] == 30.0
    assert tail["Sunday"] == 36.0


def test_unsupported_source_type_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        base_layer.parse_source(str(tmp_path / "notes.txt"))


def _record(headcount, start="06:00", end="16:00", weekday="Sunday", workgroup="Inbound"):
    return {"workgroup": workgroup, "weekday": weekday, "shift_name": "Day",
            "start_time": start, "end_time": end, "headcount": headcount}


def test_one_percent_rule_baseline_and_shortfall():
    # 700 min hours * 1% / 10h shift = 0.7 -> baseline ceil = 1
    results = base_layer.compute_one_percent_rule([_record(0), _record(3, weekday="Monday")], {"Inbound": 700})
    by_day = {r["weekday"]: r for r in results}
    assert by_day["Sunday"]["baseline"] == 1 and not by_day["Sunday"]["passed"] and by_day["Sunday"]["shortfall"] == 1
    assert by_day["Monday"]["passed"] and by_day["Monday"]["shortfall"] == 0


def test_one_percent_rule_skips_workgroups_without_minimum_hours():
    assert base_layer.compute_one_percent_rule([_record(5)], {}) == []


def test_one_percent_rule_wraps_shifts_past_midnight():
    # 22:00 -> 06:00 is 8h: 800 * 1% / 8 = 1.0 -> baseline 1
    results = base_layer.compute_one_percent_rule([_record(1, start="22:00", end="06:00")], {"Inbound": 800})
    assert results[0]["duration_hours"] == 8 and results[0]["baseline"] == 1
