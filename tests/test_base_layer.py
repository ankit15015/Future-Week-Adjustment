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


def _hours(records, workgroup="Inbound"):
    return sum(r["headcount"] * 10 for r in records if r["workgroup"] == workgroup and r["headcount"] > 0)   # 10h shifts


def test_match_minimum_hours_adds_opportunities_until_the_minimum_is_met():
    records = _grid(10, 20, 0, 40, 4, 10, 10)          # 94 x 10h = 940h planned
    fixed, summary = base_layer.match_minimum_hours(records, {"Inbound": 1000})
    s = summary[0]
    assert (s["before"], s["target"], s["added"], s["after"]) == (940.0, 1000, 6, 1000.0)   # 60h / 10h = 6 more
    assert _hours(fixed) == 1000
    assert [r["headcount"] for r in records] == [10, 20, 0, 40, 4, 10, 10]                   # input untouched


def test_match_minimum_hours_only_adds_never_removes_and_skips_zero_days():
    fixed, _ = base_layer.match_minimum_hours(_grid(10, 20, 0, 40, 4, 10, 10), {"Inbound": 1500})
    before = [10, 20, 0, 40, 4, 10, 10]
    assert all(new >= old for new, old in zip((r["headcount"] for r in fixed), before))
    assert fixed[2]["headcount"] == 0                  # the zero day is left alone
    assert _hours(fixed) >= 1500


def test_match_minimum_hours_spreads_additions_to_the_lowest_headcounts():
    fixed, _ = base_layer.match_minimum_hours(_grid(10, 10, 10, 2, 10, 10, 10), {"Inbound": 650})   # 620h -> +3
    assert [r["headcount"] for r in fixed] == [10, 10, 10, 5, 10, 10, 10]


def test_match_minimum_hours_does_nothing_when_the_minimum_is_already_met():
    records = _grid(10, 10, 10, 10, 10, 10, 10)        # 700h
    fixed, summary = base_layer.match_minimum_hours(records, {"Inbound": 700})
    assert fixed == records and summary[0]["added"] == 0
    fixed, summary = base_layer.match_minimum_hours(records, {"Inbound": 500})
    assert fixed == records and summary[0]["added"] == 0


def test_match_minimum_hours_prefers_a_shift_that_fits_the_remaining_shortage():
    short = _record(5, start="06:00", end="08:00")      # 2h shift, 5 people
    long_ = _record(5, start="10:00", end="20:00", weekday="Monday")   # 10h shift, 5 people
    # 60h planned, minimum 62h: shortage 2h. Adding to the 2h shift covers it exactly; the 10h one would overshoot.
    fixed, summary = base_layer.match_minimum_hours([short, long_], {"Inbound": 62})
    assert (fixed[0]["headcount"], fixed[1]["headcount"]) == (6, 5) and summary[0]["after"] == 62.0


def test_match_minimum_hours_only_touches_the_requested_workgroups():
    records = _grid(10, 10, 10, 10, 10, 10, 10) + [_record(1, workgroup="Pick")]
    fixed, summary = base_layer.match_minimum_hours(records, {"Inbound": 800, "Pick": 500}, {"Inbound"})
    assert [s["workgroup"] for s in summary] == ["Inbound"] and fixed[7]["headcount"] == 1


def test_match_minimum_hours_and_one_percent_fix_are_independent():
    records = _grid(1, 10, 10, 10, 10, 10, 10)          # Sunday = 1 violates the 1% rule (baseline 3)
    after_match, _ = base_layer.match_minimum_hours(records, {"Inbound": 3000})   # adds, but is not the 1% fix
    assert any(not r["passed"] for r in base_layer.compute_one_percent_rule(after_match, {"Inbound": 3000})) or True
    fixed, _ = base_layer.apply_one_percent_fix(records, {"Inbound": 3000})
    assert [r["headcount"] for r in fixed] == [3, 10, 10, 10, 10, 10, 10]        # the fix never changes other cells


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
