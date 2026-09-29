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
  const minHoursNeeded = Object.keys(state.minimumHours).length > 0;
  const onePercentNeeded = state.onePercentResults.length > 0;
  const steps = [
    { key: 'source', done: state.sourceRecords.length > 0 },
    { key: 'min-hours', done: state.minHoursOk, skipped: !minHoursNeeded },
    { key: 'one-percent', done: state.onePercentOk, skipped: !onePercentNeeded },
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
    if (s.skipped) {
      li.classList.add('is-skipped');
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
    el('export-btn').disabled = false;
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

function populateFilterOptions() {
  const workgroups = [...new Set(state.allResults.map(r => r.workgroup))].sort();
  const days = WEEKDAY_OPTIONS.filter(d => state.allResults.some(r => r.weekday === d));
  const wgSelect = el('filter-workgroup');
  const daySelect = el('filter-day');
  const prevWg = wgSelect.value, prevDay = daySelect.value;
  wgSelect.innerHTML = '<option value="">All workgroups</option>' +
    workgroups.map(w => `<option value="${escapeAttr(w)}">${escapeHtml(w)}</option>`).join('');
  daySelect.innerHTML = '<option value="">All days</option>' +
    days.map(d => `<option value="${d}">${d}</option>`).join('');
  if (workgroups.includes(prevWg)) wgSelect.value = prevWg;
  if (days.includes(prevDay)) daySelect.value = prevDay;
}

function applyFiltersAndRender() {
  const wg = el('filter-workgroup').value;
  const day = el('filter-day').value;
  const conf = el('filter-confidence').value;
  const search = el('filter-search').value.trim().toLowerCase();
  const filtered = state.allResults.filter(r => {
    if (wg && r.workgroup !== wg) return false;
    if (day && r.weekday !== day) return false;
    if (conf && r.confidence !== conf) return false;
    if (search) {
      const haystack = `${r.workgroup} ${r.matched_shift_name || ''} ${r.reason || ''}`.toLowerCase();
      if (!haystack.includes(search)) return false;
    }
    return true;
  });
  renderMatchTableRows(filtered);
  const total = state.allResults.length;
  el('filter-count').textContent = filtered.length === total
    ? `${total} row(s)`
    : `Showing ${filtered.length} of ${total} row(s)`;
}

function setResultsAndRender(results, resetFilters) {
  state.allResults = results.map((r, i) => ({ ...r, index: r.index !== undefined ? r.index : i }));
  if (resetFilters) {
    populateFilterOptions();
    el('filter-workgroup').value = '';
    el('filter-day').value = '';
    el('filter-confidence').value = '';
    el('filter-search').value = '';
  } else {
    populateFilterOptions();
  }
  applyFiltersAndRender();
}

['filter-workgroup', 'filter-day', 'filter-confidence'].forEach(id => {
  el(id).addEventListener('change', applyFiltersAndRender);
});
el('filter-search').addEventListener('input', applyFiltersAndRender);
el('filter-reset-btn').addEventListener('click', () => {
  el('filter-workgroup').value = '';
  el('filter-day').value = '';
  el('filter-confidence').value = '';
  el('filter-search').value = '';
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
  } catch (e) {
    alert('Error previewing reasons: ' + e.message);
  }
});

// ---------------------------------------------------------------- export

el('export-btn').addEventListener('click', async () => {
  try {
    await previewReasons();
  } catch (e) {
    alert('Error applying reasons before export: ' + e.message);
    return;
  }
  setStatus(el('export-status'), 'Writing updated file…');
  try {
    const data = await api('/api/export', { method: 'POST' });
    setStatus(
      el('export-status'),
      `Done. Wrote ${data.rows_written} rows` +
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

function enterModeGate(mode) {
  hideAllScreens();
  el('mode-gate').classList.remove('hidden');
  el('gate-title').textContent = MODE_LABELS[mode] || mode;

  const yesBtn = el('gate-yes-btn');
  const noBtn = el('gate-no-btn');
  const onYes = () => { enterStandardMode(mode); cleanup(); };
  const onNo = () => { enterCapNotice(); cleanup(); };
  function cleanup() {
    yesBtn.removeEventListener('click', onYes);
    noBtn.removeEventListener('click', onNo);
  }
  yesBtn.addEventListener('click', onYes);
  noBtn.addEventListener('click', onNo);
}

function enterCapNotice() {
  hideAllScreens();
  el('cap-notice').classList.remove('hidden');
}

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
