'use strict';
// Scan progress inside the scan button, in two phases: reading (OCR) and
// checking (detection). Within a phase the bar moves with time, against how long
// that phase took in earlier scans with the same settings on this browser. The
// counts the scan reports (OCR passes, detection checks) are shown as text only:
// OCR also selects and assesses its text without reporting a count, so one
// finished pass can be a small or a large part of reading. A phase never shows
// complete before it ends, and the bar never moves back.
(() => {
  const STORE_KEY = 'vipi-scan-timing';
  const DEFAULT_MS = {read: 15000, checking: 3000};  // before the first timed scan
  const EASE = 1.6;          // at the expected duration a phase shows 80 % (1 - e^-1.6)
  const PHASE_CAP = 0.97;    // a running phase never shows as complete
  const LEARN = 0.5;         // weight of the newest scan in the stored durations
  const FINISH_MS = 300;     // time the bar shows full before it clears

  const now = () => performance.now();
  function loadTiming(configuration) {
    try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}')[configuration] || {}; } catch { return {}; }
  }
  function saveTiming(configuration, timing) {
    try {
      const all = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
      all[configuration] = timing;
      localStorage.setItem(STORE_KEY, JSON.stringify(all));
    } catch { /* timing is a convenience; the bar still works without it */ }
  }

  /** The running phase and its count, [done, planned] or null before anything is planned. */
  window.vipiScanCount = job => {
    const checking = job.state === 'checking';
    const [done, planned] = (checking ? job.progress?.checked : job.progress?.read) ?? [0, 0];
    return {checking, count: planned ? [done, planned] : null};
  };

  /** Drive the fill of `element` (a button or the editor's scan control) for one scan. */
  window.vipiScanMeter = (element, configuration) => {
    const saved = loadTiming(configuration);
    const expected = {read: saved.read ?? DEFAULT_MS.read, checking: saved.checking ?? DEFAULT_MS.checking};
    const readShare = expected.read / (expected.read + expected.checking);
    const started = now();
    let phase = 'read', phaseStarted = started, readMs = null;
    let shown = 0, frame = null, done = false;

    function paint() {
      const [from, span] = phase === 'read' ? [0, readShare] : [readShare, 1 - readShare];
      const timed = 1 - Math.exp(-EASE * (now() - phaseStarted) / expected[phase]);
      shown = Math.max(shown, from + span * Math.min(PHASE_CAP, timed));
      element.style.setProperty('--progress', shown.toFixed(4));
      if (!done) frame = requestAnimationFrame(paint);
    }

    /** Feed the latest polled job; it switches the phase when checking starts. */
    function update(job) {
      if (job.state !== 'checking' || phase !== 'read') return;
      readMs = now() - phaseStarted;
      phase = 'checking';
      phaseStarted = now();
    }

    /** End the scan; a finished scan fills the bar and updates the stored durations. */
    function stop(finished) {
      if (finished) {
        const phaseMs = now() - phaseStarted;
        // A checking phase too short to be polled counts as part of reading.
        const measured = readMs === null ? {read: phaseMs} : {read: readMs, checking: phaseMs};
        const blend = key => measured[key] === undefined ? saved[key]
          : saved[key] === undefined ? measured[key] : saved[key] * (1 - LEARN) + measured[key] * LEARN;
        saveTiming(configuration, {read: blend('read'), checking: blend('checking')});
        element.style.setProperty('--progress', '1');
      }
      done = true;
      cancelAnimationFrame(frame);
      setTimeout(() => { element.classList.remove('scan-meter'); element.style.removeProperty('--progress'); }, finished ? FINISH_MS : 0);
    }

    element.classList.add('scan-meter');
    element.style.setProperty('--progress', '0');
    frame = requestAnimationFrame(paint);
    return {update, stop};
  };
})();
