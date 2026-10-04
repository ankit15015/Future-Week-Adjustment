"""
Parses a "Base layer" source file (headcount by Shift x Day-of-week x Workgroup)
from either a spreadsheet (.xlsx/.xlsb) or an image/PDF screenshot of one.

Both paths produce the same flat record shape:
    {workgroup, weekday, shift_name, start_time ("HH:MM"), end_time ("HH:MM"), headcount}
"""
import re
import datetime as dt
import os

WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

TIME_RE = re.compile(r'^\d{1,2}:\d{2}$')
INT_RE = re.compile(r'^\d{1,4}(\.\d+)?$')


def normalize_weekday(s):
    if s is None:
        return None
    s = str(s).strip().lower()
    for wd in WEEKDAYS:
        if wd.lower() == s:
            return wd
    if len(s) >= 3:
        for wd in WEEKDAYS:
            if wd.lower().startswith(s[:3]):
                return wd
    return None


def normalize_workgroup(s):
    """
    Case/whitespace-insensitive, and order-insensitive for combined workgroup
    labels like "Pack - Batch, Pack - Flow, Sort" vs "Pack - Batch,Sort,Pack - Flow"
    (same sub-workgroups, listed in a different order between the source and
    destination files).
    """
    parts = [re.sub(r'\s+', ' ', p.strip().lower()) for p in str(s).split(',')]
    parts = sorted(p for p in parts if p)
    return ','.join(parts)


def split_workgroups(s):
    """
    Individual workgroup names from a combined label, in their original order and spelling:
    "Pack - Batch, Pack - Flow, Sort" -> ["Pack - Batch", "Pack - Flow", "Sort"].
    """
    return [re.sub(r'\s+', ' ', p.strip()) for p in str(s).split(',') if p.strip()]


def to_time(value):
    """Normalize a cell value (Excel time float, datetime.time, or 'HH:MM' string) to datetime.time."""
    if value is None or value == '':
        return None
    if isinstance(value, dt.time):
        return value
    if isinstance(value, dt.datetime):
        return value.time()
    if isinstance(value, (int, float)):
        total_seconds = round(float(value) * 24 * 3600) % (24 * 3600)
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        return dt.time(hour=int(h), minute=int(m))
    if isinstance(value, str):
        v = value.strip()
        m = re.match(r'^(\d{1,2}):(\d{2})', v)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            return dt.time(hour=h % 24, minute=mi)
    return None


def time_to_str(t):
    return None if t is None else t.strftime('%H:%M')


# ---------------------------------------------------------------------------
# Spreadsheet (.xlsx / .xlsb) parsing
# ---------------------------------------------------------------------------

def grid_from_openpyxl(ws):
    grid = {}
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and cell.value != '':
                grid.setdefault(cell.row, []).append((cell.column, cell.value))
    for r in grid:
        grid[r].sort(key=lambda x: x[0])
    return grid


def grid_from_pyxlsb(sheet):
    grid = {}
    for row in sheet.rows():
        for c in row:
            if c.v is not None and c.v != '':
                grid.setdefault(c.r + 1, []).append((c.c + 1, c.v))
    for r in grid:
        grid[r].sort(key=lambda x: x[0])
    return grid


def _find_left_neighbor_value(row_vals, label_col):
    """Given a row's [(col, value), ...] and the column of a label cell, return
    (column, numeric value) of the nearest populated cell to its left in that
    same row, or (None, None) if there isn't one / it isn't numeric."""
    candidates = [(c, v) for c, v in row_vals if c < label_col]
    if not candidates:
        return None, None
    c, v = max(candidates, key=lambda cv: cv[0])
    try:
        return c, float(v)
    except (TypeError, ValueError):
        return None, None


