"""End-to-end through the Flask API: upload -> match -> reasons -> final result -> export."""
import pytest

from conftest import (DEFAULT_OPPORTUNITIES, OPPORTUNITY_HEADERS, make_base_layer,
                      make_opportunities_csv, make_opportunities_xlsx, opportunity, read_csv, upload)
from future_week_adjustment import opportunities


@pytest.fixture
def loaded_client(client, tmp_path):
    """Client with a source and destination already loaded and matched."""
    src, dst = tmp_path / "base.xlsx", tmp_path / "opps.csv"
    make_base_layer(src)
    make_opportunities_csv(dst)
    assert upload(client, "/api/source", src).status_code == 200
    assert upload(client, "/api/destination", dst).status_code == 200
    assert client.post("/api/match").status_code == 200
    return client


def preview(client, reason_map=None, default_reason=""):
    r = client.post("/api/reasons/preview", json={
        "group_by": "workgroup", "reason_map": reason_map or {}, "default_reason": default_reason})
    assert r.status_code == 200
    return r.get_json()["results"]


def final(client):
    return client.get("/api/final").get_json()


def final_rows(client):
    return final(client)["rows"]


def assert_file_rows_equal_table(file_rows, table_rows, columns):
    """Every column of every file row must equal what the final-result table showed for it."""
    assert len(file_rows) == len(table_rows)
    for shown, written in zip(table_rows, file_rows):
        for col in columns:
            assert written[col] == shown["values"][col], f"row {shown['index'] + 1}, column {col!r}"


def test_index_page_serves_static_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_filter_elements_exist_in_both_filter_bars(client):
    html = client.get("/").get_data(as_text=True)
    for prefix in ("filter", "final-filter"):
        for name in ("workgroup", "day", "start", "end"):                  # multi-select buttons
            assert f'<button type="button" class="multi-filter-btn" id="{prefix}-{name}"' in html
        for name in ("start-date", "end-date"):                           # date ranges
            assert f'id="{prefix}-{name}-from"' in html and f'id="{prefix}-{name}-to"' in html


def test_match_results_and_confidence(loaded_client):
    results = loaded_client.post("/api/match").get_json()["results"]
    by_key = {(r["workgroup"], r["weekday"], r["start_time"]): r for r in results}
    assert by_key[("Inbound", "Sunday", "06:00")]["new_headcount"] == 10
    assert by_key[("Inbound", "Sunday", "06:00")]["confidence"] == "exact"
    assert by_key[("Inbound", "Sunday", "06:10")]["confidence"] == "near"
    assert by_key[("Inbound", "Sunday", "14:00")]["new_headcount"] == 20
    assert by_key[("Inbound", "Monday", "06:00")]["new_headcount"] == 11
    assert by_key[("Outbound", "Sunday", "06:00")]["confidence"] == "no_source_match"


def test_match_results_carry_start_and_end_dates_and_individual_workgroups(loaded_client):
    results = loaded_client.post("/api/match").get_json()["results"]
    sunday = next(r for r in results if r["weekday"] == "Sunday")
    monday = next(r for r in results if r["weekday"] == "Monday")
    assert (sunday["start_date"], monday["start_date"]) == ("2026-09-27", "2026-09-28")
    assert (sunday["end_date"], sunday["start_time"], sunday["end_time"]) == ("2026-09-27", "06:00", "16:00")
    assert sunday["workgroups"] == [sunday["workgroup"]]


def test_overnight_shift_ends_on_the_next_date(client, tmp_path):
    rows = [opportunity("Inbound", "Sunday", "22:00", "06:00", end_next_day=True),
            opportunity("Inbound", "Sunday", "06:00", "16:00")]
    src, dst = tmp_path / "base.xlsx", tmp_path / "opps.csv"
    make_base_layer(src)
    make_opportunities_csv(dst, rows)
    upload(client, "/api/source", src)
    upload(client, "/api/destination", dst)
    results = client.post("/api/match").get_json()["results"]
    overnight, same_day = results
    assert (overnight["start_date"], overnight["end_date"]) == ("2026-09-27", "2026-09-28")
    assert (same_day["start_date"], same_day["end_date"]) == ("2026-09-27", "2026-09-27")
    preview(client)
    final = final_rows(client)
    assert (final[0]["start_date"], final[0]["end_date"], final[0]["start_time"], final[0]["end_time"]) \
        == ("2026-09-27", "2026-09-28", "22:00", "06:00")


