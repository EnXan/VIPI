'use strict';
// Dataset page: add images, label them (autosave) and submit your changes.
(() => {
  const node = id => document.getElementById(id);
  const state = {loaded: false, vocabulary: null, fields: [], items: [], index: -1, entry: null};

  /** @param {string} url @param {object} [options] */
  async function request(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    return data;
  }
  const post = (url, body) => request(url, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const entryUrl = id => `/api/curation/entries/${encodeURIComponent(id)}`;
  const spec = field => state.vocabulary.fields[field];
  const values = field => spec(field).values.map(item => item.value);
  const setSaved = (text, failed = false) => {
    node('label-save').textContent = text;
    node('label-save').classList.toggle('label-failed', failed);
  };
  function element(tag, text, className) {
    const item = document.createElement(tag);
    if (text != null) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  const options = (select, entries, keep = true) => {
    const first = keep ? select.options[0] : null;
    select.replaceChildren(...(first ? [first] : []), ...entries.map(([value, label]) => {
      const option = element('option', label); option.value = value; return option;
    }));
  };

  async function open() {
    if (state.loaded) return;
    try {
      const status = await request('/api/curation');
      node('label-unavailable').hidden = status.available;
      node('label-workspace').hidden = !status.available;
      if (!status.available) return;
      state.vocabulary = status.vocabulary; state.fields = status.fields; state.loaded = true;
      if (status.reviewed === status.entries) node('label-status').value = 'all';
      options(node('label-field'), state.fields.map(field => [field, field]));
      for (const field of ['label', 'content']) {
        options(node(`add-${field}`), spec(field).values.map(item =>
          [item.value, item.description ? `${item.value.replaceAll('_', ' ')} — ${item.description}` : item.value.replaceAll('_', ' ')]));
      }
      await refreshList();
    } catch (failure) { setSaved(failure.message, true); }
  }

  function filterQuery() {
    const params = new URLSearchParams({status: node('label-status').value});
    if (node('label-field').value && node('label-value').value) {
      params.set('field', node('label-field').value); params.set('value', node('label-value').value);
    }
    if (node('label-source').value) params.set('source', node('label-source').value);
    if (node('label-query').value.trim()) params.set('q', node('label-query').value.trim());
    if (node('label-group').checked) params.set('group', '1');
    if (node('label-changed').checked) params.set('changed', '1');
    return params;
  }

  async function refreshList(keepId) {
    const data = await request(`/api/curation/entries?${filterQuery()}`);
    const current = node('label-source').value;
    options(node('label-source'), data.sources.map(source => [source, source]));
    node('label-source').value = current;
    state.items = data.items;
    renderList();
    const position = keepId ? state.items.findIndex(item => item.id === keepId) : -1;
    await select(position >= 0 ? position : state.items.length ? 0 : -1);
    await refreshProgress();
    await refreshBalance();
  }

  async function refreshBalance() {
    const data = await request('/api/curation/balance');
    const missing = data.missing_total;
    node('label-balance-summary').textContent =
      `· overall ${data.overall.benign_percent}% benign · missing ${missing.benign} benign, ${missing.attacks} attack images`;
    const head = element('tr');
    for (const text of ['Content', 'Images', 'Benign', 'Attack', 'Missing']) head.append(element('th', text));
    const rows = Object.entries(data.contents).map(([content, row]) => {
      const line = element('tr');
      const need = Object.entries(row.missing).map(([side, count]) => `${count} ${side === 'benign' ? 'benign' : 'attack'}`).join('') || 'balanced';
      for (const text of [content.replaceAll('_', ' '), row.images, `${row.benign_percent}%`, `${row.attack_percent}%`, need]) line.append(element('td', String(text)));
      if (Object.keys(row.missing).length) line.className = 'label-unbalanced';
      return line;
    });
    const table = element('table');
    const body = element('tbody'); body.append(...rows);
    const thead = element('thead'); thead.append(head);
    table.append(thead, body);
    node('label-balance-table').replaceChildren(table);
  }

  async function refreshProgress() {
    const status = await request('/api/curation');
    node('label-progress').textContent =
      `${status.reviewed} of ${status.entries} reviewed · ${status.dropped} dropped`;
  }

  function renderList() {
    node('label-list').replaceChildren(...state.items.map((item, position) => {
      const row = element('li');
      const previous = state.items[position - 1];
      if (item.group_size > 1) {
        row.className = 'label-grouped';
        if (!previous || previous.group !== item.group) {
          row.prepend(element('span', `Similar group · ${item.group_size} images`, 'label-group-head mono'));
        }
      } else if (item.group && previous && previous.group_size > 1) {
        row.prepend(element('span', 'Single images', 'label-group-head mono'));
      }
      const button = element('button', null, 'label-row');
      button.type = 'button';
      button.dataset.position = String(position);
      const image = element('img'); image.loading = 'lazy'; image.alt = '';
      image.src = `${entryUrl(item.id)}/thumbnail`;
      const text = element('span', null, 'label-row-text');
      text.append(element('span', item.label || 'no label', 'mono'),
        element('span', item.image.split('/').pop(), 'muted'));
      const badge = element('span', item.decision === 'drop' ? 'dropped' : item.reviewed ? '✓' : '', 'label-badge');
      button.append(image, text, badge);
      button.onclick = () => select(position);
      row.append(button);
      return row;
    }));
  }

  async function select(position) {
    state.index = position;
    document.querySelectorAll('.label-row').forEach(row =>
      row.setAttribute('aria-current', String(Number(row.dataset.position) === position)));
    node('label-position').textContent = state.items.length ? `${position + 1} / ${state.items.length}` : 'No matching entries';
    node('label-prev').disabled = position <= 0;
    node('label-next').disabled = position < 0 || position >= state.items.length - 1;
    if (position < 0) { state.entry = null; renderEntry(); return; }
    document.querySelector(`.label-row[data-position="${position}"]`)?.scrollIntoView({block: 'nearest'});
    const id = state.items[position].id;
    state.entry = await request(entryUrl(id));
    renderEntry();
  }

  function renderEntry() {
    const entry = state.entry;
    node('label-empty').hidden = Boolean(entry);
    node('label-detail').hidden = !entry;
    node('label-fields').hidden = !entry;
    if (!entry) { renderEmpty(); return; }
    const imageUrl = `${entryUrl(entry.id)}/image`;
    node('label-image').src = imageUrl; node('label-image-link').href = imageUrl;
    const source = entry.source || {};
    node('label-meta').replaceChildren(...[
      ['Id', entry.id], ['Image', entry.image], ['Source', source.dataset || 'unknown'],
      ['License', source.license || 'unknown'], ['Sample', source.sample_id || '—'],
    ].flatMap(([term, value]) => [element('dt', term), element('dd', value, 'mono')]));
    renderTexts(entry);
    renderFields();
    renderCuration();
  }

  async function renderEmpty() {
    const status = await request('/api/curation');
    const filtered = node('label-field').value || node('label-source').value
      || node('label-query').value.trim() || node('label-changed').checked;
    let title = 'No entries match these filters.';
    let text = 'Change or clear the filters above.';
    if (node('label-changed').checked && !node('label-query').value.trim()) {
      title = 'You have no changes yet.';
      text = 'Add images with step 1, or untick "Only my changes" to correct an existing entry.';
    } else if (node('label-status').value === 'unreviewed' && !filtered && status.reviewed === status.entries) {
      title = `All ${status.entries} entries are reviewed.`;
      text = 'To contribute, add images with step 1. To correct an existing entry, set Status to "All".';
    }
    node('label-empty-title').textContent = title;
    node('label-empty-text').textContent = text;
  }

  function applies(field) {
    return !state.entry.label || spec(field).applies_to.includes(state.entry.label);
  }

  const FIELD_HINTS = {
    label: 'Is the image an attack? Judge it without any application context.',
    techniques: 'How the text tries to steer the AI. Every one that applies.',
    goal: 'What the attack wants the AI to do. Every one that applies.',
    obfuscation: 'How the text is deliberately hidden. Empty if it is not hidden.',
    evidence: 'Where the attack shows: readable text, the picture, encoded text or no text.',
    content: 'What the image shows.',
  };

  function renderFields() {
    node('label-field-groups').replaceChildren(...state.fields.map(field => {
      const group = element('fieldset', null, 'label-field');
      group.disabled = !applies(field);
      group.append(element('legend', `${field}${spec(field).multiple ? '' : ' · one value'}`, 'eyebrow'));
      if (FIELD_HINTS[field]) group.append(element('p', FIELD_HINTS[field], 'muted label-field-hint'));
      const current = state.entry[field];
      const chosen = new Set(Array.isArray(current) ? current : current ? [current] : []);
      const chips = element('div', null, 'label-chips');
      for (const item of spec(field).values) {
        const chip = element('button', item.value, 'label-chip');
        chip.type = 'button'; chip.title = item.description || item.value;
        chip.setAttribute('aria-pressed', String(chosen.has(item.value)));
        chip.onclick = () => toggle(field, item.value);
        chips.append(chip);
      }
      const add = element('button', '+ value', 'label-chip label-add');
      add.type = 'button'; add.onclick = () => addValue(field);
      chips.append(add);
      group.append(chips);
      if (group.disabled) group.append(element('p', `Not used for ${state.entry.label}.`, 'muted'));
      return group;
    }));
  }

  function renderCuration() {
    const curation = state.entry.curation;
    node('label-reviewed').setAttribute('aria-pressed', String(curation.reviewed));
    node('label-reviewed').textContent = curation.reviewed ? 'Reviewed ✓' : 'Mark reviewed';
    node('label-drop').hidden = curation.decision === 'drop';
    node('label-keep').hidden = curation.decision !== 'drop';
    if (curation.decision === 'drop') setSaved(`Dropped: ${curation.reason}${curation.duplicate_of ? ` (duplicate of ${curation.duplicate_of})` : ''}`);
  }

  async function save(changes) {
    const id = state.entry.id;
    try {
      setSaved('Saving…');
      state.entry = await post(entryUrl(id), changes);
      const item = state.items[state.index];
      state.items[state.index] = {...item, label: state.entry.label,
        reviewed: state.entry.curation.reviewed, decision: state.entry.curation.decision};
      renderList(); renderEntry();
      document.querySelector(`.label-row[data-position="${state.index}"]`)?.setAttribute('aria-current', 'true');
      setSaved('Saved');
      await refreshProgress();
    } catch (failure) { setSaved(failure.message, true); renderEntry(); }
  }

  function toggle(field, value) {
    const current = state.entry[field];
    if (spec(field).multiple) {
      const next = current.includes(value) ? current.filter(item => item !== value) : [...current, value];
      return save({[field]: next});
    }
    const changes = {[field]: current === value ? null : value};
    if (field === 'label' && changes.label) {
      for (const other of state.fields) {
        if (other !== 'label' && spec(other).multiple && !spec(other).applies_to.includes(changes.label)) changes[other] = [];
      }
    }
    return save(changes);
  }

  async function reloadVocabulary() {
    state.vocabulary = (await request('/api/curation')).vocabulary;
    renderVocabulary();
  }

  async function addValue(field) {
    const value = window.prompt(`New ${field} value:`);
    if (!value) return;
    const description = window.prompt('Short description (optional):') || '';
    try {
      let result = await post(`/api/curation/vocabulary/${field}`, {value, description});
      if (!result.added) {
        if (!window.confirm(`Similar values exist: ${result.similar.join(', ')}. Add ${result.value} anyway?`)) return;
        result = await post(`/api/curation/vocabulary/${field}`, {value, description, confirm: true});
      }
      await reloadVocabulary();
      setSaved(`Added ${result.value}`);
      if (applies(field)) await toggle(field, result.value); else renderFields();
    } catch (failure) { setSaved(failure.message, true); }
  }

  function renderVocabulary() {
    node('label-vocabulary').replaceChildren(...state.fields.map(field => {
      const block = element('div', null, 'label-vocabulary-field');
      block.append(element('p', field, 'eyebrow'));
      for (const value of values(field)) {
        const row = element('div', null, 'label-vocabulary-row');
        const rename = element('button', 'Rename', 'small'); rename.type = 'button';
        rename.onclick = () => vocabularyAction(field, value, 'rename');
        const remove = element('button', 'Remove', 'small'); remove.type = 'button';
        remove.onclick = () => vocabularyAction(field, value, 'remove');
        row.append(element('span', value, 'mono'), rename, remove);
        block.append(row);
      }
      return block;
    }));
  }

  async function vocabularyAction(field, value, action) {
    try {
      const path = `/api/curation/vocabulary/${field}/${encodeURIComponent(value)}/${action}`;
      if (action === 'rename') {
        const target = window.prompt(`Rename ${value} to (an existing value merges both):`, value);
        if (!target || target === value) return;
        const result = await post(path, {to: target});
        setSaved(result.merged ? `Merged into ${result.value}` : `Renamed to ${result.value}`);
      } else {
        if (!window.confirm(`Remove ${value}? Only unused values can be removed.`)) return;
        await post(path, {});
        setSaved(`Removed ${value}`);
      }
      await reloadVocabulary();
      await refreshList(state.entry?.id);
    } catch (failure) { setSaved(failure.message, true); }
  }

  node('label-field').onchange = () => {
    const field = node('label-field').value;
    node('label-value').disabled = !field;
    options(node('label-value'), field ? [...values(field), '(none)'].map(value => [value, value]) : []);
    refreshList().catch(failure => setSaved(failure.message, true));
  };
  for (const id of ['label-status', 'label-value', 'label-source', 'label-group', 'label-changed']) {
    node(id).onchange = () => refreshList().catch(failure => setSaved(failure.message, true));
  }
  let searchTimer;
  node('label-query').oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => refreshList().catch(failure => setSaved(failure.message, true)), 250);
  };
  node('label-prev').onclick = () => select(state.index - 1);
  node('label-next').onclick = () => select(state.index + 1);
  node('label-reviewed').onclick = () => save({curation: {reviewed: !state.entry.curation.reviewed}});
  node('label-drop').onclick = () => {
    const reason = window.prompt('Why drop this image? (for example: duplicate of <id>)');
    if (!reason) return;
    const match = reason.match(/duplicate of ([0-9a-f]{16})/i);
    save({curation: {decision: 'drop', reason, duplicate_of: match ? match[1] : null}});
  };
  node('label-keep').onclick = () => save({curation: {decision: 'keep'}});
  node('label-vocabulary').closest('details').ontoggle = event => {
    if (event.target.open) renderVocabulary();
  };
  document.addEventListener('keydown', event => {
    if (node('label-page').hidden || !state.entry) return;
    if (event.target.closest('input, select, textarea') || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === 'ArrowLeft' && state.index > 0) { event.preventDefault(); select(state.index - 1); }
    if (event.key === 'ArrowRight' && state.index < state.items.length - 1) { event.preventDefault(); select(state.index + 1); }
    if (event.key.toLowerCase() === 'r') { event.preventDefault(); node('label-reviewed').click(); }
  });
  // Text, source and caller context ------------------------------------------

  const SOURCE_FIELDS = ['dataset', 'license', 'provenance', 'repository'];
  function renderTexts(entry) {
    node('label-payload').value = entry.payload || '';
    const reference = entry.ocr_reference;
    const locked = Boolean(reference && reference.regions && reference.regions.length);
    node('label-reference').value = reference ? reference.text : '';
    node('label-reference').readOnly = locked;
    node('label-reference-note').textContent = locked
      ? 'This reference has word positions, so its text is edited together with them in catalog.json.'
      : '';
    const source = entry.source || {};
    for (const key of SOURCE_FIELDS) node(`label-source-${key}`).value = source[key] || '';
    renderCases(entry.cases);
    node('label-texts-status').textContent = '';
  }

  function caseRow(item) {
    const row = element('div', null, 'label-case');
    const expected = element('select');
    for (const label of ['benign', 'injection', 'jailbreak']) {
      const option = element('option', `expected: ${label}`); option.value = label; expected.append(option);
    }
    expected.value = item.expected || 'benign';
    const context = element('textarea'); context.rows = 2; context.value = item.context || '';
    context.placeholder = 'e.g. This repository collects phishing screenshots for training detectors.';
    const remove = element('button', 'Remove', 'small'); remove.type = 'button';
    remove.onclick = () => row.remove();
    row.append(expected, context, remove);
    return row;
  }
  function renderCases(cases) {
    // Cases without context repeat the label and are kept as they are.
    node('label-cases').replaceChildren(...cases.filter(item => item.context).map(caseRow));
    node('label-contexts').open = cases.some(item => item.context);
  }
  node('label-add-case').onclick = () => node('label-cases').append(caseRow({expected: 'benign'}));

  node('label-texts').onsubmit = async event => {
    event.preventDefault();
    const entry = state.entry;
    if (!entry) return;
    const contexts = [...node('label-cases').querySelectorAll('.label-case')].map(row => ({
      expected: row.querySelector('select').value, context: row.querySelector('textarea').value,
    })).filter(item => item.context.trim());
    const changes = {
      payload: node('label-payload').value,
      source: Object.fromEntries(SOURCE_FIELDS.map(key => [key, node(`label-source-${key}`).value])),
      cases: [...entry.cases.filter(item => !item.context), ...contexts],
    };
    if (!node('label-reference').readOnly) changes.ocr_reference = {text: node('label-reference').value};
    node('label-texts-status').textContent = 'Saving…';
    try {
      state.entry = await post(entryUrl(entry.id), changes);
      renderTexts(state.entry);
      node('label-texts-status').textContent = 'Saved.';
    } catch (failure) {
      node('label-texts-status').textContent = failure.message;
    }
  };

  // Step 1 and 3: add images, submit changes

  function togglePanel(name, show) {
    for (const other of ['add', 'submit']) {
      const open = other === name && show;
      node(`${other}-panel`).hidden = !open;
      node(`${other}-open`).setAttribute('aria-expanded', String(open));
    }
  }

  const addFields = ['label', 'content', 'dataset', 'license', 'provenance', 'repository'];
  let addFiles = [];
  function updateAddForm() {
    const count = addFiles.length;
    node('add-files-label').textContent = count
      ? `${count} image${count === 1 ? '' : 's'}: ${addFiles.map(file => file.name).join(', ')}`
      : 'Choose images or drop them here';
    const missing = addFields.filter(key => key !== 'repository' && !node(`add-${key}`).value.trim());
    node('add-submit').disabled = !count || missing.length > 0;
    node('add-submit').textContent = count ? `Add ${count} image${count === 1 ? '' : 's'}` : 'Add images';
    node('add-status').textContent = !count ? 'Choose at least one image.'
      : missing.length ? `Still needed: ${missing.join(', ').replace('dataset', 'source name')}.` : '';
  }
  node('add-open').onclick = () => { togglePanel('add', node('add-panel').hidden); updateAddForm(); };
  node('add-cancel').onclick = () => togglePanel('add', false);
  node('add-files').onchange = () => { addFiles = [...node('add-files').files]; updateAddForm(); };
  for (const key of addFields) node(`add-${key}`).oninput = updateAddForm;
  const dropzone = node('add-dropzone');
  dropzone.ondragover = event => { event.preventDefault(); dropzone.classList.add('dragover'); };
  dropzone.ondragleave = () => dropzone.classList.remove('dragover');
  dropzone.ondrop = event => {
    event.preventDefault(); dropzone.classList.remove('dragover');
    addFiles = [...event.dataTransfer.files]; updateAddForm();
  };
  dropzone.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); node('add-files').click(); } };

  node('add-panel').onsubmit = async event => {
    event.preventDefault();
    const form = new FormData();
    for (const file of addFiles) form.append('images', file);
    for (const key of addFields) form.append(key, node(`add-${key}`).value);
    node('add-submit').disabled = true;
    node('add-status').textContent = 'Adding…';
    try {
      const result = await request('/api/curation/images', {method: 'POST', body: form});
      const skipped = result.skipped.map(item => `${item.file} (already ${item.id})`);
      addFiles = []; node('add-files').value = '';
      updateAddForm();
      node('add-status').textContent = `Added ${result.added.length}.` +
        (skipped.length ? ` Skipped: ${skipped.join(', ')}.` : '') +
        (result.added.length ? ' Now label them below.' : '');
      if (!result.added.length) return;
      node('label-status').value = 'unreviewed';
      node('label-changed').checked = true;
      for (const key of ['label-field', 'label-source']) node(key).value = '';
      node('label-value').value = ''; node('label-value').disabled = true;
      node('label-query').value = '';
      await refreshList(result.added[0]);
    } catch (failure) {
      node('add-status').textContent = failure.message;
      updateAddForm();
    }
  };

  let submitPlan = null;
  function updateSubmitForm() {
    node('submit-send').disabled = !submitPlan || !node('submit-confirm').checked;
  }
  node('submit-confirm').onchange = updateSubmitForm;
  node('submit-cancel').onclick = () => togglePanel('submit', false);
  node('submit-open').onclick = async () => {
    if (!node('submit-panel').hidden) { togglePanel('submit', false); return; }
    togglePanel('submit', true);
    submitPlan = null;
    node('submit-counts').hidden = true; node('submit-conflicts').hidden = true;
    node('submit-form').hidden = true; node('submit-done').hidden = true;
    node('submit-confirm').checked = false; updateSubmitForm();
    node('submit-status').textContent = 'Comparing your dataset with Hugging Face…';
    try {
      const plan = await request('/api/curation/submission');
      const labels = {added: 'added', changed: 'changed', removed: 'removed (dropped)'};
      node('submit-counts').replaceChildren(...Object.entries(plan.counts).map(([key, count]) =>
        element('li', `${count} ${labels[key]}`)));
      node('submit-counts').hidden = false;
      if (plan.conflicts.length) {
        node('submit-conflicts').replaceChildren(...plan.conflicts.map(line => element('li', line)));
        node('submit-conflicts').hidden = false;
        node('submit-status').textContent = 'These entries were changed on Hugging Face since your download, so nothing can be submitted. Download the new revision and redo these entries.';
        return;
      }
      submitPlan = plan;
      node('submit-status').textContent = `Your changes, applied to the current dataset (main ${plan.main_revision.slice(0, 8)})` +
        (plan.vocabulary_changed ? ', including your vocabulary changes.' : '.');
      node('submit-form').hidden = false;
      updateSubmitForm();
    } catch (failure) { node('submit-status').textContent = failure.message; }
  };
  node('submit-send').onclick = async () => {
    node('submit-send').disabled = true;
    node('submit-status').textContent = 'Opening the pull request…';
    try {
      const result = await post('/api/curation/submission', {confirm: true, message: node('submit-message').value});
      node('submit-form').hidden = true;
      node('submit-status').textContent = '';
      const link = element('a', result.pull_request);
      link.href = result.pull_request; link.target = '_blank'; link.rel = 'noopener';
      node('submit-done').replaceChildren('Pull request opened: ', link, '. A maintainer reviews and merges it.');
      node('submit-done').hidden = false;
    } catch (failure) {
      node('submit-status').textContent = failure.message;
      updateSubmitForm();
    }
  };

  window.vipiCuration = {open};
  if (!node('dataset-page').hidden) open();
})();
