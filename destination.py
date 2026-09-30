"""
Reads/writes the "Opportunities" destination file (.csv or .xlsx): one row per
shift instance, with a Headcount column and a Reason column somewhere among its
headers (by name, not a hardcoded letter, so minor layout drift doesn't break it).
"""
import csv
import datetime as dt
import os

HEADCOUNT_HEADER = 'Headcount'
REASON_HEADER = 'Reason'
WORKGROUP_HEADER = 'Workgroup(s)'
START_HEADER_PREFIX = 'Opportunity Start Date-Time'
END_HEADER_PREFIX = 'Opportunity End Date-Time'


def _find_header(fieldnames, prefix_or_name):
    for fn in fieldnames:
        if fn.strip().lower() == prefix_or_name.strip().lower():
            return fn
    for fn in fieldnames:
        if fn.strip().lower().startswith(prefix_or_name.strip().lower()):
            return fn
    return None


def load_destination(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        return _load_csv(path)
    elif ext in ('.xlsx', '.xlsm'):
        return _load_xlsx(path)
    else:
        raise ValueError(f"Unsupported destination file type: {ext}")


def _load_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    return _build_result(fieldnames, rows, ext='.csv')


def _load_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        raise ValueError("Destination workbook's first sheet is empty")
    fieldnames = [str(h).strip() if h is not None else '' for h in all_rows[0]]
    rows = []
    for r in all_rows[1:]:
        if all(v is None or v == '' for v in r):
            continue
        row = {}
        for i, fn in enumerate(fieldnames):
            v = r[i] if i < len(r) else None
            row[fn] = '' if v is None else v
        rows.append(row)
    return _build_result(fieldnames, rows, ext='.xlsx', sheet_name=wb.sheetnames[0], source_path=path)


def _build_result(fieldnames, rows, ext, sheet_name=None, source_path=None):
    hc_header = _find_header(fieldnames, HEADCOUNT_HEADER)
    reason_header = _find_header(fieldnames, REASON_HEADER)
    wg_header = _find_header(fieldnames, WORKGROUP_HEADER) or _find_header(fieldnames, 'Workgroup')
    start_header = _find_header(fieldnames, START_HEADER_PREFIX)
    end_header = _find_header(fieldnames, END_HEADER_PREFIX)

    missing = [name for name, val in [('Headcount', hc_header), ('Reason', reason_header),
                                       ('Workgroup(s)', wg_header), ('Opportunity Start Date-Time', start_header)]
               if val is None]
    if missing:
        raise ValueError(f"Destination file is missing expected column(s): {', '.join(missing)}")

    parsed_rows = []
    for i, row in enumerate(rows):
        start_raw = str(row.get(start_header, '')).strip()
        end_raw = str(row.get(end_header, '')).strip() if end_header else ''
        start_dt = _parse_datetime(start_raw)
        end_dt = _parse_datetime(end_raw) if end_raw else None
        parsed_rows.append({
            'index': i,
            'raw': row,
            'workgroup': str(row.get(wg_header, '')).strip(),
            'start_dt': start_dt,
            'end_dt': end_dt,
            'weekday': start_dt.strftime('%A') if start_dt else None,
            'start_time': start_dt.time() if start_dt else None,
            'end_time': end_dt.time() if end_dt else None,
            'old_headcount': str(row.get(hc_header, '')).strip(),
            'old_reason': str(row.get(reason_header, '')).strip(),
        })

    return {
        'fieldnames': fieldnames,
        'rows': parsed_rows,
        'ext': ext,
        'sheet_name': sheet_name,
        '_source_path': source_path,
        'headers': {
            'headcount': hc_header,
            'reason': reason_header,
            'workgroup': wg_header,
            'start': start_header,
            'end': end_header,
        },
    }


def _parse_datetime(raw):
    if not raw:
        return None
    if isinstance(raw, dt.datetime):
        return raw
    raw = str(raw).strip()
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M:%S'):
        try:
            return dt.datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(raw)
    except ValueError:
        return None


def write_destination(loaded, updates, out_path):
    """
    updates: dict {row_index: {'headcount': value_or_None, 'reason': value_or_None}}
    Only cells present (and not None) in `updates` are changed; everything else in
    the original file is left exactly as it was.
    """
    hc_header = loaded['headers']['headcount']
    reason_header = loaded['headers']['reason']

    if loaded['ext'] == '.csv':
        _write_csv(loaded, updates, out_path, hc_header, reason_header)
    else:
        _write_xlsx(loaded, updates, out_path, hc_header, reason_header)


def _write_csv(loaded, updates, out_path, hc_header, reason_header):
    fieldnames = loaded['fieldnames']
    with open(out_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for parsed_row in loaded['rows']:
            row = dict(parsed_row['raw'])
            upd = updates.get(parsed_row['index'], {})
            if upd.get('headcount') is not None:
                row[hc_header] = upd['headcount']
            if upd.get('reason') is not None:
                row[reason_header] = upd['reason']
            writer.writerow(row)


def _write_xlsx(loaded, updates, out_path, hc_header, reason_header):
    import openpyxl
    wb = openpyxl.load_workbook(loaded['_source_path'])
    ws = wb[loaded['sheet_name']]
    header_row = next(ws.iter_rows(min_row=1, max_row=1))
    col_by_header = {}
    for cell in header_row:
        if cell.value is not None:
            col_by_header[str(cell.value).strip()] = cell.column
    hc_col = col_by_header.get(hc_header)
    reason_col = col_by_header.get(reason_header)

    for parsed_row in loaded['rows']:
        sheet_row = parsed_row['index'] + 2  # +1 header, +1 to move to 1-indexed data row
        upd = updates.get(parsed_row['index'], {})
        if upd.get('headcount') is not None and hc_col:
            ws.cell(row=sheet_row, column=hc_col, value=upd['headcount'])
        if upd.get('reason') is not None and reason_col:
            ws.cell(row=sheet_row, column=reason_col, value=upd['reason'])
    wb.save(out_path)
