/* Scanner controls and a separate replayable event stream. All evidence is textContent. */
(() => {
  const node = id => document.getElementById(id);
  const labels = {jev:'Jev',openai:'OpenAI Decisions','prompt-guard':'Prompt Guard 2',image:'Originalbild',context:'Bild + OCR + Kontext'};
  const verdicts = {flagged:'Verdächtig · Prüfung nötig',not_flagged:'Keine Auffälligkeit in den konfigurierten Prüfungen',unclear:'Offen · Prüfung nötig'};
  let currentRun, checkId, stream, answers = [], readings = [], revision = 0, terminal = false;
  let savedChecks = [], observing = null, checking = false, settingsEdited = false;
  const prettyScore = value => value == null ? '—' : value.toFixed(4);
  function options() {
    const text_classifier = node('text-classifier').value;
    const image_check = node('image-check').value, context_check = node('context-check').value;
    if ([text_classifier,image_check,context_check].every(x => x === 'off')) return null;
    let context = {}, thresholds = null;
    try {
      if (node('detector-context').value.trim()) context = JSON.parse(node('detector-context').value);
      if (!context || Array.isArray(context) || typeof context !== 'object') throw new Error('object');
      const task = node('detector-task').value.trim(); if (task) context.task = task;
      if (node('detector-thresholds').value.trim()) thresholds = JSON.parse(node('detector-thresholds').value);
    } catch { throw new Error('Kontext und Schwellenwerte müssen gültige JSON-Objekte sein.'); }
    return {text_classifier,image_check,context_check,context,thresholds,reuse:node('detector-reuse').checked};
  }
  function reset() {
    revision++; currentRun = checkId = observing = null; answers = []; readings = []; savedChecks = [];
    stream?.close(); stream = null; terminal = false; checking = false;
    node('detection').hidden = true; node('detect-saved').disabled = true; node('detect-saved').hidden = true;
    node('download-detection').hidden = true;
    node('detection-history').replaceChildren();
  }
  function table(rows) {
    const result = document.createElement('table'), head = document.createElement('thead'), header = document.createElement('tr');
    for (const text of ['Quelle','Textbereich','Status','Score','Urteil','Dauer','Tokens','Kosten USD']) { const cell = document.createElement('th'); cell.textContent = text; header.append(cell); }
    head.append(header); result.append(head); const body = document.createElement('tbody');
    for (const row of rows) {
      const tr = document.createElement('tr');
      const range = row.reading_id ? `${row.reading_id.slice(0,8)} · ${row.start ?? 0}–${row.end ?? 'Ende'}` : row.signal;
      for (const text of [labels[row.signal] || row.signal,range,row.error || row.status,prettyScore(row.probability),verdicts[row.verdict] || 'Offen',row.replayed ? 'Gespeichert' : `${(row.latency_seconds || 0).toFixed(2)} s`,row.input_tokens ?? '—',row.estimated_usd == null ? '—' : row.estimated_usd.toFixed(6)]) {
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
    const title = document.createElement('summary'); title.textContent = 'Geprüfter OCR-Text';
    detail.append(title);
    for (const reading of readings) {
      const text = document.createElement('pre'); text.textContent = reading.text; detail.append(text);
    }
    node('detection-readings').append(detail);
  }
  function render(state) {
    node('detection').hidden = false;
    const result = state.result;
    checking = !['completed','failed'].includes(state.state);
    node('detection-status').textContent = state.state === 'failed' ? `Unterbrochen: ${state.error}` : `${state.completed} / ${state.total} Prüfungen · ${state.state === 'completed' ? 'Abgeschlossen' : state.state === 'queued' ? 'Wartet auf OCR / Scanner' : 'Läuft'}`;
    node('detection-verdict').textContent = result?.verdict === 'flagged' ? 'Verdächtiger Inhalt erkannt.' : 'Detektor-Ergebnisse';
    const scope = state.evidence_scope || result?.evidence_scope;
    node('detection-scope').textContent = scope === 'final_ocr' ? `Geprüft wird der finale OCR-Text.${(state.signals || []).some(x => x === 'image' || x === 'context') ? ' Zusätzliche Bildprüfungen erscheinen separat.' : ''}${result && !result.threshold_version ? ' Ohne Schwellenwerte zeigen wir Scores; das Urteil bleibt offen.' : ''}` : state.state === 'queued' ? 'Die Prüfung startet nach dem OCR-Ergebnis.' : 'Frühere Prüfung: enthält auch einzelne OCR-Varianten. Starte eine neue Prüfung für den finalen Text.';
    node('detection-note').textContent = `${state.context_available || result?.context_available ? 'Nutzerauftrag vorhanden.' : 'Kein Anwendungskontext angegeben.'} ${result?.threshold_version ? `Schwellenwerte: ${result.threshold_version}.` : 'Ohne konfigurierte Schwellenwerte bleibt das Urteil offen.'} ${result?.missing_text_evidence ? 'Keine OCR-Texte als Beleg verfügbar.' : ''} ${result?.comparison?.disagreements?.length ? `${result.comparison.disagreements.length} Textbereiche mit unterschiedlichen Urteilen.` : ''} Maximalwerte sind keine kalibrierten Bildwahrscheinlichkeiten. Prompt Guard nutzt seine native Definition.`;
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
      note.textContent = failures.length ? 'Prüfung fehlgeschlagen' : !rows.length ? 'Wartet auf Ergebnis' : value.verdict === 'flagged' ? 'Verdächtig' : value.verdict === 'not_flagged' ? 'Keine Auffälligkeit' : 'Score verfügbar · Bewertung offen';
      const native = rows.find(x => x.native_label)?.native_label;
      if (native && value.verdict === 'unclear' && !failures.length) note.textContent = `Modellklasse: ${native === 'MALICIOUS' ? 'Verdächtig' : 'Unauffällig'} · Schwellenwerturteil offen`;
      card.dataset.verdict = failures.length ? 'error' : value.verdict;
      if (failures.length) score.textContent = '—';
      const stats = result?.comparison?.signals?.[signal];
      card.append(title,score,note);
      if (failures.length) {
        const message = document.createElement('p'); message.className = 'muted'; message.textContent = failures[0].error || failures[0].status; card.append(message);
      }
      if (stats) {
        const more = document.createElement('details'); const summary = document.createElement('summary'); summary.textContent = 'Technische Details';
        const cost = document.createElement('p'); cost.className = 'mono muted';
        cost.textContent = `${stats.checks} Prüfschritte · ${stats.replayed} gespeichert · ${stats.input_tokens} Tokens · $${stats.estimated_usd.toFixed(6)}${stats.cost_incomplete ? ' (unvollständig)' : ''}`;
        more.append(summary,cost); card.append(more);
      }
      node('detection-signals').append(card);
    }
    node('detection-answers').replaceChildren(table(answers)); renderReadings();
    node('detect-saved').disabled = !terminal || !optionsEnabled() || !['completed','failed'].includes(state.state);
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
    node('text-classifier').value = saved.text_classifier;
    node('image-check').value = scope === 'final_ocr' ? saved.image_check : 'off';
    node('context-check').value = scope === 'final_ocr' ? saved.context_check : 'off';
    const {task = '', ...context} = saved.context || {};
    node('detector-task').value = task;
    node('detector-context').value = Object.keys(context).length ? JSON.stringify(context,null,2) : '';
    node('detector-thresholds').value = Object.keys(saved.thresholds || {}).length ? JSON.stringify(saved.thresholds,null,2) : '';
    node('detector-reuse').checked = saved.reuse !== false;
    node('context-note').textContent = task ? 'Nutzerauftrag wird separat als Kontext übergeben.' : 'Kein Nutzerauftrag angegeben · Kontext unbekannt.';
  }
  async function observeCheck(id) {
    stream?.close(); const token = ++revision; checkId = id;
    node('detection-history').value = id; node('download-detection').hidden = true;
    const response = await fetch(`/api/runs/${currentRun}/detections/${id}`), state = await response.json();
    if (token !== revision) return;
    if (!response.ok) throw new Error(state.error);
    restoreSettings(state.options, state.evidence_scope || state.result?.evidence_scope);
    answers = state.answers || []; render(state); await loadReadings(token);
    if (token !== revision || ['completed','failed'].includes(state.state)) return;
    stream = new EventSource(`/api/runs/${currentRun}/detections/${id}/events?after=${state.event_id}`);
    for (const name of ['detection_queued','detection_started','check_started','check_completed','detection_completed','detection_failed']) stream.addEventListener(name, async event => {
      if (token !== revision) return;
      const data = JSON.parse(event.data);
      if (name === 'check_completed') { answers.push(data.answer); render(data); }
      else if (name === 'detection_started') { render(data); await loadReadings(token); }
      else if (name === 'check_started') node('detection-status').textContent = `${data.completed} / ${data.total} · ${labels[data.active_signal]} läuft …`;
      else if (name === 'detection_completed' || name === 'detection_failed') {
        stream?.close(); await observeCheck(id);
      }
    });
    stream.onerror = () => { if (token === revision) node('detection-status').textContent = 'Verbindung zur Prüfung wird wiederhergestellt …'; };
  }
  async function observeRun(id, finished) {
    if (!id) return;
    terminal = finished; node('detect-saved').hidden = !finished; node('detect-saved').disabled = !finished || !optionsEnabled() || checking;
    const key = `${id}:${finished}`; if (observing === key) return; observing = key;
    if (id !== currentRun) { reset(); currentRun = id; observing = key; terminal = finished; node('detect-saved').hidden = !finished; }
    const token = revision;
    try {
      const response = await fetch(`/api/runs/${id}/detections`), data = await response.json();
      if (token !== revision || !response.ok) return;
      savedChecks = data.checks || [];
      node('detection-history').replaceChildren(new Option('Gespeicherte Prüfung auswählen', ''), ...savedChecks.map((x,index) => new Option(`Prüfung ${index + 1} · ${x.evidence_scope === 'final_ocr' ? 'Finaler Text' : 'Alte Variantenprüfung'}`,x.check_id)));
      const latest = savedChecks.filter(x => x.evidence_scope === 'final_ocr').at(-1);
      if (latest) await observeCheck(latest.check_id);
      else if (savedChecks.length) {
        answers = []; readings = []; checking = false; checkId = null;
        render({state:'completed',completed:0,total:0,signals:[],evidence_scope:'final_ocr'});
        node('detection-verdict').textContent = 'Finaler Text noch nicht geprüft.';
        node('detection-status').textContent = 'Detektor wählen und „Erkannten Text prüfen“ starten.';
        node('detection-scope').textContent = 'Frühere Variantenprüfungen sind unter den Prüfdetails gespeichert.';
      }
    } catch (failure) { error(failure.message); }
    node('detect-saved').disabled = !terminal || !optionsEnabled() || checking;
  }
  function optionsEnabled() { return ['text-classifier','image-check','context-check'].some(id => node(id).value !== 'off'); }
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
  for (const id of ['text-classifier','image-check','context-check']) node(id).onchange = () => {
    settingsEdited = true;
    node('detect-saved').hidden = !terminal; node('detect-saved').disabled = !terminal || !optionsEnabled() || checking; };
  for (const id of ['detector-context','detector-thresholds','detector-reuse']) node(id).addEventListener('input', () => { settingsEdited = true; });
  node('detector-task').oninput = () => { settingsEdited = true; node('context-note').textContent = node('detector-task').value.trim() ? 'Nutzerauftrag wird separat als Kontext übergeben.' : 'Kein Nutzerauftrag angegeben · Kontext unbekannt.'; };
  window.vipiDetection = {options,reset,observeRun};
  fetch('/api/detectors').then(x => x.json()).then(data => {
    node('detector-availability').textContent = data.providers.map(x => `${x.label}: ${x.available ? 'bereit' : x.reason}`).join(' · ');
  }).catch(() => { node('detector-availability').textContent = 'Verfügbarkeit konnte nicht geladen werden.'; });
})();
