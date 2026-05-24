/** Thin fetch wrapper used by every page. */

export async function api(method, path, body, isFile) {
  const opts = { method };
  if (isFile) {
    opts.body = body;
  } else if (body) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || JSON.stringify(err));
  }
  return res.json();
}

export function timeAgo(ts) {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return 'just now';
  if (d < 3600) return Math.floor(d / 60) + 'm ago';
  if (d < 86400) return Math.floor(d / 3600) + 'h ago';
  return Math.floor(d / 86400) + 'd ago';
}

export function formatFileSize(bytes) {
  if (bytes === 0) return '0 B';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
  return (bytes / 1073741824).toFixed(2) + ' GB';
}

/** URL to the Inspect AI log viewer on port 7575. */
export const inspectUrl = 'http://' + window.location.hostname + ':7575';

/** Read a query-string parameter. */
export function param(name) {
  return new URLSearchParams(window.location.search).get(name) || '';
}

/**
 * Demo mode: set body class so CSS can hide destructive controls.
 * The backend middleware is the real guard (403 on all non-GET).
 */
export async function applyDemoGuard() {
  try {
    const s = await fetch('/api/settings').then(r => r.json());
    if (!s.demo) return;
    document.body.classList.add('demo-mode');
  } catch {}
}
