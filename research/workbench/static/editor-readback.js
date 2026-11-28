'use strict';
// Editor: what VIPI reads back from the written file, shown in the selected layer's
// properties. After every change the file is written and read with VIPI's own
// readers (no OCR, no detector), so a hidden layer shows whether it survived.
(() => {
  const {element, reveal} = window.vipiEditorUi;
  // The reading VIPI reports for a layer, for the detector's normalized input.
  const READING = {metadata: 'image_metadata', code: 'barcode', svg: 'svg_source'};
  const readingOf = layer => layer.kind === 'stego' ? layer.stego : READING[layer.kind];

  const block = (title, ...children) => element('div', {class: 'editor-readback-block'},
    element('h3', {}, title), ...children);
  const text = value => element('pre', {tabindex: 0}, reveal(value || ''));

  function statistics(lsb) {
    if (!lsb) return '';
    const rows = Object.entries(lsb).map(([channel, values]) => element('tr', {},
      element('td', {}, channel.toUpperCase()), element('td', {}, values.chi_square.toFixed(1)), element('td', {}, values.observed_pairs)));
    return element('details', {class: 'editor-details'},
      element('summary', {}, 'Low-bit statistics'),
      element('p', {class: 'muted editor-hint'}, 'χ² over even/odd value pairs per channel, as vipi scan --lsb-stats reports it. Changed low bits move it towards the pair count.'),
      element('table', {}, element('thead', {}, element('tr', {}, element('th', {}, 'Channel'), element('th', {}, 'χ²'), element('th', {}, 'Pairs'))),
        element('tbody', {}, ...rows)));
  }

  /**
   * The read-back for one layer: whether it arrived in the file and what VIPI reads.
   * Returns '' for layers that are not written as hidden data (text, removed areas).
   */
  window.vipiEditorReadback = ({layer, result, dirty, format, reason}) => {
    if (layer.kind === 'text' || layer.kind === 'heal' || layer.visible === false) return '';
    if (reason) return '';  // the properties already say why it is not written
    const mine = result?.layers.find(item => item.id === layer.id);
    if (dirty || !mine) return block('In the file', element('p', {class: 'muted'}, 'Writing the file and reading it back…'));
    const file = `the ${format.toUpperCase()}`;
    const detector = result.readings?.[readingOf(layer)];
    const normalized = detector && detector.detector_text && detector.detector_text !== detector.text
      ? element('details', {class: 'editor-details'}, element('summary', {}, 'What the detector gets'),
        element('p', {class: 'muted editor-hint'}, 'VIPI normalizes the read text before the detector sees it:'), text(detector.detector_text))
      : '';
    let body;
    if (layer.kind === 'scaling') {
      body = mine.status === 'read'
        ? [element('p', {class: 'status-read'}, `✓ The text appears when ${file} is downscaled.`)]
        : [element('p', {class: `status-${mine.status}`}, `${mine.exact_pixels} of ${mine.payload_pixels} payload pixels survive downscaling.`)];
    } else if (layer.kind === 'alpha') {
      body = mine.status === 'read'
        ? [element('p', {class: 'status-read'}, '✓ The text shows in its view (on black, or with alpha dropped).')]
        : [element('p', {class: `status-${mine.status}`}, `${mine.shown_pixels} of ${mine.text_pixels} text pixels show in its view.`)];
    } else if (mine.status === 'read') {
      body = [element('p', {class: 'status-read'}, `✓ VIPI reads it from ${file} as written:`), text((mine.read ?? [mine.expected]).join('\n'))];
    } else if (mine.status === 'changed') {
      body = [element('p', {class: 'status-changed'}, `≠ VIPI reads something else from ${file}:`), text(mine.read.join('\n')),
        element('p', {class: 'muted editor-hint'}, 'Written:'), text(mine.expected)];
    } else if (mine.status === 'missing') {
      body = [element('p', {class: 'status-missing'}, `✗ VIPI finds nothing of it in ${file}.`),
        format === 'jpeg' ? element('p', {class: 'muted editor-hint'}, 'JPEG compression changes pixels; pixel layers survive only in PNG or lossless WebP.') : ''];
    } else {
      body = [element('p', {class: 'muted'}, mine.reason || 'Not checked in this format.')];
    }
    return block('In the file', ...body, normalized, layer.kind === 'stego' ? statistics(result.lsb_statistics) : '');
  };
})();
