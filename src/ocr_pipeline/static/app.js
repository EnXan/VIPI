const $ = (id) => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const states = {queued:'Start wird vorbereitet …',preparing:'OCR-Modell wird geladen …',processing:'Varianten werden parallel verarbeitet …',transforming:'Bild wird angepasst …',ocr:'Text wird erkannt …',saving:'Ergebnis wird gespeichert …',assembling:'Texte werden zusammengesetzt …',evaluating:'Referenztext wird geprüft …',completed:'Alle Schritte abgeschlossen.',failed:'Pipeline unterbrochen.'};
let selectedFile, source, runId, total = 0, completed = 0, latestStep, displayedStep;
let running = false, followLive = true, filePreview, lastEvent = 0, currentState = 'queued';
const steps = new Map();
const workerStates = new Map();
let workerCount = 4, selectedWorker = null;
const selectedDatasets = new Set();
const datasetLabels = new Map();
let catalogPage, catalogOffset = 0, catalogRequest = 0, searchTimer;
let batchId, batchRunning = false, batchTimer, batchSnapshot;
let currentEvaluation;
let previewDatasetId;

function error(message) { $('error').textContent = message; $('error').hidden = !message; }
function busy(value) {
  running = value || batchRunning;
  $('start').disabled = running || (!selectedFile && !selectedDatasets.size) || !$('model').value;
  $('start').textContent = selectedDatasets.size ? `Auswahl ausführen (${selectedDatasets.size}) ↗` : 'Text extrahieren ↗';
  for (const id of ['model','backend','workers','image-input','dataset-category','dataset-search','select-matching','clear-selection']) $(id).disabled = running;
  for (const input of document.querySelectorAll('.dataset-card input')) input.disabled = running;
  $('dataset-prev').disabled = running || !catalogOffset;
  $('dataset-next').disabled = running || !catalogPage || catalogOffset + catalogPage.limit >= catalogPage.total;
}
function renderWorkers() {
  $('worker-status').replaceChildren();
  const labels = {preparing:'Modell laden',transforming:'Bild anpassen',ocr:'OCR',saving:'Speichern',idle:'Bereit',completed:'Abgeschlossen',failed:'Angehalten'};
  for (let id = 1; id <= workerCount; id++) {
    const entry = workerStates.get(id) || {state:'idle'};
    const button = document.createElement('button'); button.type = 'button'; button.className = 'worker-card';
    button.disabled = !entry.step?.image_url; button.setAttribute('aria-pressed', String(selectedWorker === id));
    const title = document.createElement('span'); title.textContent = `Worker ${id} · ${labels[entry.state] || entry.state}`;
    const label = document.createElement('span'); label.className = 'muted'; label.textContent = entry.step?.label || '—';
    button.append(title, label);
    button.onclick = () => { selectedWorker = id; followLive = true; showStep(entry.step); renderWorkers(); };
    $('worker-status').append(button);
  }
}
function updateWorker(data, state) {
  const id = data.worker_id || data.step?.worker_id || 1;
  workerStates.set(id, {state,step:data.step}); renderWorkers();
}
function workerProgress(state) { progress(workerCount > 1 ? 'processing' : state); }
function follows(data) { return followLive && (selectedWorker === null || selectedWorker === (data.worker_id || data.step?.worker_id || 1)); }
function progress(state) {
  currentState = state;
  $('status').textContent = states[state] || state;
  $('counter').textContent = total ? `${completed} / ${total}` : '';
  $('progress').max = total || 1; $('progress').value = completed;
}
function svgNode(tag, attributes = {}) {
  const node = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}
