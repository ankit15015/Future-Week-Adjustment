const state = {
  sourceRecords: [],
  matchResults: [],
  reasonedResults: [],
  groups: { workgroup: [], shift_type: [] },
  minimumHours: {},
  minHoursOk: true,
  onePercentResults: [],
  onePercentOk: true,
  destLoaded: false,
  exportDone: false,
};

function updateStepRail() {
  const sourceLoaded = state.sourceRecords.length > 0;
  // Only known to be skippable once a source file has actually been checked -
  // before that, show them as regular upcoming steps, not "not needed".
  const minHoursSkipped = sourceLoaded && Object.keys(state.minimumHours).length === 0;
  const onePercentSkipped = sourceLoaded && state.onePercentResults.length === 0;
  const steps = [
    { key: 'source', done: sourceLoaded },
    { key: 'min-hours', done: sourceLoaded && state.minHoursOk, skipped: minHoursSkipped },
    { key: 'one-percent', done: sourceLoaded && state.onePercentOk, skipped: onePercentSkipped },
    { key: 'dest', done: state.destLoaded },
    { key: 'match', done: state.matchResults.length > 0 },
    { key: 'reason', done: state.reasonedResults.length > 0 },
    { key: 'export', done: state.exportDone },
  ];
  let currentSet = false;
  steps.forEach(s => {
    const li = document.querySelector(`.rail-step[data-rail="${s.key}"]`);
    if (!li) return;
    li.classList.remove('is-done', 'is-current', 'is-skipped');
    const existingNote = li.querySelector('.rail-note');
    if (existingNote) existingNote.remove();
    if (s.skipped) {
      li.classList.add('is-skipped');
      const note = document.createElement('span');
      note.className = 'rail-note';
      note.textContent = 'not needed here';
      li.appendChild(note);
    } else if (s.done) {
      li.classList.add('is-done');
    } else if (!currentSet) {
      li.classList.add('is-current');
      currentSet = true;
    }
  });
}

function el(id) { return document.getElementById(id); }

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = body.description || body.message || msg;
    } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

function setStatus(elm, text, cls) {
  elm.textContent = text;
  elm.className = 'status' + (cls ? ' ' + cls : '');
}

// ---------------------------------------------------------------- file lists

async function loadFileList(selectId, kind) {
  const select = el(selectId);
  try {
    const data = await api(`/api/files?kind=${kind}`);
    select.innerHTML = '<option value="">-- choose a file from the folder --</option>' +
      data.files.map(f => `<option value="${escapeAttr(f.name)}">${escapeHtml(f.name)}</option>`).join('');
  } catch (e) {
    select.innerHTML = '<option value="">(could not list folder)</option>';
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function escapeAttr(s) { return escapeHtml(s); }

function roundClean(n) {
  return Math.round(n * 100) / 100;
}

// ---------------------------------------------------------------- source

async function submitSource(formData) {
  setStatus(el('source-status'), 'Reading source file…');
  el('source-table-wrap').classList.add('hidden');
  el('source-warnings').innerHTML = '';
  try {
    const data = await api('/api/source', { method: 'POST', body: formData });
    state.sourceRecords = data.records;
    state.minimumHours = data.minimum_hours || {};
    state.destLoaded = false;
    state.matchResults = [];
    state.reasonedResults = [];
    state.exportDone = false;
    setStatus(el('source-status'), `Loaded "${data.filename}" (${data.kind}) — ${data.record_count} shift/day/workgroup cells found.`, 'ok');
    if (data.warnings && data.warnings.length) {
      el('source-warnings').innerHTML = data.warnings.map(w => `<div>${escapeHtml(w)}</div>`).join('');
    }
    renderSourceTable();
    el('source-table-wrap').classList.remove('hidden');
    el('match-table-wrap').classList.add('hidden');
    el('match-summary').innerHTML = '';
    setupMinHoursStep();
    setupOnePercentStep(data.one_percent_rule || []);
    updateMatchButtonState();
    updateStepRail();
  } catch (e) {
    setStatus(el('source-status'), 'Error: ' + e.message, 'error');
  }
}

el('source-load-btn').addEventListener('click', () => {
  const filename = el('source-file-select').value;
  if (!filename) { setStatus(el('source-status'), 'Choose a file from the dropdown first.', 'error'); return; }
  const fd = new FormData();
  fd.append('filename', filename);
  submitSource(fd);
});

el('source-upload-input').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  submitSource(fd);
});

function renderSourceTable() {
  const tbody = document.querySelector('#source-table tbody');
  tbody.innerHTML = '';
  state.sourceRecords.forEach((r, i) => tbody.appendChild(sourceRowEl(r, i)));
  const wgs = new Set(state.sourceRecords.map(r => r.workgroup));
  const days = new Set(state.sourceRecords.map(r => r.weekday));
  el('source-summary').textContent = `${state.sourceRecords.length} rows · ${wgs.size} workgroup(s) · ${days.size} day(s)`;
}

const WEEKDAY_OPTIONS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];