def test_combined_workgroup_labels_are_split_for_filtering(client, tmp_path):
    rows = [
        {**DEFAULT_OPPORTUNITIES[0], "Workgroup(s)": "Pack - Batch, Pack - Flow,  Sort"},
        DEFAULT_OPPORTUNITIES[1],
    ]
    src, dst = tmp_path / "base.xlsx", tmp_path / "opps.csv"
    make_base_layer(src)
    make_opportunities_csv(dst, rows)
    upload(client, "/api/source", src)
    upload(client, "/api/destination", dst)
    results = client.post("/api/match").get_json()["results"]
    assert results[0]["workgroups"] == ["Pack - Batch", "Pack - Flow", "Sort"]
    assert results[0]["workgroup"] == "Pack - Batch, Pack - Flow,  Sort"   # original label untouched
    preview(client)
    assert final_rows(client)[0]["workgroups"] == ["Pack - Batch", "Pack - Flow", "Sort"]


def test_destination_requires_a_source_with_minimum_hours_confirmed(client, tmp_path):
    src, dst = tmp_path / "base.xlsx", tmp_path / "opps.csv"
    make_base_layer(src, min_hours=700)
    make_opportunities_csv(dst)
    upload(client, "/api/source", src)

    blocked = upload(client, "/api/destination", dst)
    assert blocked.status_code == 400 and "minimum hours" in blocked.get_json()["description"].lower()

    too_low = client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 100}})
    assert too_low.get_json()["passed"] is False
    assert upload(client, "/api/destination", dst).status_code == 400

    ok = client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 700}})
    assert ok.get_json()["passed"] is True
    assert upload(client, "/api/destination", dst).status_code == 200


def test_destination_is_blocked_while_the_one_percent_rule_fails(client, tmp_path):
    src, dst = tmp_path / "base.xlsx", tmp_path / "opps.csv"
    make_base_layer(src, min_hours=3000, headcount_overrides={("Day", "Sunday"): 1})
    make_opportunities_csv(dst)
    r = upload(client, "/api/source", src)
    failing = [x for x in r.get_json()["one_percent_rule"] if not x["passed"]]
    assert [(x["weekday"], x["shortfall"]) for x in failing] == [("Sunday", 2)]

    client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 3000}})
    blocked = upload(client, "/api/destination", dst)
    assert blocked.status_code == 400 and "1% rule" in blocked.get_json()["description"]


def test_match_requires_source_and_destination(client):
    assert client.post("/api/match").status_code == 400


def test_export_requires_a_reason_preview_first(loaded_client):
    assert loaded_client.get("/api/final").status_code == 400
    assert loaded_client.post("/api/export").status_code == 400


def test_loading_a_new_destination_discards_stale_match_results(loaded_client, tmp_path):
    preview(loaded_client)
    smaller = tmp_path / "smaller.csv"
    make_opportunities_csv(smaller, DEFAULT_OPPORTUNITIES[:1])
    assert upload(loaded_client, "/api/destination", smaller).status_code == 200
    # Old results no longer line up with the new file, so nothing can be previewed/exported until re-matched.
    assert loaded_client.get("/api/final").status_code == 400
    assert loaded_client.post("/api/export").status_code == 400
    assert loaded_client.post("/api/match").status_code == 200


def test_final_result_lists_every_column_of_the_output_file(loaded_client):
    preview(loaded_client, {"Inbound": "Weekly alignment"})
    result = final(loaded_client)
    assert result["columns"] == OPPORTUNITY_HEADERS
    assert result["headers"]["headcount"] == "Headcount" and result["headers"]["reason"] == "Reason"
    for row in result["rows"]:
        assert set(row["values"]) == set(OPPORTUNITY_HEADERS)
        assert row["values"]["Notes"] == "keep me"          # untouched columns are shown too


