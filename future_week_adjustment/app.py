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

SOURCE_EXTS = {'.xlsx', '.xlsm', '.xlsb', '.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
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
    try:
        records, warnings, minimum_hours, total_hours = base_layer.parse_source(path)
    except Exception as e:
        abort(400, description=f"Could not read source file: {e}")

    sdata = get_session()
    sdata['source_records'] = records
    sdata['source_filename'] = orig_name
    sdata['source_kind'] = 'image' if ext in ('.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp') else 'spreadsheet'
    sdata['minimum_hours'] = minimum_hours
    sdata['min_hours_confirmed'] = not minimum_hours  # nothing to confirm if the source has none
    one_percent_results = _compute_one_percent(sdata)

    weekdays_present = sorted(set(r['weekday'] for r in records), key=base_layer.WEEKDAYS.index)
    workgroups = sorted(set(r['workgroup'] for r in records))
    return jsonify({
        'filename': orig_name,
        'kind': sdata['source_kind'],
        'records': records,
        'warnings': warnings,
        'weekdays_present': weekdays_present,
        'workgroups': workgroups,
        'record_count': len(records),
        'minimum_hours': minimum_hours,
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
        abort(400, description=f"Could not read destination file: {e}")

    sdata['destination'] = loaded
    sdata['destination_filename'] = orig_name

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


def build_final_rows(results):
    """
    Single source of truth for the final result. Returns (rows, updates):
      rows    - what the "Apply & download" table shows, i.e. the value each row will
                hold in the downloaded file.
      updates - the cell changes written to the file (None = leave the original cell alone).
    A row with no source match keeps its original Headcount, and a blank reason keeps the
    original Reason cell, so `rows` shows those originals rather than a blank.
    """
    rows = []
    updates = {}
    for r in results:
        new_headcount = r['new_headcount']
        new_reason = r.get('reason') or None
        updates[r['index']] = {'headcount': new_headcount, 'reason': new_reason}
        rows.append({
            'index': r['index'],
            'workgroup': r['workgroup'],
            'weekday': r['weekday'],
            'start_time': r['start_time'],
            'end_time': r['end_time'],
            'headcount': new_headcount if new_headcount is not None else r['old_headcount'],
            'updated': new_headcount is not None,
            'reason': new_reason if new_reason is not None else r['old_reason'],
        })
    return rows, updates


@app.route('/api/final')
def api_final():
    sdata = get_session()
    if 'reasoned_results' not in sdata:
        abort(400, description="Preview reasons first.")
    rows, _ = build_final_rows(sdata['reasoned_results'])
    return jsonify({'rows': rows})


@app.route('/api/export', methods=['POST'])
def api_export():
    sdata = get_session()
    if 'reasoned_results' not in sdata:
        abort(400, description="Preview reasons before exporting.")
    loaded = sdata['destination']
    rows, updates = build_final_rows(sdata['reasoned_results'])

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
