const $ = (id) => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const states = {queued:'Preparing scan …',preparing:'Loading OCR model …',processing:'Processing variants in parallel …',transforming:'Transforming image …',ocr:'Recognizing text …',saving:'Saving result …',assembling:'Assembling text …',evaluating:'Checking reference text …',completed:'OCR complete.',failed:'Pipeline interrupted.',cancelled:'Scan cancelled.'};
let selectedFile, source, runId, total = 0, completed = 0, latestStep, displayedStep;
let running = false, followLive = true, filePreview, lastEvent = 0, currentState = 'queued';
const steps = new Map();
const workerStates = new Map();
let workerCount = 4, selectedWorker = null;
const selectedDatasets = new Set();
const datasetLabels = new Map();
const datasetItems = new Map();
let catalogPage, catalogOffset = 0, catalogRequest = 0, searchTimer;
let batchId, batchRunning = false, batchTimer, batchSnapshot;
let currentEvaluation;
let activeDataset = 'ocr_evaluation';
let cancellationRequested = false;
let setupStep = 1;
let scanStartedAt, detectionStartedAt, batchStartedAt, batchProgressAtStart = 0, etaModel;
let detectionPhaseActive = false, liveDetectionVerdict = null;
const openImageDetails = new Set();
const scanResultDwellMs = 2600;
let scanResultTimer, scanResultUntil = 0, pendingScanActivity = null, activeScanResultKey = '', queuedScanResults = [];
const scanResultKeys = new Set();

function formatTime(seconds) {
  const rounded = Math.max(1, Math.round(seconds));
  if (rounded < 60) return `${rounded} sec`;
  const minutes = Math.floor(rounded / 60), rest = rounded % 60;
  return rest ? `${minutes} min ${rest} sec` : `${minutes} min`;
}
function updateEstimatedTime() {
  if (!etaModel) return;
  const {done,total,started,label,terminal} = etaModel;
  if (terminal) { $('estimated-time').textContent = label === 'Complete' ? 'Complete' : label; return; }
  const detectionFollows = label === 'OCR' && (document.querySelector('.text-classifier:checked') || $('image-check').value !== 'off' || $('context-check').value !== 'off');
  const suffix = detectionFollows ? ' · detection follows' : '';
  if (!done || !total) { $('estimated-time').textContent = `Estimating ${label.toLowerCase()} time …${suffix}`; return; }
  const remaining = Math.max(0,total - done), elapsed = (Date.now() - started) / 1000;
  $('estimated-time').textContent = remaining ? `Estimated ${label.toLowerCase()} time remaining: about ${formatTime(elapsed / done * remaining)}${suffix}` : `${label} complete`;
}
setInterval(updateEstimatedTime,1000);
function applyScanActivity(imageUrl, stage, verdict = '') {
  const frame = $('scan-image-frame'), image = $('scan-activity-image');
  const label = $('scan-activity-label');
  if (!frame || !image || !label) return;
  if (imageUrl && image.getAttribute('src') !== imageUrl) image.src = imageUrl;
  image.hidden = !image.getAttribute('src');
  frame.dataset.stage = stage;
  if (verdict) frame.dataset.outcome = verdict; else delete frame.dataset.outcome;
  const labels = {idle:'Ready',scanning:'Scanning image',ocr_complete:'OCR complete',detection:'Checking detected text',flagged:'Detection flagged',not_flagged:'Not flagged',unclear:'Detection needs review',failed:'Run failed',cancelled:'Run cancelled'};
  label.textContent = labels[verdict] || labels[stage] || 'Processing';
  activeScanResultKey = verdict ? `${imageUrl || ''}\u0000${verdict}` : '';
  scanResultUntil = verdict ? Date.now() + scanResultDwellMs : 0;
  clearTimeout(scanResultTimer);
  if (verdict) scanResultTimer = setTimeout(releaseScanResult, scanResultDwellMs);
}
function releaseScanResult() {
  if (Date.now() < scanResultUntil) {
    scanResultTimer = setTimeout(releaseScanResult, scanResultUntil - Date.now());
    return;
  }
  scanResultUntil = 0;
  if (queuedScanResults.length) {
    const next = queuedScanResults.shift();
    applyScanActivity(next.imageUrl, next.stage, next.verdict);
  } else if (pendingScanActivity) {
    const next = pendingScanActivity; pendingScanActivity = null;
    applyScanActivity(next.imageUrl, next.stage, next.verdict);
  } else {
    const frame = $('scan-image-frame');
    if (frame) {
      const image = $('scan-activity-image');
      const stage = ['failed','cancelled'].includes(frame.dataset.stage) ? frame.dataset.stage : 'ocr_complete';
      applyScanActivity(image?.src,stage);
    }
    activeScanResultKey = '';
  }
}
function setScanActivity(imageUrl, stage, verdict = '') {
  const frame = $('scan-image-frame');
  if (!frame || !$('scan-activity-image') || !$('scan-activity-label')) return;
  const next = {imageUrl,stage,verdict};
  const resultKey = verdict ? `${imageUrl || ''}\u0000${verdict}` : '';
  if (scanResultUntil > Date.now()) {
    if (resultKey && !scanResultKeys.has(resultKey)) {
      scanResultKeys.add(resultKey);
      queuedScanResults.push(next);
    } else if (!resultKey) pendingScanActivity = next;
    return;
  }
  if (resultKey && (resultKey === activeScanResultKey || scanResultKeys.has(resultKey))) return;
  if (resultKey) scanResultKeys.add(resultKey);
  applyScanActivity(imageUrl, stage, verdict);
}
function clearScanActivity() {
  clearTimeout(scanResultTimer); scanResultTimer = null; scanResultUntil = 0;
  pendingScanActivity = null; queuedScanResults = []; activeScanResultKey = ''; scanResultKeys.clear();
  const frame = $('scan-image-frame');
  if (frame) delete frame.dataset.outcome;
}

function updateEvaluationEmpty() {
  $('evaluation-empty').hidden = !$('evaluation').hidden || !$('detection-evaluation').hidden || !$('batch-details').hidden;
}
function selectWorkbenchPage(page) {
  $('scan-page').hidden = page !== 'scan';
  $('evaluation-page').hidden = page !== 'evaluation';
  $('tab-scan').setAttribute('aria-selected', String(page === 'scan'));
  $('tab-evaluation').setAttribute('aria-selected', String(page === 'evaluation'));
  try { sessionStorage.setItem('vipi-workbench-page', page); } catch {}
}

