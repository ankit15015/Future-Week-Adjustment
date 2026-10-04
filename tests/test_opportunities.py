import openpyxl
import pytest

from conftest import (DEFAULT_OPPORTUNITIES, OPPORTUNITY_HEADERS, make_opportunities_csv,
                      make_opportunities_xlsx, read_csv)
from future_week_adjustment import opportunities


def test_load_csv_detects_columns_by_header_name(tmp_path):
    path = tmp_path / "opps.csv"
    make_opportunities_csv(path)
    loaded = opportunities.load_destination(str(path))

    assert len(loaded["rows"]) == len(DEFAULT_OPPORTUNITIES)
    assert loaded["headers"]["headcount"] == "Headcount"
    first = loaded["rows"][0]
    assert (first["workgroup"], first["weekday"], first["old_headcount"], first["old_reason"]) \
        == ("Inbound", "Sunday", "1", "old reason A")
    assert first["start_time"].strftime("%H:%M") == "06:00"


def test_load_rejects_a_file_missing_required_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Workgroup(s),Something\nInbound,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing expected column"):
        opportunities.load_destination(str(path))


def test_load_rejects_unsupported_extension(tmp_path):
    with pytest.raises(ValueError):
        opportunities.load_destination(str(tmp_path / "opps.txt"))


def test_write_csv_changes_only_headcount_and_reason(tmp_path):
    src = tmp_path / "opps.csv"
    make_opportunities_csv(src)
    loaded = opportunities.load_destination(str(src))
    out = tmp_path / "out.csv"
    opportunities.write_destination(loaded, {0: {"headcount": 99, "reason": "new"}, 1: {"headcount": None, "reason": None}}, str(out))

    rows = read_csv(out)
    assert (rows[0]["Headcount"], rows[0]["Reason"]) == ("99", "new")
    assert (rows[1]["Headcount"], rows[1]["Reason"]) == ("1", "old reason B")   # None = leave alone
    assert all(r["Notes"] == "keep me" for r in rows)                            # other columns untouched
    assert len(rows) == len(DEFAULT_OPPORTUNITIES)


def test_write_csv_keep_writes_only_the_chosen_rows(tmp_path):
    src = tmp_path / "opps.csv"
    make_opportunities_csv(src)
    loaded = opportunities.load_destination(str(src))
    out = tmp_path / "out.csv"
    opportunities.write_destination(loaded, {i: {"headcount": i * 10, "reason": None} for i in range(5)}, str(out), keep={1, 3})

    rows = read_csv(out)
    assert [r["Headcount"] for r in rows] == ["10", "30"]


def test_xlsx_blank_row_does_not_shift_writes_onto_the_wrong_rows(tmp_path):
    """Regression: blank rows are skipped on load, so worksheet row != index + 2."""
    src = tmp_path / "opps.xlsx"
    make_opportunities_xlsx(src, blank_row_after=1)   # worksheet row 3 is blank
    loaded = opportunities.load_destination(str(src))
    assert [r["sheet_row"] for r in loaded["rows"]] == [2, 4, 5, 6, 7]

    out = tmp_path / "out.xlsx"
    opportunities.write_destination(loaded, {1: {"headcount": 55, "reason": "hit"}}, str(out))
    ws = openpyxl.load_workbook(out).active
    hc_col = OPPORTUNITY_HEADERS.index("Headcount") + 1
    assert ws.cell(3, hc_col).value is None        # the blank row stays blank
    assert ws.cell(4, hc_col).value == 55          # data row #2 got the update
    assert ws.cell(2, hc_col).value in (1, "1")    # data row #1 untouched


def test_xlsx_keep_removes_the_other_rows(tmp_path):
    src = tmp_path / "opps.xlsx"
    make_opportunities_xlsx(src, blank_row_after=1)
    loaded = opportunities.load_destination(str(src))
    out = tmp_path / "out.xlsx"
    opportunities.write_destination(loaded, {i: {"headcount": 100 + i, "reason": None} for i in range(5)}, str(out), keep={1, 4})

    ws = openpyxl.load_workbook(out).active
    hc_col = OPPORTUNITY_HEADERS.index("Headcount") + 1
    data = [r for r in ws.iter_rows(min_row=2, values_only=True) if any(v is not None for v in r)]
    assert [row[hc_col - 1] for row in data] == [101, 104]
