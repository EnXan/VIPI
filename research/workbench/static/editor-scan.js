'use strict';
// Editor: "Scan with VIPI" runs the full product scan of the written file through the
// workbench scan service and shows verdict, score per reading and recognized text.
(() => {
  const {element} = window.vipiEditorUi;

  /** @param {object} ctx editor state and helpers from editor.js */
  window.vipiEditorScan = ({state, node, current, imageBlob, snapshot, expectedOcr, unsupported, status, kinds}) => {
    // Scan with VIPI: the full product scan of the written file, as `vipi scan` runs it

    const SCAN_POLL_MS = 400;  // the scan control shows each reported step soon
    const VERDICTS = {
      injection_detected: ['Prompt injection detected', 'A reading scored at or above the threshold.'],
      no_injection_detected: ['No prompt injection detected', 'Every reading scored below the threshold.'],
      null: ['No result', 'A check did not complete; see the problems below.'],
    };
    const SCORE_NAMES = {ocr: 'OCR text', ocr_black: 'OCR on black', ocr_rgb: 'OCR with alpha dropped', image_metadata: 'Metadata', barcode: 'QR codes and barcodes',
      openstego: 'OpenStego', openstego_random_lsb: 'OpenStego RandomLSB', png_lsb: 'PNG LSB layouts', svg_source: 'SVG source text'};
    const words = text => (text.toLowerCase().match(/[\p{L}\p{N}]+/gu) || []);
    async function scanNow() {
      const button = node('editor-scan');
      const label = node('editor-scan-label');
      const control = button.closest('.editor-scan-control');  // the whole white control fills
      let meter = null, finished = false;
      try {
        button.disabled = true;
        label.textContent = 'Writing…';
        const result = await current();
        const form = new FormData();
        form.append('image', imageBlob(result), `${result.name}.${result.extension}`);
        form.append('configuration', node('editor-scan-configuration').value);
        for (const layer of state.layers) if (layer.kind === 'stego' && layer.stego === 'png_lsb' && !unsupported(layer)) form.append('lsb_layout', kinds().stego.layout(layer));
        const started = await fetch('/api/scans', {method: 'POST', body: form});
        const data = await started.json().catch(() => ({}));
        if (!started.ok) throw new Error(data.error || `Scan failed (${started.status}).`);
        state.scan = {version: snapshot(), expected: expectedOcr(), label: state.doc.label};
        label.textContent = 'Reading…';
        button.setAttribute('aria-busy', 'true');
        meter = window.vipiScanMeter(control, node('editor-scan-configuration').value);
        let job;
        do {
          await new Promise(resolve => setTimeout(resolve, SCAN_POLL_MS));
          const response = await fetch(`/api/scans/${data.id}`);
          job = await response.json();
          meter.update(job);
          const {checking, count} = window.vipiScanCount(job);
          const phase = checking ? 'Checking' : 'Reading';
          label.textContent = count ? `${phase} ${count[0]}/${count[1]}` : `${phase}…`;
        } while (job.state !== 'done' && job.state !== 'failed');
        finished = job.state === 'done';
        state.scan.job = job;
        renderScan();
        node('editor-scan-panel').scrollIntoView({behavior: 'smooth', block: 'nearest'});
      } catch (error) {
        status(error.message, true);
      } finally {
        button.removeAttribute('aria-busy');
        meter?.stop(finished);
        button.disabled = false;
        label.textContent = 'Scan with VIPI';
      }
    }
    const percent = value => value === null || value === undefined ? '—' : String(Math.round(value * 100));
    function renderScores(result) {
      const scores = {};
      for (const values of Object.values(result.readings || {})) for (const [name, value] of Object.entries(values)) scores[name] = Math.max(value, scores[name] ?? value);
      if (!Object.keys(scores).length && result.injection_probability !== null) scores.ocr = result.injection_probability;
      const rows = Object.entries(scores).sort((a, b) => b[1] - a[1]).map(([name, value]) => element('tr', {},
        element('td', {}, SCORE_NAMES[name] ?? name), element('td', {class: value >= result.threshold ? 'hit' : ''}, percent(value))));
      node('editor-scan-scores').replaceChildren(rows.length
        ? element('table', {}, element('thead', {}, element('tr', {}, element('th', {}, 'Reading'), element('th', {}, 'Score'))), element('tbody', {}, ...rows))
        : element('p', {class: 'muted'}, 'No reading was checked.'));
    }
    function renderCoverage(expectedText, recognized) {
      const expected = words(expectedText), found = new Set(words(recognized || ''));
      const missing = [...new Set(expected.filter(word => !found.has(word)))];
      const hits = expected.filter(word => found.has(word)).length;
      node('editor-scan-coverage').textContent = expected.length
        ? `${hits} of ${expected.length} expected words found${missing.length ? `; missing: ${missing.slice(0, 20).join(', ')}${missing.length > 20 ? ' …' : ''}` : ''}.`
        : 'No visible text was expected.';
    }
    function renderScan() {
      const scan = state.scan;
      if (!scan?.job) return;
      const {job} = scan;
      node('editor-scan-panel').hidden = false;
      node('editor-scan-stale').hidden = scan.version === snapshot();
      const banner = node('editor-scan-verdict');
      if (job.state === 'failed') {
        banner.dataset.verdict = 'failed';
        node('editor-scan-headline').textContent = 'The scan failed';
        node('editor-scan-note').textContent = job.error;
        for (const id of ['editor-scan-facts', 'editor-scan-scores', 'editor-scan-text', 'editor-scan-coverage']) node(id).replaceChildren();
        return;
      }
      const result = job.result;
      const [title, note] = VERDICTS[result.verdict] || [String(result.verdict), ''];
      banner.dataset.verdict = result.verdict === null ? 'no_result' : result.verdict;
      const ok = result.verdict === null ? null : (result.verdict === 'injection_detected') === (scan.label !== 'benign');
      node('editor-scan-headline').replaceChildren(title, ok === null ? '' : element('span', {class: 'editor-expect', 'data-ok': String(ok)}, `${ok ? 'as expected' : 'not expected'} for ${scan.label}`));
      node('editor-scan-note').textContent = note;
      const facts = [
        ['Injection probability', `${percent(result.injection_probability)} (detected at ≥ ${percent(result.threshold)})`],
        ['Detector', result.detector], ['OCR', `${(result.ocr_seconds ?? 0).toFixed(1)} s`], ['Detection', `${(result.detection_seconds ?? 0).toFixed(1)} s`],
        ['API cost', result.cost_usd ? `$${result.cost_usd.toFixed(4)}` : 'free'],
        ...(result.image_check ? [['Image check', `${result.image_check.status} · ${percent(result.image_check.probability)}`]] : []),
        ...(result.ocr_incomplete ? [['OCR', 'may have missed text']] : []),
      ];
      node('editor-scan-facts').replaceChildren(...facts.map(([term, value]) => element('div', {}, element('dt', {}, term), element('dd', {}, value))));
      renderScores(result);
      node('editor-scan-text').textContent = result.text || '— no text recognized —';
      renderCoverage(scan.expected, result.text);
      node('editor-scan-errors').hidden = !result.errors?.length;
      node('editor-scan-errors').replaceChildren(...(result.errors || []).map(error => element('li', {}, typeof error === 'string' ? error : JSON.stringify(error))));
    }
    async function bind() {
      node('editor-scan').onclick = scanNow;
      // A focus ring after a click looks like a selection border; show it for keyboard use only.
      const control = node('editor-scan').parentElement;
      control.addEventListener('pointerdown', () => { control.dataset.pointer = ''; });
      control.addEventListener('keydown', event => { if (event.key === 'Tab') delete control.dataset.pointer; });
      control.addEventListener('focusout', event => { if (!control.contains(event.relatedTarget)) delete control.dataset.pointer; });
      try {
        const response = await fetch('/api/configurations');
        if (!response.ok) throw new Error();
        const data = await response.json();
        const short = item => [item.run_on === 'local' ? 'Local' : 'Cloud', item.ocr_label, item.detector_label.split(' (')[0]].join(' · ');
        node('editor-scan-configuration').replaceChildren(...data.configurations.map(item => element('option', {value: item.id, selected: item.id === data.default, title: item.label}, `${short(item)}${item.paid ? ' · paid' : ''}`)));
      } catch { status('Scan settings could not be loaded.', true); }
    }
    return {bind};
  };
})();
