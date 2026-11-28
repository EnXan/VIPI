'use strict';
// Notifications at the top centre of the page, for status updates and errors on
// every workbench page. Newest on top; each closes itself or with its × button.
(() => {
  const SHOW_MS = {info: 4000, error: 8000};  // errors stay longer: they often need reading
  let stack = null;

  function container() {
    if (!stack) {
      stack = document.createElement('ol');
      stack.className = 'toasts';
      stack.setAttribute('aria-label', 'Notifications');
      document.body.append(stack);
    }
    return stack;
  }
  function dismiss(item) {
    if (!item.isConnected || item.dataset.leaving) return;
    item.dataset.leaving = 'true';
    item.addEventListener('animationend', () => item.remove(), {once: true});
    // Without animations (reduced motion), remove right away.
    if (getComputedStyle(item).animationName === 'none') item.remove();
  }

  /** Show `message`; kind 'error' or 'info'. Returns a function that closes it. */
  window.vipiToast = (message, {kind = 'info'} = {}) => {
    if (!message) return () => {};
    const item = document.createElement('li');
    item.className = 'toast';
    item.dataset.kind = kind;
    item.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = kind === 'error' ? '!' : 'i';
    const text = document.createElement('p');
    text.textContent = message;
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Close notification');
    close.textContent = '×';
    close.onclick = () => dismiss(item);
    item.append(icon, text, close);
    container().prepend(item);
    let timer = setTimeout(() => dismiss(item), SHOW_MS[kind] ?? SHOW_MS.info);
    // Hovering keeps it open, so a long error can be read.
    item.addEventListener('pointerenter', () => clearTimeout(timer));
    item.addEventListener('pointerleave', () => { timer = setTimeout(() => dismiss(item), SHOW_MS.info); });
    return () => dismiss(item);
  };
})();