function drawBoxes(svg, step, animate = false) {
  svg.replaceChildren(); svg.setAttribute('viewBox', `0 0 ${step.width} ${step.height}`);
  for (const [index, region] of (step.regions || []).entries()) {
    const group = svgNode('g', {class:'box-group'});
    const points = region.polygon.map(point => point.join(',')).join(' ');
    for (const shadow of [true, false]) {
      const polygon = svgNode('polygon', {points, class:`text-box ${shadow ? 'shadow' : ''} ${animate ? 'reveal' : ''}`});
      if (animate) polygon.style.animationDelay = `${Math.min(index * 16, 220)}ms`;
      group.append(polygon);
    }
    const title = svgNode('title'); title.textContent = region.text; group.append(title);
    const [x, y] = region.polygon[0];
    const label = svgNode('text', {x, y:Math.max(14, y - 5), class:'text-label', 'font-size':Math.max(12, step.width / 65)});
    label.textContent = region.text; group.append(label); svg.append(group);
  }
}
function showStep(step, animate = false) {
  displayedStep = step;
  $('workspace').hidden = false; $('step-label').textContent = step.label || 'Original';
  $('dimensions').textContent = `${step.width} × ${step.height}`;
  $('canvas').style.width = `${Math.min(760, 480 * step.width / step.height)}px`;
  // Image and overlay share one aspect ratio, including small and rotated views.
  $('canvas').style.aspectRatio = `${step.width} / ${step.height}`;
  if ($('preview').getAttribute('src') !== step.image_url) {
    $('boxes').replaceChildren(); $('preview').style.visibility = 'hidden'; $('boxes').style.visibility = 'hidden';
    $('preview').onload = () => { $('preview').style.visibility = 'visible'; $('boxes').style.visibility = 'visible'; };
    $('preview').src = step.image_url;
  }
  drawBoxes($('boxes'), step, animate);
  $('boxes').toggleAttribute('hidden', !$('show-boxes').checked);
  $('step-text').textContent = step.text === undefined ? 'OCR läuft …' : step.text || 'Kein Text erkannt.';
  $('live').hidden = followLive && selectedWorker === null;
  for (const card of $('variants').children) card.classList.toggle('selected', card.dataset.step === step.id);
}
function addVariant(step) {
  steps.set(step.id, step); $('history').hidden = false;
  let card = $('variants').querySelector(`[data-step="${step.id}"]`);
  if (card) return;
  card = document.createElement('button'); card.type = 'button'; card.className = 'variant'; card.dataset.step = step.id; card.dataset.index = step.index;
  card.setAttribute('aria-label', `Schritt ${step.index}: ${step.label}`);
  const thumb = document.createElement('div'); thumb.className = 'thumb';
  const canvas = document.createElement('div'); canvas.className = 'canvas'; canvas.style.width = `${Math.min(360, 136 * step.width / step.height)}px`;
  const image = document.createElement('img'); image.src = step.image_url; image.alt = step.label; image.loading = 'lazy'; image.width = step.width; image.height = step.height;
  const overlay = svgNode('svg'); drawBoxes(overlay, step);
  canvas.append(image, overlay); thumb.append(canvas);
  const label = document.createElement('span'); label.className = 'label'; label.textContent = `${step.index.toString().padStart(3,'0')} · ${step.label}`;
  const text = document.createElement('pre'); text.textContent = step.text || 'Kein Text erkannt.';
  card.append(thumb, label, text); card.onclick = () => { followLive = false; showStep(steps.get(step.id)); $('workspace').scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'}); };
  const next = [...$('variants').children].find(item => Number(item.dataset.index) > step.index);
  $('variants').insertBefore(card, next || null); $('variant-count').textContent = `${steps.size} Varianten`;
}
function finish(text, regions = [], evaluation = null) {
  busy(false); progress('completed'); $('final').hidden = false;
  for (const [id, entry] of workerStates) workerStates.set(id, {...entry,state:'completed'});
  renderWorkers();
  $('final-text').textContent = text || 'Kein Text erkannt.';
  $('alternative-list').replaceChildren();
  let alternatives = 0;
  for (const region of regions) {
    if (!region.alternatives?.length) continue;
    const group = document.createElement('div'); group.className = 'reading-group';
    const primary = document.createElement('p'); primary.textContent = region.text;
    group.append(primary);
    const list = document.createElement('ul');
    for (const reading of region.alternatives) {
      const item = document.createElement('li'); item.textContent = reading.text;
      const support = document.createElement('span'); support.className = 'mono muted'; support.textContent = ` · ${reading.support} Ansicht${reading.support === 1 ? '' : 'en'}`;
      item.append(support); list.append(item); alternatives++;
    }
    group.append(list); $('alternative-list').append(group);
  }
  $('alternative-readings').hidden = !alternatives;
  $('alternative-summary').textContent = `${alternatives} abweichende Lesarten`;
  $('download-txt').href = `/api/runs/${runId}/result.txt`; $('download-json').href = `/api/runs/${runId}/result.json`;
  renderEvaluation(evaluation);
  if (source) source.close();
}
function handle(event) {
  const data = JSON.parse(event.data);
  if (data.run_id !== runId) return;
  if (data.id <= lastEvent) return;
  lastEvent = data.id;
  switch (data.type) {
    case 'run_started':
      total = data.total; workerCount = data.workers || 1;
      workerStates.clear(); for (let id = 1; id <= workerCount; id++) workerStates.set(id, {state:'preparing'});
      renderWorkers(); progress('preparing'); break;
    case 'step_started': latestStep = data.step; updateWorker(data, 'transforming'); workerProgress('transforming'); break;
    case 'image_ready': latestStep = data.step; updateWorker(data, 'transforming'); if (follows(data)) showStep(data.step); break;
    case 'ocr_started': updateWorker(data, 'ocr'); workerProgress('ocr'); break;
    case 'saving': updateWorker(data, 'saving'); workerProgress('saving'); break;
    case 'step_completed':
      latestStep = data.step; completed = data.completed; addVariant(data.step);
      updateWorker(data, 'idle'); if (follows(data)) showStep(data.step, true); workerProgress('saving'); break;
    case 'assembling': progress('assembling'); break;
    case 'evaluating': progress('evaluating'); break;
    case 'run_completed': finish(data.text, data.regions, data.evaluation); break;
    case 'run_failed':
      for (const [id, entry] of workerStates) workerStates.set(id, {...entry,state:'failed'});
      renderWorkers(); busy(false); progress('failed'); error(data.error); source.close(); break;
  }
}
async function restore(id, connect = true) {
  const response = await fetch(`/api/runs/${id}`);
  if (!response.ok) throw new Error('Der gespeicherte Lauf konnte nicht geladen werden.');
  const state = await response.json(); runId = id; total = state.total; completed = state.completed;
  $('model').value = state.model;
  $('backend').value = state.backend || 'cpu'; updateBackend();
  workerCount = state.workers || 1;
  if (state.workers) $('workers').value = state.workers;
  workerStates.clear();
  for (const step of state.variants) workerStates.set(step.worker_id || 1, {state:'idle',step});
  for (const [id, entry] of Object.entries(state.active_steps || {})) workerStates.set(Number(id), entry);
  renderWorkers();
  for (const step of state.variants) addVariant(step);
  latestStep = state.current || state.variants.at(-1); if (latestStep?.image_url && followLive) showStep(latestStep);
  lastEvent = state.event_id; progress(state.state);
  if (state.state === 'completed') finish(state.result.text, state.result.regions, state.result.evaluation);
  else if (state.state === 'failed') {
    for (const [id, entry] of workerStates) workerStates.set(id, {...entry,state:'failed'});
    renderWorkers(); busy(false); error(state.error); if (source) source.close();
  }
  else if (connect) { busy(true); subscribe(); }
}
function subscribe() {
  if (source) source.close();
  source = new EventSource(`/api/runs/${runId}/events?after=${lastEvent}`);
  for (const name of ['run_started','step_started','image_ready','ocr_started','saving','step_completed','assembling','evaluating','run_completed','run_failed']) source.addEventListener(name, handle);
  source.onopen = () => { if (running && $('status').textContent.startsWith('Verbindung')) progress(currentState); };
  source.onerror = () => { if (running) $('status').textContent = 'Verbindung wird wiederhergestellt …'; };
}
function selectFile(file) {
  if (running || !file) return;
  if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { error('Bitte PNG, JPEG oder WebP verwenden.'); return; }
  selectedDatasets.clear(); refreshSelection();
  selectedFile = file; error(''); $('file-label').textContent = file.name || 'Eingefügtes Bild';
  if (filePreview) URL.revokeObjectURL(filePreview); filePreview = URL.createObjectURL(file);
  const image = new Image(); image.onload = () => {
    followLive = true; showStep({width:image.width,height:image.height,label:'Original · Vorschau',image_url:filePreview,text:'Bereit für die Pipeline.'}); progress('Bereit');
  }; image.src = filePreview; busy(false);
}
$('image-input').onchange = () => selectFile($('image-input').files[0]);
$('dropzone').onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); if (!running) $('image-input').click(); } };
for (const name of ['dragenter','dragover']) $('dropzone').addEventListener(name, event => {event.preventDefault(); $('dropzone').classList.add('dragover');});
for (const name of ['dragleave','drop']) $('dropzone').addEventListener(name, event => {event.preventDefault(); $('dropzone').classList.remove('dragover');});
$('dropzone').addEventListener('drop', event => selectFile(event.dataTransfer.files[0]));
document.addEventListener('paste', event => { const item = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith('image/')); if (item) { event.preventDefault(); selectFile(item.getAsFile()); } });
function updateBackend() {
  for (const option of $('backend').options) {
    option.disabled = option.dataset.available !== 'true' || (option.value !== 'cpu' && $('model').value === 'tesseract');
  }
  if ($('model').value === 'tesseract') $('backend').value = 'cpu';
  $('backend-note').textContent = $('backend').value === 'coreml'
    ? 'Apple wählt CPU, GPU oder Neural Engine. Tempo und Erkennung können abweichen; nicht alle Operationen werden beschleunigt.'
    : $('backend').value === 'cuda'
      ? 'OCR läuft auf der NVIDIA-GPU. Zunächst 1–2 Worker wählen; jeder Worker benötigt eigenen GPU-Speicher.'
      : 'CPU-Threads werden auf die Worker verteilt.';
}
$('model').onchange = () => { updateBackend(); busy(running); };
$('backend').onchange = updateBackend;
$('show-boxes').onchange = () => { $('boxes').toggleAttribute('hidden', !$('show-boxes').checked); };
$('live').onclick = () => { followLive = true; selectedWorker = null; renderWorkers(); if (latestStep?.image_url) showStep(latestStep); };
async function copy(button, text) {
  try { await navigator.clipboard.writeText(text || ''); button.textContent = 'Kopiert'; setTimeout(() => button.textContent = 'Kopieren', 1500); }
  catch { error('Kopieren nicht verfügbar. Den Text auswählen und manuell kopieren.'); }
}
$('copy-step').onclick = () => copy($('copy-step'), displayedStep?.text);
$('copy-final').onclick = () => copy($('copy-final'), $('final-text').textContent);
$('upload-form').onsubmit = async event => {
  event.preventDefault(); if (running || (!selectedFile && !selectedDatasets.size)) return;
  if (selectedDatasets.size) { await startSelection(); return; }
  batchId = null; batchSnapshot = null; $('batch-report').hidden = $('category-summary').hidden = true;
  error(''); busy(true); followLive = true; completed = total = lastEvent = 0; latestStep = null;
  selectedWorker = null; workerCount = Number($('workers').value); workerStates.clear(); renderWorkers();
  steps.clear(); $('variants').replaceChildren(); $('history').hidden = $('final').hidden = true;
  renderEvaluation(null);
  progress('queued'); if (source) source.close();
  const body = new FormData(); body.append('image', selectedFile, selectedFile.name || 'clipboard.png'); body.append('model', $('model').value);
  body.append('workers', $('workers').value);
  body.append('backend', $('backend').value);
  try {
    const response = await fetch('/api/runs', {method:'POST',body}); const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Die Pipeline konnte nicht starten.');
    runId = data.run_id; history.replaceState(null, '', `/?run=${runId}`); subscribe();
  } catch (failure) { error(failure.message); busy(false); progress('Start fehlgeschlagen.'); }
};
async function initialize() {
  try {
    const response = await fetch('/api/models'); const data = await response.json();
    for (const model of data.models) {
      const option = new Option(model.label + (model.available ? '' : ' · nicht vorbereitet'), model.id);
      option.disabled = !model.available; option.title = model.reason || ''; $('model').append(option);
    }
    const chosen = data.models.find(model => model.id === data.default && model.available) || data.models.find(model => model.available);
    $('model').value = chosen?.id || ''; if (!chosen) error('Modelle fehlen. Im Terminal: vipi-ocr prepare-models');
    for (const backend of data.backends) {
      const option = new Option(backend.label + (backend.available ? '' : ' · nicht verfügbar'),backend.id);
      option.dataset.available = String(backend.available); option.disabled = !backend.available; $('backend').append(option);
    }
    $('backend').value = data.default_backend; updateBackend();
    await loadCatalog();
    const params = new URLSearchParams(location.search);
    if (params.get('batch')) await observeBatch(params.get('batch'), params.get('run'));
    else if (params.get('run')) await restore(params.get('run'));
  } catch (failure) { error(failure.message); }
}

