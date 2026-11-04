"""
Flask app for the Future Week Adjustment dashboard: the JSON API plus the single page UI.

State for a user's in-progress run (source records, loaded destination, match results)
is kept server-side in SESSIONS, keyed by a session cookie - see docs/architecture.md.
"""
import os
import uuid
from datetime import datetime

from flask import Flask, jsonify, request, render_template, session, send_from_directory, abort
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from . import base_layer
from . import matching
from . import opportunities

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Folder listed by the "pick a file" dropdowns. Defaults to the folder that contains this
# project, so files sitting next to the repo show up; override with DASHBOARD_DATA_DIR.
DATA_DIR = os.path.abspath(os.environ.get('DASHBOARD_DATA_DIR') or os.path.join(PROJECT_ROOT, '..'))
# Working folders for uploaded inputs and generated outputs (git-ignored).
INSTANCE_DIR = os.path.join(PROJECT_ROOT, 'instance')
UPLOAD_DIR = os.path.join(INSTANCE_DIR, 'uploads')
OUTPUT_DIR = os.path.join(INSTANCE_DIR, 'output')
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

SOURCE_EXTS = {'.xlsx', '.xlsm', '.xlsb', '.csv', '.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
DEST_EXTS = {'.csv', '.xlsx', '.xlsm'}

app = Flask(__name__)
app.secret_key = os.environ.get('DASHBOARD_SECRET', 'local-dev-only-' + uuid.uuid4().hex)

SESSIONS = {}


@app.errorhandler(HTTPException)
def handle_http_error(e):
    """API errors come back as JSON {description} - the page shows that text to the user."""
    if request.path.startswith('/api/'):
        return jsonify({'description': e.description}), e.code
    return e


def get_session():
    sid = session.get('sid')
    if not sid or sid not in SESSIONS:
        sid = uuid.uuid4().hex
        session['sid'] = sid
        SESSIONS[sid] = {}
    return SESSIONS[sid]


def save_upload(file_storage, subdir):
    fname = secure_filename(file_storage.filename)
    if not fname:
        fname = uuid.uuid4().hex
    dest_dir = os.path.join(UPLOAD_DIR, subdir)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{uuid.uuid4().hex}_{fname}")
    file_storage.save(path)
    return path, fname


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/files')
def list_files():
    kind = request.args.get('kind', 'source')
    exts = SOURCE_EXTS if kind == 'source' else DEST_EXTS
    files = []
    try:
        for name in sorted(os.listdir(DATA_DIR)):
            full = os.path.join(DATA_DIR, name)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in exts:
                files.append({
                    'name': name,
                    'size': os.path.getsize(full),
                    'modified': datetime.fromtimestamp(os.path.getmtime(full)).isoformat(timespec='seconds'),
                })
    except FileNotFoundError:
        pass
    return jsonify({'dir': DATA_DIR, 'files': files})


def _resolve_input_path(subdir):
    """Either use an existing file from DATA_DIR (?filename=) or an uploaded file (multipart 'file')."""
    filename = request.form.get('filename') or request.args.get('filename')
    if filename:
        safe = secure_filename(filename)
        candidates = [os.path.join(DATA_DIR, filename), os.path.join(DATA_DIR, safe)]
        for c in candidates:
            if os.path.isfile(c):
                return c, os.path.basename(c)
        abort(404, description=f"File not found in data folder: {filename}")
    if 'file' in request.files and request.files['file'].filename:
        path, orig_name = save_upload(request.files['file'], subdir)
        return path, orig_name
    abort(400, description="Provide either 'filename' (existing file in the data folder) or upload a 'file'.")


def _compute_one_percent(sdata):
    minimum_hours = sdata.get('minimum_hours', {})
    results = base_layer.compute_one_percent_rule(sdata.get('source_records', []), minimum_hours)
    sdata['one_percent_results'] = results
    sdata['one_percent_ok'] = all(r['passed'] for r in results)
    return results


@app.route('/api/source', methods=['POST'])
def api_source():
    path, orig_name = _resolve_input_path('source')
    ext = os.path.splitext(path)[1].lower()
    if ext not in SOURCE_EXTS:
        abort(400, description=f"Unsupported source file type: {ext}")
    site = (request.form.get('site') or '').strip().upper() or None
    try:
        sites = base_layer.list_sites(path)
        if len(sites) > 1 and site is None:
            # One file holds several sites' Base Layers: the user must say which one this run is for.
            return jsonify({'needs_site': True, 'sites': sites, 'filename': orig_name})
        if site and sites and site not in sites:
            abort(400, description=f"Site {site} is not in this file.")
        if len(sites) == 1:
            site = sites[0]
        records, warnings, minimum_hours, total_hours = base_layer.parse_source(path, site)
    except HTTPException:
        raise
    except Exception as e:
        abort(400, description=f"Could not read source file: {e}")
    if not records and site:
        abort(400, description=f"No Base Layer data found for site {site}.")

    sdata = get_session()
    sdata['source_records'] = records
    sdata['source_filename'] = orig_name
    sdata['source_kind'] = 'image' if ext in ('.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp') else 'spreadsheet'
    sdata['minimum_hours'] = minimum_hours
    sdata['min_hours_confirmed'] = not minimum_hours  # nothing to confirm if the source has none
    sdata['min_hours_entries'] = {}
    sdata['source_snapshots'] = {}
    sdata['source_site'] = site or ''
    one_percent_results = _compute_one_percent(sdata)

    weekdays_present = sorted(set(r['weekday'] for r in records), key=base_layer.WEEKDAYS.index)
    workgroups = sorted(set(r['workgroup'] for r in records))
    return jsonify({
        'filename': orig_name,
        'site': site or '',
        'kind': sdata['source_kind'],
        'records': records,
        'warnings': warnings,
        'weekdays_present': weekdays_present,
        'workgroups': workgroups,
        'record_count': len(records),
        'minimum_hours': minimum_hours,
        'minimum_hours_from_file': bool(minimum_hours),
        'one_percent_rule': one_percent_results,
    })


@app.route('/api/source/update', methods=['POST'])
def api_source_update():
    body = request.get_json(force=True)
    records = body.get('records', [])
    for r in records:
        try:
            r['headcount'] = float(r['headcount'])
        except (TypeError, ValueError):
            abort(400, description=f"Invalid headcount value: {r.get('headcount')!r}")
        if r.get('weekday') not in base_layer.WEEKDAYS:
            abort(400, description=f"Invalid weekday: {r.get('weekday')!r}")
        if not base_layer.TIME_RE.match(str(r.get('start_time', ''))) or not base_layer.TIME_RE.match(str(r.get('end_time', ''))):
            abort(400, description="start_time/end_time must be in HH:MM format")
    sdata = get_session()
    sdata['source_records'] = records
    one_percent_results = _compute_one_percent(sdata)
    return jsonify({'record_count': len(records), 'one_percent_rule': one_percent_results})


def _source_fix_response(sdata, records, **extra):
    sdata['source_records'] = records
    sdata.pop('match_results', None)       # earlier matches were built from the old headcounts
    sdata.pop('reasoned_results', None)
    return jsonify({'records': records, 'one_percent_rule': _compute_one_percent(sdata), **extra})


@app.route('/api/source/one-percent-fix', methods=['POST'])
def api_one_percent_fix():
    """ONE PERCENT FIX: raise every non-zero headcount that is below its 1% baseline up to it."""
    sdata = get_session()
    if 'source_records' not in sdata:
        abort(400, description="Load a source file first.")
    if not sdata.get('minimum_hours'):
        abort(400, description="This source file has no Minimum Hours, so there is no 1% rule to fix.")
    records, changed = base_layer.apply_one_percent_fix(sdata['source_records'], sdata['minimum_hours'])
    sdata.setdefault('source_snapshots', {})['one_percent'] = records
    return _source_fix_response(sdata, records, changed=changed)


@app.route('/api/source/match-minimum-hours', methods=['POST'])
def api_match_minimum_hours():
    """MATCH MINIMUM HOURS: scale headcounts so each workgroup's total hours reach its target."""
    sdata = get_session()
    if 'source_records' not in sdata:
        abort(400, description="Load a source file first.")
    if not sdata.get('minimum_hours'):
        abort(400, description="This source file has no Minimum Hours to match.")
    records, summary = base_layer.match_minimum_hours(
        sdata['source_records'], sdata['minimum_hours'], sdata.get('min_hours_entries'))
    sdata.setdefault('source_snapshots', {})['min_hours'] = records
    return _source_fix_response(sdata, records, summary=summary)


STAGE_LABELS = {'current': 'Base Layer', 'one_percent': 'after 1 percent fix', 'min_hours': 'after minimum hours match'}


@app.route('/api/source/download')
def api_source_download():
    """Download the Base Layer as an xlsx: its current state, or the state right after a fix."""
    sdata = get_session()
    stage = request.args.get('stage', 'current')
    if stage not in STAGE_LABELS:
        abort(400, description="Unknown stage.")
    records = sdata.get('source_records') if stage == 'current' else sdata.get('source_snapshots', {}).get(stage)
    if not records:
        abort(400, description="Run that fix first.")
    stem = os.path.splitext(sdata.get('source_filename', 'Base Layer'))[0]
    site = sdata.get('source_site', '')
    name = secure_filename(f"{stem}{' - ' + site if site and site not in stem else ''} - {STAGE_LABELS[stage]}.xlsx")
    base_layer.write_base_layer_xlsx(records, sdata.get('minimum_hours', {}), os.path.join(OUTPUT_DIR, name), site)
    return send_from_directory(OUTPUT_DIR, name, as_attachment=True)


@app.route('/api/minimum-hours/set', methods=['POST'])
def api_minimum_hours_set():
    """
    For a source file that does not state Minimum Hours: the user supplies them per workgroup.
    This switches on the minimum-hours check, the 1% rule and both fixes for those workgroups.
    An empty mapping clears them again.
    """
    sdata = get_session()
    if 'source_records' not in sdata:
        abort(400, description="Load a source file first.")
    hours = (request.get_json(silent=True) or {}).get('hours') or {}
    known = {r['workgroup'] for r in sdata['source_records']}
    minimum = {}
    for workgroup, raw in hours.items():
        if raw in (None, ''):
            continue
        if workgroup not in known:
            abort(400, description=f"Unknown workgroup: {workgroup}")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            abort(400, description=f"Minimum hours for {workgroup} must be a number.")
        if value <= 0:
            abort(400, description=f"Minimum hours for {workgroup} must be greater than 0.")
        minimum[workgroup] = value
    sdata['minimum_hours'] = minimum
    sdata['min_hours_entries'] = dict(minimum)        # the entered figure is also the committed hours
    sdata['min_hours_confirmed'] = True
    sdata['source_snapshots'] = {}
    sdata.pop('match_results', None)
    sdata.pop('reasoned_results', None)
    # Sanity check against the hours this file already plans: a Minimum Hours far from its total is
    # probably a typo (extra/missing zero), so say so - but still accept it.
    totals = base_layer.total_hours_by_workgroup(sdata['source_records'])
    warnings = []
    for workgroup, value in minimum.items():
        total = totals.get(workgroup, 0)
        if total and value > total:
            warnings.append(f"{workgroup}: minimum {value:g} h is more than this file's planned {total:g} h - "
                            f"Match minimum hours would RAISE headcounts. Check for an extra digit.")
        elif total and value < total * 0.1:
            warnings.append(f"{workgroup}: minimum {value:g} h is under 10% of this file's planned {total:g} h - "
                            f"Match minimum hours would cut headcounts sharply. Check for a missing digit.")
    return jsonify({'minimum_hours': minimum, 'one_percent_rule': _compute_one_percent(sdata), 'warnings': warnings})


@app.route('/api/minimum-hours/validate', methods=['POST'])
def api_minimum_hours_validate():
    sdata = get_session()
    if 'source_records' not in sdata:
        abort(400, description="Load a source file first.")
    required = sdata.get('minimum_hours', {})
    body = request.get_json(force=True)
    entries = body.get('entries', {})

    checks = []
    all_ok = True
    for workgroup, required_hours in required.items():
        raw = entries.get(workgroup)
        try:
            entered = float(raw)
        except (TypeError, ValueError):
            entered = None
        passed = entered is not None and entered >= required_hours
        all_ok = all_ok and passed
        checks.append({
            'workgroup': workgroup,
            'required': required_hours,
            'entered': entered,
            'passed': passed,
        })

    sdata['min_hours_confirmed'] = all_ok
    sdata['min_hours_entries'] = {c['workgroup']: c['entered'] for c in checks if c['entered'] is not None}
    return jsonify({'passed': all_ok, 'checks': checks})


@app.route('/api/destination', methods=['POST'])
def api_destination():
    sdata = get_session()
    if not sdata.get('min_hours_confirmed'):
        abort(400, description="Confirm minimum hours for every workgroup before loading a destination file.")
    if not sdata.get('one_percent_ok'):
        abort(400, description="Fix the shift(s) failing the 1% rule before loading a destination file.")
    path, orig_name = _resolve_input_path('destination')
    ext = os.path.splitext(path)[1].lower()
    if ext not in DEST_EXTS:
        abort(400, description=f"Unsupported destination file type: {ext}")
    try:
        loaded = opportunities.load_destination(path)
    except Exception as e:
        hint = " This looks like a Base Layer - load it under Source instead." if 'missing expected column' in str(e) and base_layer.looks_like_base_layer(path) else ""
        abort(400, description=f"Could not read destination file: {e}{hint}")

    sdata['destination'] = loaded
    sdata['destination_filename'] = orig_name
    # Results from a previous destination no longer line up with its rows - force a re-match.
    sdata.pop('match_results', None)
    sdata.pop('reasoned_results', None)

    workgroups = sorted(set(r['workgroup'] for r in loaded['rows'] if r['workgroup']))
    weekdays_present = sorted(set(r['weekday'] for r in loaded['rows'] if r['weekday']), key=base_layer.WEEKDAYS.index)
    return jsonify({
        'filename': orig_name,
        'row_count': len(loaded['rows']),
        'columns': loaded['fieldnames'],
        'headers_detected': loaded['headers'],
        'workgroups': workgroups,
        'weekdays_present': weekdays_present,
    })


@app.route('/api/match', methods=['POST'])
def api_match():
    sdata = get_session()
    if 'source_records' not in sdata:
        abort(400, description="Load a source file first.")
    if 'destination' not in sdata:
        abort(400, description="Load a destination file first.")

    results = matching.match_destination(sdata['destination'], sdata['source_records'])
    sdata['match_results'] = results

    summary = {
        'total': len(results),
        'exact': sum(1 for r in results if r['confidence'] == 'exact'),
        'near': sum(1 for r in results if r['confidence'] == 'near'),
        'far': sum(1 for r in results if r['confidence'] == 'far'),
        'no_match': sum(1 for r in results if r['confidence'] in ('no_source_match', 'no_time')),
    }
    by_workgroup = matching.distinct_groups(results, 'workgroup')
    by_shift_type = matching.distinct_groups(results, 'shift_type')

    return jsonify({
        'results': results,
        'summary': summary,
        'groups': {
            'workgroup': [{'key': k, 'count': c} for k, c in by_workgroup],
            'shift_type': [{'key': k, 'count': c} for k, c in by_shift_type],
        },
    })


@app.route('/api/reasons/preview', methods=['POST'])
def api_reasons_preview():
    sdata = get_session()
    if 'match_results' not in sdata:
        abort(400, description="Run matching first.")
    body = request.get_json(force=True)
    group_by = body.get('group_by', 'workgroup')
    reason_map = body.get('reason_map', {})
    default_reason = body.get('default_reason', '')

    results = matching.apply_reasons(sdata['match_results'], group_by, reason_map, default_reason)
    sdata['reasoned_results'] = results
    sdata['reason_settings'] = {'group_by': group_by, 'reason_map': reason_map, 'default_reason': default_reason}
    return jsonify({'results': results})


def build_final_rows(loaded, results):
    """
    Single source of truth for the final result. Returns (rows, updates):
      rows    - what the "Apply & download" table shows. Each row carries `values`: every
                column of the output file, exactly as it will be written (built by the same
                opportunities.output_values the file writer uses), and `changed`: the
                columns whose value differs from the original file.
      updates - the cell changes written to the file (None = leave the original cell alone).
    A row with no source match keeps its original Headcount, and a blank reason keeps the
    original Reason cell, so `values` holds those originals rather than a blank.
    """
    headcount_col = loaded['headers']['headcount']
    reason_col = loaded['headers']['reason']
    parsed_by_index = {p['index']: p for p in loaded['rows']}
    rows = []
    updates = {}
    for r in results:
        new_headcount = opportunities.clean_headcount(r['new_headcount'])
        new_reason = r.get('reason') or None
        update = {'headcount': new_headcount, 'reason': new_reason}
        updates[r['index']] = update

        parsed = parsed_by_index[r['index']]
        values = {col: opportunities.format_cell(v)
                  for col, v in opportunities.output_values(loaded, parsed, update).items()}
        original = {col: opportunities.format_cell(v) for col, v in parsed['raw'].items()}
        rows.append({
            'index': r['index'],
            'workgroup': r['workgroup'],
            'workgroups': r['workgroups'],
            'weekday': r['weekday'],
            'start_date': r['start_date'],
            'end_date': r['end_date'],
            'start_time': r['start_time'],
            'end_time': r['end_time'],
            'headcount': values[headcount_col],
            'reason': values[reason_col],
            'updated': new_headcount is not None,
            'confidence': r['confidence'],                 # review-only context, not written to the file
            'matched_shift_name': r['matched_shift_name'],  # review-only context, not written to the file
            'values': values,
            # column -> original value, for the cells this tool changes
            'changed': {col: original.get(col, '') for col in loaded['fieldnames'] if values.get(col) != original.get(col)},
        })
    return rows, updates


@app.route('/api/final')
def api_final():
    sdata = get_session()
    if 'reasoned_results' not in sdata:
        abort(400, description="Preview reasons first.")
    loaded = sdata['destination']
    rows, _ = build_final_rows(loaded, sdata['reasoned_results'])
    return jsonify({'columns': loaded['fieldnames'], 'headers': loaded['headers'], 'rows': rows})


@app.route('/api/export', methods=['POST'])
def api_export():
    sdata = get_session()
    if 'reasoned_results' not in sdata:
        abort(400, description="Preview reasons before exporting.")
    loaded = sdata['destination']
    rows, updates = build_final_rows(loaded, sdata['reasoned_results'])

    # The page sends the row indices it is currently showing (after any filters), so the
    # file holds exactly the rows on screen. No body = every row.
    body = request.get_json(silent=True) or {}
    keep = None
    if body.get('indices') is not None:
        try:
            keep = {int(i) for i in body['indices']}
        except (TypeError, ValueError):
            abort(400, description="indices must be a list of row numbers.")
        if not keep:
            abort(400, description="No rows selected — your filters match nothing.")
        if not keep <= updates.keys():
            abort(400, description="Unknown row in selection — run the match again.")
    filtered = keep is not None and len(keep) < len(rows)

    orig_name = sdata.get('destination_filename', 'destination')
    stem, ext = os.path.splitext(orig_name)
    out_name = f"{stem} - Updated{' (filtered)' if filtered else ''}{ext}"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    opportunities.write_destination(loaded, updates, out_path, keep=keep)

    written = [r for r in rows if keep is None or r['index'] in keep]
    return jsonify({
        'download_url': f"/api/download/{out_name}",
        'filename': out_name,
        'rows_written': len(written),
        'rows_total': len(rows),
        'rows_unmatched': sum(1 for r in written if not r['updated']),
        'filtered': filtered,
    })


@app.route('/api/download/<path:filename>')
def api_download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)
