// Report rendering uses the shared workbench state and controls from app.js.

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
    label.textContent = `${score.valid ? 'Complete' : 'Incomplete'} · ${(score.coverage * 100).toFixed(1)}% ${evaluation.version >= 3 ? 'words' : 'reference'}${score.exact ? ` · ${(score.exact.coverage * 100).toFixed(1)}% exact` : ''}`;
    card.querySelector('.label').after(label);
  }
  if (!evaluation) return;
  const wordCoverage = evaluation.version >= 3;
  $('evaluation-heading').textContent = evaluation.final.valid ? 'Reference covered in final text.' : 'Reference incomplete in final text.';
  $('evaluation-rule').textContent = wordCoverage
    ? `Pass: all reference words are covered in the final scanner text. Minor OCR errors are allowed: one edit for words of 2–9 characters; up to ${100 * evaluation.policy.word_error_rate}% for longer words. Single characters must match after normalization. Case and punctuation are ignored for coverage; exact words retain literal case and attached symbols. Split OCR fragments may cover one reference word. Additional text is allowed. ${evaluation.method === 'word_regions' ? `Matches must overlap annotated reference regions. Word order is preserved within each region and ignored between regions.${evaluation.reference.regions_are_independent ? ' OCR regions spanning multiple independent reference regions count as group conflicts.' : ''}` : 'Reference word order is preserved.'} Scope: ${evaluation.reference.scope}. Annotation quality: ${evaluation.reference.quality}.`
    : `Legacy evaluation v${evaluation.version}: exact normalized tokens, including punctuation. It has not been rescored with tolerant word coverage. Annotation quality: ${evaluation.reference.quality}.`;
  $('evaluation-scores').replaceChildren();
  const initialScore = evaluation.original ? ['Original',evaluation.original] : ['First OCR attempt',evaluation.first_attempt];
  for (const [name,score] of [initialScore,['Pipeline diagnostic',evaluation.detection],['Final text (primary)',evaluation.final]]) {
    if (!score) continue;
    const panel = document.createElement('div'); panel.className = 'evaluation-score';
    const title = document.createElement('span'); title.textContent = name;
    const value = document.createElement('strong'); value.textContent = `${(score.coverage * 100).toFixed(1)} %`;
    const state = document.createElement('span'); state.textContent = score.valid ? 'Valid' : 'Incomplete';
    panel.append(title,value,state); $('evaluation-scores').append(panel);
    if (score.exact) {
      const fidelity = document.createElement('span');
      fidelity.textContent = `${(score.exact.coverage * 100).toFixed(1)}% exact words`;
      panel.append(fidelity);
    }
  }
  const missing = evaluation.final.missing.length ? `Missing from final text: ${evaluation.final.missing.join(' ')}` : `${evaluation.valid_step_ids.length} variants also cover the full reference.`;
  const groupConflicts = evaluation.final.group_conflicts || [];
  $('evaluation-missing').textContent = groupConflicts.length
    ? `${missing} Group conflicts: ${groupConflicts.length} OCR regions overlap multiple independent reference regions.`
    : missing;
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
      button.textContent = `${(score.coverage * 100).toFixed(1)} %${score.valid ? ' ✓' : ''}`;
      button.title = `${step.label}${score.exact ? ` · ${(score.exact.coverage * 100).toFixed(1)}% exact words` : ''}`;
      button.onclick = () => inspectStep(step.id); td.append(button);
    }
    body.append(row);
  }
  $('evaluation-matrix').replaceChildren(element);
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
  image.src = imageThumbnail(item,data);
  image.alt = item.image.split('/').at(-1); image.loading = 'lazy'; content.append(image);
  const text = document.createElement('div'); text.className = 'image-evaluation-text';
  const payload = item.cases?.[0]?.payload;
  const reference = addDetailText(text,'Reference text',item.reference_text || payload || 'Not available in this saved report.');
  const recognized = addDetailText(text,'Recognized text',item.recognized_text ?? (item.state === 'queued' || item.state === 'running' ? 'Waiting for OCR to finish.' : 'Not available in this saved report.'));
  if ((item.reference_available !== false && !item.reference_text && !payload) || (item.recognized_text == null && item.state === 'completed')) {
    const loadText = document.createElement('button'); loadText.type = 'button'; loadText.className = 'small'; loadText.textContent = 'Load saved text';
    loadText.onclick = async () => {
      loadText.disabled = true; loadText.textContent = 'Loading …';
      try {
        if (item.reference_available !== false && !item.reference_text && !payload) {
          const response = await fetch(`/api/datasets/${encodeURIComponent(item.dataset_id)}/reference?dataset=${encodeURIComponent(item.dataset || data.dataset || 'ocr_evaluation')}`);
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
  if (item.scoring_unavailable) addDetailText(text,'Scoring unavailable',item.scoring_unavailable);
  if (item.cost) addDetailText(text,'API cost estimate and usage',JSON.stringify(item.cost,null,2));
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
  const state = item.state === 'cancelled' ? 'Cancelled' : item.state === 'running' ? 'Running' : item.state === 'failed' ? 'Failed' : item.state === 'queued' ? 'Pending' : item.valid == null ? 'Unscored' : item.valid ? 'Complete' : 'Incomplete';
  const badge = document.createElement('span'); badge.className = `result-badge ocr-${state.toLowerCase()}`; badge.textContent = state; cell.append(badge);
  if (item.coverage !== undefined) {
    const coverage = document.createElement('span'); coverage.className = 'result-detail'; coverage.textContent = `${(item.coverage * 100).toFixed(1)}% ${item.evaluation_version >= 3 ? 'words' : 'reference'}`; cell.append(coverage);
  }
  if (item.exact_coverage != null) {
    const exact = document.createElement('span'); exact.className = 'result-detail';
    exact.textContent = `${(item.exact_coverage * 100).toFixed(1)}% exact words`; cell.append(exact);
  }
  if (item.group_conflicts?.length) {
    const conflicts = document.createElement('span'); conflicts.className = 'result-detail';
    conflicts.textContent = `${item.group_conflicts.length} group conflict${item.group_conflicts.length === 1 ? '' : 's'}`; cell.append(conflicts);
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
  const profileLabels = {baseline:'Original only · baseline',transforms:'Previous VIPI pipeline','adaptive-jev':'Decisions + local recovery'};
  const profileLabel = profileLabels[data.ocr_profile] || 'Historical profile';
  $('batch-progress').textContent = `${data.completed} / ${data.total} model/image runs · ${data.images_per_model || data.total} images × ${(data.models || [data.model]).length} models · ${profileLabel}`;
  const performanceTable = table(['Model','State','Scored images','Pass rate','Mean / median / P95','Est. API cost','Unknown costs','Cost per passed image']);
  for (const model of data.model_summaries || []) {
    const row = document.createElement('tr'), perf = model.performance || {};
    cell(row,ocrModelLabel(model.model)); cell(row,model.state);
    cell(row,`${model.summary.valid + model.summary.invalid + model.summary.errors}/${model.summary.total}`);
    cell(row,model.summary.pass_rate == null ? '—' : `${(100*model.summary.pass_rate).toFixed(1)}%`);
    cell(row,`${duration(perf.mean_seconds)} / ${duration(perf.median_seconds)} / ${duration(perf.p95_seconds)}`);
    cell(row,money(perf.estimated_api_cost_usd)); cell(row,perf.cost_unknown_images || 0);
    cell(row,money(perf.estimated_api_cost_per_pass_usd)); performanceTable.body.append(row);
  }
  $('model-comparison').replaceChildren(performanceTable.element);
  const selectedModel = $('report-model').value;
  $('report-model').replaceChildren(new Option('All models',''));
  for (const id of data.models || [data.model]) $('report-model').append(new Option(ocrModelLabel(id),id));
  $('report-model').value = selectedModel;
  const wordCoverage = data.evaluation_policy?.version >= 3;
  const percent = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
  $('batch-ocr-heading').textContent = wordCoverage ? 'OCR word coverage' : 'Legacy exact-token coverage';
  $('batch-ocr-summary').textContent = `${percent(data.summary.pass_rate)} pass rate · ${data.summary.valid} complete · ${data.summary.invalid} incomplete · ${data.summary.errors} errors · ${data.summary.cancelled || 0} cancelled · ${data.summary.pending} pending`;
  $('batch-exact-summary').hidden = !wordCoverage;
  $('batch-exact-summary').textContent = `${percent(data.summary.exact_pass_rate)} exact-word pass rate · ${data.summary.exact_valid || 0} / ${data.summary.exact_evaluated || 0} processed images · ${percent(data.summary.mean_exact_word_coverage)} mean exact word coverage`;
  $('batch-evaluation-rule').textContent = wordCoverage
    ? `A case passes when all annotated reference words are covered in the final scanner text, allowing minor spelling errors. Mean word coverage: ${percent(data.summary.mean_word_coverage)}. Exact words are scored separately with literal case and attached symbols. Pending and cancelled images are excluded; technical errors count as failed cases. References may cover only the annotated payload, not every visible text region.`
    : 'Historical exact-token results are preserved. Start a new evaluation to measure tolerant word coverage and separate exact-word fidelity.';
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
  const {element,body} = table(['Model','Image','Scan duration','OCR / initialization','Est. API cost',wordCoverage ? 'Word coverage / exact words' : 'Legacy OCR completeness','Detection outcome','Details']);
  for (const item of data.items) {
    if ($('only-failures').checked && !(item.state === 'completed' && item.valid === false) && item.state !== 'failed') continue;
    if ($('report-category').value && item.category !== $('report-category').value) continue;
    if ($('report-model').value && (item.model || data.model) !== $('report-model').value) continue;
    const row = document.createElement('tr'); cell(row,ocrModelLabel(item.model || data.model));
    const imageCell = cell(row,''); imageCell.className = 'image-name';
    const preview = document.createElement('img'); preview.className = 'table-image'; preview.src = imageThumbnail(item,data); preview.alt = ''; preview.loading = 'lazy'; imageCell.append(preview);
    const imageButton = document.createElement('button'); imageButton.type = 'button'; imageButton.className = 'table-link'; imageButton.textContent = item.image.split('/').at(-1); imageButton.title = item.image; imageButton.disabled = batchRunning || !item.run_id;
    imageButton.onclick = async () => { try { selectWorkbenchPage('scan'); clearRun(); history.replaceState(null,'',`/?batch=${data.batch_id}&run=${item.run_id}`); await restore(item.run_id); } catch (failure) { error(failure.message); } };
    imageCell.append(imageButton);
    const category = document.createElement('span'); category.className = 'muted'; category.textContent = datasetLabels.get(item.category) || item.category; imageCell.append(category);
    cell(row,duration(item.elapsed_seconds)); cell(row,`${duration(item.inference_seconds)} / ${duration(item.initialization_seconds)}`);
    const costCell = cell(row,money(item.cost?.estimated_usd)); costCell.title = item.cost?.note || 'Cost unavailable';
    row.append(renderOCRStatus(item));
    row.append(renderDetectionStatus(item,withDetection));
    const detailsCell = cell(row,'');
    const details = document.createElement('details'); details.className = 'image-row-details';
    const key = `${data.batch_id}:${item.model || data.model}:${item.dataset_id}`; details.open = openImageDetails.has(key);
    const summary = document.createElement('summary'); summary.textContent = 'Text, labels and scores'; details.append(summary,renderImageDetails(item,data));
    details.addEventListener('toggle',() => { if (details.open) openImageDetails.add(key); else openImageDetails.delete(key); });
    detailsCell.append(details); body.append(row);
  }
  if (!body.children.length) {
    const row = document.createElement('tr');
    const empty = cell(row, $('only-failures').checked ? 'No OCR-incomplete or failed images in this selection.' : 'No images in this selection.');
    empty.colSpan = 8; body.append(row);
  }
  $('batch-images').replaceChildren(element);
  const activeItem = data.items.find(item => item.run_id === data.current_run_id) || data.items.find(item => item.state === 'running') || [...data.items].reverse().find(item => item.run_id);
  const selectedItem = activeItem || datasetItems.get([...selectedDatasets][0]);
  const imageUrl = activeItem?.run_id ? `/api/runs/${activeItem.run_id}/input` : selectedItem?.thumbnail_url;
  const detectorRunning = activeItem?.detection?.state === 'running' || activeItem?.cases?.some(sample => sample.state === 'running') || (batchRunning && detectionPhaseActive);
  const finalVerdict = activeItem?.detection?.verdict || activeItem?.cases?.[0]?.verdict || (activeItem?.run_id === data.current_run_id ? liveDetectionVerdict : null);
  $('counter').textContent = `${data.completed} / ${data.total} model/image runs`;
  $('progress').setAttribute('aria-label','Completed images'); $('progress').max = data.total || 1; $('progress').value = data.completed;
  $('status').textContent = data.cancel_requested && batchRunning ? 'Stopping after the current operation …' : ['completed','failed','cancelled'].includes(data.state) ? (data.state === 'completed' ? 'Evaluation complete.' : `Batch ${data.state}.`) : detectorRunning ? 'Running detection checks …' : activeItem?.state === 'running' ? `${ocrModelLabel(activeItem.model || data.model)} · ${activeItem.image.split('/').at(-1)} …` : 'Preparing next model/image …';
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