def _find_minimum_hours_after(grid, from_row, max_row, lookahead=6):
    """Scan a few rows below a block's data rows for a 'Minimum Hours' labeled cell.
    Returns (minimum_hours, total_hours): minimum_hours is the value immediately to
    the label's left; total_hours is the value one row above it in that same column
    (the block's grand Total Hours figure, e.g. 10536 sitting right above 7265
    'Minimum Hours' in a real Baselayer file)."""
    for rr in range(from_row, min(from_row + lookahead, max_row + 1)):
        row_vals = grid.get(rr, [])
        for col, v in row_vals:
            if isinstance(v, str) and v.strip().lower() == 'minimum hours':
                value_col, min_hours = _find_left_neighbor_value(row_vals, col)
                if min_hours is None:
                    continue
                total_hours = None
                above_vals = grid.get(rr - 1, [])
                for c2, v2 in above_vals:
                    if c2 == value_col:
                        try:
                            total_hours = float(v2)
                        except (TypeError, ValueError):
                            total_hours = None
                        break
                return min_hours, total_hours
    return None, None


def _duration_hours(start_t, end_t):
    """Hours between two datetime.time values, wrapping past midnight if end <= start."""
    start_minutes = start_t.hour * 60 + start_t.minute
    end_minutes = end_t.hour * 60 + end_t.minute
    diff = end_minutes - start_minutes
    if diff <= 0:
        diff += 24 * 60
    return diff / 60.0


def parse_blocks_from_grid(grid):
    """Generic 'Shift / Start Time / End Time' block parser shared by all spreadsheet layouts."""
    if not grid:
        return [], [], {}, {}
    max_row = max(grid.keys())
    records = []
    warnings = []
    minimum_hours_by_workgroup = {}
    total_hours_by_workgroup = {}
    rows_sorted = sorted(grid.keys())
    header_rows = []
    for r in rows_sorted:
        vals = grid[r]
        shift_col = None
        for col, v in vals:
            if isinstance(v, str) and v.strip().lower() == 'shift':
                shift_col = col
                break
        if shift_col is None:
            continue
        start_col = end_col = None
        for col, v in vals:
            if col <= shift_col or not isinstance(v, str):
                continue
            lv = v.strip().lower()
            if start_col is None and lv.startswith('start'):
                start_col = col
            elif start_col is not None and end_col is None and col > start_col and lv.startswith('end'):
                end_col = col
        if start_col is None or end_col is None:
            continue
        header_rows.append((r, shift_col, start_col, end_col))

    last_weekday_by_col = None
    for (hr, shift_col, start_col, end_col) in header_rows:
        header_vals = dict(grid[hr])
        weekday_by_col = {}
        for probe in range(hr - 1, max(hr - 4, 0), -1):
            probe_vals = dict(grid.get(probe, []))
            found_any = False
            for col, v in probe_vals.items():
                if col <= end_col:
                    continue
                wd = normalize_weekday(v)
                if wd:
                    weekday_by_col[col] = wd
                    found_any = True
            if found_any:
                break
        if not weekday_by_col and last_weekday_by_col:
            weekday_by_col = last_weekday_by_col
        if not weekday_by_col:
            warnings.append(f"Row {hr}: could not find day-of-week header, block skipped")
            continue
        last_weekday_by_col = weekday_by_col
        day_cols = sorted(weekday_by_col.keys())
        workgroup_by_col = {
            col: str(header_vals[col]).strip()
            for col in day_cols
            if col in header_vals and str(header_vals[col]).strip()
        }
        if len(workgroup_by_col) < len(day_cols):
            warnings.append(f"Row {hr}: blank workgroup label (unused template slot), block skipped")
            continue

        r2 = hr + 1
        anchor_start_minutes = None
        while r2 <= max_row:
            row_vals = dict(grid.get(r2, []))
            if shift_col not in row_vals or row_vals[shift_col] in (None, ''):
                break
            shift_name = str(row_vals[shift_col]).strip()
            if shift_name.lower() == 'shift':
                break
            start_t = to_time(row_vals.get(start_col))
            end_t = to_time(row_vals.get(end_col))

            # A shift whose own start time is earlier than the block's first
            # (anchor) shift is the early-morning tail of the PREVIOUS day's
            # overnight period (e.g. a "P6" starting 02:45, right after a "P5"
            # starting 21:00) - its headcount belongs to the day AFTER its
            # column's literal label, not the literal label itself. Verified
            # against a real Base Layer + destination file example.
            is_early_tail = False
            if start_t is not None:
                start_minutes = start_t.hour * 60 + start_t.minute
                if anchor_start_minutes is None:
                    anchor_start_minutes = start_minutes
                elif start_minutes < anchor_start_minutes:
                    is_early_tail = True

            for col in day_cols:
                hc_raw = row_vals.get(col)
                if hc_raw in (None, ''):
                    continue
                try:
                    hc = float(hc_raw)
                except (TypeError, ValueError):
                    continue
                weekday = weekday_by_col[col]
                if is_early_tail:
                    weekday = WEEKDAYS[(WEEKDAYS.index(weekday) + 1) % 7]
                records.append({
                    'workgroup': workgroup_by_col[col],
                    'weekday': weekday,
                    'shift_name': shift_name,
                    'start_time': time_to_str(start_t),
                    'end_time': time_to_str(end_t),
                    'headcount': hc,
                })
            r2 += 1

        block_workgroup = workgroup_by_col[day_cols[0]]
        min_hours, total_hours = _find_minimum_hours_after(grid, r2, max_row)
        if min_hours is not None:
            minimum_hours_by_workgroup[block_workgroup] = min_hours
        if total_hours is not None:
            total_hours_by_workgroup[block_workgroup] = total_hours
    return records, warnings, minimum_hours_by_workgroup, total_hours_by_workgroup


