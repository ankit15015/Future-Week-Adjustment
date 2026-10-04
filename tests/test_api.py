"""End-to-end through the Flask API: upload -> match -> reasons -> final result -> export."""
import pytest

from conftest import (DEFAULT_OPPORTUNITIES, OPPORTUNITY_HEADERS, make_base_layer,
                      make_opportunities_csv, make_opportunities_xlsx, read_csv, upload)
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
        for name in ("workgroup", "day", "date", "start", "end"):
            assert f'id="{prefix}-{name}"' in html


def test_match_results_and_confidence(loaded_client):
    results = loaded_client.post("/api/match").get_json()["results"]
    by_key = {(r["workgroup"], r["weekday"], r["start_time"]): r for r in results}
    assert by_key[("Inbound", "Sunday", "06:00")]["new_headcount"] == 10
    assert by_key[("Inbound", "Sunday", "06:00")]["confidence"] == "exact"
    assert by_key[("Inbound", "Sunday", "06:10")]["confidence"] == "near"
    assert by_key[("Inbound", "Sunday", "14:00")]["new_headcount"] == 20
    assert by_key[("Inbound", "Monday", "06:00")]["new_headcount"] == 11
    assert by_key[("Outbound", "Sunday", "06:00")]["confidence"] == "no_source_match"


def test_match_results_carry_date_and_individual_workgroups(loaded_client):
    results = loaded_client.post("/api/match").get_json()["results"]
    sunday = next(r for r in results if r["weekday"] == "Sunday")
    monday = next(r for r in results if r["weekday"] == "Monday")
    assert (sunday["date"], monday["date"]) == ("2026-09-27", "2026-09-28")
    assert sunday["workgroups"] == [sunday["workgroup"]]


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
    make_base_layer(src, min_hours=700, headcount_overrides={("Day", "Sunday"): 0})
    make_opportunities_csv(dst)
    r = upload(client, "/api/source", src)
    failing = [x for x in r.get_json()["one_percent_rule"] if not x["passed"]]
    assert [(x["weekday"], x["shortfall"]) for x in failing] == [("Sunday", 1)]

    client.post("/api/minimum-hours/validate", json={"entries": {"Inbound": 700}})
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
