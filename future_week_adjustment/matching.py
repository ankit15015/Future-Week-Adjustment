"""
Matches destination rows (from opportunities.py) against source records
(from base_layer.py) to compute the new Headcount (Column H) for each row.
"""
import datetime as dt

from .base_layer import normalize_workgroup, split_workgroups


def _time_diff_minutes(t1, t2):
    m1 = t1.hour * 60 + t1.minute
    m2 = t2.hour * 60 + t2.minute
    d = abs(m1 - m2)
    return min(d, 1440 - d)


def _parse_time_str(s):
    if not s:
        return None
    h, m = s.split(':')
    return dt.time(hour=int(h), minute=int(m))


def build_source_index(source_records):
    index = {}
    for rec in source_records:
        key = (rec['weekday'], normalize_workgroup(rec['workgroup']))
        index.setdefault(key, []).append(rec)
    return index


def match_row(source_index, weekday, workgroup, start_time):
    if weekday is None or start_time is None:
        return None, 'no_time', None
    key = (weekday, normalize_workgroup(workgroup))
    candidates = source_index.get(key)
    if not candidates:
        return None, 'no_source_match', None
    best = min(candidates, key=lambda r: _time_diff_minutes(_parse_time_str(r['start_time']), start_time))
    diff = _time_diff_minutes(_parse_time_str(best['start_time']), start_time)
    if diff == 0:
        confidence = 'exact'
    elif diff <= 15:
        confidence = 'near'
    else:
        confidence = 'far'
    return best['headcount'], confidence, best


def match_destination(loaded_destination, source_records):
    """Returns a list of match results, one per destination row, in original order."""
    source_index = build_source_index(source_records)
    results = []
    for row in loaded_destination['rows']:
        headcount, confidence, matched_rec = match_row(
            source_index, row['weekday'], row['workgroup'], row['start_time']
        )
        results.append({
            'index': row['index'],
            'workgroup': row['workgroup'],
            'workgroups': split_workgroups(row['workgroup']),
            'weekday': row['weekday'],
            'date': row['start_dt'].date().isoformat() if row['start_dt'] else '',
            'start_time': row['start_time'].strftime('%H:%M') if row['start_time'] else '',
            'end_time': row['end_time'].strftime('%H:%M') if row['end_time'] else '',
            'old_headcount': row['old_headcount'],
            'new_headcount': headcount,
            'confidence': confidence,
            'matched_shift_name': matched_rec['shift_name'] if matched_rec else None,
            'old_reason': row['old_reason'],
        })
    return results


def shift_type_key(start_time_str, end_time_str):
    return f"{start_time_str}–{end_time_str}" if start_time_str and end_time_str else '(unknown shift)'


def distinct_groups(match_results, group_by):
    """group_by: 'workgroup' or 'shift_type'"""
    seen = {}
    for r in match_results:
        if group_by == 'workgroup':
            key = r['workgroup'] or '(blank)'
        else:
            key = shift_type_key(r['start_time'], r['end_time'])
        seen[key] = seen.get(key, 0) + 1
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))


def apply_reasons(match_results, group_by, reason_map, default_reason):
    """Attach a 'reason' field to each match result based on the chosen grouping."""
    out = []
    for r in match_results:
        if group_by == 'workgroup':
            key = r['workgroup'] or '(blank)'
        else:
            key = shift_type_key(r['start_time'], r['end_time'])
        reason = reason_map.get(key) or default_reason or ''
        out.append({**r, 'reason': reason})
    return out
