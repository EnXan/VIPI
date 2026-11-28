'use strict';
// Editor page: compose a fixture from visible and hidden layers, read it back with VIPI, export it.
// Helpers live in editor-ui.js, the layer kinds in editor-layers.js.
(() => {
  const {contrast, element, eyeIcon, reveal, rgbOf, transform, loadImage, enableScrubbing} = window.vipiEditorUi;
  const node = id => document.getElementById(id);
  const ENCODE_DELAY_MS = 150;  // pause after a change before writing; the write takes ~20 ms
  const LINE_HEIGHT = 1.25;
  const SIZES = [['800x450', 'Wide 800 × 450'], ['1280x720', 'HD 1280 × 720'], ['1024x1024', 'Square 1024 × 1024'], ['512x256', 'Banner 512 × 256'], ['custom', 'Custom']];
  const ZOOM_STEPS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16];
  const VIEWS = [['original', 'Original'], ['black', 'On black'], ['rgb', 'Alpha dropped'], ['bitplane', 'Bit plane'], ['scaled', 'Downscaled']];
  const STATUS = {read: ['✓', 'read'], changed: ['≠', 'read differently'], missing: ['✗', 'not read'], skipped: ['–', 'not in this format'], pending: ['…', 'checking']};

  const state = {
    options: null, opened: false, doc: null, layers: [], selected: null, background: null,
    history: [], future: [], result: null, dirty: true, timer: null, encoding: null, drag: null, nextId: 1,
    backgrounds: 0, zoom: 'fit', view: {mode: 'original', method: 'pillow_nearest', width: null, channel: 'r', bit: 0}, codes: new Map(),
  };
  const canvas = node('editor-canvas');
  const context = canvas.getContext('2d');
  const viewport = node('editor-viewport');
  const previewImage = node('editor-preview');
  let kinds = null;
  let heal = null;
  let textLines = null;  // Live-Text-like line selection (editor-text.js)

  /** Messages and errors appear as notifications (toast.js). */
  const status = (text, failed = false) => window.vipiToast(text, {kind: failed ? 'error' : 'info'});
  /** The steady writing state under the canvas ("Up to date."). */
  const writingState = text => { node('editor-status').textContent = text; };
  const selectedLayer = () => state.layers.find(layer => layer.id === state.selected) || null;
  const unsupported = layer => kinds[layer.kind].unsupported?.(layer) ?? null;
  /** Hidden layers stay in the document but are not drawn or written. */
  const shown = layer => layer.visible !== false;

  // History

  const snapshot = () => JSON.stringify({doc: state.doc, layers: state.layers, selected: state.selected});
  function restore(text) {
    const saved = JSON.parse(text);
    state.doc = saved.doc; state.layers = saved.layers; state.selected = saved.selected;
    refresh();
  }
  /** Record the current state before a change, then apply `change`. */
  function commit(change) {
    state.history.push(snapshot());
    state.future = [];
    change();
    refresh();
  }
  function undo() { if (state.history.length) { state.future.push(snapshot()); restore(state.history.pop()); } }
  function redo() { if (state.future.length) { state.history.push(snapshot()); restore(state.future.pop()); } }
  /** Change one layer property; `live` coalesces typing and slider drags into one undo step. */
  function setProperty(layer, key, value, live = false) {
    if (!live || !state.liveEdit) state.history.push(snapshot());
    state.future = [];
    state.liveEdit = live;
    layer[key] = value;
    refresh({properties: !live});
  }
  function addLayer(kind) {
    commit(() => { const layer = kinds[kind].create(); state.layers = [...state.layers, layer]; state.selected = layer.id; });
  }

  // Codes: module images come from zxing-cpp on the server

  const codeKey = layer => `${layer.format}\n${layer.text}`;
  function codeEntry(layer) {
    const key = codeKey(layer);
    if (!state.codes.has(key)) {
      const entry = {image: null, error: null};
      entry.ready = fetch('/api/fixtures/code', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({format: layer.format, text: layer.text})})
        .then(async response => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(data.error || `Code failed (${response.status}).`);
          entry.image = await loadImage(`data:image/png;base64,${data.image}`);
        })
        .catch(error => { entry.error = error.message; })
        .then(() => { if (state.opened) refresh({properties: selectedLayer()?.kind === 'code'}); });
      state.codes.set(key, entry);
    }
    return state.codes.get(key);
  }
  const codesReady = () => Promise.all(state.layers.filter(layer => layer.kind === 'code' && layer.visible).map(layer => codeEntry(layer).ready));

  // Canvas

  const fontOf = (layer, size = layer.size) => `${layer.italic ? 'italic ' : ''}${layer.bold ? 600 : 400} ${size}px "${layer.font}", sans-serif`;
  function textBox(layer) {
    context.font = fontOf(layer);
    const lines = transform(layer.text, layer.encoding).split('\n');
    const width = Math.max(1, ...lines.map(line => context.measureText(line).width));
    return {lines, width, height: lines.length * layer.size * LINE_HEIGHT, rotation: layer.rotation};
  }
  function codeBox(layer) {
    const image = codeEntry(layer).image;
    return {width: (image?.width ?? 21) * layer.module, height: (image?.height ?? 21) * layer.module, rotation: 0};
  }
  const box = layer => layer.kind === 'code' ? codeBox(layer) : textBox(layer);
  function drawText(target, layer) {
    const {lines} = textBox(layer);
    target.save();
    target.translate(layer.x, layer.y);
    target.rotate(layer.rotation * Math.PI / 180);
    target.transform(1, 0, Math.tan(layer.skew * Math.PI / 180), 1, 0, 0);
    if (layer.mirror) target.scale(-1, 1);
    target.globalAlpha = layer.opacity;
    target.filter = layer.blur > 0 ? `blur(${layer.blur}px)` : 'none';
    target.font = fontOf(layer);
    target.fillStyle = layer.color;
    target.textAlign = 'center';
    target.textBaseline = 'middle';
    lines.forEach((line, index) => target.fillText(line, 0, (index - (lines.length - 1) / 2) * layer.size * LINE_HEIGHT));
    target.restore();
  }
  /** The code's modules in the layer's colours, made once per image and colour pair. */
  function codeModules(entry, layer) {
    const key = `${layer.color}|${layer.paper}`;
    if (entry.modules?.key === key) return entry.modules.canvas;
    const image = entry.image;
    const modules = document.createElement('canvas');
    modules.width = image.width; modules.height = image.height;
    const paint = modules.getContext('2d');
    paint.drawImage(image, 0, 0);
    const pixels = paint.getImageData(0, 0, image.width, image.height);
    const [dark, light] = [layer.color, layer.paper].map(rgbOf);
    for (let index = 0; index < pixels.data.length; index += 4) {
      const colour = pixels.data[index] < 128 ? dark : light;
      pixels.data.set(colour, index);
    }
    paint.putImageData(pixels, 0, 0);
    entry.modules = {key, canvas: modules};
    return modules;
  }
  function drawCode(target, layer) {
    const entry = codeEntry(layer);
    if (!entry.image) return;
    const modules = codeModules(entry, layer);
    const {width, height} = codeBox(layer);
    target.save();
    target.imageSmoothingEnabled = false;
    target.globalAlpha = layer.opacity;
    target.drawImage(modules, Math.round(layer.x - width / 2), Math.round(layer.y - height / 2), width, height);
    target.restore();
  }
  function paint(target, skip = null) {
    const {width, height} = state.doc;
    target.save();
    const healed = heal?.background();
    target.fillStyle = state.doc.background;
    target.fillRect(0, 0, width, height);
    if (healed) target.drawImage(healed, 0, 0, width, height);
    else if (state.background) target.drawImage(state.background.image, 0, 0, width, height);
    target.restore();
    for (const layer of state.layers) {
      if (!layer.visible || layer.id === skip) continue;
      if (layer.kind === 'text') drawText(target, layer);
      else if (layer.kind === 'code') drawCode(target, layer);
    }
  }
  function drawSelection(target) {
    const layer = selectedLayer();
    if (!layer || !kinds[layer.kind].visible || !layer.visible) return;
    const {width, height, rotation} = box(layer);
    target.save();
    target.translate(layer.x, layer.y);
    target.rotate(rotation * Math.PI / 180);
    target.lineWidth = Math.max(1, state.doc.width / 600);
    target.setLineDash([6, 4]);
    // Ink and paper dashes stay visible on light and dark images alike.
    for (const [colour, offset] of [['#0B0C10', 0], ['#F2F3F5', 6]]) {
      target.strokeStyle = colour;
      target.lineDashOffset = offset;
      target.strokeRect(-width / 2 - 6, -height / 2 - 6, width + 12, height + 12);
    }
    target.restore();
  }
  /** Show the written file (or the SVG render OCR sees) once it is current; the composition while editing. */
  function draw() {
    canvas.width = state.doc.width;
    canvas.height = state.doc.height;
    if (state.editing) paint(context, state.editing.layer.id);
    else if (state.written && !state.dirty) context.drawImage(state.written, 0, 0, state.doc.width, state.doc.height);
    else paint(context);
    heal?.overlay(context);
    textLines?.overlay(context);
    if (!state.editing) drawSelection(context);
  }
  async function composed() {
    await codesReady();
    await heal?.ready();
    const target = document.createElement('canvas');
    target.width = state.doc.width; target.height = state.doc.height;
    paint(target.getContext('2d'));
    return new Promise(resolve => target.toBlob(resolve, 'image/png'));
  }
  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return {x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height};
  }
  function hit(point) {
    for (const layer of [...state.layers].reverse()) {
      if (!kinds[layer.kind].visible || !layer.visible) continue;
      const {width, height, rotation} = box(layer);
      const angle = -rotation * Math.PI / 180;
      const dx = point.x - layer.x, dy = point.y - layer.y;
      const x = dx * Math.cos(angle) - dy * Math.sin(angle), y = dx * Math.sin(angle) + dy * Math.cos(angle);
      if (Math.abs(x) <= width / 2 + 6 && Math.abs(y) <= height / 2 + 6) return layer;
    }
    return null;
  }
  // Text tool (T): a click in the image edits the text under it or places a new
  // text layer there; the tool ends once the text is placed.
  let textTool = false;
  function setTextTool(next) {
    textTool = next;
    if (next) { heal?.setActive(false); textLines?.setActive(false); }
    node('editor-tool-list').querySelector('[data-kind=text]')?.setAttribute('aria-pressed', String(next));
    canvas.style.cursor = next ? 'text' : 'default';
    if (next) status('Click in the image to place text; Esc cancels.');
  }
  function placeText(event) {
    event.preventDefault();  // keeps the focus on the text box opened below
    const point = canvasPoint(event), found = hit(point);
    setTextTool(false);
    if (found?.kind === 'text') { state.selected = found.id; refresh({encode: false}); startEditing(found); return; }
    const before = snapshot();
    const layer = kinds.text.create('', {x: Math.round(point.x), y: Math.round(point.y)});
    state.layers = [...state.layers, layer];
    state.selected = layer.id;
    refresh({encode: false});
    startEditing(layer, before);
  }
  canvas.addEventListener('pointerdown', event => {
    if (textTool && event.button === 0) { placeText(event); return; }
    const layer = hit(canvasPoint(event));
    state.selected = layer?.id ?? null;
    if (layer) {
      const point = canvasPoint(event);
      state.drag = {layer, dx: point.x - layer.x, dy: point.y - layer.y, before: snapshot(), moved: false};
      canvas.setPointerCapture(event.pointerId);
    }
    refresh({encode: false});
  });
  canvas.addEventListener('pointermove', event => {
    if (!state.drag) { canvas.style.cursor = textTool ? 'text' : hit(canvasPoint(event)) ? 'move' : 'default'; return; }
    const point = canvasPoint(event);
    state.drag.layer.x = Math.round(point.x - state.drag.dx);
    state.drag.layer.y = Math.round(point.y - state.drag.dy);
    state.drag.moved = true;
    state.dirty = true;
    draw();
  });
  // Edit a text layer in place: double-click opens an editable box over it with
  // the layer's font, size, colour and rotation at the current zoom.
  // Enter adds a line; Cmd/Ctrl+Enter or a click elsewhere keeps the text; Escape discards it.
  /** `before` is given for a layer created by the text tool: it is dropped again if left empty. */
  function startEditing(layer, before = null) {
    finishEditing(true);
    const factor = scale();
    const box = element('div', {class: 'editor-inline-text', role: 'textbox', 'aria-multiline': 'true', 'aria-label': 'Layer text', spellcheck: 'false'});
    box.contentEditable = 'plaintext-only';
    if (box.contentEditable !== 'plaintext-only') box.contentEditable = 'true';
    box.textContent = layer.text;
    Object.assign(box.style, {
      left: `${canvas.offsetLeft + layer.x * factor}px`, top: `${canvas.offsetTop + layer.y * factor}px`,
      font: fontOf(layer, layer.size * factor),
      lineHeight: String(LINE_HEIGHT), color: layer.color,
      transform: `translate(-50%, -50%) rotate(${layer.rotation}deg) skewX(${layer.skew}deg)`,
    });
    state.editing = {layer, box, original: layer.text, before: before ?? snapshot(), fresh: Boolean(before)};
    box.addEventListener('input', () => { layer.text = box.innerText.replace(/\n$/, ''); });
    box.addEventListener('keydown', event => {
      event.stopPropagation();
      if (event.key === 'Escape') { event.preventDefault(); finishEditing(false); }
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); finishEditing(true); }
    });
    box.addEventListener('blur', () => finishEditing(true));
    viewport.append(box);
    draw();
    box.focus();
    const range = document.createRange();
    range.selectNodeContents(box);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
  function finishEditing(keep) {
    const editing = state.editing;
    if (!editing) return;
    state.editing = null;
    editing.box.remove();
    if (!keep) editing.layer.text = editing.original;
    if (editing.fresh && !editing.layer.text.trim()) {
      state.layers = state.layers.filter(item => item !== editing.layer);
      state.selected = null;
      refresh({encode: false});
      return;
    }
    if (editing.layer.text !== editing.original) { state.history.push(editing.before); state.future = []; refresh(); }
    else draw();
  }
  canvas.addEventListener('dblclick', event => {
    const layer = hit(canvasPoint(event));
    if (!layer) return;
    state.selected = layer.id;
    if (layer.kind === 'text') { refresh({encode: false}); startEditing(layer); return; }
    refresh({encode: false});
    node('editor-properties').querySelector('textarea')?.focus();
  });
  canvas.addEventListener('pointerup', () => {
    if (state.drag?.moved) { state.history.push(state.drag.before); state.future = []; refresh(); }
    state.drag = null;
  });

  // Panels

  function renderProperties() {
    const layer = selectedLayer();
    const target = node('editor-properties');
    if (!layer) { target.replaceChildren(element('p', {class: 'muted'}, 'Select a layer, or add one with the tools on the left.')); return; }
    const reason = unsupported(layer);
    target.replaceChildren(element('p', {class: 'editor-kind-title mono'}, kinds[layer.kind].title), ...kinds[layer.kind].properties(layer),
      reason ? element('p', {class: 'editor-warning'}, `${reason} This layer is not written until you change it.`) : '',
      element('div', {id: 'editor-layer-readback'}));
    renderReadback();
  }
  function badge(layer) {
    if (!shown(layer)) return element('span', {class: 'editor-badge muted', title: 'Not drawn or written; the layer stays in the document'}, 'hidden');
    if (layer.kind === 'text') return element('span', {class: 'editor-badge muted'}, 'OCR in full scan');
    if (layer.kind === 'heal') return element('span', {class: 'editor-badge muted'}, 'applied to the background');
    const result = state.result?.layers.find(item => item.id === layer.id);
    const key = unsupported(layer) ? 'skipped' : (state.dirty || !result) ? 'pending' : result.status;
    let [mark, text] = STATUS[key];
    if (layer.kind === 'scaling' && (key === 'read' || key === 'changed')) text = key === 'read' ? 'appears when downscaled' : `${result.exact_pixels} of ${result.payload_pixels} pixels survive`;
    if (layer.kind === 'alpha' && (key === 'read' || key === 'changed')) text = key === 'read' ? 'shows in its view' : `${result.shown_pixels} of ${result.text_pixels} pixels show`;
    const detail = (key === 'changed' || key === 'missing') && result?.read ? ` — VIPI reads: ${result.read.length ? result.read.join(' | ') : 'nothing'}` : '';
    const reason = key === 'skipped' ? ` — ${unsupported(layer) ?? result?.reason ?? ''}` : '';
    return element('span', {class: `editor-badge status-${key}`, title: `${text}${detail}${reason}`}, `${mark} ${text}`);
  }
  function move(layer, offset) {
    const index = state.layers.indexOf(layer), target = index + offset;
    if (target < 0 || target >= state.layers.length) return;
    commit(() => { const next = [...state.layers]; [next[index], next[target]] = [next[target], next[index]]; state.layers = next; });
  }
  function remove(layer) {
    commit(() => { state.layers = state.layers.filter(item => item !== layer); if (state.selected === layer.id) state.selected = null; });
  }
  function renderLayers() {
    const icon = (label, title, onclick) => element('button', {class: 'editor-icon', type: 'button', title, 'aria-label': title, onclick}, label);
    const eye = layer => {
      const on = shown(layer);
      return element('button', {class: 'editor-icon editor-eye', type: 'button', title: on ? 'Hide layer' : 'Show layer', 'aria-label': on ? 'Hide layer' : 'Show layer',
        'aria-pressed': String(on), onclick: () => setProperty(layer, 'visible', !on)}, eyeIcon(on));
    };
    const rows = [...state.layers].reverse().map(layer => element('li', {class: 'editor-layer', 'aria-current': String(layer.id === state.selected), 'data-kind': kinds[layer.kind].visible ? 'visible' : 'hidden', 'data-shown': String(shown(layer))},
      eye(layer),
      element('button', {class: 'editor-layer-name', type: 'button', onclick: () => { state.selected = layer.id; refresh({encode: false}); }},
        element('span', {class: 'editor-kind mono'}, kinds[layer.kind].icon),
        element('span', {class: 'editor-layer-text'}, element('strong', {}, kinds[layer.kind].name(layer)), badge(layer))),
      element('span', {class: 'editor-layer-actions'}, icon('↑', 'Move layer up', () => move(layer, 1)), icon('↓', 'Move layer down', () => move(layer, -1)), icon('×', 'Delete layer', () => remove(layer)))));
    const base = element('li', {class: 'editor-layer', 'data-kind': 'background'},
      element('span', {class: 'editor-icon muted', 'aria-hidden': 'true'}, '▭'),
      element('span', {class: 'editor-layer-name'}, element('span', {class: 'editor-kind mono'}, 'BG'), element('span', {class: 'editor-layer-text'}, element('strong', {}, state.background ? 'Background image' : `Background ${state.doc.background}`))), element('span'));
    node('editor-layers').replaceChildren(...rows, base);
  }

  // Expected and read-back

  const visibleTexts = () => state.layers.filter(layer => layer.kind === 'text' && layer.visible && layer.text.trim()).sort((a, b) => a.y - b.y || a.x - b.x);
  const expectedOcr = () => visibleTexts().map(layer => transform(layer.text, layer.encoding)).join('\n');
  const expectedDecoded = () => visibleTexts().filter(layer => layer.encoding === 'base64').map(layer => layer.text).join('\n');
  // Thresholds for the labels set from text properties (ADR 0093).
  const LOW_CONTRAST = 3;        // WCAG minimum contrast for large text
  const SMALL_FONT = 12;         // px; the dataset renderers use 9 and 11 px against 19 px
  const HIGH_TRANSPARENCY = 0.5; // opacity at or below which text counts as see-through
  /** Average colour of the background (without layers) behind a text layer. */
  function backgroundBehind(layer) {
    const {width, height} = textBox(layer);
    const sample = document.createElement('canvas');
    sample.width = Math.max(1, Math.round(width)); sample.height = Math.max(1, Math.round(height));
    const target = sample.getContext('2d', {willReadFrequently: true});
    target.translate(-Math.round(layer.x - width / 2), -Math.round(layer.y - height / 2));
    target.fillStyle = state.doc.background;
    target.fillRect(0, 0, state.doc.width, state.doc.height);
    const image = heal?.background() ?? state.background?.image;
    if (image) target.drawImage(image, 0, 0, state.doc.width, state.doc.height);
    const {data} = target.getImageData(0, 0, sample.width, sample.height);
    const sum = [0, 0, 0];
    for (let index = 0; index < data.length; index += 4) for (let channel = 0; channel < 3; channel++) sum[channel] += data[index + channel];
    return sum.map(value => value / (data.length / 4));
  }
  function autoObfuscation() {
    const found = new Set();
    for (const layer of visibleTexts()) {
      if (contrast(rgbOf(layer.color), backgroundBehind(layer)) < LOW_CONTRAST) found.add('low_contrast');
      if (layer.size <= SMALL_FONT) found.add('small_font');
      if (layer.opacity <= HIGH_TRANSPARENCY) found.add('high_transparency');
      if (layer.encoding === 'homoglyphs') found.add('unicode_homoglyphs');
      if (layer.italic) found.add('italic_font');
      if (layer.rotation) found.add('rotated_text');
      if (layer.mirror) found.add('mirrored_text');
      if (layer.skew) found.add('distorted_text');
      if (layer.blur > 0) found.add('blur');
      if (layer.encoding === 'base64') found.add('base64');
    }
    for (const layer of state.layers.filter(item => shown(item) && !unsupported(item))) {
      if (layer.kind === 'scaling') found.add('image_scaling');
      if (layer.kind === 'alpha') found.add('high_transparency');
      if (layer.kind === 'metadata' && layer.encoding === 'base64') found.add('base64');
      if (layer.kind === 'metadata' && layer.encoding === 'homoglyphs') found.add('unicode_homoglyphs');
    }
    return found;
  }
  const obfuscation = () => [...new Set([...autoObfuscation(), ...state.doc.obfuscation])];
  function renderExpected() {
    node('editor-expected-ocr').textContent = expectedOcr() || '—';
    const decoded = expectedDecoded();
    node('editor-expected-decoded-block').hidden = !decoded;
    node('editor-expected-decoded').textContent = decoded;
    const auto = autoObfuscation();
    node('editor-obfuscation').replaceChildren(...state.options.obfuscation.map(({value, description}) => {
      const automatic = auto.has(value);
      return element('button', {class: 'label-chip', type: 'button', title: automatic ? `${description} Set by the layer properties.` : description, 'aria-pressed': String(automatic || state.doc.obfuscation.includes(value)), disabled: automatic, onclick: () => commit(() => {
        state.doc.obfuscation = state.doc.obfuscation.includes(value) ? state.doc.obfuscation.filter(item => item !== value) : [...state.doc.obfuscation, value];
      })}, value);
    }));
  }
  /** Preview and the selected layer's read-back once the written file is back. */
  function renderReadback() {
    showPreview();
    const target = node('editor-layer-readback'), layer = selectedLayer();
    if (!target || !layer) return;
    target.replaceChildren(window.vipiEditorReadback({layer, result: state.result, dirty: state.dirty,
      format: state.doc.format, reason: unsupported(layer)}));
  }

  // Encode, export, open

  function recipe() {
    const view = state.view.mode === 'original' ? {} : {view: {mode: state.view.mode, method: state.view.method, width: viewWidth(), channel: state.view.channel, bit: Number(state.view.bit)}};
    return {
      version: 1, format: state.doc.format, label: state.doc.label, obfuscation: obfuscation(),
      expected_ocr: expectedOcr(), expected_decoded: expectedDecoded(),
      canvas: {width: state.doc.width, height: state.doc.height, background: state.doc.background, background_image: state.background?.url ?? null},
      layers: state.layers.map(layer => {
        if (layer.kind === 'metadata') return {...layer, value: kinds.metadata.value(layer)};
        if (layer.kind === 'stego') return {...layer, layout: kinds.stego.layout(layer), depth: Number(layer.depth)};
        return {...layer};
      }),
      ...view,
    };
  }
  async function encodeNow() {
    const form = new FormData();
    form.append('raster', await composed(), 'canvas.png');
    form.append('recipe', JSON.stringify(recipe()));
    form.append('name', node('editor-name').value);
    const response = await fetch('/api/fixtures/encode', {method: 'POST', body: form});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Encoding failed (${response.status}).`);
    return data;
  }
  function scheduleEncode() {
    state.dirty = true;
    state.written = null;
    clearTimeout(state.timer);
    state.timer = setTimeout(encode, ENCODE_DELAY_MS);
  }
  const version = () => snapshot() + JSON.stringify(state.view);
  async function encode() {
    const started = version();
    writingState('Writing hidden layers…');
    const job = encodeNow();
    state.encoding = job;
    try {
      const result = await job;
      if (state.encoding !== job) return;
      state.result = result;
      state.dirty = started !== version();
      if (!state.dirty) {
        const shown = result.display ? `data:image/png;base64,${result.display}` : `data:${result.mime};base64,${result.image}`;
        state.written = await loadImage(shown).catch(() => null);
        if (!state.dirty) draw();
      }
      writingState(state.dirty ? 'Writing hidden layers…' : 'Up to date.');
    } catch (error) {
      if (state.encoding === job) status(error.message, true);
    }
    renderLayers(); renderReadback();
  }
  async function current() {
    clearTimeout(state.timer);
    if (state.dirty || !state.result) await encode();
    if (state.dirty || !state.result) throw new Error('The fixture could not be written; see the message under the canvas.');
    return state.result;
  }
  function download(blob, name) {
    const link = element('a', {href: URL.createObjectURL(blob), download: name});
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }
  const imageBlob = result => new Blob([Uint8Array.from(atob(result.image), char => char.charCodeAt(0))], {type: result.mime});
  async function exportImage() {
    try { const result = await current(); download(imageBlob(result), `${result.name}.${result.extension}`); } catch (error) { status(error.message, true); }
  }
  async function exportFixture() {
    try {
      const result = await current();
      download(imageBlob(result), `${result.name}.${result.extension}`);
      download(new Blob([JSON.stringify(result.fixture, null, 2) + '\n'], {type: 'application/json'}), `${result.name}.fixture.json`);
      status(`Exported ${result.name}.${result.extension} and ${result.name}.fixture.json.`);
    } catch (error) { status(error.message, true); }
  }
  function readFile(file, as) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error('The file could not be read.'));
      if (as === 'url') reader.readAsDataURL(file); else reader.readAsText(file);
    });
  }
  async function setBackground(url) {
    const image = await loadImage(url);
    commit(() => { state.background = {url, image, id: ++state.backgrounds}; state.doc.width = image.naturalWidth; state.doc.height = image.naturalHeight; });
  }
  async function openFixture(file) {
    try {
      const data = JSON.parse(await readFile(file, 'text'));
      const saved = data.recipe ?? data;
      if (!Array.isArray(saved.layers) || !saved.canvas) throw new Error('This file is not an editor fixture.');
      state.history.push(snapshot()); state.future = [];
      state.doc = {width: saved.canvas.width, height: saved.canvas.height, background: saved.canvas.background || '#ffffff',
        format: saved.format || 'png', label: saved.label || 'injection', obfuscation: []};
      state.layers = saved.layers.filter(layer => kinds[layer.kind]).map(layer => { const {value, layout, ...rest} = layer; return rest; });
      // Keep only the chips set by hand; the others follow from the layers again.
      const auto = autoObfuscation();
      state.doc.obfuscation = (saved.obfuscation || []).filter(value => !auto.has(value));
      state.nextId = 1 + Math.max(0, ...state.layers.map(layer => Number(String(layer.id).slice(1)) || 0));
      state.selected = null;
      if (data.image) node('editor-name').value = String(data.image).replace(/\.[^.]+$/, '');
      state.background = saved.canvas.background_image ? {url: saved.canvas.background_image, image: await loadImage(saved.canvas.background_image), id: ++state.backgrounds} : null;
      refresh();
      status(`Opened ${file.name}.`);
    } catch (error) { status(error.message, true); }
  }

  // Zoom and views

  const viewWidth = () => Math.min(state.view.width ?? Math.round(state.doc.width / 4), state.doc.width - 1);
  function fitScale() {
    // The viewport has a fixed size; zoom changes only the image inside it.
    const padding = 32;
    const width = viewport.clientWidth - padding, height = viewport.clientHeight - padding;
    return Math.max(0.01, Math.min(width / state.doc.width, height / state.doc.height));
  }
  const scale = () => state.zoom === 'fit' ? fitScale() : state.zoom;
  function applyZoom() {
    const factor = scale();
    const width = `${Math.round(state.doc.width * factor)}px`, height = `${Math.round(state.doc.height * factor)}px`;
    for (const item of [canvas, previewImage]) { item.style.width = width; item.style.height = height; }
    canvas.classList.toggle('editor-pixels', factor >= 2);
    node('editor-zoom-level').textContent = state.zoom === 'fit' ? `Fit ${Math.round(factor * 100)}%` : `${Math.round(factor * 100)}%`;
  }
  function setZoom(next) {
    finishEditing(true);
    const centerX = (viewport.scrollLeft + viewport.clientWidth / 2) / Math.max(1, viewport.scrollWidth);
    const centerY = (viewport.scrollTop + viewport.clientHeight / 2) / Math.max(1, viewport.scrollHeight);
    state.zoom = next === 'fit' ? 'fit' : Math.min(ZOOM_STEPS.at(-1), Math.max(ZOOM_STEPS[0], next));
    applyZoom();
    viewport.scrollLeft = centerX * viewport.scrollWidth - viewport.clientWidth / 2;
    viewport.scrollTop = centerY * viewport.scrollHeight - viewport.clientHeight / 2;
  }
  function zoomStep(direction) {
    const now = scale();
    const next = direction > 0 ? ZOOM_STEPS.find(value => value > now * 1.001) : [...ZOOM_STEPS].reverse().find(value => value < now * 0.999);
    setZoom(next ?? (direction > 0 ? ZOOM_STEPS.at(-1) : ZOOM_STEPS[0]));
  }
  function setView(change) {
    state.view = {...state.view, ...change};
    renderView();
    scheduleEncode();
    renderReadback();
  }
  // A view other than Original shows the server's preview of the written file. While
  // a new one is written, whatever is on screen stays until the new image is decoded,
  // so switching views or editing never blanks the stage.
  let previewShown = {view: null, data: null};
  const viewKey = () => JSON.stringify(state.view);
  function showPreview() {
    if (state.view.mode === 'original') { canvas.hidden = false; previewImage.hidden = true; return; }
    const data = !state.dirty && state.result?.preview;
    if (data && data !== previewShown.data) {
      const view = viewKey(), next = new Image();
      next.src = `data:image/png;base64,${data}`;
      next.decode().then(() => {
        if (viewKey() !== view || state.view.mode === 'original') return;  // the user moved on
        previewImage.src = next.src;
        previewShown = {view, data};
        canvas.hidden = true;
        previewImage.hidden = false;
      }).catch(() => null);
    } else if (data) {  // the new view looks the same as the one on screen
      previewShown.view = viewKey();
      canvas.hidden = true;
      previewImage.hidden = false;
    } else if (previewShown.view === viewKey()) {
      canvas.hidden = true;
      previewImage.hidden = false;
    }
  }
  function renderView() {
    for (const [mode] of VIEWS) node(`editor-view-${mode}`).setAttribute('aria-checked', String(state.view.mode === mode));
    node('editor-view-method').value = state.view.method;
    node('editor-view-width').value = viewWidth();
    node('editor-view-width').max = state.doc.width - 1;
    node('editor-view-channel').value = state.view.channel;
    node('editor-view-bit').value = String(state.view.bit);
    node('editor-view-scaled-options').hidden = state.view.mode !== 'scaled';
    node('editor-view-bitplane-options').hidden = state.view.mode !== 'bitplane';
    showPreview();
  }
  function bindView() {
    node('editor-view-modes').replaceChildren(...VIEWS.map(([mode, title]) => element('button', {id: `editor-view-${mode}`, class: 'editor-segment-button', type: 'button', role: 'radio', 'aria-checked': 'false', onclick: () => setView({mode})}, title)));
    node('editor-view-method').replaceChildren(...state.options.scaling.map(item => element('option', {value: item.id}, item.title)));
    node('editor-zoom-in').onclick = () => zoomStep(1);
    node('editor-zoom-out').onclick = () => zoomStep(-1);
    node('editor-zoom-fit').onclick = () => setZoom('fit');
    node('editor-zoom-actual').onclick = () => setZoom(1);
    node('editor-view-method').onchange = event => setView({method: event.target.value});
    node('editor-view-channel').onchange = event => setView({channel: event.target.value});
    node('editor-view-bit').onchange = event => setView({bit: Number(event.target.value)});
    node('editor-view-width').onchange = event => {
      const value = Math.round(Number(event.target.value));
      if (value >= 1 && value < state.doc.width) setView({width: value}); else renderView();
    };
    viewport.addEventListener('wheel', event => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      setZoom(scale() * Math.exp(-event.deltaY / 300));
    }, {passive: false});
    window.addEventListener('resize', () => { if (state.zoom === 'fit') applyZoom(); });
  }

  // Export menu: one button, a choice of what to export

  function bindExportMenu() {
    const button = node('editor-export'), menu = node('editor-export-menu');
    const items = () => [...menu.querySelectorAll('[role=menuitem]')];
    const close = (focus = false) => { menu.hidden = true; button.setAttribute('aria-expanded', 'false'); if (focus) button.focus(); };
    const openMenu = () => { menu.hidden = false; button.setAttribute('aria-expanded', 'true'); items()[0].focus(); };
    button.onclick = () => (menu.hidden ? openMenu() : close());
    node('editor-export-image').onclick = () => { close(); exportImage(); };
    node('editor-export-fixture').onclick = () => { close(); exportFixture(); };
    menu.addEventListener('keydown', event => {
      const list = items(), index = list.indexOf(document.activeElement);
      if (event.key === 'Escape') { event.preventDefault(); close(true); }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        list[(index + (event.key === 'ArrowDown' ? 1 : list.length - 1)) % list.length].focus();
      }
    });
    document.addEventListener('pointerdown', event => { if (!menu.hidden && !event.target.closest('.editor-menu')) close(); });
  }

  // Document bar and tools

  /** Size presets; "Original" (the background image's own size) when there is one. */
  function renderSizes() {
    const image = state.background?.image;
    const presets = image ? [['original', `Original ${image.naturalWidth} × ${image.naturalHeight}`], ...SIZES] : SIZES;
    node('editor-size').replaceChildren(...presets.map(([id, text]) => element('option', {value: id}, text)));
    const sizeId = `${state.doc.width}x${state.doc.height}`;
    node('editor-size').value = image && image.naturalWidth === state.doc.width && image.naturalHeight === state.doc.height ? 'original'
      : SIZES.some(([id]) => id === sizeId) ? sizeId : 'custom';
  }
  function renderBar() {
    renderSizes();
    node('editor-width').value = state.doc.width;
    node('editor-height').value = state.doc.height;
    node('editor-background').value = state.doc.background;
    node('editor-format').value = state.doc.format;
    node('editor-label').value = state.doc.label;
    node('editor-background-clear').hidden = !state.background;
    node('editor-background-image-label').textContent = state.background ? 'Replace image' : 'Add image';
    node('editor-undo').disabled = !state.history.length;
    node('editor-redo').disabled = !state.future.length;
  }
  function refresh({encode: reencode = true, properties = true} = {}) {
    // Mark the change first, so the canvas shows it now instead of the
    // last written file until the server answers.
    if (reencode) scheduleEncode();
    draw();
    applyZoom();
    renderBar();
    renderView();
    if (properties) renderProperties();
    renderLayers();
    renderExpected();
    renderReadback();
    textLines?.sync();
    if (state.scan?.job) node('editor-scan-stale').hidden = state.scan.version === snapshot();
  }
  function bindBar() {
    node('editor-format').replaceChildren(...state.options.formats.map(id => element('option', {value: id}, id.toUpperCase())));
    node('editor-label').replaceChildren(...state.options.labels.map(id => element('option', {value: id}, id)));
    node('editor-tool-list').replaceChildren(...Object.entries(kinds).filter(([, spec]) => !spec.internal).map(([kind, spec]) => element('button', {
      class: 'editor-tool', type: 'button', 'data-kind': kind,
      ...(kind === 'text'
        ? {title: 'Text tool (T): click in the image to place text', 'aria-label': 'Text tool', 'aria-pressed': 'false', onclick: () => setTextTool(!textTool)}
        : {title: `Add layer: ${spec.title} (${spec.key.toUpperCase()})`, 'aria-label': `Add layer: ${spec.title}`, onclick: () => addLayer(kind)}),
    }, element('span', {'aria-hidden': 'true'}, spec.icon))));
    node('editor-size').onchange = event => {
      if (event.target.value === 'custom') return;
      const image = state.background?.image;
      const [width, height] = event.target.value === 'original' && image
        ? [image.naturalWidth, image.naturalHeight] : event.target.value.split('x').map(Number);
      commit(() => { state.doc.width = width; state.doc.height = height; });
    };
    for (const key of ['width', 'height']) {
      node(`editor-${key}`).onchange = event => {
        const value = Math.round(Number(event.target.value));
        if (value >= 16) commit(() => { state.doc[key] = value; }); else renderBar();
      };
    }
    node('editor-background').oninput = event => { state.doc.background = event.target.value; state.dirty = true; draw(); };
    node('editor-background').onchange = event => commit(() => { state.doc.background = event.target.value; });
    node('editor-format').onchange = event => commit(() => { state.doc.format = event.target.value; });
    node('editor-label').onchange = event => commit(() => { state.doc.label = event.target.value; });
    node('editor-name').onchange = () => scheduleEncode();
    node('editor-background-image').onchange = async event => {
      const file = event.target.files[0];
      event.target.value = '';
      if (!file) return;
      try { await setBackground(await readFile(file, 'url')); } catch (error) { status(error.message, true); }
    };
    node('editor-background-clear').onclick = () => commit(() => { state.background = null; });
    node('editor-open').onchange = event => { const file = event.target.files[0]; event.target.value = ''; if (file) openFixture(file); };
    bindExportMenu();
    node('editor-undo').onclick = undo;
    node('editor-redo').onclick = redo;
  }
  document.addEventListener('keydown', event => {
    if (node('editor-page').hidden || !kinds) return;
    const typing = event.target.closest?.('input, textarea, select, [contenteditable]');
    const command = event.metaKey || event.ctrlKey;
    if (command && event.key.toLowerCase() === 'z' && !typing) { event.preventDefault(); if (event.shiftKey) redo(); else undo(); return; }
    if (typing || command || event.altKey) return;
    const kind = Object.keys(kinds).find(name => kinds[name].key === event.key);
    const keys = {'+': () => zoomStep(1), '=': () => zoomStep(1), '-': () => zoomStep(-1), 0: () => setZoom('fit'), 1: () => setZoom(1)};
    if (textTool && event.key === 'Escape') { event.preventDefault(); setTextTool(false); return; }
    if (kind === 'text') { event.preventDefault(); setTextTool(!textTool); return; }
    if (kind || keys[event.key]) { event.preventDefault(); if (kind) addLayer(kind); else keys[event.key](); return; }
    const layer = selectedLayer();
    if (!layer) return;
    if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); remove(layer); return; }
    const distance = event.shiftKey ? 10 : 1;
    const offsets = {ArrowLeft: [-distance, 0], ArrowRight: [distance, 0], ArrowUp: [0, -distance], ArrowDown: [0, distance]};
    if ('x' in layer && offsets[event.key]) {
      event.preventDefault();
      commit(() => { layer.x += offsets[event.key][0]; layer.y += offsets[event.key][1]; });
    }
  });

  async function open() {
    if (state.opened) return;
    try {
      const response = await fetch('/api/fixtures/options');
      if (!response.ok) throw new Error(`Editor options failed (${response.status}).`);
      state.options = await response.json();
    } catch (error) { status(error.message, true); return; }
    kinds = window.vipiEditorLayers({state, setProperty, commit, setView, textBox, heal: () => heal,
      codeError: layer => codeEntry(layer).error});
    state.doc = {width: 800, height: 450, background: '#ffffff', format: 'png', label: 'injection', obfuscation: []};
    bindBar();
    bindView();
    heal = window.vipiEditorHeal({state, canvas, viewport, node, commit, draw, scale, canvasPoint, status,
      onStart: () => { if (textTool) setTextTool(false); textLines?.setActive(false); },
      snap: stroke => textLines?.touching(stroke) ?? [],
      recompose: () => { scheduleEncode(); draw(); }});
    heal.bind();
    textLines = window.vipiEditorText({state, canvas, node, draw, canvasPoint, scale, status, heal,
      onStart: () => { if (textTool) setTextTool(false); heal.setActive(false); }});
    textLines.sync();
    window.vipiEditorScan({state, node, current, imageBlob, snapshot, expectedOcr, unsupported, status, kinds: () => kinds}).bind();
    enableScrubbing(node('editor-page'));
    await document.fonts.load('400 32px "Geist"').catch(() => null);
    await document.fonts.load('400 32px "Geist Mono"').catch(() => null);
    state.layers = [kinds.text.create()];
    state.selected = state.layers[0].id;
    state.opened = true;
    refresh();
  }
  window.vipiEditor = {open};
})();