function cell(row, text, tag = 'td') { const node = document.createElement(tag); node.textContent = text; row.append(node); return node; }
function table(headers) {
  const element = document.createElement('table'), head = document.createElement('thead'), row = document.createElement('tr');
  for (const header of headers) cell(row, header, 'th'); head.append(row);
  const body = document.createElement('tbody'); element.append(head, body); return {element,body};
}
function renderEffects(container, effects) {
  container.replaceChildren();
  const {element,body} = table(['Effekt','Besser','Gleich','Schlechter','Neu gültig','Ø Δ']);
  for (const effect of effects) {
    if (!effect.comparisons) continue;
    const row = document.createElement('tr'), delta = 100 * effect.delta_sum / effect.comparisons;
    for (const value of [effect.label,effect.improved,effect.unchanged,effect.worse,effect.recovered,`${delta > 0 ? '+' : ''}${delta.toFixed(1)} pp`]) cell(row, value);
    body.append(row);
  }
  if (body.children.length) container.append(element);
}
function inspectStep(id) {
  const step = steps.get(id); if (!step) return;
  followLive = false; showStep(step); $('workspace').scrollIntoView({block:'start',behavior:'instant'});
}
function renderEvaluation(evaluation) {
  currentEvaluation = evaluation; $('evaluation').hidden = !evaluation;
  for (const card of $('variants').children) {
    card.querySelector('.step-score')?.remove();
    const score = evaluation?.steps[card.dataset.step]; if (!score) continue;
    const label = document.createElement('span'); label.className = 'step-score';
    label.textContent = `${score.valid ? 'Gültig' : 'Unvollständig'} · ${(score.coverage * 100).toFixed(1)} % Referenz`;
    card.querySelector('.label').after(label);
  }
  if (!evaluation) return;
  $('evaluation-heading').textContent = evaluation.valid ? 'Referenztext erkannt.' : 'Referenztext unvollständig.';
  $('evaluation-rule').textContent = `Zusätzlicher Text ist erlaubt. Groß-/Kleinschreibung und Leerraum werden ignoriert; Schreibfehler zählen als fehlend. ${evaluation.method === 'word_regions' ? 'TextOCR: Wortregionen ohne feste Lesereihenfolge; Erkennungen aus Varianten dürfen sich ergänzen.' : 'Der vollständige Referenztext muss in einer Variante oder im finalen Text enthalten sein.'} Annotation: ${evaluation.reference.quality}.`;
  $('evaluation-scores').replaceChildren();
  for (const [name,score] of [['Original',evaluation.original],['Pipeline',evaluation.detection],['Finaler Text',evaluation.final]]) {
    const panel = document.createElement('div'); panel.className = 'evaluation-score';
    const title = document.createElement('span'); title.textContent = name;
    const value = document.createElement('strong'); value.textContent = `${(score.coverage * 100).toFixed(1)} %`;
    const state = document.createElement('span'); state.textContent = score.valid ? 'Gültig' : 'Unvollständig';
    panel.append(title,value,state); $('evaluation-scores').append(panel);
  }
  $('evaluation-missing').textContent = evaluation.detection.missing.length ? `Fehlend: ${evaluation.detection.missing.join(' ')}` : `${evaluation.valid_step_ids.length} Varianten erfassen die gesamte Referenz.`;
  $('reference-text').textContent = evaluation.reference.text;
  renderEffects($('evaluation-effects'), evaluation.effects);
  const {element,body} = table(['Ansicht','Unverändert','Graustufen','CLAHE','Invertiert','Threshold']);
  const views = new Map();
  for (const step of [...steps.values()].sort((a,b) => a.index - b.index)) {
    if (!views.has(step.view_id)) views.set(step.view_id, {}); views.get(step.view_id)[step.filter] = step;
  }
  for (const [name,filters] of views) {
    const row = document.createElement('tr'); cell(row, name);
    for (const filter of ['unchanged','grayscale','clahe','inverted','threshold']) {
      const step = filters[filter], score = evaluation.steps[step.id], td = cell(row, '');
      const button = document.createElement('button'); button.type = 'button'; button.className = 'table-link';
      button.textContent = `${(score.coverage * 100).toFixed(1)} %${score.valid ? ' ✓' : ''}`; button.title = step.label;
      button.onclick = () => inspectStep(step.id); td.append(button);
    }
    body.append(row);
  }
  $('evaluation-matrix').replaceChildren(element);
}
$('best-variant').onclick = () => { if (currentEvaluation) inspectStep(currentEvaluation.best_step_id); };

