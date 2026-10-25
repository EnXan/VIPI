/* Scanner controls and a separate replayable event stream. All evidence is textContent. */
(() => {
  const node = id => document.getElementById(id);
  const labels = {jev:'Jev',openai:'OpenAI Decisions','prompt-guard':'Prompt Guard 2',image:'Source image',context:'Image + OCR + context'};
  const verdicts = {flagged:'Flagged · review needed',not_flagged:'No issues found in configured checks',unclear:'Unclear · review needed'};
  const thresholdValues = new Map(['jev','openai','prompt-guard','image','context'].map(signal => [signal,80]));
  let currentRun, checkId, stream, answers = [], readings = [], revision = 0, terminal = false;
  let savedChecks = [], observing = null, checking = false, settingsEdited = false;
  const prettyScore = value => value == null ? '—' : value.toFixed(4);
  function selectedSignals(ignoreContext = false) {
    return [
      ...[...document.querySelectorAll('.text-classifier:checked')].map(input => input.value),
      ...(node('image-check').value === 'openai' ? ['image'] : []),
      ...(!ignoreContext && node('context-check').value === 'openai' ? ['context'] : []),
    ];
  }
  function renderThresholdControls() {
    const container = node('threshold-controls');
    container.replaceChildren();
    for (const signal of selectedSignals()) {
      const value = thresholdValues.get(signal);
      const row = document.createElement('section'); row.className = 'threshold-row';
      const title = document.createElement('h3'); title.textContent = labels[signal]; row.append(title);
      const label = document.createElement('label'); label.className = 'threshold-control';
      const caption = document.createElement('span'); caption.textContent = 'Score threshold';
      const controls = document.createElement('span'); controls.className = 'threshold-control-inputs';
      const slider = document.createElement('input'); slider.type = 'range'; slider.min = '0'; slider.max = '100'; slider.step = '0.1'; slider.value = value;
      slider.setAttribute('aria-label', `${labels[signal]} score threshold, percent`);
      const number = document.createElement('input'); number.type = 'number'; number.min = '0'; number.max = '100'; number.step = '0.1'; number.value = value; number.inputMode = 'decimal';
      number.setAttribute('aria-label', `${labels[signal]} score threshold, percent`);
      const suffix = document.createElement('span'); suffix.textContent = '%';
      const sync = event => {
        if (event.currentTarget.value === '') return;
        const next = Number(event.currentTarget.value);
        if (!Number.isFinite(next)) return;
        thresholdValues.set(signal,Math.max(0,Math.min(100,Math.round(next * 10) / 10)));
        slider.value = number.value = String(thresholdValues.get(signal));
      };
      slider.addEventListener('input', sync); number.addEventListener('input', sync);
      controls.append(slider,number,suffix); label.append(caption,controls); row.append(label);
      container.append(row);
    }
  }
  function buildThresholds(ignoreContext = false) {
    const signals = {};
    for (const signal of selectedSignals(ignoreContext)) {
      const value = thresholdValues.get(signal);
      signals[signal] = {threshold:value / 100};
    }
    return {version:node('detector-threshold-version').value.trim(),signals};
  }
  function options(ignoreContext = false) {
    const text_classifiers = [...document.querySelectorAll('.text-classifier:checked')].map(input => input.value);
    const image_check = node('image-check').value, context_check = ignoreContext ? 'off' : node('context-check').value;
    if (!text_classifiers.length && image_check === 'off' && context_check === 'off') return null;
    let context = {};
    try {
      if (!ignoreContext && node('detector-context').value.trim()) context = JSON.parse(node('detector-context').value);
      if (!context || Array.isArray(context) || typeof context !== 'object') throw new Error('object');
    } catch { throw new Error('Context must be a valid JSON object.'); }
    if (!ignoreContext && context_check === 'openai' && !Object.keys(context).length) {
      throw new Error('Add caller context when the context check is enabled.');
    }
    const signals = [...text_classifiers, ...(image_check === 'openai' ? ['image'] : []), ...(context_check === 'openai' ? ['context'] : [])];
    const thresholds = buildThresholds(ignoreContext);
    if (signals.length) {
      if (!thresholds.version) throw new Error('Enter a threshold set version before running detection.');
      const invalidThreshold = [...node('threshold-controls').querySelectorAll('input[type="number"]')].some(input => input.value === '' || !input.checkValidity());
      if (invalidThreshold) throw new Error('Enter a valid score threshold for each selected check.');
    }
    return {text_classifiers,image_check,context_check,context:ignoreContext ? {} : context,thresholds,reuse:node('detector-reuse').checked};
  }
  function reset() {
    revision++; currentRun = checkId = observing = null; answers = []; readings = []; savedChecks = [];
    stream?.close(); stream = null; terminal = false; checking = false;
    node('detection').hidden = true; node('detect-saved').disabled = true; node('detect-saved').hidden = true;
    node('download-detection').hidden = true;
    node('detection-history').replaceChildren();
    updateCancelControl();
  }
  function table(rows) {
    const result = document.createElement('table'), head = document.createElement('thead'), header = document.createElement('tr');
    for (const text of ['Source','Text range','Status','Score','Verdict','Duration','Tokens','Cost USD']) { const cell = document.createElement('th'); cell.textContent = text; header.append(cell); }
    head.append(header); result.append(head); const body = document.createElement('tbody');
    for (const row of rows) {
      const tr = document.createElement('tr');
      const range = row.reading_id ? `${row.reading_id.slice(0,8)} · ${row.start ?? 0}–${row.end ?? 'end'}` : row.signal;
      for (const text of [labels[row.signal] || row.signal,range,row.error || row.status,prettyScore(row.probability),verdicts[row.verdict] || 'Unclear',row.replayed ? 'Cached' : `${(row.latency_seconds || 0).toFixed(2)} s`,row.input_tokens ?? '—',row.estimated_usd == null ? '—' : row.estimated_usd.toFixed(6)]) {
        const cell = document.createElement('td'); cell.textContent = text; tr.append(cell);
      }
      body.append(tr);
    }
    result.append(body); return result;
  }
  function renderReadings() {
    node('detection-readings').replaceChildren();
    if (!readings.length) return;
    const detail = document.createElement('details');
    const title = document.createElement('summary'); title.textContent = 'Inspected OCR text';
    detail.append(title);
    for (const reading of readings) {
      const text = document.createElement('pre'); text.textContent = reading.text; detail.append(text);
    }
    node('detection-readings').append(detail);
  }
  function render(state) {
    node('detection').hidden = false;
    const result = state.result;
    window.dispatchEvent(new CustomEvent('vipi:detection-state',{detail:{state:state.state,completed:state.completed,total:state.total,verdict:result?.verdict}}));
    checking = !['completed','failed','cancelled'].includes(state.state);
    if (checking && state.cancel_requested) cancellationRequested = true;
    updateCancelControl();
    node('detection-status').textContent = state.state === 'cancelled' ? 'Detection cancelled. Completed answers are saved.' : state.cancel_requested && checking ? 'Stopping detection after the current operation …' : state.state === 'failed' ? `Interrupted: ${state.error}` : `${state.completed} / ${state.total} checks · ${state.state === 'completed' ? 'Complete' : state.state === 'queued' ? 'Waiting for OCR / scanner' : 'Running'}`;
    node('detection-verdict').textContent = result?.verdict === 'flagged' ? 'Suspicious content detected.' : 'Detector results';
    const scope = state.evidence_scope || result?.evidence_scope;
    node('detection-scope').textContent = scope === 'final_ocr' ? `Checking the final OCR text.${(state.signals || []).some(x => x === 'image' || x === 'context') ? ' Additional image checks are shown separately.' : ''}${result && !result.threshold_version ? ' Scores are shown without thresholds; no verdict is assigned.' : ''}` : state.state === 'queued' ? 'The check starts after OCR completes.' : 'Previous check: includes individual OCR variants. Start a new check to inspect the final text.';
    node('detection-note').textContent = `${state.context_available || result?.context_available ? 'User task provided.' : 'No application context provided.'} ${result?.threshold_version ? `Thresholds: ${result.threshold_version}.` : 'Without configured thresholds, no verdict is assigned.'} ${result?.missing_text_evidence ? 'No OCR text is available as evidence.' : ''} ${result?.comparison?.disagreements?.length ? `${result.comparison.disagreements.length} text regions have different verdicts.` : ''} Maximum scores are not calibrated image probabilities. Prompt Guard uses its native definition.`;
    node('detection-signals').replaceChildren();
    const signals = result?.signals || Object.fromEntries((state.signals || []).map(signal => {
      const rows = answers.filter(x => x.signal === signal && x.probability != null);
      return [signal,{max_score:rows.length ? Math.max(...rows.map(x => x.probability)) : null,checks:answers.filter(x => x.signal === signal).length,verdict:'unclear'}];
    }));
    for (const [signal, value] of Object.entries(signals)) {
      const card = document.createElement('div'); card.className = 'detection-signal';
      const title = document.createElement('span'); title.textContent = labels[signal];
      const score = document.createElement('strong'); score.textContent = prettyScore(value.max_score);
      const rows = answers.filter(x => x.signal === signal);
      const failures = rows.filter(x => x.status !== 'completed');
      const note = document.createElement('p'); note.className = 'muted';
      note.textContent = failures.length ? 'Check failed' : !rows.length ? 'Waiting for result' : value.verdict === 'flagged' ? 'Flagged' : value.verdict === 'not_flagged' ? 'No issues found' : 'Score available · verdict pending';
      const native = rows.find(x => x.native_label)?.native_label;
      if (native && value.verdict === 'unclear' && !failures.length) note.textContent = `Model class: ${native === 'MALICIOUS' ? 'Malicious' : 'Benign'} · threshold verdict pending`;
      card.dataset.verdict = failures.length ? 'error' : value.verdict;
      if (failures.length) score.textContent = '—';
      const stats = result?.comparison?.signals?.[signal];
      card.append(title,score,note);
      if (failures.length) {
        const message = document.createElement('p'); message.className = 'muted'; message.textContent = failures[0].error || failures[0].status; card.append(message);
      }
      if (stats) {
        const more = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Technical details';
        const cost = document.createElement('p'); cost.className = 'mono muted';
        cost.textContent = `${stats.checks} checks · ${stats.replayed} cached · ${stats.input_tokens} tokens · $${stats.estimated_usd.toFixed(6)}${stats.cost_incomplete ? ' (incomplete)' : ''}`;
        more.append(summary,cost); card.append(more);
      }
      node('detection-signals').append(card);
    }
    node('detection-answers').replaceChildren(table(answers)); renderReadings();
    node('detect-saved').disabled = !terminal || !optionsEnabled() || !['completed','failed','cancelled'].includes(state.state);
    if (result) {
      node('download-detection').hidden = false;
      node('download-detection').href = `/api/runs/${currentRun}/detections/${checkId}/result.json`;
    }
  }
  async function loadReadings(token) {
    const response = await fetch(`/api/runs/${currentRun}/detections/${checkId}/readings`), data = await response.json();
    if (token !== revision) return;
    readings = data.readings || []; renderReadings();
  }
  function restoreSettings(saved, scope) {
    if (!saved || settingsEdited) return;
    const selected = saved.text_classifiers ?? (saved.text_classifier === 'compare' ? ['jev','openai','prompt-guard'] : saved.text_classifier === 'off' ? [] : saved.text_classifier ? [saved.text_classifier] : []);
    for (const input of document.querySelectorAll('.text-classifier')) input.checked = selected.includes(input.value);
    node('image-check').value = scope === 'final_ocr' ? saved.image_check : 'off';
    node('context-check').value = scope === 'final_ocr' ? saved.context_check : 'off';
    node('detector-context').value = Object.keys(saved.context || {}).length ? JSON.stringify(saved.context,null,2) : '';
    const savedThresholds = saved.thresholds || {};
    node('detector-threshold-version').value = savedThresholds.version || '';
    for (const [signal,values] of Object.entries(savedThresholds.signals || {})) {
      const value = values.threshold ?? values.high;
      if (value !== undefined) thresholdValues.set(signal,Math.round(value * 1000) / 10);
    }
    node('detector-reuse').checked = saved.reuse !== false;
    updateThresholdRequirement();
  }
  async function observeCheck(id) {
    stream?.close(); const token = ++revision; checkId = id;
    node('detection-history').value = id; node('download-detection').hidden = true;
    const response = await fetch(`/api/runs/${currentRun}/detections/${id}`), state = await response.json();
    if (token !== revision) return;
    if (!response.ok) throw new Error(state.error);
    restoreSettings(state.options, state.evidence_scope || state.result?.evidence_scope);
    answers = state.answers || []; render(state); await loadReadings(token);
    if (token !== revision || ['completed','failed','cancelled'].includes(state.state)) return;
    stream = new EventSource(`/api/runs/${currentRun}/detections/${id}/events?after=${state.event_id}`);
    for (const name of ['detection_queued','detection_started','check_started','check_completed','detection_completed','detection_failed','detection_cancelled','cancellation_requested']) stream.addEventListener(name, async event => {
      if (token !== revision) return;
      const data = JSON.parse(event.data);
      if (name === 'check_completed') { answers.push(data.answer); render(data); }
      else if (name === 'detection_started') { render(data); await loadReadings(token); }
      else if (name === 'check_started') node('detection-status').textContent = data.cancel_requested ? 'Stopping detection …' : `${data.completed} / ${data.total} · ${labels[data.active_signal]} running …`;
      else if (name === 'cancellation_requested') render(data);
      else if (name === 'detection_completed' || name === 'detection_failed' || name === 'detection_cancelled') {
        stream?.close(); await observeCheck(id);
      }
    });
    stream.onerror = () => { if (token === revision) node('detection-status').textContent = 'Reconnecting to check …'; };
  }
  async function observeRun(id, finished, preferredCheck = null, refresh = false) {
    if (!id) return;
    terminal = finished; node('detect-saved').hidden = !finished; node('detect-saved').disabled = !finished || !optionsEnabled() || checking;
    const key = `${id}:${finished}:${preferredCheck || ''}`; if (observing === key && !refresh) return; observing = key;
    if (id !== currentRun) { reset(); currentRun = id; observing = key; terminal = finished; node('detect-saved').hidden = !finished; }
    const token = ++revision;
    try {
      const response = await fetch(`/api/runs/${id}/detections`), data = await response.json();
      if (token !== revision || !response.ok) return;
      savedChecks = data.checks || [];
      node('detection-history').replaceChildren(new Option('Select saved check', ''), ...savedChecks.map((x,index) => new Option(`Check ${index + 1} · ${x.case_index ? `Case ${x.case_index}` : x.evidence_scope === 'final_ocr' ? 'Final text' : 'Previous variant check'}`,x.check_id)));
      const latest = savedChecks.find(x => x.check_id === preferredCheck) || savedChecks.filter(x => x.evidence_scope === 'final_ocr').at(-1);
      if (latest) await observeCheck(latest.check_id);
      else if (savedChecks.length) {
        answers = []; readings = []; checking = false; checkId = null;
        render({state:'completed',completed:0,total:0,signals:[],evidence_scope:'final_ocr'});
        node('detection-verdict').textContent = 'Final text has not been checked yet.';
        node('detection-status').textContent = 'Choose a detector and select “Check recognized text”.';
        node('detection-scope').textContent = 'Previous variant checks are saved under Check details.';
      }
    } catch (failure) { error(failure.message); }
    node('detect-saved').disabled = !terminal || !optionsEnabled() || checking;
  }
  function optionsEnabled() { return document.querySelectorAll('.text-classifier:checked').length > 0 || ['image-check','context-check'].some(id => node(id).value !== 'off'); }
  node('detect-saved').onclick = async () => {
    try {
      const selected = options(); if (!selected || !runId) return;
      node('detect-saved').disabled = true;
      const response = await fetch(`/api/runs/${runId}/detections`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selected)}), data = await response.json();
      if (!response.ok) throw new Error(data.error);
      currentRun = runId; observing = null; await observeRun(runId,true);
    } catch (failure) { error(failure.message); }
    finally { node('detect-saved').disabled = !terminal || !optionsEnabled() || checking; }
  };
  node('detection-history').onchange = () => { const id = node('detection-history').value; if (id) observeCheck(id).catch(x => error(x.message)); };
  for (const control of [...document.querySelectorAll('.text-classifier'),node('image-check'),node('context-check')]) control.onchange = () => {
    settingsEdited = true;
    updateThresholdRequirement();
    node('detect-saved').hidden = !terminal; node('detect-saved').disabled = !terminal || !optionsEnabled() || checking; };
  for (const id of ['detector-context','detector-threshold-version','detector-reuse']) node(id).addEventListener('input', () => { settingsEdited = true; });
  node('threshold-controls').addEventListener('input', () => { settingsEdited = true; });
  function updateThresholdRequirement() {
    const selected = optionsEnabled();
    node('threshold-settings').hidden = !selected;
    node('detector-threshold-version').required = selected;
    renderThresholdControls();
    const contextRequired = node('context-check').value === 'openai' && node('dataset-mode-note').hidden;
    node('detector-context').required = contextRequired;
  }
  node('detector-context').oninput = () => { settingsEdited = true; };
  node('detector-threshold-version').oninput = () => { settingsEdited = true; };
  updateThresholdRequirement();
  window.vipiDetection = {options,reset,observeRun,isChecking:() => checking};
  fetch('/api/detectors').then(x => x.json()).then(data => {
    node('detector-availability').textContent = data.providers.map(x => `${x.label}: ${x.available ? 'ready' : x.reason}`).join(' · ');
  }).catch(() => { node('detector-availability').textContent = 'Could not load availability.'; });
})();
