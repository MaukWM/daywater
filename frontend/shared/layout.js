/** Shared layout: header, toolbar, breadcrumb helpers. */

import { api } from './api.js';

// ── Header + toolbar ─────────────────────────────────────────────────── //

export function renderLayout() {
  // Global toolbar (settings + processes)
  const toolbar = document.createElement('div');
  toolbar.id = 'global-toolbar';
  toolbar.style.cssText = 'position:fixed; top:0.75rem; right:1.5rem; z-index:200; display:flex; gap:0.5rem; align-items:center;';
  toolbar.innerHTML = `
    <div style="position:relative;">
      <button onclick="window.location.href='/settings.html'" style="font-size:0.72rem; padding:0.3rem 0.6rem;">Settings</button>
    </div>
    <div style="position:relative;">
      <button onclick="window._toggleProcessPanel()" style="font-size:0.72rem; padding:0.3rem 0.6rem;">Processes</button>
      <div id="proc-panel" hidden style="position:absolute; right:0; top:100%; margin-top:0.5rem; width:420px; background:var(--surface); border:1px solid var(--border); padding:0.75rem; z-index:200; box-shadow:0 4px 12px rgba(0,0,0,0.4);">
        <div id="proc-list" style="font-size:0.78rem; max-height:300px; overflow-y:auto;"></div>
        <div style="margin-top:0.5rem; display:flex; gap:0.5rem;">
          <button onclick="window._refreshProcesses()" style="font-size:0.72rem; padding:0.2rem 0.5rem;">Refresh</button>
          <button onclick="window._killAllDolphins()" class="danger" style="font-size:0.72rem; padding:0.2rem 0.5rem;">Kill All</button>
        </div>
      </div>
    </div>
  `;
  document.body.prepend(toolbar);

  // Header
  const header = document.createElement('header');
  header.innerHTML = `
    <h1 style="cursor:pointer;" onclick="location.href='/index.html'">DAYWATER</h1>
    <p class="subtitle">gamecube reverse engineering platform</p>
  `;
  document.body.prepend(header);

  // ── Demo banner ──────────────────────────────────────────────────────
  api('GET', '/api/settings').then(s => {
    if (!s.demo) return;
    document.body.classList.add('demo-mode');
    const banner = document.createElement('div');
    banner.id = 'demo-banner';
    banner.textContent = 'Demo mode \u2014 read only.';
    document.body.prepend(banner);
    // Set CSS variable so fixed elements can offset below the banner
    requestAnimationFrame(() => {
      document.documentElement.style.setProperty('--demo-banner-h', banner.offsetHeight + 'px');
    });
  }).catch(() => {});

  // Wire up toolbar globals
  window._toggleProcessPanel = () => {
    const p = document.getElementById('proc-panel');
    const wasHidden = p.hidden;
    _closeAllPanels();
    if (wasHidden) { p.hidden = false; _refreshProcesses(); }
  };
  window._refreshProcesses = _refreshProcesses;
  window._killAllDolphins = async () => {
    if (!confirm('Kill all running Dolphin processes?')) return;
    await api('POST', '/api/processes/kill-all');
    _refreshProcesses();
  };

  // Close panels on outside click
  document.addEventListener('click', (e) => {
    const tb = document.getElementById('global-toolbar');
    if (tb && !tb.contains(e.target)) _closeAllPanels();
  });
}

function _closeAllPanels() {
  const proc = document.getElementById('proc-panel');
  if (proc) proc.hidden = true;
}

async function _refreshProcesses() {
  const el = document.getElementById('proc-list');
  try {
    const procs = await api('GET', '/api/processes');
    if (!procs.length) {
      el.innerHTML = '<span style="color:var(--text-dim);">No Dolphin processes running.</span>';
      return;
    }
    el.innerHTML = `<table class="kb-table"><tr><th>PID</th><th>Age</th><th>RAM</th><th>User Dir</th><th></th></tr>` +
      procs.map(p => `<tr>
        <td style="font-family:monospace;">${p.pid}</td>
        <td>${p.age_human}</td>
        <td>${p.rss_mb} MB</td>
        <td style="font-size:0.68rem; color:var(--text-dim); max-width:200px; overflow:hidden; text-overflow:ellipsis;">${p.user_dir}</td>
        <td><button class="danger" style="padding:0.1rem 0.4rem; font-size:0.65rem;" onclick="window._killDolphin(${p.pid})">kill</button></td>
      </tr>`).join('') + '</table>';
  } catch { el.innerHTML = '<span style="color:var(--red);">Failed to load processes.</span>'; }
}

window._killDolphin = async (pid) => {
  await api('POST', `/api/processes/${pid}/kill`);
  _refreshProcesses();
};

// ── Breadcrumb helper ─────────────────────────────────────────────────── //

export function breadcrumb(el, parts) {
  el.innerHTML = parts.map((p, i) => {
    if (i < parts.length - 1) {
      return `<a href="${p.href}">${p.text}</a><span class="sep">/</span>`;
    }
    return `<span>${p.text}</span>`;
  }).join('');
}