function sourceRowEl(r, i) {
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input data-field="workgroup" value="${escapeAttr(r.workgroup)}"></td>
    <td>
      <select data-field="weekday">
        ${WEEKDAY_OPTIONS.map(d => `<option value="${d}" ${d === r.weekday ? 'selected' : ''}>${d}</option>`).join('')}
      </select>
    </td>
    <td><input data-field="shift_name" value="${escapeAttr(r.shift_name)}"></td>
    <td><input data-field="start_time" value="${escapeAttr(r.start_time || '')}" placeholder="HH:MM" size="6"></td>
    <td><input data-field="end_time" value="${escapeAttr(r.end_time || '')}" placeholder="HH:MM" size="6"></td>
    <td><input data-field="headcount" value="${escapeAttr(r.headcount)}" size="6"></td>
    <td><button class="secondary small" data-action="remove">&times;</button></td>
  `;
  tr.querySelectorAll('input, select').forEach(inp => {
    inp.addEventListener('change', () => {
      const field = inp.dataset.field;
      state.sourceRecords[i][field] = field === 'headcount' ? inp.value : inp.value;
    });
  });
  tr.querySelector('[data-action="remove"]').addEventListener('click', () => {
    state.sourceRecords.splice(i, 1);
    renderSourceTable();
  });
  return tr;
}

el('source-add-row').addEventListener('click', () => {
  state.sourceRecords.push({ workgroup: '', weekday: 'Monday', shift_name: '', start_time: '', end_time: '', headcount: '0' });
  renderSourceTable();
});

el('source-save').addEventListener('click', async () => {
  try {
    const data = await persistSourceRecords();
    setStatus(el('source-status'), `Saved ${data.record_count} rows.`, 'ok');
    updateMatchButtonState();
  } catch (e) {
    setStatus(el('source-status'), 'Error saving: ' + e.message, 'error');
  }
});

// ---------------------------------------------------------------- destination lock

function refreshDestinationLock() {
  if (state.minHoursOk && state.onePercentOk) {
    el('dest-locked-msg').classList.add('hidden');
    el('dest-controls').classList.remove('hidden');
  } else {
    const reasons = [];
    if (!state.minHoursOk) reasons.push('confirm minimum hours');
    if (!state.onePercentOk) reasons.push('fix the shift(s) failing the 1% rule');
    el('dest-locked-msg').textContent = `Before loading a destination file: ${reasons.join(' and ')}.`;
    el('dest-locked-msg').classList.remove('hidden');
    el('dest-controls').classList.add('hidden');
    state.destLoaded = false;
    updateMatchButtonState();
  }
  updateStepRail();
}

// ---------------------------------------------------------------- minimum hours

function setupMinHoursStep() {
  const workgroups = Object.keys(state.minimumHours);
  if (workgroups.length === 0) {
    el('step-min-hours').classList.add('hidden');
    state.minHoursOk = true;
    refreshDestinationLock();
    return;
  }
  el('step-min-hours').classList.remove('hidden');
  state.minHoursOk = false;
  refreshDestinationLock();
  el('min-hours-groups').innerHTML = workgroups.map(wg => `
    <div class="min-hours-item" data-workgroup="${escapeAttr(wg)}">
      <div class="mh-label">${escapeHtml(wg)}</div>
      <input type="number" step="any" placeholder="Hours you're committing to">
      <div class="mh-result"></div>
    </div>
  `).join('');
  setStatus(el('min-hours-status'), '', '');
}

async function runMinHoursValidation() {
  const entries = {};
  document.querySelectorAll('#min-hours-groups .min-hours-item').forEach(item => {
    const wg = item.dataset.workgroup;
    const val = item.querySelector('input').value;
    if (val !== '') entries[wg] = val;
  });
  const data = await api('/api/minimum-hours/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entries }),
  });
  data.checks.forEach(check => {
    const item = document.querySelector(`#min-hours-groups .min-hours-item[data-workgroup="${cssEscape(check.workgroup)}"]`);
    if (!item) return;
    item.classList.remove('passed', 'failed');
    const resultEl = item.querySelector('.mh-result');
    let promptEl = item.querySelector('.mh-shortfall-prompt');
    if (promptEl) promptEl.remove();
    if (check.passed) {
      item.classList.add('passed');
      resultEl.textContent = `OK — meets the required ${check.required} hours.`;
      resultEl.className = 'mh-result ok';
    } else {
      item.classList.add('failed');
      const entered = check.entered !== null && check.entered !== undefined ? check.entered : 0;
      const shortfall = (check.required - entered).toFixed(2);
      resultEl.textContent = `Short — needs ${check.required}, you entered ${check.entered ?? '(nothing)'}.`;
      resultEl.className = 'mh-result short';
      const prompt = document.createElement('div');
      prompt.className = 'mh-shortfall-prompt';
      prompt.innerHTML = `
        You're ${shortfall} hours short of this source file's minimum. Add those hours?
        <div class="mh-actions">
          <button class="primary small" data-action="add">Yes, add it</button>
          <button class="secondary small" data-action="skip">No</button>
        </div>
      `;
      prompt.querySelector('[data-action="add"]').addEventListener('click', async () => {
        item.querySelector('input').value = check.required;
        await runMinHoursValidation();
      });
      prompt.querySelector('[data-action="skip"]').addEventListener('click', () => {
        prompt.remove();
      });
      item.appendChild(prompt);
    }
  });
  state.minHoursOk = data.passed;
  if (data.passed) {
    setStatus(el('min-hours-status'), 'All workgroups meet their minimum hours.', 'ok');
  } else {
    setStatus(el('min-hours-status'), 'Fix the workgroup(s) above before continuing.', 'error');
  }
  refreshDestinationLock();
  return data;
}