function refreshSelection() {
  for (const input of document.querySelectorAll('.dataset-card input')) input.checked = selectedDatasets.has(input.value);
  $('dataset-selected').textContent = `${selectedDatasets.size} Bild${selectedDatasets.size === 1 ? '' : 'er'} ausgewählt`;
  if (selectedDatasets.size) $('file-label').textContent = `${selectedDatasets.size} Datensatzbild${selectedDatasets.size === 1 ? '' : 'er'} ausgewählt`;
  else $('file-label').textContent = selectedFile?.name || 'Bild wählen, hierher ziehen oder einfügen';
  busy(running);
}
function selectDataset(item) {
  selectedFile = null;
  followLive = true; selectedWorker = null;
  previewDatasetId = item.id;
  const preview = new Image(); preview.onload = () => {
    if (previewDatasetId !== item.id || !selectedDatasets.has(item.id) || running) return;
    showStep({width:preview.width,height:preview.height,label:`Datensatz · ${item.name}`,image_url:item.thumbnail_url,text:'Bereit für die Pipeline. Der Referenztext wird erst nach OCR zur Auswertung verwendet.'});
  }; preview.src = item.thumbnail_url;
  refreshSelection();
}
async function loadCatalog() {
  const request = ++catalogRequest;
  const params = new URLSearchParams({category:$('dataset-category').value,q:$('dataset-search').value,offset:catalogOffset});
  try {
    const response = await fetch(`/api/datasets?${params}`), data = await response.json();
    if (request !== catalogRequest) return;
    if (!response.ok) throw new Error(data.error);
    catalogPage = data; $('catalog-error').hidden = true; $('catalog-count').textContent = `· ${data.catalog_total} Bilder`;
    for (const category of data.categories) datasetLabels.set(category.id, category.label);
    if ($('dataset-category').options.length === 1) for (const category of data.categories) $('dataset-category').append(new Option(`${category.label} (${category.count})`,category.id));
    $('dataset-count').textContent = data.total ? `${catalogOffset + 1}–${Math.min(catalogOffset + data.limit,data.total)} von ${data.total} Treffern` : 'Keine Treffer';
    $('dataset-images').replaceChildren();
    for (const item of data.items) {
      const card = document.createElement('label'); card.className = 'dataset-card';
      const image = document.createElement('img'); image.src = item.thumbnail_url; image.alt = `${item.label} · ${item.name}`; image.loading = 'lazy';
      const label = document.createElement('span'); label.className = 'dataset-label';
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = item.id; input.checked = selectedDatasets.has(item.id); input.setAttribute('aria-label', `${item.label}: ${item.name}`);
      input.onchange = () => { if (input.checked) { selectedDatasets.add(item.id); selectDataset(item); } else { selectedDatasets.delete(item.id); refreshSelection(); } };
      const name = document.createElement('span'); name.textContent = `${item.label} · ${item.name}`; label.append(input,name);
      const reference = document.createElement('p'); reference.className = 'dataset-reference'; reference.textContent = item.text_preview;
      card.append(image,label,reference); $('dataset-images').append(card);
    }
    refreshSelection();
  } catch (failure) { if (request === catalogRequest) { $('catalog-error').hidden = false; $('catalog-error').textContent = `Datensatzauswahl nicht verfügbar: ${failure.message}`; } }
}
$('dataset-category').onchange = () => { catalogOffset = 0; loadCatalog(); };
$('dataset-search').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { catalogOffset = 0; loadCatalog(); },250); };
$('dataset-prev').onclick = () => { catalogOffset = Math.max(0,catalogOffset - catalogPage.limit); loadCatalog(); };
$('dataset-next').onclick = () => { catalogOffset += catalogPage.limit; loadCatalog(); };
$('select-matching').onclick = () => { if (!catalogPage) return; for (const id of catalogPage.matching_ids) selectedDatasets.add(id); selectedFile = null; if (catalogPage.items[0]) selectDataset(catalogPage.items[0]); else refreshSelection(); };
$('clear-selection').onclick = () => { selectedDatasets.clear(); refreshSelection(); };

