'use strict';
// Workbench shell: page tabs, "Scan an image" and "Evaluate". Dataset lives in curation.js.

const $ = id => document.getElementById(id);
const state = {configurations: [], defaultConfiguration: null, threshold: 80, image: null, runId: null};
const POLL_MS = 1000;

/** @param {string} url @param {object} [options] */
async function request(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}
const postJson = (url, body = {}) => request(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});

function showError(message) {
  $('error').textContent = message || '';
  $('error').hidden = !message;
}
const percent = value => (value === null || value === undefined) ? '—' : `${(value * 100).toFixed(1)}%`;
const points = value => (value === null || value === undefined) ? '' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)} pp`;
function element(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === 'class') node.className = value; else if (value !== undefined && value !== null) node.setAttribute(key, value);
  }
  for (const child of children) node.append(child instanceof Node ? child : String(child ?? ''));
  return node;
}
const configuration = id => state.configurations.find(item => item.id === id);

// Pages

function selectPage(page) {
  for (const name of ['scan', 'evaluation', 'dataset']) {
    $(`${name}-page`).hidden = page !== name;
    $(`tab-${name}`).setAttribute('aria-selected', String(page === name));
  }
  document.querySelector('main').dataset.page = page;
  showError('');
  if (page === 'dataset' && window.vipiCuration) window.vipiCuration.open();
  if (page === 'evaluation') { refreshEvaluationSetup(); refreshRuns(); }
  try { sessionStorage.setItem('vipi-workbench-page', page); } catch { /* storage unavailable */ }
}
for (const name of ['scan', 'evaluation', 'dataset']) $(`tab-${name}`).onclick = () => selectPage(name);

// Settings: where the scan runs and which text recognition it uses

/**
 * Render "Run on" and "Text recognition" (and optionally the threshold) into a container.
 * @returns {{value: () => string, threshold: () => number}}
 */
function settingsPanel(container, {withThreshold, onChange}) {
  const name = container.id;
  const runOn = element('fieldset', {class: 'choice'}, element('legend', {}, 'Run on'));
  for (const [value, title, note] of [
    ['local', 'This computer', 'Free. Needs the models from vipi setup.'],
    ['cloud', 'Cloud', 'Paid API calls. Needs the provider API keys on the server.'],
  ]) {
    runOn.append(element('label', {}, element('input', {type: 'radio', name: `${name}-run-on`, value}), ' ',
      element('span', {}, element('strong', {}, title), element('br'), element('span', {class: 'muted'}, note))));
  }
  const ocr = element('select', {id: `${name}-ocr`});
  const ocrLabel = element('label', {class: 'field'}, 'Text recognition (OCR)', ocr);
  container.append(runOn, ocrLabel);
  let threshold = null;
  if (withThreshold) {
    threshold = element('input', {id: `${name}-threshold`, type: 'number', min: '0', max: '100', step: '1', value: String(state.threshold)});
    container.append(element('label', {class: 'field'}, 'Flag as injection at a detector score of at least (0–100)', threshold,
      element('span', {class: 'muted'}, `Product default: ${state.threshold}.`)));
  }
  const selected = () => container.querySelector(`input[name="${name}-run-on"]:checked`).value;
  function fillOcr(keep) {
    const choices = state.configurations.filter(item => item.run_on === selected());
    ocr.replaceChildren(...choices.map(item => element('option', {value: item.id}, item.ocr_label)));
    if (choices.some(item => item.id === keep)) ocr.value = keep;
  }
  const initial = configuration(state.defaultConfiguration);
  container.querySelector(`input[value="${initial.run_on}"]`).checked = true;
  fillOcr(initial.id);
  runOn.onchange = () => { fillOcr(); onChange(); };
  ocr.onchange = onChange;
  if (threshold) threshold.oninput = onChange;
  return {
    value: () => ocr.value,
    threshold: () => (threshold ? Number(threshold.value) : state.threshold),
  };
}

// Scan an image

let scanSettings;
function updateScanSummary() {
  const item = configuration(scanSettings.value());
  const threshold = scanSettings.threshold();
  const valid = Number.isFinite(threshold) && threshold >= 0 && threshold <= 100;
  $('scan-settings-summary').textContent = `${item.label} · flagged at score ≥ ${valid ? threshold : '?'}${item.paid ? ' · paid API calls' : ''}`;
  $('scan-start').disabled = !state.image || !valid;
}
$('scan-settings-toggle').onclick = () => {
  const open = $('scan-settings').hidden;
  $('scan-settings').hidden = !open;
  $('scan-settings-toggle').setAttribute('aria-expanded', String(open));
  $('scan-settings-toggle').textContent = open ? 'Hide settings' : 'Change settings';
};

function chooseImage(file) {
  if (!file || !file.type.startsWith('image/')) { showError('Choose a PNG, JPEG or WEBP image.'); return; }
  showError('');
  state.image = file;
  const preview = $('input-preview');
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  $('file-label').textContent = file.name || 'Pasted image';
  $('scan-status').textContent = 'Ready to scan.';
  updateScanSummary();
}
$('image-input').onchange = event => chooseImage(event.target.files[0]);
const dropzone = $('dropzone');
dropzone.ondragover = event => { event.preventDefault(); dropzone.classList.add('dragover'); };
dropzone.ondragleave = () => dropzone.classList.remove('dragover');
dropzone.ondrop = event => { event.preventDefault(); dropzone.classList.remove('dragover'); chooseImage(event.dataTransfer.files[0]); };
dropzone.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); $('image-input').click(); } };
document.addEventListener('paste', event => {
  if ($('scan-page').hidden) return;
  const file = [...event.clipboardData.files].find(item => item.type.startsWith('image/'));
  if (file) chooseImage(file);
});

const VERDICTS = {
  flagged: ['Prompt injection found', 'The detector flagged the recognized text.'],
  not_flagged: ['No prompt injection found', 'The detector did not flag the recognized text.'],
  unclear: ['Unclear — review the image', 'The scan could not decide; see the problems below.'],
};
function renderScan(job) {
  const result = job.result;
  $('scan-result').hidden = false;
  const banner = $('verdict-banner');
  if (job.state === 'failed') {
    banner.dataset.verdict = 'failed';
    $('scan-verdict').textContent = 'The scan failed';
    $('scan-verdict-note').textContent = job.error;
  } else {
    const [title, note] = VERDICTS[result.verdict] || [result.verdict, ''];
    banner.dataset.verdict = result.verdict;
    $('scan-verdict').textContent = title;
    $('scan-verdict-note').textContent = note;
  }
  const facts = result ? [
    ['Detector score', result.score === null ? '—' : `${Math.round(result.score * 100)} (flagged at ≥ ${job.threshold})`],
    ['Settings', configuration(job.configuration).label],
    ['Time', `${(result.ocr_seconds + result.detection_seconds).toFixed(1)} s`],
    ['API cost', result.cost_usd === null ? 'unknown' : `$${result.cost_usd.toFixed(4)}`],
  ] : [['Settings', configuration(job.configuration).label]];
  $('scan-facts').replaceChildren(...facts.flatMap(([term, value]) => [element('dt', {}, term), element('dd', {}, value)]));
  const errors = result ? result.errors : [];
  $('scan-errors').replaceChildren(...errors.map(text => element('li', {}, text)));
  $('scan-errors').hidden = !errors.length;
  $('scan-text').textContent = result ? (result.text || '(no text found)') : '';
  $('scan-steps-details').hidden = !job.steps.length;
  $('scan-steps-summary').textContent = `OCR passes (${job.steps.length})`;
  $('scan-steps').replaceChildren(...job.steps.map(step => element('figure', {class: 'step'},
    element('img', {src: step.image_url, alt: step.label, loading: 'lazy'}),
    element('figcaption', {}, element('strong', {}, step.label), element('pre', {}, step.text || '(no text)')))));
}
$('copy-text').onclick = () => navigator.clipboard.writeText($('scan-text').textContent);

$('scan-start').onclick = async () => {
  showError('');
  const form = new FormData();
  form.append('image', state.image, state.image.name || 'pasted.png');
  form.append('configuration', scanSettings.value());
  form.append('threshold', String(scanSettings.threshold()));
  $('scan-start').disabled = true;
  $('scan-result').hidden = true;
  $('scan-status').textContent = 'Starting…';
  try {
    const {id} = await request('/api/scans', {method: 'POST', body: form});
    for (;;) {
      const job = await request(`/api/scans/${id}`);
      if (job.state === 'done' || job.state === 'failed') {
        $('scan-status').textContent = job.state === 'done' ? 'Done.' : 'Failed.';
        renderScan(job);
        break;
      }
      $('scan-status').textContent = job.state === 'checking' ? 'Checking the text for prompt injection…' : 'Reading the text in the image…';
      await new Promise(resolve => setTimeout(resolve, POLL_MS));
    }
  } catch (error) {
    showError(error.message);
    $('scan-status').textContent = '';
  } finally {
    updateScanSummary();
  }
};

// Evaluate

let evaluationSettings;
const selectedSplit = () => document.querySelector('input[name="split"]:checked').value;
function describeBaseline(baseline) {
  if (baseline.state === 'none') return 'No baseline saved for these settings yet. After this run you can save it as the baseline.';
  const when = baseline.completed_at ? ` from ${baseline.completed_at.slice(0, 10)}` : '';
  if (baseline.state === 'fresh') return `Baseline ${baseline.run_id}${when} matches this checkout. The run will be compared with it.`;
  return `Baseline ${baseline.run_id}${when} is out of date (changed: ${baseline.differences.join(', ')}). The comparison will be marked "not the same inputs"; save a new baseline before comparing changes.`;
}
let setupRequest = 0;
async function refreshEvaluationSetup() {
  if (!evaluationSettings) return;
  const ticket = ++setupRequest;
  const split = selectedSplit();
  const item = configuration(evaluationSettings.value());
  $('test-confirm-row').hidden = split !== 'test';
  $('baseline-status').textContent = 'Checking the saved baseline…';
  $('evaluation-start').disabled = true;
  try {
    const params = new URLSearchParams({configuration: item.id, split});
    const setup = await request(`/api/evaluations/setup?${params}`);
    if (ticket !== setupRequest) return;
    $(`split-${split}-count`).textContent = `(${setup.entries} images)`;
    $('baseline-status').textContent = describeBaseline(setup.baseline);
    $('baseline-status').dataset.state = setup.baseline.state;
    $('evaluation-cost').hidden = !item.paid;
    $('evaluation-cost').textContent = `Cloud runs make paid API calls (OCR, review and detection) for each of the ${setup.entries} images.`;
    $('evaluation-start').disabled = split === 'test' && !$('test-confirm').checked;
    $('evaluation-start').textContent = `Start evaluation · ${item.label} · ${setup.entries} images`;
  } catch (error) {
    if (ticket === setupRequest) $('baseline-status').textContent = error.message;
  }
}
for (const input of document.querySelectorAll('input[name="split"]')) input.onchange = refreshEvaluationSetup;
$('test-confirm').onchange = refreshEvaluationSetup;

$('evaluation-start').onclick = async () => {
  showError('');
  const item = configuration(evaluationSettings.value());
  if (item.paid && !window.confirm(`Start a paid cloud evaluation with ${item.label}?`)) return;
  try {
    const {run_id: runId} = await postJson('/api/evaluations', {configuration: item.id, split: selectedSplit(), confirm_test: $('test-confirm').checked});
    openRun(runId);
    refreshRuns();
  } catch (error) { showError(error.message); }
};

const RUN_STATES = {running: 'Running', stopping: 'Stopping', stopped: 'Stopped — resume to finish', complete: 'Complete', failed: 'Failed'};
let pollTimer = null;
async function openRun(runId) {
  state.runId = runId;
  clearTimeout(pollTimer);
  try {
    renderRun(await request(`/api/evaluations/${runId}`));
  } catch (error) { showError(error.message); }
}

function metricRow(label, metric, fields, rate = true) {
  const pick = values => fields.reduce((value, field) => (value ?? {})[field], values);
  return {label, metric, fields, rate, pick};
}
const HEADLINE = [
  metricRow('OCR word coverage', 'word coverage (tolerant)', ['word_weighted_coverage']),
  metricRow('Images fully read', 'full reference pass', ['image_rates', 'reference_pass']),
  metricRow('Attacks flagged', 'attacks flagged (recall)', ['detection', 'recall']),
  metricRow('Benign images flagged', 'benign flagged (false-positive rate)', ['detection', 'false_positive_rate']),
  metricRow('Detection accuracy', 'detection accuracy', ['detection', 'accuracy']),
];
const LOWER_IS_BETTER = new Set(['benign flagged (false-positive rate)']);

function renderRun(run) {
  const item = configuration(run.configuration);
  $('run-view').hidden = false;
  $('run-eyebrow').textContent = `${run.split.toUpperCase()} SPLIT · ${run.run_id}`;
  $('run-title').textContent = `${item ? item.label : run.configuration} — ${RUN_STATES[run.state]}`;
  const active = run.state === 'running' || run.state === 'stopping';
  $('run-stop').hidden = run.state !== 'running';
  $('run-resume').hidden = !(run.state === 'stopped' || run.state === 'failed');
  $('run-progress-block').hidden = run.state === 'complete';
  $('run-progress').max = run.progress.total || 1;
  $('run-progress').value = run.progress.done;
  $('run-progress-text').textContent = `${run.progress.done} of ${run.progress.total} images scanned${run.state === 'stopping' ? ' · stopping after the current image' : ''}`;
  $('run-error').hidden = !run.error;
  $('run-error').textContent = run.error || '';
  for (const [id, url] of [['run-report', run.report_url], ['run-comparison', run.comparison_url]]) {
    $(id).hidden = !url;
    if (url) $(id).href = url;
  }
  const comparison = run.comparison;
  const note = $('run-baseline-note');
  if (run.is_baseline) note.textContent = 'This run is the saved baseline.';
  else if (comparison) note.textContent = comparison.matched
    ? `Compared with baseline ${comparison.baseline.run_id} (same inputs).`
    : `Compared with baseline ${comparison.baseline.run_id}, but the inputs differ (${comparison.differences.join(', ')}). This is not a direct comparison.`;
  else note.textContent = run.state === 'complete' ? 'No baseline was saved when this run finished, so there is nothing to compare with.' : '';
  note.dataset.state = comparison && !comparison.matched ? 'stale' : '';
  renderMetrics(run);
  renderChanges(comparison);
  // Partial reports count unscanned images as misses; show results only when complete.
  renderContents(run.state === 'complete' ? run.contents : []);
  $('run-save').hidden = run.state !== 'complete' || run.is_baseline;
  if (active) pollTimer = setTimeout(() => openRun(run.run_id), POLL_MS * 2);
  else refreshRuns();
}

function renderMetrics(run) {
  if (!run.metrics) { $('run-metrics').replaceChildren(); return; }
  const aggregates = Object.fromEntries((run.comparison?.aggregates || []).map(row => [row.metric, row]));
  $('run-metrics').replaceChildren(...HEADLINE.map(row => {
    const value = row.pick(run.metrics);
    const compared = aggregates[row.metric];
    const children = [element('span', {class: 'metric-label'}, row.label), element('strong', {}, percent(value))];
    if (compared && compared.delta !== null) {
      const better = LOWER_IS_BETTER.has(row.metric) ? compared.delta < 0 : compared.delta > 0;
      children.push(element('span', {class: `delta ${compared.delta === 0 ? '' : better ? 'better' : 'worse'}`},
        `${points(compared.delta)} vs. baseline ${percent(compared.baseline)}`));
    }
    return element('div', {class: 'metric'}, ...children);
  }));
  const detection = run.metrics.detection;
  $('run-metrics').append(element('p', {class: 'muted metric-note'},
    `${detection.attacks.flagged} of ${detection.attacks.images} attacks and ${detection.benign.flagged} of ${detection.benign.images} benign images flagged; ${detection.unclear} unclear, ${detection.no_result} without result. OCR uses the ${run.metrics.referenced} images with reference text.`));
}

const CHANGE_TITLES = {
  detection_regressed: 'Detection now wrong',
  detection_improved: 'Detection now right',
  newly_failed: 'Scan newly failed',
  recovered: 'Scan recovered',
  regressed: 'OCR got worse',
  improved: 'OCR got better',
};
function renderChanges(comparison) {
  const counts = comparison?.case_counts;
  if (!counts) { $('run-changes').replaceChildren(); return; }
  $('run-changes').replaceChildren(element('h3', {}, 'Changed images compared with the baseline'),
    element('ul', {class: 'changes'}, ...Object.entries(CHANGE_TITLES).map(([key, title]) =>
      element('li', {'data-kind': key.includes('regressed') || key === 'newly_failed' ? 'worse' : 'better'}, element('strong', {}, counts[key]), ` ${title}`))),
    element('p', {class: 'muted'}, 'The comparison report lists every changed image.'));
}

function renderContents(contents) {
  if (!contents.length) { $('run-contents').replaceChildren(); return; }
  const head = element('tr', {}, ...['Content', 'Images', 'OCR word coverage', 'Attacks flagged', 'Benign flagged', 'Accuracy'].map(text => element('th', {}, text)));
  const rows = contents.map(row => element('tr', {}, element('td', {}, row.content.replaceAll('_', ' ')), element('td', {}, row.images),
    element('td', {}, percent(row.word_coverage)), element('td', {}, percent(row.recall)), element('td', {}, percent(row.false_positive_rate)), element('td', {}, percent(row.accuracy))));
  $('run-contents').replaceChildren(element('table', {}, element('caption', {}, 'By content type'), element('thead', {}, head), element('tbody', {}, ...rows)));
}

$('run-stop').onclick = async () => { await postJson(`/api/evaluations/${state.runId}/stop`).catch(error => showError(error.message)); openRun(state.runId); };
$('run-resume').onclick = async () => {
  try { await postJson(`/api/evaluations/${state.runId}/resume`); openRun(state.runId); } catch (error) { showError(error.message); }
};
$('run-save-button').onclick = async () => {
  try {
    const {path} = await postJson(`/api/evaluations/${state.runId}/baseline`);
    window.alert(`Saved as the baseline: ${path}. Commit this file.`);
    openRun(state.runId);
    refreshEvaluationSetup();
  } catch (error) { showError(error.message); }
};

async function refreshRuns() {
  try {
    const {runs} = await request('/api/evaluations');
    $('runs-empty').hidden = runs.length > 0;
    if (!runs.length) { $('runs').replaceChildren(); return; }
    const head = element('tr', {}, ...['Run', 'Settings', 'Images', 'State', ''].map(text => element('th', {}, text)));
    const rows = runs.map(run => {
      const open = element('button', {class: 'small', type: 'button'}, 'Open');
      open.onclick = () => { openRun(run.run_id); $('run-view').scrollIntoView({behavior: 'smooth'}); };
      const label = configuration(run.configuration)?.label || run.configuration;
      return element('tr', {}, element('td', {class: 'mono'}, run.run_id.slice(0, 15)), element('td', {}, `${label} · ${run.split}`),
        element('td', {}, `${run.progress.done}/${run.progress.total}`), element('td', {}, `${RUN_STATES[run.state]}${run.is_baseline ? ' · baseline' : ''}`), element('td', {}, open));
    });
    $('runs').replaceChildren(element('table', {}, element('thead', {}, head), element('tbody', {}, ...rows)));
  } catch (error) { showError(error.message); }
}

// Start

(async () => {
  try {
    const options = await request('/api/configurations');
    state.configurations = options.configurations;
    state.defaultConfiguration = options.default;
    state.threshold = options.threshold;
    scanSettings = settingsPanel($('scan-settings'), {withThreshold: true, onChange: updateScanSummary});
    evaluationSettings = settingsPanel($('evaluation-settings'), {withThreshold: false, onChange: refreshEvaluationSetup});
    updateScanSummary();
    let page = 'scan';
    try { page = sessionStorage.getItem('vipi-workbench-page') || 'scan'; } catch { /* storage unavailable */ }
    selectPage(['scan', 'evaluation', 'dataset'].includes(page) ? page : 'scan');
  } catch (error) { showError(error.message); }
})();