function cssEscape(s) {
  return String(s).replace(/["\\]/g, '\\$&');
}

el('min-hours-confirm-btn').addEventListener('click', async () => {
  try {
    await runMinHoursValidation();
  } catch (e) {
    setStatus(el('min-hours-status'), 'Error: ' + e.message, 'error');
  }
});

// ---------------------------------------------------------------- 1% rule

function setupOnePercentStep(results) {
  state.onePercentResults = results;
  if (results.length === 0) {
    el('step-one-percent').classList.add('hidden');
    state.onePercentOk = true;
    refreshDestinationLock();
    return;
  }
  el('step-one-percent').classList.remove('hidden');
  state.onePercentOk = results.every(r => r.passed);
  const failing = results.filter(r => !r.passed);
  if (state.onePercentOk) {
    setStatus(el('one-percent-status'), `All ${results.length} shift/day combination(s) meet their baseline.`, 'ok');
  } else {
    setStatus(
      el('one-percent-status'),
      `${failing.length} of ${results.length} shift/day combination(s) are short of their baseline — fix them before continuing.`,
      'error'
    );
  }
  el('one-percent-fix-all-btn').classList.toggle('hidden', failing.length === 0);
  renderOnePercentTable();
  refreshDestinationLock();
}

function renderOnePercentTable() {
  const showAll = el('one-percent-show-all').checked;
  const results = state.onePercentResults;
  const rows = showAll ? results : results.filter(r => !r.passed);
  const tbody = document.querySelector('#one-percent-table tbody');
  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="op-empty">Every shift/day meets its baseline &mdash; nothing to fix.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((r, i) => `
    <tr class="${r.passed ? '' : 'row-failed'}" data-op-index="${i}">
      <td>${escapeHtml(r.workgroup)}</td>
      <td>${escapeHtml(r.shift_name)}</td>
      <td>${escapeHtml(r.weekday)}</td>
      <td>${r.headcount}</td>
      <td>${r.baseline}</td>
      <td>${r.passed
        ? '<span class="badge exact">Pass</span>'
        : `<span class="badge far">Short by ${r.shortfall}</span>`}</td>
      <td>${r.passed ? '' : `<button class="secondary op-fix-btn" data-action="fix">Fix (+${r.shortfall})</button>`}</td>
    </tr>
  `).join('');
  tbody.querySelectorAll('[data-action="fix"]').forEach((btn, i) => {
    const row = rows[i];
    btn.addEventListener('click', () => applyOnePercentFix(row));
  });
}

el('one-percent-show-all').addEventListener('change', renderOnePercentTable);

async function persistSourceRecords() {
  const records = state.sourceRecords.map(r => ({
    workgroup: r.workgroup,
    weekday: r.weekday,
    shift_name: r.shift_name,
    start_time: r.start_time,
    end_time: r.end_time,
    headcount: parseFloat(r.headcount),
  }));
  const data = await api('/api/source/update', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ records }),
  });
  setupOnePercentStep(data.one_percent_rule || []);
  return data;
}

function findMatchingSourceRecord(row) {
  return state.sourceRecords.find(r =>
    r.workgroup === row.workgroup && r.shift_name === row.shift_name &&
    r.weekday === row.weekday && r.start_time === row.start_time && r.end_time === row.end_time
  );
}

async function applyOnePercentFix(row) {
  const rec = findMatchingSourceRecord(row);
  if (!rec) return;
  rec.headcount = row.baseline;
  try {
    await persistSourceRecords();
    renderSourceTable();
  } catch (e) {
    setStatus(el('one-percent-status'), 'Error applying fix: ' + e.message, 'error');
  }
}

el('one-percent-fix-all-btn').addEventListener('click', async () => {
  state.onePercentResults.filter(r => !r.passed).forEach(row => {
    const rec = findMatchingSourceRecord(row);
    if (rec) rec.headcount = row.baseline;
  });
  try {
    await persistSourceRecords();
    renderSourceTable();
  } catch (e) {
    setStatus(el('one-percent-status'), 'Error applying fixes: ' + e.message, 'error');
  }
});

// ---------------------------------------------------------------- destination

async function submitDestination(formData) {
  setStatus(el('dest-status'), 'Reading destination file…');
  el('dest-summary-wrap').classList.add('hidden');
  try {
    const data = await api('/api/destination', { method: 'POST', body: formData });
    setStatus(el('dest-status'), `Loaded "${data.filename}".`, 'ok');
    el('dest-summary').textContent =
      `${data.row_count} rows · ${data.workgroups.length} workgroup(s): ${data.workgroups.join(', ')} · ` +
      `Headcount column: "${data.headers_detected.headcount}" · Reason column: "${data.headers_detected.reason}"`;
    el('dest-summary-wrap').classList.remove('hidden');
    state.destLoaded = true;
    state.matchResults = [];
    state.reasonedResults = [];
    state.exportDone = false;
    el('match-table-wrap').classList.add('hidden');
    el('match-summary').innerHTML = '';
    updateMatchButtonState();
    updateStepRail();
  } catch (e) {
    setStatus(el('dest-status'), 'Error: ' + e.message, 'error');
  }
}

el('dest-load-btn').addEventListener('click', () => {
  const filename = el('dest-file-select').value;
  if (!filename) { setStatus(el('dest-status'), 'Choose a file from the dropdown first.', 'error'); return; }
  const fd = new FormData();
  fd.append('filename', filename);
  submitDestination(fd);
});

el('dest-upload-input').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  submitDestination(fd);
});

function updateMatchButtonState() {
  el('match-btn').disabled = !(state.sourceRecords.length > 0 && state.destLoaded);
}

