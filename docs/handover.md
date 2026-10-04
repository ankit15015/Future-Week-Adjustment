# Handover notes

Read this first if you are taking the project over.

## Status

The **Standard** workflow is complete and tested end to end: Base Layer -> minimum hours -> 1% rule
-> Opportunities file -> match -> reasons -> reviewed, filterable final result -> download.
`pytest` runs 46 tests (all passing at handover).

Last verified on Python 3.13 on Windows. Render uses Python 3.11.9; that combination has **not**
been run here (there is no CI), so run `pytest` on 3.11 before relying on it.

## Known limitations

1. **Reduce and Overstaffed are placeholders.** After the "adjust max cap?" question they run the
   exact same workflow as Standard; the only difference is the badge in the header. The mode is
   not sent to the server and no reduction or redistribution logic exists. The start-screen card
   text ("Trim headcount against a target...", "Flag and redistribute shifts...") describes
   intended behaviour that is not built. Either implement it or reword the cards.
2. **No authentication** on the app or on shared/deployed links (see [deployment.md](deployment.md)).
3. **In-memory state**: lost on restart, never evicted, one worker only.
4. **OCR sources are unreliable by nature** - always review the extracted grid.
5. **Output name collisions**: the download is `<name> - Updated.<ext>` (or `... (filtered)`);
   running again for the same input silently overwrites the previous output.
6. **`.xlsm` macros are not preserved**: `.xlsm` is accepted but openpyxl is not run with
   `keep_vba`, so macros would be dropped on write.
7. **A filtered download is a partial file by design** (it contains only the rows you filtered
   to). Do not use it where the full schedule is expected.

## Gotchas

- **Terminology**: *Source* = Base Layer, *Destination* = Opportunities file. API paths and
  session keys use "source"/"destination"; module names use the domain terms
  (`base_layer.py`, `opportunities.py`).
- **Header names matter** in the Opportunities file: `Headcount`, `Reason`, `Workgroup(s)` (or
  `Workgroup`), `Opportunity Start Date-Time`, optionally `Opportunity End Date-Time`. Column
  position does not. Date-times must be ISO-like (`2026-09-27T06:00`).
- **Weekday is derived from the start date**, so a shift that starts at 23:00 belongs to that
  day, and the early-morning "tail shift" rule in the source parser exists to line the two up.
- **Templates are cached** when running with `debug=False`; restart after editing
  `templates/index.html`.
- **The data folder default is the parent of the repo**, which is why the file dropdowns work
  out of the box when the repo sits next to the data files. Set `DASHBOARD_DATA_DIR` otherwise.
- **Do not commit real data.** `instance/` and `.env` are git-ignored; keep it that way. Test
  data is synthetic (see `tests/conftest.py`).
- `scripts/cloudflared.exe` is a 55 MB downloaded binary and must stay out of git (it is
  ignored).

## Maintenance checklist

- Dependencies are range-pinned in `requirements.txt`. Upgrade deliberately, run `pytest`, then
  try a real OCR PDF - OCR is the most fragile dependency (`rapidocr-onnxruntime`, `onnxruntime`,
  `opencv`).
- When the Base Layer format changes, the place to adapt is `parse_blocks_from_grid` in
  `base_layer.py`; add a case to `tests/test_base_layer.py` first.
- When the Opportunities export format changes, header detection is in
  `opportunities._build_result`.

## Suggested next steps

1. Decide the fate of Reduce / Overstaffed: implement, hide, or reword.
2. Add CI (a GitHub Actions workflow running `pip install -r requirements-dev.txt && pytest` on
   Python 3.11). Pushing a workflow file needs a token with the `workflow` scope.
3. Add authentication (or put the Render service behind an access layer) before real data goes
   to a hosted copy.
4. Store run state per session on disk or in Redis if multiple workers or restarts matter.
5. Make output file names unique (timestamp) to stop silent overwrites.

## Where things came from

The git history documents the evolution of the matching and tail-shift rules; commits named
"Fix early-morning tail shift ..." and "Revert weekday attribution ..." are worth reading before
touching `parse_blocks_from_grid`.
