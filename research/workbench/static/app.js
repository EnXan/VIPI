const $ = (id) => document.getElementById(id);
const svgNS = 'http://www.w3.org/2000/svg';
const states = {queued:'Preparing scan …',preparing:'Loading OCR model …',processing:'Processing variants in parallel …',transforming:'Transforming image …',ocr:'Recognizing text …',saving:'Saving result …',assembling:'Assembling text …',evaluating:'Checking reference text …',completed:'OCR complete.',failed:'Pipeline interrupted.',cancelled:'Scan cancelled.'};
let selectedFile, source, runId, total = 0, completed = 0, latestStep, displayedStep;
let running = false, followLive = true, filePreview, lastEvent = 0, currentState = 'queued';
const steps = new Map();
const workerStates = new Map();
let workerCount = 4, selectedWorker = null;
const selectedDatasets = new Set();
function selectedOCRModels() { return [...document.querySelectorAll('.ocr-model:checked')].map(input => input.value); }
function ocrModelLabel(id) { return [...$('model').options].find(option => option.value === id)?.textContent || id; }
function selectedModelChanged() { $('model').value = selectedOCRModels()[0] || ''; updateBackend(); busy(running); }
function imageThumbnail(item,data) { return item.dataset === 'upload' ? `/api/batches/${data.batch_id}/input` : `/api/datasets/${encodeURIComponent(item.dataset_id)}/thumbnail?dataset=${encodeURIComponent(item.dataset || data.dataset || 'ocr_evaluation')}`; }
function duration(value) { return Number.isFinite(value) ? `${value.toFixed(2)} s` : '—'; }
function money(value) { return Number.isFinite(value) ? `$${value.toFixed(6)}` : '—'; }
function safeLocalUrl(value) {
  try {
    const url = new URL(value, window.location.href);
    const sameOrigin = url.origin === window.location.origin;
    const localBlob = url.protocol === 'blob:' && sameOrigin;
    const localApi = sameOrigin && url.pathname.startsWith('/api/');
    return localBlob || localApi ? url.href : null;
  } catch {
    return null;
  }
}
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
  if (imageUrl) {
    const safeUrl = safeLocalUrl(imageUrl);
    if (safeUrl && image.getAttribute('src') !== safeUrl) image.src = safeUrl;
    else if (!safeUrl) image.removeAttribute('src');
  }
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
  $('label-page').hidden = page !== 'label';
  document.querySelector('main').dataset.page = page;
  $('tab-scan').setAttribute('aria-selected', String(page === 'scan'));
  $('tab-evaluation').setAttribute('aria-selected', String(page === 'evaluation'));
  $('tab-label').setAttribute('aria-selected', String(page === 'label'));
  if (page === 'label' && window.vipiCuration) window.vipiCuration.open();
  try { sessionStorage.setItem('vipi-workbench-page', page); } catch {}
}

