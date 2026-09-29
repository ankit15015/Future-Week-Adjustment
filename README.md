# Baselayer -> Opportunities Dashboard

A local dashboard to copy Headcount from a Base Layer source (Excel `.xlsx`,
`.xlsb`, or a screenshot/PDF of one) into an Opportunities file (`.csv` or
`.xlsx`), and to fill in the Reason column yourself right in the browser.

## Run it

```
cd dashboard
python app.py
```

This opens `http://127.0.0.1:5057` in your browser automatically. It only
listens on your own machine (127.0.0.1), nothing is exposed on the network.

First time only, install dependencies:

```
pip install -r requirements.txt
```

## How it works

1. **Source** - pick a Base Layer file from the dropdown (it lists files
   already sitting in this project's parent folder) or upload one. Works with
   `.xlsx`/`.xlsb` directly, and with a screenshot/PDF via OCR (review the
   extracted table before continuing - OCR can misread things, especially
   anything covered by a tooltip/overlay in a screenshot; edit any cell
   directly in the grid, or add/remove rows).
2. **Destination** - pick or upload the Opportunities file (`.csv`/`.xlsx`).
   Its Headcount and Reason columns are found by header name, not by a fixed
   column letter, so minor column reordering won't break it.
3. **Match** - matches each destination row to a source cell by weekday
   (from its Start Date-Time) + workgroup + closest shift start time, and
   always overwrites Headcount with the source value when a match is found.
   Rows with no matching workgroup/day in the source keep their original
   Headcount and are flagged "No source match" for you to check by hand.
4. **Reason** - group by Workgroup or by Shift type, type a reason for each
   group, plus one default/fallback reason, then preview.
5. **Apply & download** - writes a new file named
   `<original name> - Updated.csv` (or `.xlsx`) into `dashboard/output/`,
   with everything else in the file untouched, and gives you a download link.

## Notes

- Nothing here is deleted/overwritten in place - the original file you picked
  stays as-is, and a new "- Updated" file is written instead.
- `dashboard/uploads/` and `dashboard/output/` are working folders for the
  app; safe to clear out periodically.
