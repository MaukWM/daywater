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
      <button onclick="window._toggleSettingsPanel()" style="font-size:0.72rem; padding:0.3rem 0.6rem;">Settings</button>
      <div id="settings-panel" hidden style="position:absolute; right:0; top:100%; margin-top:0.5rem; width:380px; background:var(--surface); border:1px solid var(--border); padding:0.75rem; z-index:200; box-shadow:0 4px 12px rgba(0,0,0,0.4);">
        <div style="font-size:0.68rem; font-weight:600; color:var(--green-dim); text-transform:uppercase; letter-spacing:0.06em; margin-bottom:0.5rem;">Settings</div>
        <div style="margin-bottom:0.6rem;">
          <label style="font-size:0.75rem; display:block; margin-bottom:0.2rem;">OpenAI API Key</label>
          <div style="display:flex; gap:0.4rem;">
            <input type="password" id="settings-api-key" placeholder="sk-..." style="flex:1; font-family:inherit; font-size:0.78rem; background:var(--bg); color:var(--text); border:1px solid var(--border); padding:0.35rem 0.5rem;">
            <button onclick="window._toggleKeyVis()" id="key-vis-btn" style="font-size:0.68rem; padding:0.2rem 0.4rem;">show</button>
          </div>
          <div id="settings-key-status" style="font-size:0.68rem; color:var(--text-dim); margin-top:0.2rem;"></div>
        </div>
        <div style="margin-bottom:0.6rem;">
          <label style="font-size:0.75rem; display:block; margin-bottom:0.2rem;">Model</label>
          <input type="text" id="settings-model" placeholder="openai/gpt-5.5" style="width:100%; font-family:inherit; font-size:0.78rem; background:var(--bg); color:var(--text); border:1px solid var(--border); padding:0.35rem 0.5rem;">
          <div style="font-size:0.65rem; color:var(--text-dim); margin-top:0.15rem;">e.g. openai/gpt-5.5, anthropic/claude-sonnet-4-5-20250514</div>
        </div>
        <div style="display:flex; align-items:center; gap:0.5rem;">
          <button onclick="window._saveSettings()" style="font-size:0.72rem; padding:0.25rem 0.6rem;">Save</button>
          <span id="settings-saved" style="font-size:0.68rem; color:var(--green); margin-left:0.5rem;" hidden>saved</span>
          <span style="flex:1;"></span>
          <a href="/setup.html" style="font-size:0.65rem; color:var(--text-dim);">Re-run Setup</a>
        </div>
      </div>
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

  // Wire up toolbar globals
  window._toggleSettingsPanel = () => {
    const p = document.getElementById('settings-panel');
    const wasHidden = p.hidden;
    _closeAllPanels();
    if (wasHidden) { p.hidden = false; _loadSettings(); }
  };
  window._toggleProcessPanel = () => {
    const p = document.getElementById('proc-panel');
    const wasHidden = p.hidden;
    _closeAllPanels();
    if (wasHidden) { p.hidden = false; _refreshProcesses(); }
  };
  window._toggleKeyVis = () => {
    const i = document.getElementById('settings-api-key');
    const b = document.getElementById('key-vis-btn');
    if (i.type === 'password') { i.type = 'text'; b.textContent = 'hide'; }
    else { i.type = 'password'; b.textContent = 'show'; }
  };
  window._saveSettings = async () => {
    const body = {};
    const k = document.getElementById('settings-api-key').value.trim();
    const m = document.getElementById('settings-model').value.trim();
    if (k) body.openai_api_key = k;
    if (m !== undefined) body.model = m;
    await api('POST', '/api/settings', body);
    const s = document.getElementById('settings-saved');
    s.hidden = false;
    setTimeout(() => { s.hidden = true; }, 2000);
    _loadSettings();
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
  document.getElementById('settings-panel').hidden = true;
  document.getElementById('proc-panel').hidden = true;
}

async function _loadSettings() {
  try {
    const s = await api('GET', '/api/settings');
    const ki = document.getElementById('settings-api-key');
    const st = document.getElementById('settings-key-status');
    const mi = document.getElementById('settings-model');
    ki.value = '';
    if (s.openai_api_key_set) {
      ki.placeholder = `Set (${s.openai_api_key_preview})`;
      st.textContent = 'Key is configured.';
      st.style.color = 'var(--green-dim)';
    } else {
      ki.placeholder = 'sk-...';
      st.textContent = 'No key set. Required for agent runs.';
      st.style.color = 'var(--amber)';
    }
    mi.value = s.model || '';
  } catch (e) { console.error('Settings load failed:', e); }
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