function selectedInputLabel() {
  if (selectedDatasets.size) return `${selectedDatasets.size} image${selectedDatasets.size === 1 ? '' : 's'} from ${activeDataset}`;
  return selectedFile?.name || '';
}
function updateWizard() {
  $('input-next').disabled = running || batchRunning || (!selectedFile && !selectedDatasets.size);
  $('start').disabled = running || batchRunning || setupStep !== 3;
  const evaluation = activeDataset === 'detection_evaluation' && selectedDatasets.size > 0;
  $('text-classifiers').disabled = running || batchRunning;
  $('dataset-mode-note-options').hidden = !evaluation;
  $('threshold-required-note').textContent = evaluation
    ? 'Required for detection evaluation. Set a score threshold for every selected classifier and calibrate against labeled data.'
    : 'Required when detection is enabled. Set a score threshold for every selected check and calibrate against labeled data.';
}
function setSetupStep(step) {
  setupStep = step;
  for (const [index,id] of [[1,'step-input'],[2,'step-options'],[3,'step-review']]) {
    $(`${id}`).hidden = index !== step;
    const indicator = $(`step-indicator-${index}`);
    if (index === step) indicator.setAttribute('aria-current','step'); else indicator.removeAttribute('aria-current');
  }
  if (step === 3) renderScanReview();
  updateWizard();
  $('wizard-error').hidden = true;
  $('error').hidden = true;
}
function renderScanReview() {
  const list = $('scan-review'); list.replaceChildren();
  const classifierLabels = {jev:'Jev',openai:'OpenAI Decisions','prompt-guard':'Prompt Guard 2'};
  const selectedClassifiers = [...document.querySelectorAll('.text-classifier:checked')].map(input => classifierLabels[input.value]);
  const entries = [
    ['Input',selectedInputLabel()],
    ['Dataset mode', selectedDatasets.size ? (activeDataset === 'detection_evaluation' ? 'Detection evaluation' : 'OCR evaluation') : 'Single image'],
    ['OCR model',$('model').selectedOptions[0]?.textContent || '—'],
    ['Hardware',$('backend').selectedOptions[0]?.textContent || '—'],
    ['Parallel workers',$('workers').value],
    ['Text classifiers',selectedClassifiers.length ? selectedClassifiers.join(', ') : 'None · OCR only'],
    ['Image check',$('image-check').value === 'openai' ? 'OpenAI Decisions' : 'Off'],
    ['Context check',$('context-check').value === 'openai' ? 'OpenAI Decisions' : 'Off'],
    ['Caller context',selectedDatasets.size && activeDataset === 'detection_evaluation' ? 'Not used for detection evaluation' : $('detector-context').value.trim() ? 'Configured' : 'None'],
    ['Threshold set',$('detector-threshold-version').value.trim() || 'Not configured'],
    ['Reuse saved answers',$('detector-reuse').checked ? 'Yes' : 'No'],
  ];
  for (const [term,value] of entries) {
    const dt = document.createElement('dt'); dt.textContent = term;
    const dd = document.createElement('dd'); dd.textContent = value;
    list.append(dt,dd);
  }
}
function validateOptions() {
  const showError = message => { $('wizard-error').textContent = message; $('wizard-error').hidden = false; };
  if (!$('model').value || !$('backend').value || !$('workers').value) {
    showError('Choose an OCR model, hardware and worker count.'); return false;
  }
  const evaluation = activeDataset === 'detection_evaluation' && selectedDatasets.size > 0;
  const selectedClassifiers = [...document.querySelectorAll('.text-classifier:checked')].map(input => input.value);
  if (evaluation && !selectedClassifiers.length) {
    showError('Choose at least one text classifier for detection evaluation.'); return false;
  }
  try {
    const detection = window.vipiDetection?.options(evaluation);
    if (detection && (detection.text_classifiers.length || detection.image_check !== 'off' || detection.context_check !== 'off')) {
      const needed = [...detection.text_classifiers];
      if (detection.image_check === 'openai') needed.push('image');
      if (detection.context_check === 'openai') needed.push('context');
      if (needed.some(signal => !detection.thresholds?.signals?.[signal])) {
        showError(`Add a threshold entry for each selected check: ${needed.join(', ')}.`); return false;
      }
    }
  } catch (failure) { showError(failure.message); return false; }
  return true;
}
function updateCancelControl() {
  const active = running || batchRunning || window.vipiDetection?.isChecking();
  if (!active) cancellationRequested = false;
  $('cancel-run').parentElement.hidden = !active;
  $('cancel-run').hidden = !active;
  $('cancel-run').disabled = cancellationRequested || !(batchRunning ? batchId : runId);
  $('cancel-run').textContent = cancellationRequested ? 'Stopping …' : batchRunning ? 'Stop batch' : 'Stop scan';
  $('cancellation-note').hidden = !active || !cancellationRequested;
}
$('cancel-run').onclick = async () => {
  const url = batchRunning && batchId ? `/api/batches/${batchId}/cancel` : runId ? `/api/runs/${runId}/cancel` : null;
  if (!url) return;
  try {
    $('cancel-run').disabled = true;
    const response = await fetch(url,{method:'POST'}), data = await response.json();
    if (!response.ok) throw new Error(data.error);
    cancellationRequested = !!data.cancel_requested;
    if (batchRunning) await observeBatch(batchId);
  } catch (failure) { error(failure.message); }
  updateCancelControl();
};