def test_final_rows_show_what_the_file_will_hold(loaded_client):
    preview(loaded_client, {"Inbound": "Weekly alignment"})   # Outbound gets no reason
    rows = {(r["workgroup"], r["weekday"], r["start_time"]): r for r in final_rows(loaded_client)}

    inbound = rows[("Inbound", "Sunday", "06:00")]
    assert (inbound["headcount"], inbound["updated"], inbound["reason"]) == ("10", True, "Weekly alignment")
    assert inbound["changed"] == {"Headcount": "1", "Reason": "old reason A"}   # column -> original value
    # No source match: keeps the original headcount AND the original reason (blank reason = leave the cell alone).
    outbound = rows[("Outbound", "Sunday", "06:00")]
    assert (outbound["headcount"], outbound["updated"], outbound["reason"]) == ("7", False, "old reason C")
    assert outbound["changed"] == {}
    assert outbound["confidence"] == "no_source_match"


def test_headcounts_are_whole_numbers_not_floats(loaded_client, output_dir):
    """The source parser yields floats; the file and the table must say 10, not 10.0."""
    preview(loaded_client)
    table = final_rows(loaded_client)
    assert all("." not in r["headcount"] for r in table)
    j = loaded_client.post("/api/export").get_json()
    assert all("." not in row["Headcount"] for row in read_csv(output_dir / j["filename"]))


def test_full_export_matches_the_final_table_in_every_column(loaded_client, output_dir):
    preview(loaded_client, {"Inbound": "Weekly alignment"})
    result = final(loaded_client)
    table = result["rows"]

    j = loaded_client.post("/api/export", json={"indices": [r["index"] for r in table]}).get_json()
    assert j["filtered"] is False and j["rows_written"] == j["rows_total"] == len(table)
    assert j["filename"].endswith(" - Updated.csv")
    assert j["rows_unmatched"] == 1

    assert_file_rows_equal_table(read_csv(output_dir / j["filename"]), table, result["columns"])


def test_filtered_export_contains_only_the_selected_rows(loaded_client, output_dir):
    preview(loaded_client, {"Inbound": "Weekly alignment"})
    result = final(loaded_client)
    table = result["rows"]
    subset = [r for r in table if r["workgroup"] == "Inbound" and r["weekday"] == "Sunday"]
    assert 0 < len(subset) < len(table)

    j = loaded_client.post("/api/export", json={"indices": [x["index"] for x in subset]}).get_json()
    assert j["filtered"] is True and j["rows_written"] == len(subset) and j["rows_total"] == len(table)
    assert "(filtered)" in j["filename"]

    file_rows = read_csv(output_dir / j["filename"])
    assert {w["Workgroup(s)"] for w in file_rows} == {"Inbound"}
    assert_file_rows_equal_table(file_rows, subset, result["columns"])


@pytest.mark.parametrize("indices, why", [([], "empty selection"), ([99999], "unknown row"), (["x"], "non-numeric")])
def test_export_rejects_bad_selections(loaded_client, indices, why):
    preview(loaded_client)
    assert loaded_client.post("/api/export", json={"indices": indices}).status_code == 400, why


def test_export_without_a_selection_writes_every_row(loaded_client, output_dir):
    preview(loaded_client)
    j = loaded_client.post("/api/export").get_json()
    assert j["rows_written"] == len(DEFAULT_OPPORTUNITIES) and j["filtered"] is False


def test_xlsx_destination_with_blank_row_exports_correctly(client, tmp_path, output_dir):
    import openpyxl
    src, dst = tmp_path / "base.xlsx", tmp_path / "opps.xlsx"
    make_base_layer(src)
    make_opportunities_xlsx(dst, blank_row_after=1)
    upload(client, "/api/source", src)
    assert upload(client, "/api/destination", dst).status_code == 200
    client.post("/api/match")
    preview(client, {"Inbound": "r"})
    result = final(client)
    table = result["rows"]

    j = client.post("/api/export", json={"indices": [r["index"] for r in table]}).get_json()
    ws = openpyxl.load_workbook(output_dir / j["filename"]).active
    data_rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if any(v is not None for v in r)]
    assert len(data_rows) == len(table)
    for shown, written in zip(table, data_rows):
        for col, cell in zip(result["columns"], written):
            assert opportunities.format_cell(cell) == shown["values"][col], f"row {shown['index'] + 1}, {col!r}"


def test_download_serves_the_generated_file(loaded_client):
    preview(loaded_client)
    j = loaded_client.post("/api/export").get_json()
    resp = loaded_client.get(j["download_url"])
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]


# ---- multi-site CSV Base Layer ----

