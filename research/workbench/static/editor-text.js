'use strict';
// Editor: find text in the background image and remove whole lines, like Live Text.
// When a background image is added, the server looks for text lines once (only
// the detection of the tiny local OCR model, a few hundred ms on one thread;
// nothing is read). When lines were found, a pill in the bottom right corner of the canvas
// offers "Select text": click a line or drag across several, and they go into
// the Removed areas layer, where the brush's colour fill removes them.
(() => {
  const {element} = window.vipiEditorUi;
  const PAD = 3;       // px around a line, so anti-aliased glyph edges are removed too
  const HIT_SLOP = 4;  // screen px a pointer may be outside a line and still pick it

  /** @param {object} ctx editor state and helpers from editor.js */
  window.vipiEditorText = ({state, canvas, node, draw, canvasPoint, scale, status, heal, onStart}) => {
    let found = {key: null, status: 'idle', lines: []};  // status: idle | loading | ready | unavailable | failed
    let active = false, hovered = null, picked = null;   // picked: Set of lines while dragging
    let hinted = false;
    const pill = node('editor-select-text');

    const keyOf = () => state.background ? JSON.stringify([state.background.id, state.doc.width, state.doc.height, state.doc.background]) : null;
    const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
    /** Lines not yet in the Removed areas layer. */
    const remaining = () => found.lines.filter(line => !heal.marks().some(mark => mark.polygon && same(mark.polygon, line)));

    // Geometry: inside the polygon, or within `slop` document px of its edges.
    function inside([x, y], polygon) {
      let hit = false;
      for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const [xi, yi] = polygon[i], [xj, yj] = polygon[j];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) hit = !hit;
      }
      return hit;
    }
    function distance([x, y], polygon) {
      let best = Infinity;
      for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const [ax, ay] = polygon[j], [bx, by] = polygon[i];
        const length = (bx - ax) ** 2 + (by - ay) ** 2;
        const t = length ? Math.max(0, Math.min(1, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length)) : 0;
        best = Math.min(best, Math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay))));
      }
      return best;
    }
    const near = (point, polygon, slop) => inside(point, polygon) || distance(point, polygon) <= slop;
    const lineAt = ({x, y}) => remaining().find(line => near([x, y], line, HIT_SLOP / scale())) ?? null;

    // Detection, once per background image
    async function detect(key) {
      found = {key, status: 'loading', lines: []};
      renderPill();
      try {
        const form = new FormData();
        form.append('image', await heal.originalBlob(), 'background.png');
        const response = await fetch('/api/fixtures/text-lines', {method: 'POST', body: form});
        const data = await response.json().catch(() => ({}));
        if (found.key !== key) return;  // the background changed meanwhile
        if (!response.ok) throw new Error(data.error || `Finding text failed (${response.status}).`);
        found = {key, status: data.available ? 'ready' : 'unavailable', lines: data.lines};
        if (!data.available && !hinted) { hinted = true; status(data.hint); }
      } catch (error) {
        if (found.key === key) found = {key, status: 'failed', lines: []};
        status(error.message, true);
      }
      renderPill();
    }
    /** Called on every editor refresh: start detection for a new background, update the pill. */
    function sync() {
      const key = keyOf();
      if (key !== found.key) {
        if (key) detect(key); else found = {key: null, status: 'idle', lines: []};
      }
      if (active && !remaining().length) setActive(false);
      renderPill();
    }
    function renderPill() {
      const count = remaining().length;
      pill.hidden = !(found.status === 'ready' && (count || active));
      pill.setAttribute('aria-pressed', String(active));
      pill.replaceChildren(
        element('span', {class: 'editor-pill-icon', 'aria-hidden': 'true'}, active ? '✓' : '⌗'),
        active ? 'Done' : `Select text · ${count} ${count === 1 ? 'line' : 'lines'}`);
      node('editor-brush-snap').disabled = found.status !== 'ready';
    }

    function setActive(next) {
      if (next && !remaining().length) return;
      active = next;
      if (active) onStart?.();
      hovered = null; picked = null;
      canvas.classList.toggle('editor-selecting', active);
      renderPill();
      if (active) status('Click a text line or drag across several to remove them; Esc ends.');
      draw();
    }

    /** Outlines of the lines while selecting; the hovered or dragged ones filled. */
    function overlay(target) {
      if (!active) return;
      const width = 1.5 / scale();
      target.save();
      for (const line of remaining()) {
        const chosen = line === hovered || picked?.has(line);
        target.beginPath();
        line.forEach(([x, y], index) => (index ? target.lineTo(x, y) : target.moveTo(x, y)));
        target.closePath();
        if (chosen) { target.fillStyle = 'rgba(128, 128, 128, 0.35)'; target.fill(); }
        target.lineWidth = width;
        target.setLineDash([4 / scale(), 3 / scale()]);
        for (const [colour, offset] of [['#0B0C10', 0], ['#F2F3F5', 4 / scale()]]) {
          target.strokeStyle = colour;
          target.lineDashOffset = offset;
          target.stroke();
        }
      }
      target.restore();
    }
    /** Found lines a brush stroke touches, as marks (for "Snap to text"). */
    function touching(stroke) {
      if (found.status !== 'ready') return [];
      return remaining()
        .filter(line => stroke.points.some(point => near(point, line, stroke.size / 2)))
        .map(polygon => ({polygon, pad: PAD}));
    }

    // Pointer: these run before the editor's own listeners and take over while active.
    canvas.addEventListener('pointerdown', event => {
      if (!active || event.button !== 0) return;
      event.stopImmediatePropagation();
      event.preventDefault();
      const line = lineAt(canvasPoint(event));
      picked = new Set(line ? [line] : []);
      canvas.setPointerCapture(event.pointerId);
      draw();
    }, {capture: true});
    canvas.addEventListener('pointermove', event => {
      if (!active) return;
      event.stopImmediatePropagation();
      const line = lineAt(canvasPoint(event));
      if (picked && line) picked.add(line);
      if (line !== hovered || picked) { hovered = line; draw(); }
    }, {capture: true});
    canvas.addEventListener('pointerup', event => {
      if (!active) return;
      event.stopImmediatePropagation();
      const lines = [...(picked ?? [])];
      picked = null;
      if (lines.length) heal.addMarks(lines.map(polygon => ({polygon, pad: PAD})));
      else draw();
    }, {capture: true});
    canvas.addEventListener('dblclick', event => { if (active) event.stopImmediatePropagation(); }, {capture: true});
    canvas.addEventListener('pointerleave', () => { if (active && hovered) { hovered = null; draw(); } });
    document.addEventListener('keydown', event => {
      if (!active || node('editor-page').hidden || event.key !== 'Escape') return;
      if (event.target.closest?.('input, textarea, select, [contenteditable]')) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setActive(false);
    }, {capture: true});
    pill.onclick = () => setActive(!active);

    return {sync, overlay, touching, setActive, isActive: () => active};
  };
})();