def parse_spreadsheet_source(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xlsm'):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        all_records, all_warnings, all_min_hours, all_total_hours = [], [], {}, {}
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            grid = grid_from_openpyxl(ws)
            recs, warns, min_hours, total_hours = parse_blocks_from_grid(grid)
            all_records.extend(recs)
            all_warnings.extend(f"[{sheet_name}] {w}" for w in warns)
            all_min_hours.update(min_hours)
            all_total_hours.update(total_hours)
        return all_records, all_warnings, all_min_hours, all_total_hours
    elif ext == '.xlsb':
        from pyxlsb import open_workbook
        all_records, all_warnings, all_min_hours, all_total_hours = [], [], {}, {}
        with open_workbook(path) as wb:
            sheet_names = wb.sheets
            # Prefer a sheet literally named 'Baselayer'; otherwise scan all sheets.
            preferred = [s for s in sheet_names if s.strip().lower() == 'baselayer']
            candidates = preferred or sheet_names
            for sn in candidates:
                with wb.get_sheet(sn) as sheet:
                    grid = grid_from_pyxlsb(sheet)
                recs, warns, min_hours, total_hours = parse_blocks_from_grid(grid)
                if recs:
                    all_records.extend(recs)
                    all_warnings.extend(f"[{sn}] {w}" for w in warns)
                    all_min_hours.update(min_hours)
                    all_total_hours.update(total_hours)
        return all_records, all_warnings, all_min_hours, all_total_hours
    else:
        raise ValueError(f"Unsupported spreadsheet type: {ext}")


# ---------------------------------------------------------------------------
# Image / PDF (OCR) parsing
# ---------------------------------------------------------------------------

_OCR_ENGINE = None


def _get_ocr_engine():
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def _tokens_from_ocr_result(result):
    tokens = []
    if not result:
        return tokens
    for box, text, score in result:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        tokens.append({
            'x': sum(xs) / 4.0, 'y': sum(ys) / 4.0,
            'h': max(ys) - min(ys),
            'text': text.strip(), 'score': float(score),
        })
    return tokens


def _median(values):
    values = sorted(values)
    n = len(values)
    if n == 0:
        return 0
    mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2


def _cluster_rows(tokens, row_tol):
    tokens = sorted(tokens, key=lambda t: t['y'])
    rows = []
    for t in tokens:
        placed = False
        for row in rows:
            if abs(row['y'] - t['y']) <= row_tol:
                row['tokens'].append(t)
                ys = [tk['y'] for tk in row['tokens']]
                row['y'] = sum(ys) / len(ys)
                placed = True
                break
        if not placed:
            rows.append({'y': t['y'], 'tokens': [t]})
    rows.sort(key=lambda r: r['y'])
    return rows


def parse_image_grid(result):
    tokens = _tokens_from_ocr_result(result)
    # Tolerances scale with the text size actually detected in this image, so the
    # parser isn't tied to one fixed DPI/zoom level.
    row_tol = max(6, _median([t['h'] for t in tokens]) * 0.55) if tokens else 10
    default_col_tol = max(15, _median([t['h'] for t in tokens]) * 2.0) if tokens else 35
    rows = _cluster_rows(tokens, row_tol)
    header_idx = [i for i, row in enumerate(rows) if any(t['text'].lower() == 'shift' for t in row['tokens'])]

    records = []
    warnings = []
    last_weekday_by_x = None
    for h_pos, hi in enumerate(header_idx):
        row = rows[hi]
        shift_tok = next(t for t in row['tokens'] if t['text'].lower() == 'shift')
        start_tok = end_tok = None
        for t in sorted(row['tokens'], key=lambda t: t['x']):
            if t['x'] <= shift_tok['x']:
                continue
            lv = t['text'].lower()
            if start_tok is None and lv.startswith('start'):
                start_tok = t
            elif start_tok is not None and end_tok is None and t['x'] > start_tok['x'] and lv.startswith('end'):
                end_tok = t
        if not start_tok or not end_tok:
            warnings.append(f"Header near y={row['y']:.0f}: could not find Start/End Time columns")
            continue

        weekday_by_x = {}
        for probe_i in range(hi - 1, max(hi - 3, -1), -1):
            found = False
            for t in rows[probe_i]['tokens']:
                if t['x'] <= end_tok['x']:
                    continue
                wd = normalize_weekday(t['text'])
                if wd:
                    weekday_by_x[t['x']] = wd
                    found = True
            if found:
                break
        if not weekday_by_x and last_weekday_by_x:
            weekday_by_x = last_weekday_by_x
        if not weekday_by_x:
            warnings.append(f"Header near y={row['y']:.0f}: could not find day-of-week row above it")
            continue
        last_weekday_by_x = weekday_by_x
        day_xs = sorted(weekday_by_x.keys())
        gaps = [day_xs[i + 1] - day_xs[i] for i in range(len(day_xs) - 1)]
        col_tol = min(gaps) * 0.4 if gaps else default_col_tol

        workgroup_by_x = {}
        candidates = [t for t in row['tokens'] if t['x'] > end_tok['x']]
        for dx in day_xs:
            if not candidates:
                continue
            nearest = min(candidates, key=lambda t: abs(t['x'] - dx))
            if abs(nearest['x'] - dx) < col_tol:
                workgroup_by_x[dx] = nearest['text']
        if len(workgroup_by_x) < len(day_xs):
            warnings.append(f"Header near y={row['y']:.0f}: workgroup label missing for some day columns "
                             f"({len(workgroup_by_x)}/{len(day_xs)}) - block skipped")
            continue

        next_hi = header_idx[h_pos + 1] if h_pos + 1 < len(header_idx) else len(rows)
        for ri in range(hi + 1, next_hi):
            drow = rows[ri]
            time_toks = sorted([t for t in drow['tokens'] if TIME_RE.match(t['text'])], key=lambda t: t['x'])
            if len(time_toks) < 2:
                continue
            start_t_tok, end_t_tok = time_toks[0], time_toks[1]
            name_margin = start_t_tok.get('h', 15) * 1.3
            name_candidates = [t for t in drow['tokens'] if t['x'] < start_t_tok['x'] - name_margin]
            shift_name = ' '.join(t['text'] for t in sorted(name_candidates, key=lambda t: t['x'])) or '?'

            num_candidates_all = [t for t in drow['tokens'] if t['x'] > end_tok['x'] and INT_RE.match(t['text'])]
            for dx in day_xs:
                if not num_candidates_all:
                    continue
                nearest = min(num_candidates_all, key=lambda t: abs(t['x'] - dx))
                if abs(nearest['x'] - dx) >= col_tol:
                    continue
                records.append({
                    'workgroup': workgroup_by_x[dx],
                    'weekday': weekday_by_x[dx],
                    'shift_name': shift_name,
                    'start_time': start_t_tok['text'],
                    'end_time': end_t_tok['text'],
                    'headcount': float(nearest['text']),
                })
    if not records:
        warnings.append("No table cells could be read from the image - please fill in the grid manually below.")
    else:
        warnings.append("Values were read from an image with OCR and may contain mistakes "
                         "(especially anything covered by tooltips/overlays in the screenshot) - "
                         "please review every row below before matching.")
    return records, warnings


def parse_image_source(path):
    ext = os.path.splitext(path)[1].lower()
    ocr = _get_ocr_engine()
    if ext == '.pdf':
        import fitz
        doc = fitz.open(path)
        all_records, all_warnings = [], []
        for page in doc:
            pix = page.get_pixmap(dpi=150)
            png_bytes = pix.tobytes('png')
            tmp_path = path + f'.page{page.number}.png'
            with open(tmp_path, 'wb') as f:
                f.write(png_bytes)
            try:
                result, _ = ocr(tmp_path)
                recs, warns = parse_image_grid(result)
                all_records.extend(recs)
                all_warnings.extend(warns)
            finally:
                os.remove(tmp_path)
        return all_records, all_warnings
    else:
        result, _ = ocr(path)
        return parse_image_grid(result)


def parse_source(path):
    """Dispatch to the right parser based on file extension.

    Always returns (records, warnings, minimum_hours_by_workgroup,
    total_hours_by_workgroup). The OCR/image path doesn't attempt to read
    those summary figures, so it always comes back with empty dicts there.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xlsm', '.xlsb'):
        return parse_spreadsheet_source(path)
    elif ext in ('.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'):
        records, warnings = parse_image_source(path)
        return records, warnings, {}, {}
    else:
        raise ValueError(f"Unsupported source file type: {ext}")


# ---------------------------------------------------------------------------
# 1% Rule verification
# ---------------------------------------------------------------------------

def compute_one_percent_rule(records, minimum_hours_by_workgroup):
    """
    For each shift, first compute a baseline:
        baseline = ceil(workgroup's Minimum Hours * 0.01 / shift_duration_hours)
    (this matches the source file's own '1% Rule' column exactly - verified
    against a real Baselayer file). That baseline is then checked against
    the shift's own headcount on *every day of the week* individually: a day
    whose headcount is below the baseline fails, and its shortfall
    (baseline - headcount) is how much would need to be added to bring that
    one day up to the baseline. Workgroups with no Minimum Hours figure in
    the source file are skipped (nothing to verify against).
    """
    import math
    results = []
    for r in records:
        if not r['start_time'] or not r['end_time']:
            continue
        min_hours = minimum_hours_by_workgroup.get(r['workgroup'])
        if min_hours is None:
            continue
        start_t = to_time(r['start_time'])
        end_t = to_time(r['end_time'])
        duration = _duration_hours(start_t, end_t)
        if not duration:
            continue
        baseline_raw = min_hours * 0.01 / duration
        baseline = math.ceil(baseline_raw)
        headcount = r['headcount']
        passed = headcount >= baseline
        results.append({
            'workgroup': r['workgroup'],
            'shift_name': r['shift_name'],
            'weekday': r['weekday'],
            'start_time': r['start_time'],
            'end_time': r['end_time'],
            'headcount': headcount,
            'minimum_hours': min_hours,
            'duration_hours': duration,
            'baseline': baseline,
            'shortfall': 0 if passed else (baseline - headcount),
            'passed': passed,
        })
    weekday_index = {d: i for i, d in enumerate(WEEKDAYS)}
    results.sort(key=lambda r: (
        r['workgroup'], r['start_time'], weekday_index.get(r['weekday'], 99)
    ))
    return results