function datasetSelectionKey(dataset, id) { return `${dataset}|${id}`; }
function selectionFromKey(key) {
  const separator = key.indexOf('|');
  return {dataset:key.slice(0,separator),id:key.slice(separator + 1)};
}
function hasDetectionSelection() {
  return [...selectedDatasets].some(key => selectionFromKey(key).dataset === 'detection_evaluation');
}
function selectedInputLabel() {
  if (selectedDatasets.size) {
    const collections = new Set([...selectedDatasets].map(key => selectionFromKey(key).dataset));
    return `${selectedDatasets.size} image${selectedDatasets.size === 1 ? '' : 's'} from ${collections.size > 1 ? 'both datasets' : collections.has('detection_evaluation') ? 'detection_evaluation' : 'ocr_evaluation'}`;
  }
  return selectedFile?.name || '';
}
function updateWizard() {
  $('input-next').disabled = running || batchRunning || (!selectedFile && !selectedDatasets.size);
  $('start').disabled = running || batchRunning || setupStep !== 3;
  const evaluation = hasDetectionSelection();
  $('text-classifiers').disabled = running || batchRunning;
  $('dataset-mode-note-options').hidden = !evaluation;
  $('threshold-required-note').textContent = evaluation
    ? 'Required when detection is enabled. Set a score threshold for every selected classifier and calibrate against labeled data.'
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
    ['Dataset mode', selectedDatasets.size ? (hasDetectionSelection() && new Set([...selectedDatasets].map(key => selectionFromKey(key).dataset)).size > 1 ? 'OCR + detection datasets' : hasDetectionSelection() ? 'Detection evaluation' : 'OCR evaluation') : 'Single image'],
    ['OCR models',selectedOCRModels().map(ocrModelLabel).join(' → ') || '—'],
    ['OCR profile',$('ocr-profile').selectedOptions[0]?.textContent || '—'],
    ['Hardware',$('backend').selectedOptions[0]?.textContent || '—'],
    ['Parallel workers',$('workers').value],
    ['Text classifiers',selectedClassifiers.length ? selectedClassifiers.join(', ') : 'None · OCR only'],
    ['Image check',$('image-check').value === 'openai' ? 'OpenAI Decisions' : 'Off'],
    ['Context check',$('context-check').value === 'openai' ? 'OpenAI Decisions' : 'Off'],
    ['Caller context',hasDetectionSelection() ? 'Not used for detection evaluation' : $('detector-context').value.trim() ? 'Configured' : 'None'],
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
  if (!selectedOCRModels().length || !$('backend').value || !$('workers').value) {
    showError('Choose an OCR model, hardware and worker count.'); return false;
  }
  const evaluation = hasDetectionSelection();
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
  for (const id of ['model','ocr-profile','backend','workers','image-input','dataset-category','dataset-search','select-matching','clear-selection','choose-dataset','dataset-ocr','dataset-detection','text-classifiers','image-check','context-check','detector-context','detector-threshold-version','detector-reuse','input-next','options-back','options-next','review-back']) $(id).disabled = running;
  for (const input of $('threshold-controls').querySelectorAll('input')) input.disabled = running;
  for (const input of document.querySelectorAll('.ocr-model')) input.disabled = running || input.dataset.available !== 'true';
  const withoutContext = hasDetectionSelection();
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
  $('ocr-profile').value = state.ocr_profile === 'adaptive-jev' ? 'adaptive-jev' : state.ocr_profile === 'original-only-v1' ? 'baseline' : 'transforms';
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
  $('input-preview').src = safeLocalUrl(filePreview) || '';
  $('input-preview').hidden = !$('input-preview').getAttribute('src'); busy(false);
}
$('image-input').onchange = () => selectFile($('image-input').files[0]);
$('dropzone').onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); if (!running) $('image-input').click(); } };
for (const name of ['dragenter','dragover']) $('dropzone').addEventListener(name, event => {event.preventDefault(); $('dropzone').classList.add('dragover');});
for (const name of ['dragleave','drop']) $('dropzone').addEventListener(name, event => {event.preventDefault(); $('dropzone').classList.remove('dragover');});
$('dropzone').addEventListener('drop', event => selectFile(event.dataTransfer.files[0]));
document.addEventListener('paste', event => { const item = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith('image/')); if (item) { event.preventDefault(); selectFile(item.getAsFile()); } });
function updateBackend() {
  const selected = selectedOCRModels();
  const documentVlm = selected.some(id => ['paddleocr-vl-1.6','granite-docling-258m'].includes(id) || id.startsWith('lightonocr-3-'));
  const apiModel = selected.some(id => ['mistral-ocr-4-1','google-cloud-vision','gpt-6-luna'].includes(id));
  const hardwareApplies = selected.some(id => id.startsWith('ppocr-v6'));
  const sequentialProfile = ['baseline','adaptive-jev'].includes($('ocr-profile').value);
  for (const option of $('workers').options) option.disabled = (documentVlm || apiModel || sequentialProfile) && option.value !== '1';
  if (documentVlm || apiModel || sequentialProfile) $('workers').value = '1';
  for (const option of $('backend').options) {
    option.disabled = option.dataset.available !== 'true' || (option.value !== 'cpu' && !hardwareApplies);
  }
  if (!hardwareApplies) $('backend').value = 'cpu';
  $('backend-note').textContent = selected.length > 1
    ? 'Models run sequentially. Hardware applies to PP-OCR; document models and APIs use their own runtime.'
    : $('ocr-profile').value === 'adaptive-jev'
    ? 'OpenAI Decisions reviews the image and OCR. Large or small-text cases also run local overlapping tiles.'
    : apiModel
    ? 'Sends each original image to the selected OCR API once.'
    : documentVlm
    ? 'The document model uses its own local runtime; Granite uses the Docling Transformers pipeline.'
    : $('backend').value === 'coreml'
    ? 'Apple selects the CPU, GPU, or Neural Engine. Speed and recognition may vary; not all operations are accelerated.'
    : $('backend').value === 'cuda'
      ? 'OCR runs on the NVIDIA GPU. Start with 1–2 workers; each worker needs its own GPU memory.'
      : 'CPU threads are distributed across workers.';
}
$('model').onchange = () => { updateBackend(); busy(running); };
$('ocr-profile').onchange = () => { updateBackend(); updateWizard(); };
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
  const body = new FormData(); body.append('image', selectedFile, selectedFile.name || 'clipboard.png'); body.append('model', selectedOCRModels()[0]); body.append('models', JSON.stringify(selectedOCRModels()));
  body.append('workers', $('workers').value);
  body.append('backend', $('backend').value);
  body.append('ocr_profile', $('ocr-profile').value);
  try {
    const detectionOptions = window.vipiDetection?.options();
    if (detectionOptions) body.append('detection', JSON.stringify(detectionOptions));
    window.vipiDetection?.reset();
    const response = await fetch('/api/runs', {method:'POST',body}); const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not start the pipeline.');
    if (data.batch_id) {
      batchRunning = true; history.replaceState(null,'',`/?batch=${data.batch_id}`);
      selectWorkbenchPage('evaluation'); await observeBatch(data.batch_id); return;
    }
    runId = data.run_id; updateCancelControl(); window.vipiDetection?.observeRun(runId, false); history.replaceState(null, '', `/?run=${runId}`); subscribe();
  } catch (failure) { error(failure.message); busy(false); progress('Could not start scan.'); }
};
async function initialize() {
  try {
    const response = await fetch('/api/models'); const data = await response.json();
    for (const model of data.models) {
      const option = new Option(model.label + (model.available ? '' : ' · not prepared'), model.id);
      option.disabled = !model.available; option.title = model.reason || ''; $('model').append(option);
      const label = document.createElement('label'), checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.className = 'ocr-model'; checkbox.value = model.id;
      checkbox.dataset.available = String(model.available); checkbox.disabled = !model.available;
      checkbox.onchange = selectedModelChanged; label.title = model.reason || '';
      label.append(checkbox,document.createTextNode(model.label + (model.available ? '' : ' · unavailable')));
      $('ocr-model-options').append(label);
    }
    const chosen = data.models.find(model => model.id === data.default && model.available) || data.models.find(model => model.available);
    $('model').value = chosen?.id || ''; if (!chosen) error('No OCR models are prepared. Run: uv run python -m research.workbench prepare-models');
    const checked = [...document.querySelectorAll('.ocr-model')].find(input => input.value === chosen?.id);
    if (checked) checked.checked = true;
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
    else if (!['scan','evaluation','label'].includes(page)) page = 'scan';
    selectWorkbenchPage(page);
    if (params.get('batch')) await observeBatch(params.get('batch'), params.get('run'), params.get('check'));
    else if (params.get('run')) await restore(params.get('run'));
  } catch (failure) { error(failure.message); }
}

