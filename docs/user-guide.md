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

See [Filtering](#filtering-both-tables) below for the filters on this table.

## 7. Reason

Group reasons by **Workgroup** or by **Shift type** (start-end time), type a reason per group, and
optionally a default for anything not covered. A row with no reason keeps whatever was already in
its Reason cell. **Preview reasons in table above** applies them to the match table.

## Filtering (both tables)

The **Match** table and the **final result** filter the same way, and both adapt to whatever is
in the loaded file.

**Column filters (like Excel's AutoFilter).** Every column header has a filter button (▾). Click
it to see the distinct values in that column with how many rows have each, search them, tick the
ones to keep, and press **OK**. The button turns amber while a column is filtered.

- Filters on several columns combine (AND).
- Each column's list only offers values that are still possible under the other filters, so the
  counts always match what you would get.
- **Clear filter** removes one column's filter; **Reset filters** removes everything.
- This works on every column, including all the file's own columns in the final result.

**Quick filters above the table.** Shortcuts, and the **multi-select** ones let you tick as many
values as you like (click the button, tick, press **OK**; the button then reads `2 selected` or
the single value you chose, and turns amber):

| Filter | Notes |
| --- | --- |
| Workgroup (multi) | Lists each workgroup on its own. A combined label such as `Pack - Batch, Pack - Flow, Sort` is split, and a row matches if **any** of its workgroups is ticked. |
| Day (multi) | Days of the week present in the file. |
| Start time, End time (multi) | **24-hour** times (`06:45`, `23:00`), listing only the times present in the file. |
| Confidence (Match) / Match status (final) (multi) | Matched vs no source match, or exact / near / far. |
| Start date, End date (range) | Pick a **from** and/or **to** date. Use both to bound a range; use just one for "on or after" / "on or before". An overnight shift ends the next day, so its end date differs from its start date. |
| Search | Matches any text in the row. |

Ticking every value is the same as no filter (the button goes back to "All ...").

Quick filters and column filters work together. In the final result, **whatever is left on screen
is exactly what gets downloaded.**

**Start / end as separate columns.** The Opportunities file keeps each start and end in a single
date-time cell (`2026-09-27T23:45`). To make dates and times easy to filter, both tables also show
**Start date, Start time, End date and End time** as separate columns. In the final result these
four are review-only: they are **not** added to the downloaded file, which keeps exactly the
original columns.

## 8. Apply & download

Press **Show final result**. The table shows **every column of the output file**, exactly as it
will be written, so you can check all the details before downloading.

- **Yellow cells** are the values this tool changed (Headcount and Reason). Hover one to see
  what it was before.
- **Red rows** had no source match and keep their original Headcount.
- The seven italic columns on the left (`#`, `Match`, `Source shift`, `Start date`, `Start time`,
  `End date`, `End time`) are for review only and are **not** in the file.
- Headcounts are whole numbers (`9`, not `9.0`), the same on screen and in the file.
- **Hide columns that are empty in every row** tidies up files with many unused columns. The
  columns are always the file's own, so a file with more or fewer columns just shows more or fewer.

The filters are described in [Filtering](#filtering-both-tables) below. The note under the table
says how many rows will be downloaded.

- No filter: the file contains **all** rows.
- Filter on: the file contains **only the rows shown**, and is named `... - Updated (filtered).csv`.
  Do not upload a filtered file anywhere that expects the full schedule.

Press **Confirm & download** and use the link. If you change reasons afterwards, press
**Preview reasons** again and re-open **Show final result** - the table is hidden on purpose so
it can never be out of date.

The original file is never modified; a new `<name> - Updated.<ext>` is written. Downloading the
same file twice overwrites the earlier output with the same name.
