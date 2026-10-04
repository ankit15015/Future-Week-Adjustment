# User guide

This is the end-to-end workflow. Terms used by the app:

- **Source** = the *Base Layer* file: headcount per shift x day x workgroup (the plan).
- **Destination** = the *Opportunities* file: one row per shift instance, with a Headcount and a Reason column (what gets updated).

## 1. Choose a mode

The start screen offers **Standard**, **Reduce** and **Overstaffed**.

- **Standard** goes straight to the workflow.
- **Reduce** and **Overstaffed** first ask **"Do you want to adjust max cap?"**
  - **Yes** shows a link to the Amazon Scheduling site settings so you can change the max cap there, then **Continue** takes you into the workflow.
  - **No** goes straight into the workflow.

> The three modes currently run the same workflow - see [handover.md](handover.md#known-limitations).

## 2. Source

Pick a file from the dropdown (it lists files in the data folder - see `DASHBOARD_DATA_DIR`) and
press **Load selected**, or use **Upload file**.

- `.xlsx` / `.xlsb` are read directly. For `.xlsb`, a sheet named `Baselayer` is preferred.
- Screenshots/PDFs are read with OCR. **Check every row**: OCR can misread values, especially
  anything hidden behind a tooltip. Cells in the grid are editable; you can add or remove rows
  and press **Save edits**.

The parser looks for blocks with a `Shift`, `Start Time` and `End Time` header, weekday names
above it, and a workgroup name per day column. Blocks it cannot read are reported as warnings.

## 3. Minimum hours (only if the source has them)

If the source file states **Minimum Hours** for a workgroup, you must enter the hours you commit
to for each one. You can only continue if each value meets or exceeds the source minimum.

## 4. 1% rule (only if the source has Minimum Hours)

Checked automatically. For each shift:

```
baseline = ceil(Minimum Hours x 1% / shift length in hours)
```

Every day of that shift is compared to the baseline. A day below it fails, and its shortfall is
`baseline - headcount`. Use **Fix all shortfalls** (or edit rows) until nothing fails; the
destination step stays locked until then. Tick **Show passing days too** to see everything.

## 5. Destination

Load the Opportunities file (`.csv` or `.xlsx`). The Headcount, Reason, Workgroup(s) and
`Opportunity Start Date-Time` columns are found **by header name**, so reordering columns is fine.
A missing required column gives a clear error.

## 6. Match & review

Press **Run match**. Each destination row is matched to the source by:

1. weekday (taken from the row's start date),
2. workgroup (case, spacing and order of comma-separated parts are ignored),
3. the source shift whose start time is closest.

| Confidence | Meaning |
| --- | --- |
| Exact | Start times are identical |
| Near | Within 15 minutes |
| Far | More than 15 minutes apart - check these |
| No source match | No source row for that weekday + workgroup; the original Headcount is kept |
| No time | The row has no readable start date-time |

Use the filters (workgroup, day, confidence, search) to review.

## 7. Reason

Group reasons by **Workgroup** or by **Shift type** (start-end time), type a reason per group, and
optionally a default for anything not covered. A row with no reason keeps whatever was already in
its Reason cell. **Preview reasons in table above** applies them to the match table.

## 8. Apply & download

Press **Show final result**. The table lists every row exactly as it will appear in the file
(Headcount and Reason). Rows with no source match are highlighted and keep their original
Headcount.

**Filters** - workgroup, day, status (updated / unchanged) and a search box. The note under the
table says how many rows will be downloaded.

- No filter: the file contains **all** rows.
- Filter on: the file contains **only the rows shown**, and is named `... - Updated (filtered).csv`.
  Do not upload a filtered file anywhere that expects the full schedule.

Press **Confirm & download** and use the link. If you change reasons afterwards, press
**Preview reasons** again and re-open **Show final result** - the table is hidden on purpose so
it can never be out of date.

The original file is never modified; a new `<name> - Updated.<ext>` is written. Downloading the
same file twice overwrites the earlier output with the same name.
