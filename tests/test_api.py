"""End-to-end through the Flask API: upload -> match -> reasons -> final result -> export."""
import pytest

from conftest import (DEFAULT_OPPORTUNITIES, make_base_layer, make_opportunities_csv,
                      make_opportunities_xlsx, read_csv, upload)


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


def final_rows(client):
    return client.get("/api/final").get_json()["rows"]


def test_index_page_serves_static_assets(client):
    page = client.get("/")
    assert page.status_code == 200
    assert client.get("/static/css/style.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_match_results_and_confidence(loaded_client):
    results = loaded_client.post("/api/match").get_json()["results"]
    by_key = {(r["workgroup"], r["weekday"], r["start_time"]): r for r in results}
    assert by_key[("Inbound", "Sunday", "06:00")]["new_headcount"] == 10
    assert by_key[("Inbound", "Sunday", "06:00")]["confidence"] == "exact"
    assert by_key[("Inbound", "Sunday", "06:10")]["confidence"] == "near"
    assert by_key[("Inbound", "Sunday", "14:00")]["new_headcount"] == 20
    assert by_key[("Inbound", "Monday", "06:00")]["new_headcount"] == 11
    assert by_key[("Outbound", "Sunday", "06:00")]["confidence"] == "no_source_match"


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


def test_final_rows_show_what_the_file_will_hold(loaded_client):
    preview(loaded_client, {"Inbound": "Weekly alignment"})   # Outbound gets no reason
    rows = {(r["workgroup"], r["weekday"], r["start_time"]): r for r in final_rows(loaded_client)}

    inbound = rows[("Inbound", "Sunday", "06:00")]
    assert (inbound["headcount"], inbound["updated"], inbound["reason"]) == (10.0, True, "Weekly alignment")
    # No source match: keeps the original headcount AND the original reason (blank reason = leave the cell alone).
    outbound = rows[("Outbound", "Sunday", "06:00")]
    assert (outbound["headcount"], outbound["updated"], outbound["reason"]) == ("7", False, "old reason C")


def test_full_export_matches_the_final_table_row_for_row(loaded_client, output_dir):
    preview(loaded_client, {"Inbound": "Weekly alignment"})
    table = final_rows(loaded_client)

    j = loaded_client.post("/api/export", json={"indices": [r["index"] for r in table]}).get_json()
    assert j["filtered"] is False and j["rows_written"] == j["rows_total"] == len(table)
    assert j["filename"].endswith(" - Updated.csv")

    file_rows = read_csv(output_dir / j["filename"])
    assert len(file_rows) == len(table)
    for shown, written in zip(table, file_rows):
        assert float(written["Headcount"]) == float(shown["headcount"])
        assert written["Reason"] == shown["reason"]
        assert written["Notes"] == "keep me"
    assert j["rows_unmatched"] == 1


def test_filtered_export_contains_only_the_selected_rows(loaded_client, output_dir):
    preview(loaded_client, {"Inbound": "Weekly alignment"})
    table = final_rows(loaded_client)
    subset = [r for r in table if r["workgroup"] == "Inbound" and r["weekday"] == "Sunday"]
    assert 0 < len(subset) < len(table)

    r = loaded_client.post("/api/export", json={"indices": [x["index"] for x in subset]})
    j = r.get_json()
    assert j["filtered"] is True and j["rows_written"] == len(subset) and j["rows_total"] == len(table)
    assert "(filtered)" in j["filename"]

    file_rows = read_csv(output_dir / j["filename"])
    assert len(file_rows) == len(subset)
    assert {w["Workgroup(s)"] for w in file_rows} == {"Inbound"}
    for shown, written in zip(subset, file_rows):
        assert float(written["Headcount"]) == float(shown["headcount"])
        assert written["Reason"] == shown["reason"]


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
    table = final_rows(client)

    j = client.post("/api/export", json={"indices": [r["index"] for r in table]}).get_json()
    ws = openpyxl.load_workbook(output_dir / j["filename"]).active
    data_rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if any(v is not None for v in r)]
    assert len(data_rows) == len(table)
    for shown, written in zip(table, data_rows):
        assert float(written[3]) == float(shown["headcount"])
        assert written[4] == shown["reason"]


def test_download_serves_the_generated_file(loaded_client):
    preview(loaded_client)
    j = loaded_client.post("/api/export").get_json()
    resp = loaded_client.get(j["download_url"])
    assert resp.status_code == 200 and "attachment" in resp.headers["Content-Disposition"]
