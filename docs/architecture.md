# Architecture

## Overview

A single Flask process serves a one-page UI (`templates/index.html` + `static/js/app.js`) and a
JSON API. There is no database: a user's in-progress run is held in memory on the server, keyed
by a session cookie.

```
Browser (index.html + app.js)
        │  fetch JSON / multipart upload
        ▼
future_week_adjustment/app.py  ── routes, session state, file naming
        ├── base_layer.py     ── parse Base Layer (xlsx / xlsb / OCR), 1% rule
        ├── opportunities.py  ── load / write the Opportunities file (csv / xlsx)
        └── matching.py       ── match rows to source, assign reasons
```

## Modules

| Module | Responsibility |
| --- | --- |
| `app.py` | Routes, session store, upload handling, `build_final_rows`, error handler. No business rules beyond orchestration. |
| `base_layer.py` | Turns a Base Layer into flat records `{workgroup, weekday, shift_name, start_time, end_time, headcount}`; extracts Minimum/Total Hours; computes the 1% rule. Spreadsheet and OCR paths produce the same record shape. |
| `opportunities.py` | `load_destination` -> parsed rows + detected header names; `write_destination` -> writes only the cells you changed, optionally only a subset of rows (`keep`). |
| `matching.py` | `match_destination`, `apply_reasons`, `distinct_groups`. Pure functions, easy to test. |

## Run state (server side)

`SESSIONS[sid]` (sid stored in the Flask session cookie) holds:

| Key | Set by | Meaning |
| --- | --- | --- |
| `source_records`, `source_filename`, `source_kind` | `POST /api/source` | Parsed Base Layer |
| `minimum_hours`, `min_hours_confirmed` | `POST /api/source`, `/api/minimum-hours/validate` | Gate for loading a destination |
| `one_percent_results`, `one_percent_ok` | `POST /api/source`, `/api/source/update` | Gate for loading a destination |
| `destination`, `destination_filename` | `POST /api/destination` | Loaded Opportunities file |
| `match_results` | `POST /api/match` | One result per destination row |
| `reasoned_results`, `reason_settings` | `POST /api/reasons/preview` | Match results + reasons |

Consequences: state is lost on restart, is never evicted, and is per-process - so production must
run **one worker** (`gunicorn -w 1`, already set in `render.yaml`).

## The final result and the downloaded file

`build_final_rows(loaded, results)` in `app.py` is the **single definition** of what each row holds
in the output. Both `GET /api/final` (the on-screen table) and `POST /api/export` (the file) use
it, and it builds each row's `values` with `opportunities.output_values` - the same function the
CSV writer uses - so they cannot drift apart:

- Headcount = the source value, or the original value if there was no source match. Whole numbers
  are written as integers (`9`, not `9.0`) via `opportunities.clean_headcount`.
- Reason = the typed reason, or the original Reason cell if none was given.
- Every other column is the original cell, untouched. All columns are sent to the page, so the
  review table shows the whole file.

`POST /api/export` accepts `{"indices": [...]}` - the row indices currently shown after filtering.
Only those rows are written. Omitting the body writes every row.

Writing preserves everything else: CSV rows are re-emitted with all original columns; xlsx is
opened with openpyxl, edited in place, and unselected rows are deleted bottom-up.
`xlsx` rows are located by their real worksheet row (`sheet_row`), because blank rows are skipped
when loading.

## API reference

All API errors return JSON `{"description": "..."}` with the HTTP status; the UI shows `description`.

| Method & path | Purpose | Notes |
| --- | --- | --- |
| `GET /` | The page | |
| `GET /api/files?kind=source\|destination` | List files in the data folder | Filtered by allowed extension |
| `POST /api/source` | Load a Base Layer | Form: `filename` (existing file) **or** `file` (upload). Returns records, warnings, minimum hours, 1% rule results |
| `POST /api/source/update` | Save edited source records | Validates headcount, weekday, `HH:MM`; recomputes the 1% rule |
| `POST /api/minimum-hours/validate` | Confirm committed hours | Body `{entries: {workgroup: hours}}` |
| `POST /api/destination` | Load the Opportunities file | 400 until minimum hours are confirmed and the 1% rule passes |
| `POST /api/match` | Match every destination row | |
| `POST /api/reasons/preview` | Apply reasons | Body `{group_by, reason_map, default_reason}` |
| `GET /api/final` | Final rows exactly as they will be written | Requires a reasons preview. Returns `columns` (every output column, file order), `headers` (detected Headcount/Reason/... column names) and `rows`. Each row has `values` (column -> text as written), `changed` (column -> original value, only for cells this tool changed), plus `index`, `workgroup`, `workgroups`, `weekday`, `start_date`, `end_date`, `start_time`, `end_time`, `updated`, `confidence`, `matched_shift_name` |
| `POST /api/export` | Write the file | Body `{indices?: number[]}`; returns `download_url`, `rows_written`, `rows_total`, `rows_unmatched`, `filtered` |
| `GET /api/download/<file>` | Download a generated file | Served from `instance/output/` |

## Matching and rules

- **Weekday** comes from the destination row's start date-time, not from a column.
- **Workgroup** comparison (`normalize_workgroup`) ignores case and spacing, and the order of
  comma-separated parts (`"Pack, Sort"` equals `"sort,pack"`).
- **Closest start time** is circular (23:50 and 00:10 are 20 minutes apart). Confidence: exact = 0,
  near <= 15 min, far > 15 min.
- **Early-morning tail shifts**: a source shift that starts earlier than the block's first shift
  (for example 02:45 after a 21:00 shift) is the tail of the *previous* day's overnight period, so
  its headcount is moved to the day **after** its column label. This was verified against a real
  file; it has a regression test.
- **1% rule**: `baseline = ceil(MinimumHours x 0.01 / shiftHours)`, checked per shift per day.

## Front end

No framework or build step. `static/js/app.js` is organised in sections (state and step rail,
file lists, source, minimum hours / 1% rule, destination, match, reasons, export, mode select).

Filtering is shared by the two review tables (Match and final result):

- `toggleChecklist(...)` is the one checklist popup (searchable values with counts, Select all, OK)
  shared by both kinds of multi-select filter below.
- `createColumnFilters(...)` is a reusable Excel-style AutoFilter: a button per column header that
  opens the checklist for that column's distinct values, cascading with the other filters. A table
  supplies `getRows`, `getColumns` (key, label, `value(row)`), `passesOtherFilters` and `onChange`.
  The final result builds its columns from the loaded file, so any column set works.
- `createQuickFilters(prefix, {extra, onChange})` drives the filter bar above each table: multi-select
  buttons for workgroup (individual names via `split_workgroups`), day, 24-hour start time, 24-hour
  end time and one table-specific field (`extra`), plus start-date and end-date ranges. Match
  results and final rows carry `start_date` and `end_date` (the end date is the next day for
  overnight shifts); the final table shows them, with the start/end times, as review-only columns -
  the downloaded file keeps only the original columns.
- The final result downloads exactly the rows left after all filters: the page sends their `index`
  values to `POST /api/export`.
Screens (`mode-select`, `mode-gate`, `cap-notice`, `standard-mode`) are shown/hidden with a
`hidden` class. After editing a template, restart the server (templates are cached when
`debug=False`) and hard-refresh the browser for static files.

## Paths and folders

`PROJECT_ROOT` is the repository root. `instance/uploads` and `instance/output` are created on
start and git-ignored. `DATA_DIR` (the dropdown folder) defaults to the folder that contains the
project and can be set with `DASHBOARD_DATA_DIR`.