function error(message) { $('error').textContent = message; $('error').hidden = !message; }
function busy(value) {
  running = value || batchRunning;
  $('start').textContent = selectedDatasets.size ? selectedDatasets.size === 1 ? 'Scan image ↗' : `Scan ${selectedDatasets.size} images ↗` : 'Start scan ↗';
  for (const id of ['model','backend','workers','image-input','dataset-category','dataset-search','select-matching','clear-selection','choose-dataset','dataset-ocr','dataset-detection','text-classifiers','image-check','context-check','detector-context','detector-threshold-version','detector-reuse','input-next','options-back','options-next','review-back']) $(id).disabled = running;
  for (const input of $('threshold-controls').querySelectorAll('input')) input.disabled = running;
  const withoutContext = activeDataset === 'detection_evaluation' && selectedDatasets.size > 0;
  $('detector-context').disabled = $('context-check').disabled = running || withoutContext;
  $('caller-context-option').hidden = $('context-check-option').hidden = withoutContext;
  $('dataset-mode-note').hidden = $('dataset-mode-note-options').hidden = !withoutContext;
  for (const input of document.querySelectorAll('.dataset-card input')) input.disabled = running;
  $('dataset-prev').disabled = running || !catalogOffset;
  $('dataset-next').disabled = running || !catalogPage || catalogOffset + catalogPage.limit >= catalogPage.total;
  updateWizard();
  updateCancelControl();
}
function renderWorkers() {
  if (!$('ocr-detail-dialog').open) return;
  $('worker-status').replaceChildren();
  const labels = {preparing:'Loading model',transforming:'Transforming image',ocr:'OCR',saving:'Saving',idle:'Ready',completed:'Complete',failed:'Stopped',cancelled:'Cancelled'};
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
  $('run-progress').hidden = false;
  currentState = state;
  scanStartedAt ||= Date.now();
  updateCancelControl();
  const stage = state === 'failed' ? 'failed' : state === 'cancelled' ? 'cancelled' : ['assembling','evaluating','completed'].includes(state) ? 'ocr_complete' : 'scanning';
  const selected = selectedFile && filePreview ? filePreview : datasetItems.get([...selectedDatasets][0])?.thumbnail_url || $('input-preview').getAttribute('src');
  setScanActivity(selected,stage);
  if (batchRunning) return;
  $('status').textContent = cancellationRequested && !['completed','failed','cancelled'].includes(state) ? 'Stopping after the current operation …' : states[state] || state;
  $('counter').textContent = total ? `${completed} / ${total} OCR steps` : '';
  $('progress').setAttribute('aria-label','Completed OCR steps'); $('progress').max = total || 1; $('progress').value = completed;
  const terminal = state === 'completed' || state === 'failed' || state === 'cancelled';
  etaModel = {done:completed,total,started:scanStartedAt,label:state === 'completed' ? 'Complete' : state === 'failed' ? 'Run failed' : state === 'cancelled' ? 'Run cancelled' : 'OCR',terminal};
  updateEstimatedTime();
}
window.addEventListener('vipi:detection-state',event => {
  if ($('run-progress').hidden) return;
  const {state,completed:done,total,verdict} = event.detail;
  if (state === 'queued') { detectionStartedAt = null; detectionPhaseActive = false; liveDetectionVerdict = null; return; }
  if (batchRunning) {
    const batchImageUrl = runId ? `/api/runs/${runId}/input` : $('scan-activity-image').src;
    if (state === 'running') { detectionPhaseActive = true; liveDetectionVerdict = null; setScanActivity(batchImageUrl,'detection'); }
    if (['completed','failed','cancelled'].includes(state)) {
      detectionPhaseActive = false;
      const outcome = verdict || (state === 'failed' ? 'failed' : state === 'cancelled' ? 'cancelled' : 'unclear');
      liveDetectionVerdict = outcome;
      const stage = ['flagged','not_flagged','unclear'].includes(outcome) ? outcome : state;
      setScanActivity(batchImageUrl,stage,outcome);
    }
    return;
  }
  if (state === 'running') {
    detectionPhaseActive = true; liveDetectionVerdict = null;
    detectionStartedAt ||= Date.now();
    setScanActivity($('scan-activity-image').src,'detection');
    etaModel = {done,total,started:detectionStartedAt,label:'Detection'};
  } else if (['completed','failed','cancelled'].includes(state)) {
    detectionPhaseActive = false;
    const result = verdict || (state === 'failed' ? 'failed' : state === 'cancelled' ? 'cancelled' : 'unclear');
    liveDetectionVerdict = result;
    const stage = ['flagged','not_flagged','unclear'].includes(result) ? result : state === 'failed' ? 'failed' : state === 'cancelled' ? 'cancelled' : 'ocr_complete';
    setScanActivity($('scan-activity-image').src,stage,result);
    etaModel = {done:total,total,started:detectionStartedAt || Date.now(),label:state === 'completed' ? 'Complete' : state === 'failed' ? 'Detection failed' : 'Detection cancelled',terminal:true};
  }
  updateEstimatedTime();
});
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
  if (!$('ocr-detail-dialog').open) return;
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
  $('step-text').textContent = step.text === undefined ? 'OCR in progress …' : step.text || 'No text recognized.';
  $('live').hidden = followLive && selectedWorker === null;
  for (const card of $('variants').children) card.classList.toggle('selected', card.dataset.step === step.id);
}
function addVariant(step) {
  steps.set(step.id, step);
  if (!$('ocr-detail-dialog').open) return;
  $('history').hidden = false;
  let card = $('variants').querySelector(`[data-step="${step.id}"]`);
  if (card) return;
  card = document.createElement('button'); card.type = 'button'; card.className = 'variant'; card.dataset.step = step.id; card.dataset.index = step.index;
  card.setAttribute('aria-label', `Step ${step.index}: ${step.label}`);
  const thumb = document.createElement('div'); thumb.className = 'thumb';
  const canvas = document.createElement('div'); canvas.className = 'canvas'; canvas.style.width = `${Math.min(360, 136 * step.width / step.height)}px`;
  const image = document.createElement('img'); image.src = step.image_url; image.alt = step.label; image.loading = 'lazy'; image.width = step.width; image.height = step.height;
  const overlay = svgNode('svg'); drawBoxes(overlay, step);
  canvas.append(image, overlay); thumb.append(canvas);
  const label = document.createElement('span'); label.className = 'label'; label.textContent = `${step.index.toString().padStart(3,'0')} · ${step.label}`;
  const text = document.createElement('pre'); text.textContent = step.text || 'No text recognized.';
  card.append(thumb, label, text); card.onclick = () => { followLive = false; showStep(steps.get(step.id)); $('workspace').scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'}); };
  const next = [...$('variants').children].find(item => Number(item.dataset.index) > step.index);
  $('variants').insertBefore(card, next || null); $('variant-count').textContent = `${steps.size} variants`;
}
function finish(text, regions = [], evaluation = null) {
  busy(false); progress('completed'); $('final').hidden = false;
  for (const [id, entry] of workerStates) workerStates.set(id, {...entry,state:'completed'});
  renderWorkers();
  $('final-text').textContent = text || 'No text recognized.';
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
      const support = document.createElement('span'); support.className = 'mono muted'; support.textContent = ` · ${reading.support} view${reading.support === 1 ? '' : 's'}`;
      item.append(support); list.append(item); alternatives++;
    }
    group.append(list); $('alternative-list').append(group);
  }
  $('alternative-readings').hidden = !alternatives;
  $('alternative-summary').textContent = `${alternatives} alternative readings`;
  $('download-txt').href = `/api/runs/${runId}/result.txt`; $('download-json').href = `/api/runs/${runId}/result.json`;
  renderEvaluation(evaluation);
  if (source) source.close();
  window.vipiDetection?.observeRun(runId, true);
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
    case 'cancellation_requested': cancellationRequested = true; progress(currentState); break;
    case 'run_cancelled':
      for (const [id, entry] of workerStates) workerStates.set(id, {...entry,state:'cancelled'});
      renderWorkers(); busy(false); progress('cancelled'); source.close(); window.vipiDetection?.observeRun(runId, true); break;
    case 'run_failed':
      for (const [id, entry] of workerStates) workerStates.set(id, {...entry,state:'failed'});
      renderWorkers(); busy(false); progress('failed'); error(data.error); source.close(); window.vipiDetection?.observeRun(runId, true); break;
  }
}
async function restore(id, connect = true) {
  const response = await fetch(`/api/runs/${id}`);
  if (!response.ok) throw new Error('Could not load the saved run.');
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
  $('input-preview').src = `/api/runs/${id}/input`; $('input-preview').hidden = false;
  if (!selectedDatasets.size) $('file-label').textContent = 'Source image · saved run';
  latestStep = state.current || state.variants.at(-1); if (latestStep?.image_url && followLive) showStep(latestStep);
  lastEvent = state.event_id; progress(state.state);
  if (state.state === 'completed') finish(state.result.text, state.result.regions, state.result.evaluation);
  else if (['failed','cancelled'].includes(state.state)) {
    for (const [id, entry] of workerStates) workerStates.set(id, {...entry,state:state.state});
    renderWorkers(); busy(false); error(state.error || ''); if (source) source.close();
    window.vipiDetection?.observeRun(runId, true);
  }
  else if (connect) { cancellationRequested = !!state.cancel_requested; busy(true); subscribe(); }
}
function subscribe() {
  if (source) source.close();
  source = new EventSource(`/api/runs/${runId}/events?after=${lastEvent}`);
  for (const name of ['run_started','step_started','image_ready','ocr_started','saving','step_completed','assembling','evaluating','run_completed','run_failed','run_cancelled','cancellation_requested']) source.addEventListener(name, handle);
  source.onopen = () => { if (running && $('status').textContent.startsWith('Reconnecting')) progress(currentState); };
  source.onerror = () => { if (running) $('status').textContent = 'Reconnecting …'; };
}
function selectFile(file) {
  if (running || !file) return;
  if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { error('Use a PNG, JPEG, or WebP image.'); return; }
  selectWorkbenchPage('scan');
  clearRun(); runId = null; batchId = null; batchSnapshot = null; $('batch-details').hidden = $('detection-evaluation').hidden = true;
  history.replaceState(null, '', '/');
  selectedDatasets.clear(); refreshSelection();
  selectedFile = file; error(''); $('file-label').textContent = file.name || 'Pasted image';
  if (filePreview) URL.revokeObjectURL(filePreview); filePreview = URL.createObjectURL(file);
  $('input-preview').src = filePreview; $('input-preview').hidden = false; busy(false);
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
    ? 'Apple selects the CPU, GPU, or Neural Engine. Speed and recognition may vary; not all operations are accelerated.'
    : $('backend').value === 'cuda'
      ? 'OCR runs on the NVIDIA GPU. Start with 1–2 workers; each worker needs its own GPU memory.'
      : 'CPU threads are distributed across workers.';
}
$('model').onchange = () => { updateBackend(); busy(running); };
$('backend').onchange = () => { updateBackend(); updateWizard(); };
$('show-boxes').onchange = () => { $('boxes').toggleAttribute('hidden', !$('show-boxes').checked); };
$('live').onclick = () => { followLive = true; selectedWorker = null; renderWorkers(); if (latestStep?.image_url) showStep(latestStep); };
async function copy(button, text) {
  try { await navigator.clipboard.writeText(text || ''); button.textContent = 'Copied'; setTimeout(() => button.textContent = 'Copy', 1500); }
  catch { error('Copying is unavailable. Select the text and copy it manually.'); }
}
$('copy-step').onclick = () => copy($('copy-step'), displayedStep?.text);
$('copy-final').onclick = () => copy($('copy-final'), $('final-text').textContent);
$('upload-form').onsubmit = async event => {
  event.preventDefault(); if (running || (!selectedFile && !selectedDatasets.size)) return;
  if (!validateOptions()) { setSetupStep(2); return; }
  if (selectedDatasets.size) { await startSelection(); return; }
  clearScanActivity();
  batchId = null; batchSnapshot = null; runId = null; cancellationRequested = false; $('batch-report').hidden = $('category-summary').hidden = $('detection-evaluation').hidden = true;
  scanStartedAt = Date.now(); detectionStartedAt = null; detectionPhaseActive = false; liveDetectionVerdict = null;
  error(''); busy(true); followLive = true; completed = total = lastEvent = 0; latestStep = null;
  selectedWorker = null; workerCount = Number($('workers').value); workerStates.clear(); renderWorkers();
  steps.clear(); $('variants').replaceChildren(); $('history').hidden = $('final').hidden = true;
  renderEvaluation(null);
  $('ocr-detail-dialog').close(); progress('queued'); if (source) source.close();
  const body = new FormData(); body.append('image', selectedFile, selectedFile.name || 'clipboard.png'); body.append('model', $('model').value);
  body.append('workers', $('workers').value);
  body.append('backend', $('backend').value);
  try {
    const detectionOptions = window.vipiDetection?.options();
    if (detectionOptions) body.append('detection', JSON.stringify(detectionOptions));
    window.vipiDetection?.reset();
    const response = await fetch('/api/runs', {method:'POST',body}); const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not start the pipeline.');
    runId = data.run_id; updateCancelControl(); window.vipiDetection?.observeRun(runId, false); history.replaceState(null, '', `/?run=${runId}`); subscribe();
  } catch (failure) { error(failure.message); busy(false); progress('Could not start scan.'); }
};
async function initialize() {
  try {
    const response = await fetch('/api/models'); const data = await response.json();
    for (const model of data.models) {
      const option = new Option(model.label + (model.available ? '' : ' · not prepared'), model.id);
      option.disabled = !model.available; option.title = model.reason || ''; $('model').append(option);
    }
    const chosen = data.models.find(model => model.id === data.default && model.available) || data.models.find(model => model.available);
    $('model').value = chosen?.id || ''; if (!chosen) error('No OCR models are prepared. Run: uv run python -m research.workbench prepare-models');
    for (const backend of data.backends) {
      const option = new Option(backend.label + (backend.available ? '' : ' · unavailable'),backend.id);
      option.dataset.available = String(backend.available); option.disabled = !backend.available; $('backend').append(option);
    }
    $('backend').value = data.default_backend; updateBackend();
    await loadCatalog();
    const params = new URLSearchParams(location.search);
    let page = null;
    try { page = sessionStorage.getItem('vipi-workbench-page'); } catch {}
    if (params.get('batch')) page = 'evaluation';
    else if (params.get('run')) page = 'scan';
    else if (!['scan','evaluation'].includes(page)) page = 'scan';
    selectWorkbenchPage(page);
    if (params.get('batch')) await observeBatch(params.get('batch'), params.get('run'), params.get('check'));
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
  const {element,body} = table(['Effect','Better','Equal','Worse','Newly valid','Mean Δ']);
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
  openOCRDetails();
  followLive = false; showStep(step); $('workspace').scrollIntoView({block:'start',behavior:'instant'});
}
function renderEvaluation(evaluation) {
  currentEvaluation = evaluation; $('evaluation').hidden = !evaluation;
  updateEvaluationEmpty();
  for (const card of $('variants').children) {
    card.querySelector('.step-score')?.remove();
    const score = evaluation?.steps[card.dataset.step]; if (!score) continue;
    const label = document.createElement('span'); label.className = 'step-score';
    label.textContent = `${score.valid ? 'Valid' : 'Incomplete'} · ${(score.coverage * 100).toFixed(1)}% reference`;
    card.querySelector('.label').after(label);
  }
  if (!evaluation) return;
  $('evaluation-heading').textContent = evaluation.final.valid ? 'Reference found in final text.' : 'Reference incomplete in final text.';
  $('evaluation-rule').textContent = `Additional text is allowed. Case and whitespace are ignored; recognition errors count as missing. ${evaluation.method === 'word_regions' ? 'TextOCR: word regions have no fixed reading order; recognition across variants may be combined.' : 'The complete reference text must appear in one variant or in the final text.'} Annotation quality: ${evaluation.reference.quality}.`;
  $('evaluation-scores').replaceChildren();
  for (const [name,score] of [['Original',evaluation.original],['Pipeline',evaluation.detection],['Final text',evaluation.final]]) {
    const panel = document.createElement('div'); panel.className = 'evaluation-score';
    const title = document.createElement('span'); title.textContent = name;
    const value = document.createElement('strong'); value.textContent = `${(score.coverage * 100).toFixed(1)} %`;
    const state = document.createElement('span'); state.textContent = score.valid ? 'Valid' : 'Incomplete';
    panel.append(title,value,state); $('evaluation-scores').append(panel);
  }
  $('evaluation-missing').textContent = evaluation.detection.missing.length ? `Missing: ${evaluation.detection.missing.join(' ')}` : `${evaluation.valid_step_ids.length} variants contain the full reference.`;
  $('reference-text').textContent = evaluation.reference.text;
  renderEffects($('evaluation-effects'), evaluation.effects);
  const {element,body} = table(['View','Original','Grayscale','CLAHE','Inverted','Threshold','Color contrast']);
  const views = new Map();
  for (const step of [...steps.values()].sort((a,b) => a.index - b.index)) {
    if (!views.has(step.view_id)) views.set(step.view_id, {}); views.get(step.view_id)[step.filter] = step;
  }
  for (const [name,filters] of views) {
    const row = document.createElement('tr'); cell(row, name);
    for (const filter of ['unchanged','grayscale','clahe','inverted','threshold','color-contrast']) {
      const step = filters[filter], score = step && evaluation.steps[step.id], td = cell(row, '');
      if (!score) { td.textContent = '—'; continue; }
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
  $('dataset-selected').textContent = `${selectedDatasets.size} image${selectedDatasets.size === 1 ? '' : 's'} selected`;
  if (selectedDatasets.size === 1) {
    const item = datasetItems.get([...selectedDatasets][0]);
    $('file-label').textContent = item ? `${item.label} · ${item.name}` : '1 dataset image selected';
    if (item && !running) { $('input-preview').src = item.thumbnail_url; $('input-preview').hidden = false; }
  } else if (selectedDatasets.size) $('file-label').textContent = `${selectedDatasets.size} dataset images selected`;
  else {
    $('file-label').textContent = selectedFile?.name || (runId ? 'Source image · saved run' : 'Upload, drag and drop, or paste an image');
    if (!selectedFile && !runId) $('input-preview').hidden = true;
  }
  busy(running);
}
function selectDataset(item) {
  if (!batchRunning) {
    clearRun(); runId = null; batchId = null; batchSnapshot = null; $('batch-details').hidden = $('detection-evaluation').hidden = true;
    history.replaceState(null, '', '/');
  }
  selectedFile = null;
  followLive = true; selectedWorker = null;
  $('input-preview').src = item.thumbnail_url; $('input-preview').hidden = false;
  refreshSelection();
}
async function loadCatalog() {
  const request = ++catalogRequest;
  const params = new URLSearchParams({dataset:activeDataset,category:$('dataset-category').value,q:$('dataset-search').value,offset:catalogOffset});
  try {
    const response = await fetch(`/api/datasets?${params}`), data = await response.json();
    if (request !== catalogRequest) return;
    if (!response.ok) throw new Error(data.error);
    catalogPage = data; $('catalog-error').hidden = true; $('select-matching').hidden = !data.matching_ids?.length; $('catalog-count').textContent = `· ${data.catalog_total} image${data.catalog_total === 1 ? '' : 's'}`;
    for (const category of data.categories) datasetLabels.set(category.id, category.label);
    if ($('dataset-category').options.length === 1) for (const category of data.categories) $('dataset-category').append(new Option(`${category.label} (${category.count})`,category.id));
    $('dataset-count').textContent = data.total ? `${catalogOffset + 1}–${Math.min(catalogOffset + data.limit,data.total)} of ${data.total} match${data.total === 1 ? '' : 'es'}` : 'No matches';
    $('dataset-images').replaceChildren();
    for (const item of data.items) {
      datasetItems.set(item.id, item);
      const card = document.createElement('label'); card.className = 'dataset-card';
      const image = document.createElement('img'); image.src = item.thumbnail_url; image.alt = `${item.label} · ${item.name}`; image.loading = 'lazy';
      const label = document.createElement('span'); label.className = 'dataset-label';
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = item.id; input.checked = selectedDatasets.has(item.id); input.setAttribute('aria-label', `${item.label}: ${item.name}`);
      input.onchange = () => { if (input.checked) { selectedDatasets.add(item.id); selectDataset(item); } else { selectedDatasets.delete(item.id); refreshSelection(); } };
      const name = document.createElement('span'); name.textContent = `${item.label} · ${item.name}${item.case_count ? ` · ${item.case_count} case${item.case_count === 1 ? '' : 's'}` : ''}`; label.append(input,name);
      card.append(image,label); $('dataset-images').append(card);
    }
    refreshSelection();
  } catch (failure) { if (request === catalogRequest) { $('catalog-error').hidden = false; $('catalog-error').textContent = `Dataset browser unavailable: ${failure.message}`; } }
}
$('dataset-category').onchange = () => { catalogOffset = 0; loadCatalog(); };
$('dataset-search').oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { catalogOffset = 0; loadCatalog(); },250); };
$('dataset-prev').onclick = () => { catalogOffset = Math.max(0,catalogOffset - catalogPage.limit); loadCatalog(); };
$('dataset-next').onclick = () => { catalogOffset += catalogPage.limit; loadCatalog(); };
$('select-matching').onclick = () => { if (!catalogPage) return; for (const id of catalogPage.matching_ids) selectedDatasets.add(id); selectedFile = null; if (catalogPage.items[0]) selectDataset(catalogPage.items[0]); else refreshSelection(); };
$('clear-selection').onclick = () => { selectedDatasets.clear(); refreshSelection(); };
async function switchDataset(dataset) {
  activeDataset = dataset; selectedDatasets.clear(); datasetItems.clear();
  catalogOffset = 0; catalogPage = null; catalogRequest++;
  clearTimeout(searchTimer); $('dataset-search').value = '';
  $('dataset-category').replaceChildren(new Option('All categories', ''));
  $('dataset-images').replaceChildren(); $('dataset-count').textContent = '';
  $('catalog-count').textContent = '';
  $('dataset-ocr').setAttribute('aria-pressed', String(dataset === 'ocr_evaluation'));
  $('dataset-detection').setAttribute('aria-pressed', String(dataset === 'detection_evaluation'));
  if (dataset === 'detection_evaluation') {
    $('context-check').value = 'off';
    $('context-check').dispatchEvent(new Event('change'));
  }
  $('dataset-purpose').textContent = dataset === 'detection_evaluation'
    ? 'Scan without context and compare the result with every ground-truth case. Select at least one detector before scanning.'
    : 'Evaluate OCR reference coverage.';
  refreshSelection(); await loadCatalog(); updateWizard();
}
$('dataset-ocr').onclick = () => switchDataset('ocr_evaluation');
$('dataset-detection').onclick = () => switchDataset('detection_evaluation');
$('input-next').onclick = () => { if (selectedFile || selectedDatasets.size) setSetupStep(2); };
$('options-back').onclick = () => setSetupStep(1);
$('review-back').onclick = () => setSetupStep(2);
$('options-next').onclick = () => {
  $('wizard-error').hidden = true;
  if (validateOptions()) setSetupStep(3);
};
$('text-classifiers').addEventListener('change',updateWizard);
$('workers').onchange = () => updateWizard();
for (const id of ['image-check','context-check']) $(id).addEventListener('change',updateWizard);
$('tab-scan').onclick = () => selectWorkbenchPage('scan');
$('tab-evaluation').onclick = () => { updateEvaluationEmpty(); selectWorkbenchPage('evaluation'); };
$('open-scan-setup').onclick = () => { selectWorkbenchPage('scan'); setSetupStep(1); };

function clearRun() {
  clearScanActivity();
  window.vipiDetection?.reset();
  if (source) source.close(); source = null;
  scanStartedAt = detectionStartedAt = batchStartedAt = null; batchProgressAtStart = 0; detectionPhaseActive = false; liveDetectionVerdict = null; etaModel = null;
  steps.clear(); workerStates.clear(); completed = total = lastEvent = 0; latestStep = displayedStep = null;
  followLive = true; selectedWorker = null; $('variants').replaceChildren(); $('worker-status').replaceChildren();
  $('ocr-detail-dialog').close(); $('run-progress').hidden = true;
  $('history').hidden = $('final').hidden = $('workspace').hidden = true; renderEvaluation(null); error('');
}
function addDetailText(container, title, value) {
  const section = document.createElement('section'); section.className = 'image-detail-text';
  const heading = document.createElement('h4'); heading.textContent = title;
  const content = document.createElement('pre'); content.textContent = value || '—';
  section.append(heading,content); container.append(section); return content;
}
function scoreLabel(value) { return value == null ? '—' : String(value); }
function appendDetectionDetails(container, item) {
  const signals = item.detection?.signals || item.cases?.[0]?.signals || {};
  const heading = document.createElement('h4'); heading.textContent = 'Detection'; container.append(heading);
  const verdict = item.detection?.verdict || item.cases?.[0]?.verdict;
  const overall = document.createElement('p'); overall.textContent = `Overall: ${verdict || (item.detection_options ? 'Pending' : 'Not enabled')}`; container.append(overall);
  if (item.detection?.threshold_version) {
    const version = document.createElement('p'); version.className = 'muted'; version.textContent = `Threshold set: ${item.detection.threshold_version}`; container.append(version);
  }
  const rows = table(['Detector','Exact score','Verdict']);
  for (const [signal,value] of Object.entries(signals)) {
    const row = document.createElement('tr');
    cell(row,({jev:'Jev',openai:'OpenAI Decisions','prompt-guard':'Prompt Guard 2',image:'Source image',context:'Context'}[signal] || signal));
    cell(row,scoreLabel(value.max_score)); cell(row,value.verdict || 'Unclear'); rows.body.append(row);
  }
  if (rows.body.children.length) container.append(rows.element);
  for (const sample of item.cases || []) {
    const detail = document.createElement('details'); detail.className = 'image-case-detail';
    const summary = document.createElement('summary'); summary.textContent = `Case ${sample.case_index} · expected ${sample.expected} · ${sample.outcome || sample.state || 'pending'}`;
    detail.append(summary);
    if (sample.context) addDetailText(detail,'Ground-truth context',sample.context);
    container.append(detail);
  }
}
function renderImageDetails(item,data) {
  const content = document.createElement('div'); content.className = 'image-evaluation-details';
  const image = document.createElement('img'); image.className = 'image-evaluation-preview';
  image.src = `/api/datasets/${encodeURIComponent(item.dataset_id)}/thumbnail?dataset=${encodeURIComponent(data.dataset || 'ocr_evaluation')}`;
  image.alt = item.image.split('/').at(-1); image.loading = 'lazy'; content.append(image);
  const text = document.createElement('div'); text.className = 'image-evaluation-text';
  const payload = item.cases?.[0]?.payload;
  const reference = addDetailText(text,'Reference text',item.reference_text || payload || 'Not available in this saved report.');
  const recognized = addDetailText(text,'Recognized text',item.recognized_text ?? (item.state === 'queued' || item.state === 'running' ? 'Waiting for OCR to finish.' : 'Not available in this saved report.'));
  if ((!item.reference_text && !payload) || (item.recognized_text == null && item.state === 'completed')) {
    const loadText = document.createElement('button'); loadText.type = 'button'; loadText.className = 'small'; loadText.textContent = 'Load saved text';
    loadText.onclick = async () => {
      loadText.disabled = true; loadText.textContent = 'Loading …';
      try {
        if (!item.reference_text && !payload) {
          const response = await fetch(`/api/datasets/${encodeURIComponent(item.dataset_id)}/reference?dataset=${encodeURIComponent(data.dataset || 'ocr_evaluation')}`);
          const record = await response.json(); if (!response.ok) throw new Error(record.error);
          reference.textContent = record.text || '—';
        }
        if (item.recognized_text == null && item.run_id) {
          const response = await fetch(`/api/runs/${item.run_id}/result.json`), result = await response.json();
          if (!response.ok) throw new Error(result.error);
          recognized.textContent = result.text || 'No text recognized.';
        }
        loadText.hidden = true;
      } catch (failure) { loadText.disabled = false; loadText.textContent = failure.message; }
    };
    text.append(loadText);
  }
  appendDetectionDetails(text,{...item,detection_options:data.detection_options});
  if (item.error) addDetailText(text,'Run error',item.error);
  content.append(text);
  if (item.run_id) {
    const inspect = document.createElement('button'); inspect.type = 'button'; inspect.className = 'small'; inspect.textContent = 'Open scan'; inspect.disabled = batchRunning;
    inspect.onclick = async () => { try { selectWorkbenchPage('scan'); clearRun(); history.replaceState(null,'',`/?batch=${data.batch_id}&run=${item.run_id}`); await restore(item.run_id); } catch (failure) { error(failure.message); } };
    content.append(inspect);
  }
  return content;
}
function renderOCRStatus(item) {
  const cell = document.createElement('td'); cell.className = 'result-cell result-cell-ocr';
  const state = item.state === 'cancelled' ? 'Cancelled' : item.state === 'running' ? 'Running' : item.state === 'failed' ? 'Failed' : item.state === 'queued' ? 'Pending' : item.valid ? 'Complete' : 'Incomplete';
  const badge = document.createElement('span'); badge.className = `result-badge ocr-${state.toLowerCase()}`; badge.textContent = state; cell.append(badge);
  if (item.coverage !== undefined) {
    const coverage = document.createElement('span'); coverage.className = 'result-detail'; coverage.textContent = `${(item.coverage * 100).toFixed(1)}% reference`; cell.append(coverage);
  }
  return cell;
}
function renderDetectionStatus(item, enabled) {
  const cell = document.createElement('td'); cell.className = 'result-cell result-cell-detection';
  const result = item.detection || item.cases?.[0];
  const verdict = !enabled ? 'Not enabled' : !result ? (item.state === 'failed' ? 'Unavailable' : 'Pending') : result.error ? 'Error' : ({flagged:'Flagged','not_flagged':'Not flagged',unclear:'Unresolved',cancelled:'Cancelled'}[result.verdict] || 'Pending');
  const badge = document.createElement('span'); badge.className = `result-badge detection-${verdict.toLowerCase().replaceAll(' ','-')}`; badge.textContent = verdict; cell.append(badge);
  if (enabled && result?.signals) {
    const names = {jev:'Jev',openai:'OpenAI Decisions','prompt-guard':'Prompt Guard 2',image:'Source image',context:'Context'};
    const scores = Object.entries(result.signals).map(([signal,value]) => `${names[signal] || signal}: ${scoreLabel(value.max_score)}`).join(' · ');
    if (scores) { const detail = document.createElement('span'); detail.className = 'result-detail'; detail.textContent = scores; cell.append(detail); }
  }
  return cell;
}
function detectionBatchSummary(data) {
  const overall = data.detection_evaluation?.overall;
  if (overall) {
    const flagged = (overall.true_positive || 0) + (overall.false_positive || 0);
    const notFlagged = (overall.true_negative || 0) + (overall.false_negative || 0);
    return `${flagged} flagged · ${notFlagged} not flagged · ${overall.unresolved} unresolved · ${overall.error} errors · ${overall.pending} pending`;
  }
  const counts = {flagged:0,not_flagged:0,unclear:0,pending:0,error:0};
  for (const item of data.items) {
    const result = item.detection || item.cases?.[0];
    if (result?.error) counts.error++;
    else if (result?.verdict && counts[result.verdict] !== undefined) counts[result.verdict]++;
    else counts.pending++;
  }
  return `${counts.flagged} flagged · ${counts.not_flagged} not flagged · ${counts.unclear} unresolved · ${counts.error} errors · ${counts.pending} pending`;
}
function renderBatch(data) {
  const newBatch = batchSnapshot?.batch_id !== data.batch_id;
  batchSnapshot = data; $('batch-details').hidden = false; $('batch-report').hidden = false;
  if (newBatch) {
    $('batch-details').open = true; $('batch-aggregate-details').open = false;
    $('detection-evaluation').querySelector('.evaluation-more').open = false;
    openImageDetails.clear(); batchStartedAt ||= Date.now(); batchProgressAtStart = data.completed;
  }
  $('batch-heading').textContent = data.state === 'cancelled' ? 'Batch cancelled.' : data.cancel_requested && batchRunning ? 'Stopping batch …' : data.state === 'completed' ? 'Evaluation.' : data.state === 'failed' ? 'Run interrupted.' : 'Checking images.';
  $('batch-progress').textContent = `${data.completed} / ${data.total} images processed`;
  $('batch-ocr-summary').textContent = `${data.summary.valid} complete · ${data.summary.invalid} incomplete · ${data.summary.errors} errors · ${data.summary.cancelled || 0} cancelled · ${data.summary.pending} pending`;
  $('download-report').href = `/api/batches/${data.batch_id}/report.json`;
  renderDetectionEvaluation(data);
  renderEffects($('batch-effects'), data.summary.effects);
  const selectedCategory = $('report-category').value;
  $('report-category').replaceChildren(new Option('All categories', ''));
  for (const category of [...new Set(data.items.map(item => item.category))]) $('report-category').append(new Option(datasetLabels.get(category) || category,category));
  $('report-category').value = selectedCategory;
  const withDetection = !!data.detection_options;
  $('batch-detection-lane').hidden = !withDetection;
  $('batch-detection-summary').textContent = withDetection ? detectionBatchSummary(data) : '';
  const {element,body} = table(['Image','OCR completeness','Detection outcome','Details']);
  for (const item of data.items) {
    if ($('only-failures').checked && !(item.state === 'completed' && item.valid === false) && item.state !== 'failed') continue;
    if ($('report-category').value && item.category !== $('report-category').value) continue;
    const row = document.createElement('tr'), imageCell = cell(row,''); imageCell.className = 'image-name';
    const preview = document.createElement('img'); preview.className = 'table-image'; preview.src = `/api/datasets/${encodeURIComponent(item.dataset_id)}/thumbnail?dataset=${encodeURIComponent(data.dataset || 'ocr_evaluation')}`; preview.alt = ''; preview.loading = 'lazy'; imageCell.append(preview);
    const imageButton = document.createElement('button'); imageButton.type = 'button'; imageButton.className = 'table-link'; imageButton.textContent = item.image.split('/').at(-1); imageButton.title = item.image; imageButton.disabled = batchRunning || !item.run_id;
    imageButton.onclick = async () => { try { selectWorkbenchPage('scan'); clearRun(); history.replaceState(null,'',`/?batch=${data.batch_id}&run=${item.run_id}`); await restore(item.run_id); } catch (failure) { error(failure.message); } };
    imageCell.append(imageButton);
    const category = document.createElement('span'); category.className = 'muted'; category.textContent = datasetLabels.get(item.category) || item.category; imageCell.append(category);
    row.append(renderOCRStatus(item));
    row.append(renderDetectionStatus(item,withDetection));
    const detailsCell = cell(row,'');
    const details = document.createElement('details'); details.className = 'image-row-details';
    const key = `${data.batch_id}:${item.dataset_id}`; details.open = openImageDetails.has(key);
    const summary = document.createElement('summary'); summary.textContent = 'Text, labels and scores'; details.append(summary,renderImageDetails(item,data));
    details.addEventListener('toggle',() => { if (details.open) openImageDetails.add(key); else openImageDetails.delete(key); });
    detailsCell.append(details); body.append(row);
  }
  if (!body.children.length) {
    const row = document.createElement('tr');
    const empty = cell(row, $('only-failures').checked ? 'No OCR-incomplete or failed images in this selection.' : 'No images in this selection.');
    empty.colSpan = 4; body.append(row);
  }
  $('batch-images').replaceChildren(element);
  const activeItem = data.items.find(item => item.run_id === data.current_run_id) || data.items.find(item => item.state === 'running') || [...data.items].reverse().find(item => item.run_id);
  const selectedItem = activeItem || datasetItems.get([...selectedDatasets][0]);
  const imageUrl = activeItem?.run_id ? `/api/runs/${activeItem.run_id}/input` : selectedItem?.thumbnail_url;
  const detectorRunning = activeItem?.detection?.state === 'running' || activeItem?.cases?.some(sample => sample.state === 'running') || (batchRunning && detectionPhaseActive);
  const finalVerdict = activeItem?.detection?.verdict || activeItem?.cases?.[0]?.verdict || (activeItem?.run_id === data.current_run_id ? liveDetectionVerdict : null);
  $('counter').textContent = `${data.completed} / ${data.total} images`;
  $('progress').setAttribute('aria-label','Completed images'); $('progress').max = data.total || 1; $('progress').value = data.completed;
  $('status').textContent = data.cancel_requested && batchRunning ? 'Stopping after the current operation …' : ['completed','failed','cancelled'].includes(data.state) ? (data.state === 'completed' ? 'Evaluation complete.' : `Batch ${data.state}.`) : detectorRunning ? 'Running detection checks …' : activeItem?.state === 'running' ? `Scanning ${activeItem.image.split('/').at(-1)} …` : 'Preparing next image …';
  setScanActivity(imageUrl,detectorRunning ? 'detection' : activeItem?.state === 'completed' ? (finalVerdict || 'ocr_complete') : ['completed','failed','cancelled'].includes(data.state) ? (finalVerdict || (data.state === 'completed' ? 'ocr_complete' : data.state)) : 'scanning',finalVerdict || '');
  etaModel = ['completed','failed','cancelled'].includes(data.state)
    ? {done:data.total,total:data.total,started:batchStartedAt || Date.now(),label:data.state === 'completed' ? 'Complete' : `Batch ${data.state}`,terminal:true}
    : {done:data.completed - batchProgressAtStart,total:data.total - batchProgressAtStart,started:batchStartedAt || Date.now(),label:'batch'};
  updateEstimatedTime();
  renderCategories(data);
  updateEvaluationEmpty();
}
function renderDetectionEvaluation(data) {
  const evaluation = data.detection_evaluation;
  $('detection-evaluation').hidden = !evaluation;
  if (!evaluation) return;
  $('detection-evaluation-context').textContent = data.detection_context_mode === 'none'
    ? 'OCR and detection run once per image without context. The same verdict is scored against every case. Catalog context describes ground truth only; context-dependent misclassifications count normally.'
    : 'This saved report predates evaluation without context.';
  const labels = {overall:'Combined verdict',jev:'Jev',openai:'OpenAI Decisions','prompt-guard':'Prompt Guard 2',image:'Source image',context:'Image + OCR + context'};
  const outcomes = {true_positive:'True positive',true_negative:'True negative',false_positive:'False positive',false_negative:'False negative',unresolved:'Unresolved',error:'Error',cancelled:'Cancelled'};
  const percent = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
  const overall = evaluation.overall;
  $('detection-evaluation-progress').textContent = `${overall.completed} / ${overall.total} cases · ${overall.correct} correct · ${overall.incorrect} incorrect · ${overall.unresolved} unresolved · ${overall.error} errors · ${overall.cancelled || 0} cancelled · ${overall.pending} pending`;
  const metricLabels = {overall:'Combined verdict',jev:'Jev',openai:'OpenAI Decisions','prompt-guard':'Prompt Guard 2',image:'Source image',context:'Image + OCR + context'};
  const keyMetrics = $('detection-evaluation-key-metrics'); keyMetrics.replaceChildren();
  for (const [signal, stats] of [['overall',overall], ...Object.entries(evaluation.signals)]) {
    const card = document.createElement('article'); card.className = 'detection-metric-card';
    const title = document.createElement('h3'); title.textContent = metricLabels[signal] || signal;
    const measures = document.createElement('div'); measures.className = 'detection-metric-measures';
    const accuracy = document.createElement('section'), accuracyLabel = document.createElement('span'), accuracyValue = document.createElement('strong'), accuracyDetail = document.createElement('small');
    accuracyLabel.textContent = 'Correctness'; accuracyValue.textContent = percent(stats.accuracy); accuracyDetail.textContent = `${stats.correct} / ${stats.decided} decided cases correct`;
    accuracy.append(accuracyLabel,accuracyValue,accuracyDetail);
    const rate = document.createElement('section'), rateLabel = document.createElement('span'), rateValue = document.createElement('strong'), rateDetail = document.createElement('small');
    rateLabel.textContent = 'Detection rate'; rateValue.textContent = percent(stats.decision_rate); rateDetail.textContent = `${stats.decided} / ${stats.completed} completed cases decided`;
    rate.append(rateLabel,rateValue,rateDetail); measures.append(accuracy,rate);
    card.append(title,measures); keyMetrics.append(card);
  }
  const summary = table(['Detector','True positives','True negatives','False positives','False negatives','Unresolved','Errors','Cancelled','Pending','Accuracy (decided / n)','Detection rate (decided / completed)']);
  for (const [signal, stats] of [['overall',overall], ...Object.entries(evaluation.signals)]) {
    const row = document.createElement('tr'); cell(row, labels[signal] || signal);
    for (const field of ['true_positive','true_negative','false_positive','false_negative','unresolved','error','cancelled','pending']) cell(row, stats[field] || 0);
    cell(row, `${percent(stats.accuracy)} (${stats.correct}/${stats.decided})`); cell(row, percent(stats.decision_rate)); summary.body.append(row);
  }
  $('detection-evaluation-summary').replaceChildren(summary.element);
  const cases = table(['Image','Case','Ground-truth context','Expected','Verdict','Outcome','Details']);
  for (const item of data.items) for (const sample of item.cases || []) {
    const row = document.createElement('tr');
    const image = cell(row, '');
    const button = document.createElement('button'); button.type = 'button'; button.className = 'table-link';
    button.textContent = item.image.split('/').at(-1); button.disabled = batchRunning || !sample.check_id;
    button.onclick = async () => {
      try {
        selectWorkbenchPage('scan');
        clearRun(); history.replaceState(null,'',`/?batch=${data.batch_id}&run=${item.run_id}&check=${sample.check_id}`);
        await restore(item.run_id);
        await window.vipiDetection?.observeRun(item.run_id, true, sample.check_id);
        $('detection').scrollIntoView({block:'start',behavior:'instant'});
      } catch (failure) { error(failure.message); }
    };
    image.append(button); cell(row, sample.case_index);
    const context = cell(row, sample.context ? '' : 'No caller context');
    if (sample.context) {
      const detail = document.createElement('details'), title = document.createElement('summary'), text = document.createElement('pre');
      title.textContent = 'View ground-truth context'; text.textContent = sample.context; detail.append(title,text); context.append(detail);
    }
    cell(row, sample.expected); cell(row, sample.verdict || '—');
    cell(row, outcomes[sample.outcome] || (sample.state === 'running' ? 'Running' : 'Pending'));
    cell(row, sample.error || '—'); cases.body.append(row);
  }
  $('detection-evaluation-cases').replaceChildren(cases.element);
}
$('only-failures').onchange = () => { if (batchSnapshot) renderBatch(batchSnapshot); };
$('report-category').onchange = () => { if (batchSnapshot) renderBatch(batchSnapshot); };
$('category-summary-link').onclick = () => { $('batch-aggregate-details').open = true; };
function renderCategories(data) {
  const terminal = ['completed','failed','cancelled'].includes(data.state);
  $('category-summary').hidden = $('category-summary-link').hidden = !terminal;
  $('category-chart').replaceChildren(); if (!terminal) return;
  const categories = new Map((data.summary.categories || []).map(item => [item.id,item]));
  for (const id of datasetLabels.keys()) if (!categories.has(id)) categories.set(id,{id,total:0,processed:0,valid:0,invalid:0,errors:0,pending:0,success_rate:null});
  const ordered = [...categories.values()].sort((a,b) => (b.success_rate ?? -1) - (a.success_rate ?? -1) || b.processed - a.processed || (datasetLabels.get(a.id) || a.id).localeCompare(datasetLabels.get(b.id) || b.id,'en'));
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
    counts.textContent = category.total ? `${category.valid} / ${category.processed} valid · ${category.invalid} incomplete · ${category.errors} technical errors${category.cancelled ? ` · ${category.cancelled} cancelled` : ''}${category.pending ? ` · ${category.pending} pending` : ''}` : 'Not tested';
    row.setAttribute('aria-label', `${name.textContent}: ${rate.textContent}, ${counts.textContent}`);
    row.append(header,bar,counts);
    row.onclick = () => {
      $('report-category').value = $('report-category').value === category.id ? '' : category.id;
      renderBatch(data); $('batch-images').scrollIntoView({block:'start',behavior:'instant'});
    };
    $('category-chart').append(row);
  }
}
async function observeBatch(id, preferredRun = null, preferredCheck = null) {
  clearTimeout(batchTimer); batchId = id; updateCancelControl();
  try {
    const response = await fetch(`/api/batches/${id}`), data = await response.json();
    if (!response.ok) throw new Error(data.error);
    if ((data.dataset || 'ocr_evaluation') !== activeDataset) await switchDataset(data.dataset || 'ocr_evaluation');
    batchRunning = !['completed','failed','cancelled'].includes(data.state); cancellationRequested = batchRunning && !!data.cancel_requested; busy(batchRunning); renderBatch(data);
    const nextRun = !batchRunning && preferredRun ? preferredRun : data.current_run_id;
    if (nextRun && runId !== nextRun) {
      clearRun(); runId = nextRun; history.replaceState(null,'',`/?batch=${id}&run=${runId}${preferredCheck && !batchRunning ? `&check=${preferredCheck}` : ''}`); await restore(runId);
    }
    if (data.error) error(data.error);
    if (batchRunning) batchTimer = setTimeout(() => observeBatch(id),1000);
    else { busy(false); if (runId) await window.vipiDetection?.observeRun(runId, true, preferredCheck, true); }
  } catch (failure) {
    error(failure.message);
    if (batchRunning) batchTimer = setTimeout(() => observeBatch(id),3000);
  }
}
async function startSelection() {
  error(''); clearRun(); cancellationRequested = false; batchId = null; runId = null; batchStartedAt = Date.now(); batchProgressAtStart = 0; progress('queued'); batchRunning = true; busy(true); $('batch-report').hidden = $('category-summary').hidden = $('detection-evaluation').hidden = true; $('report-category').value = '';
  try {
    const detection = window.vipiDetection?.options(activeDataset === 'detection_evaluation');
    if (activeDataset === 'detection_evaluation' && !detection) throw new Error('Select at least one detector for detection evaluation.');
    const response = await fetch('/api/batches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset:activeDataset,dataset_ids:[...selectedDatasets],model:$('model').value,workers:Number($('workers').value),backend:$('backend').value,...(detection ? {detection} : {})})});
    const data = await response.json(); if (!response.ok) throw new Error(data.error);
    history.replaceState(null,'',`/?batch=${data.batch_id}`); selectWorkbenchPage('evaluation'); await observeBatch(data.batch_id);
  } catch (failure) { batchRunning = false; busy(false); $('run-progress').hidden = true; error(failure.message); }
}
function openOCRDetails() {
  if (!$('ocr-detail-dialog').open) $('ocr-detail-dialog').showModal();
  renderWorkers();
  for (const step of steps.values()) addVariant(step);
  if (latestStep?.image_url) showStep(latestStep);
  renderEvaluation(currentEvaluation);
}
$('open-ocr-details').onclick = openOCRDetails;
$('close-ocr-details').onclick = () => $('ocr-detail-dialog').close();
$('choose-dataset').onclick = () => $('dataset-dialog').showModal();
$('close-dataset').onclick = () => $('dataset-dialog').close();
initialize();
