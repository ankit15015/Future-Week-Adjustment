import datetime as dt

from future_week_adjustment import matching


def rec(weekday, start, headcount, workgroup="Inbound", name="Shift"):
    return {"workgroup": workgroup, "weekday": weekday, "shift_name": name,
            "start_time": start, "end_time": "16:00", "headcount": headcount}


SOURCE = matching.build_source_index([rec("Sunday", "06:00", 10), rec("Sunday", "14:00", 20)])


def test_exact_match():
    headcount, confidence, matched = matching.match_row(SOURCE, "Sunday", "Inbound", dt.time(6, 0))
    assert (headcount, confidence) == (10, "exact")


def test_near_match_within_15_minutes_picks_closest_shift():
    headcount, confidence, _ = matching.match_row(SOURCE, "Sunday", "Inbound", dt.time(6, 15))
    assert (headcount, confidence) == (10, "near")


def test_far_match_still_returns_the_closest_shift_but_is_flagged():
    headcount, confidence, _ = matching.match_row(SOURCE, "Sunday", "Inbound", dt.time(9, 0))
    assert (headcount, confidence) == (10, "far")


def test_no_source_match_for_unknown_workgroup_or_day():
    assert matching.match_row(SOURCE, "Sunday", "Outbound", dt.time(6, 0)) == (None, "no_source_match", None)
    assert matching.match_row(SOURCE, "Tuesday", "Inbound", dt.time(6, 0)) == (None, "no_source_match", None)


def test_no_time_when_the_destination_row_has_no_parsable_start():
    assert matching.match_row(SOURCE, None, "Inbound", None) == (None, "no_time", None)


def test_workgroup_match_ignores_case_and_order():
    index = matching.build_source_index([rec("Sunday", "06:00", 5, workgroup="Pack - Batch, Sort")])
    headcount, confidence, _ = matching.match_row(index, "Sunday", "sort,pack - batch", dt.time(6, 0))
    assert (headcount, confidence) == (5, "exact")


def test_time_difference_wraps_around_midnight():
    assert matching._time_diff_minutes(dt.time(23, 50), dt.time(0, 10)) == 20


def _results():
    return [
        {"workgroup": "Inbound", "start_time": "06:00", "end_time": "16:00"},
        {"workgroup": "Inbound", "start_time": "14:00", "end_time": "23:00"},
        {"workgroup": "", "start_time": "", "end_time": ""},
    ]


def test_apply_reasons_by_workgroup_with_default_fallback():
    out = matching.apply_reasons(_results(), "workgroup", {"Inbound": "Weekly alignment"}, "Fallback")
    assert [r["reason"] for r in out] == ["Weekly alignment", "Weekly alignment", "Fallback"]


def test_apply_reasons_by_shift_type():
    key = matching.shift_type_key("06:00", "16:00")
    out = matching.apply_reasons(_results(), "shift_type", {key: "Morning"}, "")
    assert [r["reason"] for r in out] == ["Morning", "", ""]


def test_distinct_groups_counts_and_orders_by_size():
    groups = matching.distinct_groups(_results(), "workgroup")
    assert groups == [("Inbound", 2), ("(blank)", 1)]
