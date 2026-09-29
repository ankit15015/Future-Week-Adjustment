import os
import uuid
import threading
import webbrowser
from datetime import datetime

from flask import Flask, jsonify, request, render_template, session, send_from_directory, abort
from werkzeug.utils import secure_filename

import parsing
import destination
import matching

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, '..'))
UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

SOURCE_EXTS = {'.xlsx', '.xlsm', '.xlsb', '.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
DEST_EXTS = {'.csv', '.xlsx', '.xlsm'}

app = Flask(__name__)
app.secret_key = os.environ.get('DASHBOARD_SECRET', 'local-dev-only-' + uuid.uuid4().hex)

SESSIONS = {}


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
    results = parsing.compute_one_percent_rule(sdata.get('source_records', []), minimum_hours)
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
        records, warnings, minimum_hours, total_hours = parsing.parse_source(path)
    except Exception as e:
        abort(400, description=f"Could not read source file: {e}")

    sdata = get_session()
    sdata['source_records'] = records
    sdata['source_filename'] = orig_name
    sdata['source_kind'] = 'image' if ext in ('.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp') else 'spreadsheet'
    sdata['minimum_hours'] = minimum_hours
    sdata['min_hours_confirmed'] = not minimum_hours  # nothing to confirm if the source has none
    one_percent_results = _compute_one_percent(sdata)

    weekdays_present = sorted(set(r['weekday'] for r in records), key=parsing.WEEKDAYS.index)
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
        if r.get('weekday') not in parsing.WEEKDAYS:
            abort(400, description=f"Invalid weekday: {r.get('weekday')!r}")
        if not parsing.TIME_RE.match(str(r.get('start_time', ''))) or not parsing.TIME_RE.match(str(r.get('end_time', ''))):
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
        loaded = destination.load_destination(path)
    except Exception as e:
        abort(400, description=f"Could not read destination file: {e}")

    sdata['destination'] = loaded
    sdata['destination_filename'] = orig_name

    workgroups = sorted(set(r['workgroup'] for r in loaded['rows'] if r['workgroup']))
    weekdays_present = sorted(set(r['weekday'] for r in loaded['rows'] if r['weekday']), key=parsing.WEEKDAYS.index)
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


@app.route('/api/export', methods=['POST'])
def api_export():
    sdata = get_session()
    if 'reasoned_results' not in sdata:
        abort(400, description="Preview reasons before exporting.")
    loaded = sdata['destination']
    results = sdata['reasoned_results']

    updates = {}
    for r in results:
        headcount = r['new_headcount'] if r['new_headcount'] is not None else None
        updates[r['index']] = {
            'headcount': headcount,
            'reason': r.get('reason') or None,
        }

    orig_name = sdata.get('destination_filename', 'destination')
    stem, ext = os.path.splitext(orig_name)
    out_name = f"{stem} - Updated{ext}"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    destination.write_destination(loaded, updates, out_path)

    unmatched = sum(1 for r in results if r['new_headcount'] is None)
    return jsonify({
        'download_url': f"/api/download/{out_name}",
        'filename': out_name,
        'rows_written': len(results),
        'rows_unmatched': unmatched,
    })


@app.route('/api/download/<path:filename>')
def api_download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


if __name__ == '__main__':
    port = 5057
    url = f"http://127.0.0.1:{port}/"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Dashboard running at {url}")
    print(f"Data folder: {DATA_DIR}")
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