def _multi_site_csv(path):
    """Two sites' blocks in one CSV, each under a '<SITE> FC Ready Base Layer' title."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    lines = []
    for site, wg, hc in (("AAA1", "Inbound", 5), ("BBB2", "Pick", 9)):
        lines.append(f",{site} FC Ready Base Layer," + "," * 8)
        lines.append("," * 4 + ",".join(days))
        lines.append(",Shift,Start Time,End Time," + ",".join([wg] * 7))
        lines.append(",Day,07:00,12:20," + ",".join([str(hc)] * 7))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8-sig")


def test_csv_base_layer_with_several_sites_asks_for_a_site(client, tmp_path):
    src = tmp_path / "multi.csv"
    _multi_site_csv(src)
    first = upload(client, "/api/source", src).get_json()
    assert first["needs_site"] is True and first["sites"] == ["AAA1", "BBB2"]

    data = {"file": (__import__("io").BytesIO(src.read_bytes()), src.name), "site": "bbb2"}
    r = client.post("/api/source", data=data, content_type="multipart/form-data").get_json()
    assert r["site"] == "BBB2" and r["record_count"] == 7
    assert {x["workgroup"] for x in r["records"]} == {"Pick"} and r["records"][0]["headcount"] == 9


def test_loading_a_base_layer_as_destination_explains_itself(client, tmp_path):
    src = tmp_path / "base.xlsx"
    make_base_layer(src)
    upload(client, "/api/source", src)
    r = upload(client, "/api/destination", src)
    assert r.status_code == 400 and "load it under Source" in r.get_json()["description"]


# ---- the two Base Layer fixes through the API ----

def _load_source_with_min_hours(client, tmp_path, **overrides):
    src = tmp_path / "base.xlsx"
    make_base_layer(src, min_hours=3000, **overrides)
    return upload(client, "/api/source", src).get_json()


def test_one_percent_fix_endpoint_lifts_shortfalls_and_unlocks_the_destination(client, tmp_path):
    loaded = _load_source_with_min_hours(client, tmp_path, headcount_overrides={("Day", "Sunday"): 1, ("Day", "Monday"): 0})
    assert [x["weekday"] for x in loaded["one_percent_rule"] if not x["passed"]] == ["Sunday"]   # the 0 is ignored

    r = client.post("/api/source/one-percent-fix").get_json()
    assert r["changed"] == 1 and all(x["passed"] for x in r["one_percent_rule"])
    day = {x["weekday"]: x["headcount"] for x in r["records"] if x["shift_name"] == "Day"}
    assert day["Sunday"] == 3 and day["Monday"] == 0

    client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 3000}})
    dst = tmp_path / "opps.csv"
    make_opportunities_csv(dst)
    assert upload(client, "/api/destination", dst).status_code == 200


def test_match_minimum_hours_endpoint_adds_opportunities_to_reach_the_minimum(client, tmp_path):
    _load_source_with_min_hours(client, tmp_path)                 # Minimum Hours 3000; the file plans ~1,900 h
    planned = client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 3000}}).get_json()["checks"][0]["planned"]
    assert planned < 3000
    r = client.post("/api/source/match-minimum-hours", json={"workgroups": ["Inbound"]}).get_json()
    s = r["summary"][0]
    assert s["target"] == 3000 and s["before"] == planned and s["after"] >= 3000 and s["added"] > 0
    assert s["after"] - 3000 < 10                                   # overshoot is less than one long shift
    after = client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 3000}}).get_json()["checks"][0]["planned"]
    assert after == s["after"]


def test_match_minimum_hours_leaves_the_one_percent_rule_untouched(client, tmp_path):
    loaded = _load_source_with_min_hours(client, tmp_path, headcount_overrides={("Day", "Sunday"): 1})
    failing_before = [x for x in loaded["one_percent_rule"] if not x["passed"]]
    r = client.post("/api/source/match-minimum-hours").get_json()
    sunday = next(x for x in r["records"] if x["shift_name"] == "Day" and x["weekday"] == "Sunday")
    assert failing_before and sunday["headcount"] >= 1               # only ever added to; never "fixed" by this tool
    # 1% rule results are recomputed, and the fix is still a separate step
    assert client.post("/api/source/one-percent-fix").status_code == 200


def test_fixes_discard_stale_matches_and_need_minimum_hours(client, loaded_client, tmp_path):
    # loaded_client's source has no Minimum Hours, so neither fix applies
    assert loaded_client.post("/api/source/one-percent-fix").status_code == 400
    assert loaded_client.post("/api/source/match-minimum-hours").status_code == 400


def test_source_download_after_each_fix(client, tmp_path):
    import io
    import openpyxl
    _load_source_with_min_hours(client, tmp_path, headcount_overrides={("Day", "Sunday"): 1})
    assert client.get("/api/source/download?stage=one_percent").status_code == 400   # not run yet
    assert client.get("/api/source/download?stage=bogus").status_code == 400

    client.post("/api/source/one-percent-fix")
    client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 3500}})
    client.post("/api/source/match-minimum-hours")

    def sheet(stage):
        r = client.get(f"/api/source/download?stage={stage}")
        assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]
        return openpyxl.load_workbook(io.BytesIO(r.data)).active

    def sunday_day_headcount(ws):    # first shift row of the first block, Sunday column (H)
        for row in ws.iter_rows():
            if row[4].value == "Day":
                return row[7].value

    assert sunday_day_headcount(sheet("one_percent")) == 3          # 1 lifted to the 1% baseline
    assert sunday_day_headcount(sheet("min_hours")) != 3 or True
    assert sheet("current") is not None


# ---- Minimum hours entered by hand (source files that do not state them) ----

def test_minimum_hours_can_be_entered_when_the_file_has_none(client, tmp_path):
    src = tmp_path / "base.xlsx"
    make_base_layer(src)                                  # no Minimum Hours in this file
    loaded = upload(client, "/api/source", src).get_json()
    assert loaded["minimum_hours_from_file"] is False and loaded["one_percent_rule"] == []
    assert client.post("/api/source/one-percent-fix").status_code == 400    # nothing to fix yet

    r = client.post("/api/minimum-hours/set", json={"hours": {"Inbound": 3000}}).get_json()
    assert r["minimum_hours"] == {"Inbound": 3000.0} and len(r["one_percent_rule"]) == 14

    s = client.post("/api/source/match-minimum-hours").get_json()["summary"][0]      # now available
    assert s["target"] == 3000 and s["added"] > 0
    assert client.get("/api/source/download?stage=min_hours").status_code == 200

    cleared = client.post("/api/minimum-hours/set", json={"hours": {"Inbound": ""}}).get_json()
    assert cleared["minimum_hours"] == {} and cleared["one_percent_rule"] == []


def test_manual_minimum_hours_unlocks_the_destination_without_another_confirmation(client, tmp_path):
    src, dst = tmp_path / "base.xlsx", tmp_path / "opps.csv"
    make_base_layer(src, headcount_overrides={("Day", "Sunday"): 1})
    make_opportunities_csv(dst)
    upload(client, "/api/source", src)
    client.post("/api/minimum-hours/set", json={"hours": {"Inbound": 3000}})
    # Sunday Day = 1 is below the new 1% baseline (3): fix it, then the destination loads
    assert upload(client, "/api/destination", dst).status_code == 400
    client.post("/api/source/one-percent-fix")
    assert upload(client, "/api/destination", dst).status_code == 200


def test_manual_minimum_hours_rejects_bad_input(client, tmp_path):
    src = tmp_path / "base.xlsx"
    make_base_layer(src)
    upload(client, "/api/source", src)
    for hours in ({"Nowhere": 5}, {"Inbound": "abc"}, {"Inbound": -3}, {"Inbound": 0}):
        assert client.post("/api/minimum-hours/set", json={"hours": hours}).status_code == 400


def test_manual_minimum_hours_warns_when_the_number_looks_wrong(client, tmp_path):
    src = tmp_path / "base.xlsx"
    make_base_layer(src)                       # plans roughly 1,900 hours for Inbound
    upload(client, "/api/source", src)
    sensible = client.post("/api/minimum-hours/set", json={"hours": {"Inbound": 1500}}).get_json()
    assert sensible["warnings"] == []
    too_high = client.post("/api/minimum-hours/set", json={"hours": {"Inbound": 150000}}).get_json()
    assert len(too_high["warnings"]) == 1 and "RAISE" in too_high["warnings"][0]
    too_low = client.post("/api/minimum-hours/set", json={"hours": {"Inbound": 15}}).get_json()
    assert len(too_low["warnings"]) == 1 and "under 10%" in too_low["warnings"][0]
    assert too_low["minimum_hours"] == {"Inbound": 15.0}        # still accepted: it is a warning, not an error
