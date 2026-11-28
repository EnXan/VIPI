'use strict';
// Editor: the Remove brush. Paint over text in the background image; on release the
// painted area is filled with the colour around it on the server.
// All marks (brush strokes and text lines picked in editor-text.js) live in one
// "Removed areas" layer, so undo, delete and reopening work.
(() => {
  const {element, loadImage} = window.vipiEditorUi;
  const MIN_SIZE = 2;
  const SIZE_STEP = 1.25;  // [ and ] scale the brush like Photoshop
  const STROKE_OVERLAY = 'rgba(128, 128, 128, 0.55)';  // neutral grey, readable on light and dark images

  /** @param {object} ctx editor state and helpers from editor.js */
  window.vipiEditorHeal = ({state, canvas, viewport, node, commit, draw, scale, canvasPoint, status, recompose, onStart, snap}) => {
    const cache = new Map();  // mask key -> healed image, so undo and redo are instant
    let active = false, stroke = null, pending = null, brushSize = 24;
    const brush = element('div', {class: 'editor-brush', 'aria-hidden': 'true', hidden: true});
    viewport.append(brush);

    const layer = () => state.layers.find(item => item.kind === 'heal');
    // A hidden Removed areas layer leaves the background as it was.
    const strokes = () => (layer()?.visible === false ? [] : layer()?.strokes ?? []);
    // Without a background image the brush paints over the background colour.
    const key = () => strokes().length
      ? JSON.stringify([state.background?.id ?? null, state.doc.width, state.doc.height, state.doc.background, strokes()])
      : null;

    function drawStrokes(target, list, colour) {
      target.save();
      target.strokeStyle = colour;
      target.fillStyle = colour;
      target.lineCap = 'round';
      target.lineJoin = 'round';
      for (const mark of list) {
        if (mark.polygon) {  // a text line, padded so anti-aliased edges go too
          target.lineWidth = 2 * mark.pad;
          target.beginPath();
          mark.polygon.forEach(([x, y], index) => (index ? target.lineTo(x, y) : target.moveTo(x, y)));
          target.closePath();
          target.fill();
          target.stroke();
          continue;
        }
        const {size, points} = mark;
        target.lineWidth = size;
        target.beginPath();
        points.forEach(([x, y], index) => (index ? target.lineTo(x, y) : target.moveTo(x, y)));
        if (points.length === 1) { target.arc(points[0][0], points[0][1], size / 2, 0, 2 * Math.PI); target.fill(); } else target.stroke();
      }
      target.restore();
    }
    /** The background as the editor shows it before removals: colour and image at document size. */
    const originalBlob = () => blob(target => {
      target.fillStyle = state.doc.background;
      target.fillRect(0, 0, state.doc.width, state.doc.height);
      if (state.background) target.drawImage(state.background.image, 0, 0, state.doc.width, state.doc.height);
    });
    /** Add marks (strokes or text lines) to the Removed areas layer as one undo step. */
    function addMarks(marks) {
      commit(() => {
        const existing = layer();
        if (existing) { existing.strokes = [...existing.strokes, ...marks]; existing.visible = true; }
        else state.layers = [{id: `l${state.nextId++}`, kind: 'heal', strokes: marks}, ...state.layers];
      });
    }
    function blob(paintOn) {
      const target = document.createElement('canvas');
      target.width = state.doc.width; target.height = state.doc.height;
      paintOn(target.getContext('2d'));
      return new Promise(resolve => target.toBlob(resolve, 'image/png'));
    }
    /** Ask the server to fill the painted areas; the result is cached per mask. */
    function update(current) {
      const job = (async () => {
        const form = new FormData();
        form.append('image', await originalBlob(), 'background.png');
        form.append('mask', await blob(target => {
          target.fillStyle = '#000';
          target.fillRect(0, 0, state.doc.width, state.doc.height);
          drawStrokes(target, strokes(), '#fff');
        }), 'mask.png');
        const response = await fetch('/api/fixtures/heal', {method: 'POST', body: form});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || `Removing failed (${response.status}).`);
        cache.set(current, await loadImage(`data:image/png;base64,${data.image}`));
      })();
      pending = {key: current, job};
      job.catch(error => status(error.message, true)).finally(() => {
        if (pending?.job === job) pending = null;
        if (key() === current) recompose();
      });
    }
    /** The healed background for the current strokes, or null while it is computed. */
    function background() {
      const current = key();
      if (!current) return null;
      if (cache.has(current)) return cache.get(current);
      if (pending?.key !== current) update(current);
      return null;
    }
    async function ready() {
      background();
      if (pending) await pending.job.catch(() => null);
    }
    /** Grey marks for strokes that are being painted or not yet filled. */
    function overlay(target) {
      const waiting = key() && !cache.has(key()) ? strokes() : [];
      drawStrokes(target, stroke ? [...waiting, stroke] : waiting, STROKE_OVERLAY);
    }

    // Tool state, brush cursor and size
    function setActive(next) {
      active = next;
      if (active) onStart?.();
      node('editor-tool-heal').setAttribute('aria-pressed', String(active));
      node('editor-brush-options').hidden = !active;
      canvas.classList.toggle('editor-painting', active);
      brush.hidden = true;
      if (active) status('Paint over text to remove it. [ and ] change the brush; Esc ends.');
    }
    function setSize(next) {
      brushSize = Math.max(MIN_SIZE, Math.round(next));
      node('editor-brush-size').value = brushSize;
    }
    function moveBrush(event) {
      const point = canvasPoint(event), factor = scale(), diameter = brushSize * factor;
      Object.assign(brush.style, {width: `${diameter}px`, height: `${diameter}px`,
        left: `${canvas.offsetLeft + point.x * factor}px`, top: `${canvas.offsetTop + point.y * factor}px`});
      brush.hidden = false;
    }

    // Painting: these listeners run before the editor's own (capture) and take over while active.
    const point = event => { const {x, y} = canvasPoint(event); return [Math.round(x), Math.round(y)]; };
    canvas.addEventListener('pointerdown', event => {
      if (!active || event.button !== 0) return;
      event.stopImmediatePropagation();
      event.preventDefault();
      stroke = {size: brushSize, points: [point(event)]};
      canvas.setPointerCapture(event.pointerId);
      draw();
    }, {capture: true});
    canvas.addEventListener('pointermove', event => {
      if (!active) return;
      event.stopImmediatePropagation();
      moveBrush(event);
      if (!stroke) return;
      stroke.points.push(point(event));
      draw();
    }, {capture: true});
    canvas.addEventListener('pointerup', event => {
      if (!active) return;
      event.stopImmediatePropagation();
      if (!stroke) return;
      const finished = stroke;
      stroke = null;
      // With "Snap to text", a stroke over found text lines removes those lines whole.
      const lines = node('editor-brush-snap').checked ? snap?.(finished) ?? [] : [];
      addMarks(lines.length ? lines : [finished]);
    }, {capture: true});
    canvas.addEventListener('dblclick', event => { if (active) event.stopImmediatePropagation(); }, {capture: true});
    canvas.addEventListener('pointerleave', () => { brush.hidden = true; });
    document.addEventListener('keydown', event => {
      if (node('editor-page').hidden || event.target.closest?.('input, textarea, select, [contenteditable]')) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === 'j') { event.preventDefault(); setActive(!active); }
      else if (active && event.key === 'Escape') { event.preventDefault(); setActive(false); }
      else if (active && (event.key === '[' || event.key === ']')) { event.preventDefault(); setSize(event.key === ']' ? brushSize * SIZE_STEP : brushSize / SIZE_STEP); }
    }, {capture: true});

    function bind() {
      node('editor-tool-heal').onclick = () => setActive(!active);
      node('editor-brush-size').oninput = event => { const value = Number(event.target.value); if (value >= MIN_SIZE) brushSize = Math.round(value); };
      node('editor-brush-done').onclick = () => setActive(false);
      setSize(brushSize);
    }
    return {bind, background, ready, overlay, setActive, isActive: () => active, addMarks, originalBlob, marks: strokes};
  };
})();
