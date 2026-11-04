import datetime as dt

import pytest

from conftest import make_base_layer
from future_week_adjustment import base_layer


def test_normalize_workgroup_ignores_case_spacing_and_order():
    assert base_layer.normalize_workgroup("Pack - Batch, Pack - Flow, Sort") == \
        base_layer.normalize_workgroup("sort,  pack - flow ,Pack - Batch")


def test_split_workgroups_lists_each_workgroup_once_in_original_order():
    assert base_layer.split_workgroups("Pack - Batch, Pack - Flow,  Sort") == ["Pack - Batch", "Pack - Flow", "Sort"]
    assert base_layer.split_workgroups("Pick") == ["Pick"]
    assert base_layer.split_workgroups("") == []
    assert base_layer.split_workgroups("Prep,Receive,") == ["Prep", "Receive"]


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
    # 3000 min hours * 1% / 10h shift = 3.0 -> baseline 3
    results = base_layer.compute_one_percent_rule([_record(1), _record(5, weekday="Monday")], {"Inbound": 3000})
    by_day = {r["weekday"]: r for r in results}
    assert by_day["Sunday"]["baseline"] == 3 and not by_day["Sunday"]["passed"] and by_day["Sunday"]["shortfall"] == 2
    assert by_day["Monday"]["passed"] and by_day["Monday"]["shortfall"] == 0


def test_one_percent_rule_ignores_zero_headcounts():
    """An empty (0) cell is not a staffed shift: like the sheet's own '1% Violation' column, skip it."""
    results = base_layer.compute_one_percent_rule([_record(0), _record(1, weekday="Monday")], {"Inbound": 3000})
    assert [r["weekday"] for r in results] == ["Monday"]


def test_one_percent_rule_skips_workgroups_without_minimum_hours():
    assert base_layer.compute_one_percent_rule([_record(5)], {}) == []


def test_one_percent_rule_wraps_shifts_past_midnight():
    # 22:00 -> 06:00 is 8h: 800 * 1% / 8 = 1.0 -> baseline 1
    results = base_layer.compute_one_percent_rule([_record(1, start="22:00", end="06:00")], {"Inbound": 800})
    assert results[0]["duration_hours"] == 8 and results[0]["baseline"] == 1


# ---- Base Layer fixes (ported from the macro script) ----

MIN = {"Inbound": 3000}   # 10h shift -> 1% baseline = 3


def _grid(*headcounts):
    days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    return [_record(h, weekday=d) for h, d in zip(headcounts, days)]


def test_one_percent_fix_raises_only_nonzero_cells_below_the_baseline():
    records = _grid(1, 0, 2, 3, 9, 0, 1)
    fixed, changed = base_layer.apply_one_percent_fix(records, MIN)
    assert [r["headcount"] for r in fixed] == [3, 0, 3, 3, 9, 0, 3]   # zeros stay zero, others lifted to 3
    assert changed == 3
    assert [r["headcount"] for r in records] == [1, 0, 2, 3, 9, 0, 1]   # input untouched
    assert all(r["passed"] for r in base_layer.compute_one_percent_rule(fixed, MIN))


def test_one_percent_fix_leaves_workgroups_without_minimum_hours_alone():
    fixed, changed = base_layer.apply_one_percent_fix(_grid(1, 1, 1, 1, 1, 1, 1), {})
    assert changed == 0 and all(r["headcount"] == 1 for r in fixed)


def test_match_minimum_hours_scales_rounds_up_and_respects_the_one_percent_floor():
    records = _grid(10, 20, 0, 40, 4, 10, 10)      # total = 94 x 10h = 940h
    fixed, summary = base_layer.match_minimum_hours(records, MIN, {"Inbound": 470})   # factor 0.5
    # 10->5, 20->10, 0 stays 0, 40->20, 4->2 but floor is 3, 10->5, 10->5
    assert [r["headcount"] for r in fixed] == [5, 10, 0, 20, 3, 5, 5]
    s = summary[0]
    assert (s["workgroup"], s["target"], s["before"], s["factor"]) == ("Inbound", 470, 940.0, 0.5)
    assert s["after"] >= 470 and s["after"] == 480.0   # rounded up, so at or just above the target


def test_match_minimum_hours_does_not_round_float_noise_up():
    # 940h target with factor exactly 1.0 must not nudge any cell up
    fixed, _ = base_layer.match_minimum_hours(_grid(10, 20, 0, 40, 4, 10, 10), {"Inbound": 940}, None)
    assert [r["headcount"] for r in fixed] == [10, 20, 0, 40, 4, 10, 10]


def test_match_minimum_hours_defaults_to_the_source_minimum_and_skips_other_workgroups():
    other = _record(7, workgroup="Pick")
    fixed, summary = base_layer.match_minimum_hours(_grid(10, 10, 10, 10, 10, 10, 10) + [other], {"Inbound": 350})
    assert [r["headcount"] for r in fixed[:7]] == [5] * 7   # 700h -> 350h
    assert fixed[7]["headcount"] == 7 and [s["workgroup"] for s in summary] == ["Inbound"]


def test_written_base_layer_reads_back_identically_including_tail_shifts(tmp_path):
    src = tmp_path / "base.xlsx"
    make_base_layer(src, min_hours=3000, tail_shift=True)     # has an early-morning 'Tail' shift
    records, _, minimum, _ = base_layer.parse_source(str(src))
    out = tmp_path / "out.xlsx"
    base_layer.write_base_layer_xlsx(records, minimum, str(out), site="TST1")

    back, _, minimum_back, _ = base_layer.parse_source(str(out))
    key = lambda r: (r["workgroup"], r["weekday"], r["shift_name"], r["start_time"], r["end_time"])
    assert {key(r): r["headcount"] for r in back} == {key(r): r["headcount"] for r in records}
    assert minimum_back == minimum
    assert base_layer.list_sites(str(out)) == ["TST1"]