// ---------------------------------------------------------------- match

el('match-btn').addEventListener('click', async () => {
  el('match-btn').disabled = true;
  try {
    const data = await api('/api/match', { method: 'POST' });
    state.matchResults = data.results;
    state.groups = data.groups;
    state.reasonedResults = [];
    state.exportDone = false;
    renderMatchSummary(data.summary);
    setResultsAndRender(data.results, true);
    renderReasonGroups();
    el('export-review-btn').disabled = false;
    el('export-review-wrap').classList.add('hidden');
    updateStepRail();
  } catch (e) {
    alert('Error running match: ' + e.message);
  } finally {
    el('match-btn').disabled = false;
  }
});

function renderMatchSummary(s) {
  el('match-summary').innerHTML = `
    <span class="chip total">${s.total} total</span>
    <span class="chip exact">${s.exact} exact match</span>
    <span class="chip near">${s.near} near match (&le;15min)</span>
    <span class="chip no_match">${s.far + s.no_match} needs review</span>
  `;
}

function confidenceLabel(c) {
  return { exact: 'Exact', near: 'Near', far: 'Far', no_source_match: 'No source match', no_time: 'No time' }[c] || c;
}

function renderMatchTableRows(results) {
  const tbody = document.querySelector('#match-table tbody');
  tbody.innerHTML = results.map((r) => `
    <tr>
      <td>${r.index + 1}</td>
      <td>${escapeHtml(r.workgroup)}</td>
      <td>${escapeHtml(r.weekday || '')}</td>
      <td>${escapeHtml(r.date || '')}</td>
      <td>${escapeHtml(r.start_time)}</td>
      <td>${escapeHtml(r.end_time)}</td>
      <td>${escapeHtml(r.old_headcount)}</td>
      <td><strong>${r.new_headcount !== null && r.new_headcount !== undefined ? r.new_headcount : '—'}</strong></td>
      <td><span class="badge ${r.confidence}">${confidenceLabel(r.confidence)}</span></td>
      <td class="reason-cell">${escapeHtml(r.reason || '')}</td>
    </tr>
  `).join('');
  el('match-table-wrap').classList.remove('hidden');
}

// ---- filters shared by the Match table and the final result ----
// Both tables filter on the same things: workgroup (each workgroup on its own - combined
// labels like "Pack - Batch, Sort" are split), day, date, and start/end time (24-hour).
// `prefix` is the id prefix of the filter bar: 'filter' (Match) or 'final-filter' (final result).

const COMMON_FILTERS = ['workgroup', 'day', 'date', 'start', 'end'];

function rowWorkgroups(r) {
  if (r.workgroups && r.workgroups.length) return r.workgroups;
  return r.workgroup ? [r.workgroup] : [];
}

function fillSelect(id, allLabel, options) {
  const select = el(id);
  const previous = select.value;
  select.innerHTML = `<option value="">${allLabel}</option>` +
    options.map(([value, label]) => `<option value="${escapeAttr(value)}">${escapeHtml(label)}</option>`).join('');
  if (options.some(([value]) => value === previous)) select.value = previous;
}

function populateCommonFilters(prefix, rows) {
  const byLower = new Map();
  rows.forEach(r => rowWorkgroups(r).forEach(w => { if (!byLower.has(w.toLowerCase())) byLower.set(w.toLowerCase(), w); }));
  const workgroups = [...byLower.values()].sort((a, b) => a.localeCompare(b));
  const days = WEEKDAY_OPTIONS.filter(d => rows.some(r => r.weekday === d));
  const weekdayOfDate = {};
  rows.forEach(r => { if (r.date) weekdayOfDate[r.date] = r.weekday || ''; });
  const dates = Object.keys(weekdayOfDate).sort();
  const distinctSorted = key => [...new Set(rows.map(r => r[key]).filter(Boolean))].sort();   // 'HH:MM' sorts correctly

  fillSelect(`${prefix}-workgroup`, 'All workgroups', workgroups.map(w => [w, w]));
  fillSelect(`${prefix}-day`, 'All days', days.map(d => [d, d]));
  fillSelect(`${prefix}-date`, 'All dates',
    dates.map(d => [d, weekdayOfDate[d] ? `${d} (${weekdayOfDate[d].slice(0, 3)})` : d]));
  fillSelect(`${prefix}-start`, 'Any start (24h)', distinctSorted('start_time').map(t => [t, t]));
  fillSelect(`${prefix}-end`, 'Any end (24h)', distinctSorted('end_time').map(t => [t, t]));
}

function matchesCommonFilters(prefix, r) {
  const value = name => el(`${prefix}-${name}`).value;
  const wg = value('workgroup').toLowerCase();
  if (wg && !rowWorkgroups(r).some(w => w.toLowerCase() === wg)) return false;
  if (value('day') && r.weekday !== value('day')) return false;
  if (value('date') && r.date !== value('date')) return false;
  if (value('start') && r.start_time !== value('start')) return false;
  if (value('end') && r.end_time !== value('end')) return false;
  return true;
}

function resetCommonFilters(prefix) {
  COMMON_FILTERS.forEach(name => { el(`${prefix}-${name}`).value = ''; });
}