function refreshSelection() {
  for (const input of document.querySelectorAll('.dataset-card input')) input.checked = selectedDatasets.has(input.value);
  const collections = new Set([...selectedDatasets].map(key => selectionFromKey(key).dataset));
  const source = collections.size > 1 ? 'from both datasets' : collections.has('detection_evaluation') ? 'from detection_evaluation' : collections.has('ocr_evaluation') ? 'from ocr_evaluation' : '';
  $('dataset-selected').textContent = `${selectedDatasets.size} image${selectedDatasets.size === 1 ? '' : 's'} selected${source ? ` ${source}` : ''}`;
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
      item.dataset = activeDataset;
      const key = datasetSelectionKey(activeDataset,item.id);
      datasetItems.set(key, item);
      const card = document.createElement('label'); card.className = 'dataset-card';
      const image = document.createElement('img'); image.src = item.thumbnail_url; image.alt = `${item.label} · ${item.name}`; image.loading = 'lazy';
      const label = document.createElement('span'); label.className = 'dataset-label';
      const input = document.createElement('input'); input.type = 'checkbox'; input.value = key; input.checked = selectedDatasets.has(key); input.setAttribute('aria-label', `${item.label}: ${item.name}`);
      input.onchange = () => { if (input.checked) { selectedDatasets.add(key); selectDataset(item); } else { selectedDatasets.delete(key); refreshSelection(); } };
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
$('select-matching').onclick = () => { if (!catalogPage) return; for (const id of catalogPage.matching_ids) selectedDatasets.add(datasetSelectionKey(activeDataset,id)); selectedFile = null; if (catalogPage.items[0]) selectDataset(catalogPage.items[0]); else refreshSelection(); };
$('clear-selection').onclick = () => { selectedDatasets.clear(); refreshSelection(); };
async function switchDataset(dataset) {
  activeDataset = dataset;
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
    ? 'Choose detection images for OCR-only scanning or enable detectors to evaluate the labeled cases.'
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
$('tab-label').onclick = () => selectWorkbenchPage('label');
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
async function observeBatch(id, preferredRun = null, preferredCheck = null) {
  clearTimeout(batchTimer); batchId = id; updateCancelControl();
  try {
    const response = await fetch(`/api/batches/${id}`), data = await response.json();
    if (!response.ok) throw new Error(data.error);
    if (['ocr_evaluation','detection_evaluation'].includes(data.dataset) && data.dataset !== activeDataset) await switchDataset(data.dataset);
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
    const detection = window.vipiDetection?.options(hasDetectionSelection());
    const response = await fetch('/api/batches',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selections:[...selectedDatasets].map(selectionFromKey),models:selectedOCRModels(),ocr_profile:$('ocr-profile').value,workers:Number($('workers').value),backend:$('backend').value,...(detection ? {detection} : {})})});
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
$('best-variant').onclick = () => { if (currentEvaluation) inspectStep(currentEvaluation.best_step_id); };
$('only-failures').onchange = () => { if (batchSnapshot) renderBatch(batchSnapshot); };
$('report-category').onchange = () => { if (batchSnapshot) renderBatch(batchSnapshot); };
$('report-model').onchange = () => { if (batchSnapshot) renderBatch(batchSnapshot); };
$('category-summary-link').onclick = () => { $('batch-aggregate-details').open = true; };

initialize();