function clearRun() {
  if (source) source.close(); source = null;
  steps.clear(); workerStates.clear(); completed = total = lastEvent = 0; latestStep = displayedStep = null;
  followLive = true; selectedWorker = null; $('variants').replaceChildren(); $('worker-status').replaceChildren();
  $('history').hidden = $('final').hidden = $('workspace').hidden = true; renderEvaluation(null); error('');
}
function renderBatch(data) {
  batchSnapshot = data; $('batch-report').hidden = false;
  $('batch-heading').textContent = data.state === 'completed' ? 'Die Auswertung.' : data.state === 'failed' ? 'Lauf unterbrochen.' : 'Bilder werden geprüft.';
  $('batch-progress').textContent = `${data.completed} / ${data.total} Bilder · ${data.summary.valid} gültig · ${data.summary.invalid} unvollständig · ${data.summary.errors} fehlgeschlagen · ${data.summary.pending} offen`;
  $('download-report').href = `/api/batches/${data.batch_id}/report.json`;
  renderEffects($('batch-effects'), data.summary.effects);
  const selectedCategory = $('report-category').value;
  $('report-category').replaceChildren(new Option('Alle Kategorien', ''));
  for (const category of [...new Set(data.items.map(item => item.category))]) $('report-category').append(new Option(datasetLabels.get(category) || category,category));
  $('report-category').value = selectedCategory;
  const {element,body} = table(['Bild','Status','Referenz','Finaler Text','Fehlend / Fehler']);
  for (const item of data.items) {
    if (item.state === 'queued' || ($('only-failures').checked && item.valid !== false && item.state !== 'failed')) continue;
    if ($('report-category').value && item.category !== $('report-category').value) continue;
    const row = document.createElement('tr'), td = cell(row, ''); td.className = 'image-name';
    const button = document.createElement('button'); button.type = 'button'; button.className = 'table-link';
    button.textContent = item.image.split('/').at(-1); button.title = item.image; button.disabled = batchRunning || !item.run_id;
    button.onclick = async () => { clearRun(); history.replaceState(null,'',`/?batch=${batchId}&run=${item.run_id}`); await restore(item.run_id); };
    td.append(button);
    const category = document.createElement('span'); category.className = 'muted'; category.textContent = ` · ${datasetLabels.get(item.category) || item.category}`; td.append(category);
    cell(row, item.state === 'running' ? 'Läuft …' : item.state === 'failed' ? 'Fehlgeschlagen' : item.valid ? 'Gültig' : 'Unvollständig');
    cell(row, item.coverage === undefined ? '—' : `${(item.coverage * 100).toFixed(1)} %`);
    cell(row, item.final_valid === undefined ? '—' : item.final_valid ? 'Gültig' : 'Unvollständig');
    cell(row, item.error || item.missing?.join(' ') || '—').className = 'missing-text'; body.append(row);
  }
  if (!body.children.length) {
    const row = document.createElement('tr');
    const empty = cell(row, $('only-failures').checked ? 'Keine unvollständigen oder fehlgeschlagenen Bilder in dieser Auswahl.' : 'Noch kein Bild in dieser Auswahl abgeschlossen.');
    empty.colSpan = 5; body.append(row);
  }
  $('batch-images').replaceChildren(element);
  renderCategories(data);
}
$('only-failures').onchange = () => { if (batchSnapshot) renderBatch(batchSnapshot); };
$('report-category').onchange = () => { if (batchSnapshot) renderBatch(batchSnapshot); };
function renderCategories(data) {
  const terminal = ['completed','failed'].includes(data.state);
  $('category-summary').hidden = $('category-summary-link').hidden = !terminal;
  $('category-chart').replaceChildren(); if (!terminal) return;
  const categories = new Map((data.summary.categories || []).map(item => [item.id,item]));
  for (const id of datasetLabels.keys()) if (!categories.has(id)) categories.set(id,{id,total:0,processed:0,valid:0,invalid:0,errors:0,pending:0,success_rate:null});
  const ordered = [...categories.values()].sort((a,b) => (b.success_rate ?? -1) - (a.success_rate ?? -1) || b.processed - a.processed || (datasetLabels.get(a.id) || a.id).localeCompare(datasetLabels.get(b.id) || b.id,'de'));
  for (const category of ordered) {
    const row = document.createElement('button'); row.type = 'button'; row.className = 'category-row'; row.dataset.category = category.id;
    row.disabled = !category.total; row.setAttribute('aria-pressed', String($('report-category').value === category.id));
    const header = document.createElement('span'); header.className = 'category-row-heading';
    const name = document.createElement('span'); name.textContent = datasetLabels.get(category.id) || category.id;
    const rate = document.createElement('strong'); rate.textContent = category.success_rate === null ? '—' : `${(category.success_rate * 100).toFixed(1)} %`;
    header.append(name,rate);
    const bar = document.createElement('span'); bar.className = 'category-bar'; bar.setAttribute('aria-hidden','true');
    for (const [field,style] of [['valid','category-valid'],['invalid','category-invalid'],['errors','category-error']]) {
      const segment = document.createElement('span'); segment.className = style;
      segment.style.width = `${category.processed ? 100 * category[field] / category.processed : 0}%`; bar.append(segment);
    }
    const counts = document.createElement('span'); counts.className = 'category-counts';
    counts.textContent = category.total ? `${category.valid} / ${category.processed} gültig · ${category.invalid} unvollständig · ${category.errors} technische Fehler${category.pending ? ` · ${category.pending} offen` : ''}` : 'Nicht getestet';
    row.setAttribute('aria-label', `${name.textContent}: ${rate.textContent}, ${counts.textContent}`);
    row.append(header,bar,counts);
    row.onclick = () => {
      $('report-category').value = $('report-category').value === category.id ? '' : category.id;
      renderBatch(data); $('batch-images').scrollIntoView({block:'start',behavior:'instant'});
    };
    $('category-chart').append(row);
  }
}
async function observeBatch(id, preferredRun = null) {
  clearTimeout(batchTimer); batchId = id;
  try {
    const response = await fetch(`/api/batches/${id}`), data = await response.json();
    if (!response.ok) throw new Error(data.error);
    batchRunning = !['completed','failed'].includes(data.state); busy(batchRunning); renderBatch(data);
    const nextRun = !batchRunning && preferredRun ? preferredRun : data.current_run_id;
    if (nextRun && runId !== nextRun) {
      clearRun(); runId = nextRun; history.replaceState(null,'',`/?batch=${id}&run=${runId}`); await restore(runId);
    }
    if (data.error) error(data.error);
    if (batchRunning) batchTimer = setTimeout(() => observeBatch(id),1000);
    else busy(false);
  } catch (failure) {
    error(failure.message);
    if (batchRunning) batchTimer = setTimeout(() => observeBatch(id),3000);
  }
}
async function startSelection() {
  error(''); clearRun(); batchRunning = true; busy(true); $('batch-report').hidden = $('category-summary').hidden = true; $('report-category').value = ''; runId = null;
  try {
    const response = await fetch('/api/batches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_ids:[...selectedDatasets],model:$('model').value,workers:Number($('workers').value),backend:$('backend').value})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error);
    history.replaceState(null,'',`/?batch=${data.batch_id}`); await observeBatch(data.batch_id);
  } catch (failure) { batchRunning = false; busy(false); error(failure.message); }
}
initialize();
