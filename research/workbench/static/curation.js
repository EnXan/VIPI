'use strict';
// Label page: browse the combined catalog draft and edit labels with autosave.
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
      options(node('label-field'), state.fields.map(field => [field, field]));
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
    node('label-detail-empty')?.remove();
    for (const id of ['label-image', 'label-image-link']) node(id).hidden = !entry;
    if (!entry) { node('label-field-groups').replaceChildren(); return; }
    const imageUrl = `${entryUrl(entry.id)}/image`;
    node('label-image').src = imageUrl; node('label-image-link').href = imageUrl;
    const source = entry.source || {};
    node('label-meta').replaceChildren(...[
      ['Id', entry.id], ['Image', entry.image], ['Source', source.dataset || 'unknown'],
      ['License', source.license || 'unknown'], ['Sample', source.sample_id || '—'],
    ].flatMap(([term, value]) => [element('dt', term), element('dd', value, 'mono')]));
    node('label-payload').textContent = entry.payload || '—';
    const reference = entry.ocr_reference;
    node('label-reference').textContent = reference ? `[${reference.scope}] ${reference.text}` : '—';
    node('label-reference').closest('details').open = !entry.payload && Boolean(reference);
    node('label-cases-summary').textContent = `Cases (${entry.cases.length})`;
    node('label-cases').replaceChildren(...entry.cases.map(item =>
      element('li', `${item.expected}${item.context ? ` — ${item.context}` : ' — no context'}`)));
    renderFields();
    renderCuration();
  }

  function applies(field) {
    return !state.entry.label || spec(field).applies_to.includes(state.entry.label);
  }

  function renderFields() {
    node('label-field-groups').replaceChildren(...state.fields.map(field => {
      const group = element('fieldset', null, 'label-field');
      group.disabled = !applies(field);
      group.append(element('legend', `${field}${spec(field).multiple ? '' : ' · one value'}`, 'eyebrow'));
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
  for (const id of ['label-status', 'label-value', 'label-source', 'label-group']) {
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
  window.vipiCuration = {open};
  if (!node('label-page').hidden) open();
})();