// ---- Excel-style column filters ----
// Every column of a review table gets a filter button in its header. It opens a searchable list
// of the distinct values in that column (with counts) to tick, like Excel's AutoFilter. Filters on
// several columns combine (AND), and a column's list only offers values still possible under the
// other filters. The columns come from the loaded file, so whatever it contains can be filtered.
//
//   getRows()             all rows of the table
//   getColumns()          [{key, label, value(row) -> string, title?}] currently shown columns
//   passesOtherFilters(r) the table's other (non-column) filters, so lists stay in step with them
//   onChange()            called after a filter is applied or cleared

const BLANK_LABEL = '(Blanks)';
const FILTER_LIST_LIMIT = 500;

function sortFilterValues(values) {
  const blanks = values.filter(v => v === '');
  const rest = values.filter(v => v !== '');
  const numeric = rest.length > 0 && rest.every(v => /^-?\d+(\.\d+)?$/.test(v));
  rest.sort(numeric
    ? (a, b) => parseFloat(a) - parseFloat(b)
    : (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
  return [...rest, ...blanks];
}

function createColumnFilters({ getRows, getColumns, passesOtherFilters, onChange }) {
  const selected = new Map();   // column key -> Set of values to keep
  let popup = null;

  function matches(row, exceptKey) {
    for (const col of getColumns()) {
      if (col.key === exceptKey) continue;
      const keep = selected.get(col.key);
      if (keep && !keep.has(col.value(row))) return false;
    }
    return true;
  }

  function onOutsideClick(e) {
    if (popup && !popup.contains(e.target) && !e.target.closest('.col-filter-btn')) closePopup();
  }
  function onKey(e) { if (e.key === 'Escape') closePopup(); }
  function onScroll(e) { if (popup && !popup.contains(e.target)) closePopup(); }

  function closePopup() {
    if (!popup) return;
    popup.remove();
    popup = null;
    document.removeEventListener('mousedown', onOutsideClick, true);
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('scroll', onScroll, true);
    window.removeEventListener('resize', closePopup);
  }

  function openPopup(key, btn) {
    const col = getColumns().find(c => c.key === key);
    if (!col) return;
    const counts = new Map();
    getRows().filter(r => passesOtherFilters(r) && matches(r, key)).forEach(r => {
      const v = col.value(r);
      counts.set(v, (counts.get(v) || 0) + 1);
    });
    const values = sortFilterValues([...counts.keys()]);
    const index = new Map(values.map((v, i) => [v, i]));
    const current = selected.get(key);
    const draft = new Set(current ? values.filter(v => current.has(v)) : values);

    popup = document.createElement('div');
    popup.className = 'col-filter-popup';
    popup.dataset.col = key;
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', `Filter ${col.label}`);
    popup.innerHTML = `
      <div class="cf-title">${escapeHtml(col.label)}</div>
      <input type="text" class="cf-search" placeholder="Search" aria-label="Search values">
      <label class="cf-row cf-all"><input type="checkbox" class="cf-all-box"> <span>(Select all)</span></label>
      <div class="cf-list"></div>
      <div class="cf-actions">
        <button type="button" class="secondary small cf-clear">Clear filter</button>
        <span class="cf-spacer"></span>
        <button type="button" class="secondary small cf-cancel">Cancel</button>
        <button type="button" class="primary small cf-ok">OK</button>
      </div>`;
    document.body.appendChild(popup);
    const listEl = popup.querySelector('.cf-list');
    const searchEl = popup.querySelector('.cf-search');
    const allBox = popup.querySelector('.cf-all-box');
    const okBtn = popup.querySelector('.cf-ok');

    const labelOf = v => (v === '' ? BLANK_LABEL : v);
    const visibleValues = () => {
      const q = searchEl.value.trim().toLowerCase();
      return q ? values.filter(v => labelOf(v).toLowerCase().includes(q)) : values;
    };
    function syncControls() {
      const visible = visibleValues();
      const ticked = visible.filter(v => draft.has(v)).length;
      allBox.checked = visible.length > 0 && ticked === visible.length;
      allBox.indeterminate = ticked > 0 && ticked < visible.length;
      okBtn.disabled = draft.size === 0;
    }
    function renderList() {
      const visible = visibleValues();
      listEl.innerHTML = visible.slice(0, FILTER_LIST_LIMIT).map(v => `
        <label class="cf-row"><input type="checkbox" data-i="${index.get(v)}"${draft.has(v) ? ' checked' : ''}>
          <span class="cf-val">${escapeHtml(labelOf(v))}</span><span class="cf-count">${counts.get(v)}</span></label>`).join('') +
        (visible.length > FILTER_LIST_LIMIT ? `<div class="cf-note">Showing the first ${FILTER_LIST_LIMIT} of ${visible.length} - type to narrow the list.</div>` : '') +
        (visible.length === 0 ? '<div class="cf-note">No matching values.</div>' : '');
      syncControls();
    }

    listEl.addEventListener('change', e => {
      const box = e.target.closest('input[data-i]');
      if (!box) return;
      const v = values[Number(box.dataset.i)];
      if (box.checked) draft.add(v); else draft.delete(v);
      syncControls();
    });
    searchEl.addEventListener('input', renderList);
    allBox.addEventListener('change', () => {
      visibleValues().forEach(v => { if (allBox.checked) draft.add(v); else draft.delete(v); });
      renderList();
    });
    popup.querySelector('.cf-cancel').addEventListener('click', closePopup);
    popup.querySelector('.cf-clear').addEventListener('click', () => { selected.delete(key); closePopup(); onChange(); });
    okBtn.addEventListener('click', () => {
      if (values.every(v => draft.has(v))) {
        selected.delete(key);                                   // everything ticked = no filter
      } else {
        const keep = new Set(draft);
        if (current) current.forEach(v => { if (!counts.has(v)) keep.add(v); });   // values other filters hide right now
        selected.set(key, keep);
      }
      closePopup();
      onChange();
    });

    renderList();
    // Fixed position so the table's own scrolling can't clip it; clamp to the viewport.
    const rect = btn.getBoundingClientRect();
    const width = 270;
    popup.style.width = `${width}px`;
    popup.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
    popup.style.top = `${rect.bottom + 4}px`;
    popup.style.top = `${Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - popup.offsetHeight - 8))}px`;
    document.addEventListener('mousedown', onOutsideClick, true);
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', closePopup);
    searchEl.focus();
  }

  return {
    matches: row => matches(row),
    clear() { selected.clear(); closePopup(); },
    close: closePopup,
    activeCount: () => getColumns().filter(c => selected.has(c.key)).length,
    headerCell(col, extraClass) {
      const on = selected.has(col.key);
      return `<th${extraClass ? ` class="${extraClass}"` : ''}${col.title ? ` title="${escapeAttr(col.title)}"` : ''}>${escapeHtml(col.label)}` +
        `<button type="button" class="col-filter-btn${on ? ' is-active' : ''}" data-col="${escapeAttr(col.key)}" ` +
        `title="${on ? 'Filtered - click to change' : 'Filter this column'}" aria-label="Filter ${escapeAttr(col.label)}">&#9662;</button></th>`;
    },
    bind(thead) {
      thead.addEventListener('click', e => {
        const btn = e.target.closest('.col-filter-btn');
        if (!btn) return;
        if (popup && popup.dataset.col === btn.dataset.col) { closePopup(); return; }
        closePopup();
        openPopup(btn.dataset.col, btn);
      });
    },
  };
}

// ---- Match table filters ----

// One entry per column of the Match table (same order as the cells in renderMatchTableRows).
const MATCH_COLUMNS = [
  { key: 'index', label: '#', value: r => String(r.index + 1) },
  { key: 'workgroup', label: 'Workgroup', value: r => r.workgroup },
  { key: 'weekday', label: 'Day', value: r => r.weekday || '' },
  { key: 'date', label: 'Date', value: r => r.date || '' },
  { key: 'start', label: 'Start', value: r => r.start_time },
  { key: 'end', label: 'End', value: r => r.end_time },
  { key: 'old', label: 'Old Headcount', value: r => String(r.old_headcount) },
  { key: 'new', label: 'New Headcount', value: r => (r.new_headcount === null || r.new_headcount === undefined ? '—' : String(r.new_headcount)) },
  { key: 'confidence', label: 'Confidence', value: r => confidenceLabel(r.confidence) },
  { key: 'reason', label: 'Reason', value: r => r.reason || '' },
];

// The filter bar above the table (everything except the per-column filters).
function passesMatchBarFilters(r) {
  if (!matchesCommonFilters('filter', r)) return false;
  const conf = el('filter-confidence').value;
  if (conf && r.confidence !== conf) return false;
  const search = el('filter-search').value.trim().toLowerCase();
  if (search) {
    const haystack = `${r.workgroup} ${r.matched_shift_name || ''} ${r.reason || ''} ${r.date || ''} ${r.start_time} ${r.end_time}`.toLowerCase();
    if (!haystack.includes(search)) return false;
  }
  return true;
}

const matchColumnFilters = createColumnFilters({
  getRows: () => state.allResults,
  getColumns: () => MATCH_COLUMNS,
  passesOtherFilters: passesMatchBarFilters,
  onChange: () => applyFiltersAndRender(),
});
matchColumnFilters.bind(document.querySelector('#match-table thead'));

function applyFiltersAndRender() {
  const filtered = state.allResults.filter(r => passesMatchBarFilters(r) && matchColumnFilters.matches(r));
  document.querySelector('#match-table thead').innerHTML =
    '<tr>' + MATCH_COLUMNS.map(col => matchColumnFilters.headerCell(col)).join('') + '</tr>';
  renderMatchTableRows(filtered);
  const total = state.allResults.length;
  const columnsOn = matchColumnFilters.activeCount();
  el('filter-count').textContent = (filtered.length === total ? `${total} row(s)` : `Showing ${filtered.length} of ${total} row(s)`) +
    (columnsOn ? ` · ${columnsOn} column filter(s) on` : '');
}

function setResultsAndRender(results, resetFilters) {
  state.allResults = results.map((r, i) => ({ ...r, index: r.index !== undefined ? r.index : i }));
  populateCommonFilters('filter', state.allResults);
  if (resetFilters) {
    resetCommonFilters('filter');
    el('filter-confidence').value = '';
    el('filter-search').value = '';
    matchColumnFilters.clear();
  }
  applyFiltersAndRender();
}

[...COMMON_FILTERS.map(name => `filter-${name}`), 'filter-confidence'].forEach(id => {
  el(id).addEventListener('change', applyFiltersAndRender);
});
el('filter-search').addEventListener('input', applyFiltersAndRender);
el('filter-reset-btn').addEventListener('click', () => {
  resetCommonFilters('filter');
  el('filter-confidence').value = '';
  el('filter-search').value = '';
  matchColumnFilters.clear();
  applyFiltersAndRender();
});

// ---------------------------------------------------------------- reasons

function currentGroupBy() {
  return document.querySelector('input[name="group-by"]:checked').value;
}

function renderReasonGroups() {
  const groupBy = currentGroupBy();
  const groups = state.groups[groupBy] || [];
  el('reason-groups').innerHTML = groups.map(g => `
    <div class="reason-group-item">
      <div class="grp-label"><span>${escapeHtml(g.key)}</span><span class="grp-count">${g.count} row(s)</span></div>
      <input type="text" data-key="${escapeAttr(g.key)}" placeholder="Reason for this group">
    </div>
  `).join('');
}

document.querySelectorAll('input[name="group-by"]').forEach(radio => {
  radio.addEventListener('change', renderReasonGroups);
});

async function previewReasons() {
  const groupBy = currentGroupBy();
  const reasonMap = {};
  document.querySelectorAll('#reason-groups input[data-key]').forEach(inp => {
    if (inp.value.trim()) reasonMap[inp.dataset.key] = inp.value.trim();
  });
  const defaultReason = el('default-reason').value.trim();
  const data = await api('/api/reasons/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group_by: groupBy, reason_map: reasonMap, default_reason: defaultReason }),
  });
  state.reasonedResults = data.results;
  setResultsAndRender(data.results, false);
  updateStepRail();
  return data.results;
}

el('reason-preview-btn').addEventListener('click', async () => {
  try {
    await previewReasons();
    // The final-result table was built from the previous reasons; make the user regenerate it.
    hideFinalResult();
  } catch (e) {
    alert('Error previewing reasons: ' + e.message);
  }
});

// ---------------------------------------------------------------- export

// Final rows exactly as the server will write them (GET /api/final), and the subset left
// after the filters below. The download contains the visible rows and nothing else.
let finalRows = [];
let finalColumns = [];    // every column of the output file, in file order
let finalHeaders = {};    // names of the Headcount / Reason columns
let finalVisible = [];

// Columns to show: all of them, or (if ticked) only those with something in at least one row.
// Headcount and Reason always stay - they are the two columns this tool writes.
function finalShownColumns() {
  if (!el('final-hide-empty').checked) return finalColumns;
  return finalColumns.filter(col =>
    col === finalHeaders.headcount || col === finalHeaders.reason ||
    finalRows.some(r => r.values[col] !== ''));
}

// Review-only columns (not written to the file) followed by every column of the output file.
// Column keys are prefixed so a file column can never collide with a review-only one.
function finalColumnDefs() {
  return [
    { key: 'meta:row', label: '#', meta: true, title: 'Row number in the file (review only)', value: r => String(r.index + 1) },
    { key: 'meta:match', label: 'Match', meta: true, title: 'How this row matched the source (review only, not written to the file)', value: r => confidenceLabel(r.confidence) },
    { key: 'meta:shift', label: 'Source shift', meta: true, title: 'Source shift it matched (review only, not written to the file)', value: r => r.matched_shift_name || '' },
    ...finalShownColumns().map(col => ({ key: `file:${col}`, label: col, file: col, value: r => r.values[col] ?? '' })),
  ];
}

// The filter bar above the table (everything except the per-column filters).
function passesFinalBarFilters(r) {
  if (!matchesCommonFilters('final-filter', r)) return false;
  const status = el('final-filter-status').value;
  if (status === 'updated' && !r.updated) return false;
  if (status === 'unchanged' && r.updated) return false;
  const search = el('final-filter-search').value.trim().toLowerCase();
  if (search && !Object.values(r.values).join(' ').toLowerCase().includes(search)) return false;
  return true;
}

const finalColumnFilters = createColumnFilters({
  getRows: () => finalRows,
  getColumns: finalColumnDefs,
  passesOtherFilters: passesFinalBarFilters,
  onChange: () => renderFinalTable(),
});
finalColumnFilters.bind(document.querySelector('#export-preview-table thead'));

function finalRowHtml(r, defs) {
  return `<tr class="${r.updated ? '' : 'row-failed'}">` + defs.map(def => {
    if (def.key === 'meta:row') return `<td class="meta-col">${r.index + 1}</td>`;
    if (def.key === 'meta:match') return `<td class="meta-col"><span class="badge ${r.confidence}">${confidenceLabel(r.confidence)}</span></td>`;
    if (def.key === 'meta:shift') return `<td class="meta-col">${escapeHtml(r.matched_shift_name || '')}</td>`;
    const changed = Object.prototype.hasOwnProperty.call(r.changed, def.file);
    const title = changed ? ` title="Was: ${escapeAttr(r.changed[def.file] === '' ? '(blank)' : r.changed[def.file])}"` : '';
    return `<td class="${changed ? 'cell-changed' : ''}"${title}>${escapeHtml(def.value(r))}</td>`;
  }).join('') + '</tr>';
}

function renderFinalTable() {
  finalVisible = finalRows.filter(r => passesFinalBarFilters(r) && finalColumnFilters.matches(r));

  const defs = finalColumnDefs();
  document.querySelector('#export-preview-table thead').innerHTML =
    '<tr>' + defs.map(def => finalColumnFilters.headerCell(def, def.meta ? 'meta-col' : '')).join('') + '</tr>';
  document.querySelector('#export-preview-table tbody').innerHTML = finalVisible.map(r => finalRowHtml(r, defs)).join('');

  const shown = finalVisible.length, total = finalRows.length;
  const filtered = shown < total;
  const columnsOn = finalColumnFilters.activeCount();
  el('final-filter-count').textContent = (filtered ? `Showing ${shown} of ${total} row(s)` : `${total} row(s)`) +
    (columnsOn ? ` · ${columnsOn} column filter(s) on` : '');
  el('export-confirm-note').textContent = filtered
    ? `Filters are on: the downloaded file will contain only these ${shown} of ${total} rows.`
    : `This is exactly what will be written to the file (all ${total} rows). Check it, then confirm below.`;
  el('export-confirm-btn').textContent = filtered ? `Confirm & download ${shown} filtered row(s)` : 'Confirm & download updated file';
  el('export-confirm-btn').disabled = shown === 0;
}

[...COMMON_FILTERS.map(name => `final-filter-${name}`), 'final-filter-status', 'final-hide-empty'].forEach(id => {
  el(id).addEventListener('change', renderFinalTable);
});
el('final-filter-search').addEventListener('input', renderFinalTable);
el('final-filter-reset-btn').addEventListener('click', () => {
  resetCommonFilters('final-filter');
  el('final-filter-status').value = '';
  el('final-filter-search').value = '';
  finalColumnFilters.clear();
  renderFinalTable();
});

function hideFinalResult() {
  finalColumnFilters.close();
  el('export-review-wrap').classList.add('hidden');
  setStatus(el('export-status'), '', '');
  state.exportDone = false;
}

el('export-review-btn').addEventListener('click', async () => {
  el('export-review-btn').disabled = true;
  try {
    await previewReasons();
    const final = await api('/api/final');
    finalRows = final.rows;
    finalColumns = final.columns;
    finalHeaders = final.headers;
    const total = finalRows.length;
    const unmatched = finalRows.filter(r => !r.updated).length;
    el('export-review-text').textContent =
      `${total} row(s) total — ${total - unmatched} will get an updated Headcount` +
      (unmatched ? `, ${unmatched} have no source match and keep their original Headcount (highlighted red below).` : '.');
    populateCommonFilters('final-filter', finalRows);
    resetCommonFilters('final-filter');
    el('final-filter-status').value = '';
    el('final-filter-search').value = '';
    finalColumnFilters.clear();
    renderFinalTable();
    el('export-review-wrap').classList.remove('hidden');
    setStatus(el('export-status'), '', '');
  } catch (e) {
    alert('Error preparing final result: ' + e.message);
  } finally {
    el('export-review-btn').disabled = false;
  }
});

el('export-confirm-btn').addEventListener('click', async () => {
  setStatus(el('export-status'), 'Writing updated file…');
  try {
    const data = await api('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ indices: finalVisible.map(r => r.index) }),
    });
    setStatus(
      el('export-status'),
      `Done. Wrote ${data.rows_written}` + (data.filtered ? ` of ${data.rows_total}` : '') + ' rows' +
      (data.rows_unmatched ? ` (${data.rows_unmatched} rows had no source match — review those before sending).` : '.'),
      'ok'
    );
    el('export-status').innerHTML += ` <a href="${data.download_url}">Download ${escapeHtml(data.filename)}</a>`;
    state.exportDone = true;
    updateStepRail();
  } catch (e) {
    setStatus(el('export-status'), 'Error: ' + e.message, 'error');
  }
});

// ---------------------------------------------------------------- splash / mode select

let standardModeStarted = false;
const MODE_LABELS = { standard: 'Standard', reduce: 'Reduce', overstaffed: 'Overstaffed' };

function hideAllScreens() {
  ['mode-select', 'mode-gate', 'cap-notice', 'standard-mode'].forEach(id => el(id).classList.add('hidden'));
}

function enterStandardMode(modeKey) {
  hideAllScreens();
  el('standard-mode').classList.remove('hidden');
  el('standard-mode-badge').textContent = MODE_LABELS[modeKey] || 'Standard';
  if (!standardModeStarted) {
    standardModeStarted = true;
    loadFileList('source-file-select', 'source');
    loadFileList('dest-file-select', 'destination');
  }
  updateStepRail();
}

// Mode picked on the mode-select screen; the gate and cap-notice buttons below
// are wired once and read this, so going back and picking another mode can't
// leave a stale handler behind.
let pendingMode = null;

function enterModeGate(mode) {
  pendingMode = mode;
  hideAllScreens();
  el('mode-gate').classList.remove('hidden');
  el('gate-title').textContent = MODE_LABELS[mode] || mode;
}

function enterCapNotice() {
  hideAllScreens();
  el('cap-notice').classList.remove('hidden');
}

// "Do you want to adjust max cap?" — Yes shows the settings link first, No goes straight on.
el('gate-yes-btn').addEventListener('click', () => enterCapNotice());
el('gate-no-btn').addEventListener('click', () => enterStandardMode(pendingMode));
el('cap-notice-continue-btn').addEventListener('click', () => enterStandardMode(pendingMode));

document.querySelectorAll('.mode-card').forEach(card => {
  card.addEventListener('click', () => {
    const mode = card.dataset.mode;
    if (mode === 'standard') enterStandardMode(mode);
    else enterModeGate(mode);
  });
});

el('gate-back-btn').addEventListener('click', () => {
  hideAllScreens();
  el('mode-select').classList.remove('hidden');
});

el('cap-notice-back-btn').addEventListener('click', () => {
  hideAllScreens();
  el('mode-select').classList.remove('hidden');
});

el('standard-back-btn').addEventListener('click', () => {
  hideAllScreens();
  el('mode-select').classList.remove('hidden');
});

setTimeout(() => {
  el('splash').classList.add('hidden');
  el('mode-select').classList.remove('hidden');
}, 2600);
