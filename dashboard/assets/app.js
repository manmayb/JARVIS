/**
 * Jarvis Dashboard — client-side logic.
 * Pure vanilla JS: fetches API data, renders pages, handles chat.
 */

const API = '';  // same origin

// ── State ──
let currentPage = 'overview';

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  setupNav();
  navigate('overview');
  // Auto-refresh stats every 15s
  setInterval(() => { if (currentPage === 'overview') loadOverview(); }, 15000);
});


// ── Navigation ──
function setupNav() {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => navigate(btn.dataset.page));
  });
}

function navigate(page) {
  currentPage = page;
  document.querySelectorAll('.nav-item').forEach(n =>
    n.classList.toggle('active', n.dataset.page === page));
  document.querySelectorAll('.page').forEach(p =>
    p.classList.toggle('active', p.id === `page-${page}`));

  const loaders = {
    overview: loadOverview,
    sessions: loadSessions,
    memory: loadMemory,
    chat: initChat,
    tools: loadTools,
  };
  (loaders[page] || (() => {}))();
}


// ── Overview ──
async function loadOverview() {
  try {
    const [stats, sessions] = await Promise.all([
      fetch(`${API}/api/stats`).then(r => r.json()),
      fetch(`${API}/api/sessions`).then(r => r.json()),
    ]);

    document.getElementById('stat-tools').textContent = stats.tools_loaded;
    document.getElementById('stat-sessions').textContent = sessions.sessions.length;

    const llm = stats.llm_cache;
    document.getElementById('stat-cache-hit').textContent =
      `${(llm.hit_rate * 100).toFixed(1)}%`;
    document.getElementById('stat-cache-size').textContent = llm.size;

    // Features
    const features = document.getElementById('features-list');
    const s = stats.settings;
    features.innerHTML = `
      <tr><td>Episodic Memory</td><td>${badge(s.enable_episodic_memory)}</td></tr>
      <tr><td>Semantic Memory</td><td>${badge(s.enable_semantic_memory)}</td></tr>
      <tr><td>Task Planner</td><td>${badge(s.enable_planner)}</td></tr>
      <tr><td>Redis Backend</td><td>${badge(s.redis_url, 'info')}</td></tr>
      <tr><td>Max Steps</td><td><span class="badge accent">${s.max_steps}</span></td></tr>
      <tr><td>Global Timeout</td><td><span class="badge accent">${s.global_timeout_seconds}s</span></td></tr>
    `;

    // Recent sessions
    const tbody = document.getElementById('recent-sessions');
    tbody.innerHTML = sessions.sessions.slice(0, 6).map(s => `
      <tr>
        <td><code style="color: var(--accent-light)">${s.session_id}</code></td>
        <td>${s.user_id}</td>
        <td><span class="badge accent">${s.message_count}</span></td>
        <td style="color: var(--text-muted)">${timeAgo(s.updated_at)}</td>
      </tr>
    `).join('');
  } catch (e) {
    console.error('Failed to load overview:', e);
  }
}


// ── Sessions ──
async function loadSessions() {
  const { sessions } = await fetch(`${API}/api/sessions`).then(r => r.json());
  const tbody = document.getElementById('all-sessions');
  tbody.innerHTML = sessions.map(s => `
    <tr>
      <td><code style="color: var(--accent-light)">${s.session_id}</code></td>
      <td>${s.user_id}</td>
      <td><span class="badge accent">${s.message_count}</span></td>
      <td style="color: var(--text-muted)">${s.created_at || '-'}</td>
      <td style="color: var(--text-muted)">${timeAgo(s.updated_at)}</td>
    </tr>
  `).join('');
}


// ── Memory ──
async function loadMemory() {
  try {
    const [episodes, facts] = await Promise.all([
      fetch(`${API}/api/memory/episodes`).then(r => r.json()),
      fetch(`${API}/api/memory/facts/default_user`).then(r => r.json()),
    ]);

    const epContainer = document.getElementById('episodes-list');
    if (episodes.episodes.length === 0) {
      epContainer.innerHTML = '<p style="color: var(--text-muted)">No episodes stored yet. Interact with the agent to build memory.</p>';
    } else {
      epContainer.innerHTML = episodes.episodes.map(ep => `
        <div class="episode-card">
          <div class="summary">${escapeHtml(ep.summary)}</div>
          <div class="meta-row">
            <span>🔗 ${ep.task_id}</span>
            <span>📁 ${ep.session_id}</span>
            <span>🕐 ${timeAgo(ep.created_at)}</span>
          </div>
        </div>
      `).join('');
    }

    const factsContainer = document.getElementById('facts-list');
    if (facts.facts.length === 0) {
      factsContainer.innerHTML = '<p style="color: var(--text-muted)">No user facts recorded yet.</p>';
    } else {
      factsContainer.innerHTML = `
        <div class="table-wrapper">
          <table>
            <thead><tr><th>Key</th><th>Value</th><th>Confidence</th><th>Source</th></tr></thead>
            <tbody>
              ${facts.facts.map(f => `
                <tr>
                  <td><strong>${escapeHtml(f.key)}</strong></td>
                  <td>${escapeHtml(f.value)}</td>
                  <td><span class="badge ${f.confidence >= 0.8 ? 'success' : 'warning'}">${f.confidence}</span></td>
                  <td style="color: var(--text-muted)">${f.source}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }
  } catch (e) {
    console.error('Failed to load memory:', e);
  }
}


// ── Chat ──
let chatSessionId = null;

function initChat() {
  if (chatSessionId) return; // already init
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-send');
  btn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });
}

async function sendMessage() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  addChatBubble('user', msg);

  const loadingId = addChatBubble('assistant', '<div class="loader"></div>');

  try {
    const body = { message: msg };
    if (chatSessionId) body.session_id = chatSessionId;

    const resp = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    chatSessionId = data.session_id;

    removeChatBubble(loadingId);
    const meta = `${data.steps_taken} steps · ${data.tools_used.join(', ') || 'no tools'} · ${data.status}`;
    addChatBubble('assistant', escapeHtml(data.response), meta);
  } catch (e) {
    removeChatBubble(loadingId);
    addChatBubble('assistant', `Error: ${e.message}`, '');
  }
}

let msgCounter = 0;
function addChatBubble(role, html, meta = '') {
  const id = `msg-${++msgCounter}`;
  const area = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.id = id;
  div.innerHTML = html + (meta ? `<div class="meta">${meta}</div>` : '');
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return id;
}

function removeChatBubble(id) {
  document.getElementById(id)?.remove();
}


// ── Tools ──
async function loadTools() {
  const tools = await fetch(`${API}/tools`).then(r => r.json());
  const tbody = document.getElementById('tools-list');
  tbody.innerHTML = tools.map(t => `
    <tr>
      <td><strong style="color: var(--accent-light)">${t.name}</strong></td>
      <td style="max-width: 300px">${escapeHtml(t.description)}</td>
      <td><span class="badge ${tierClass(t.permission_tier)}">${t.permission_tier}</span></td>
      <td><span class="badge accent">${t.rate_limit_per_minute}/min</span></td>
      <td>${t.timeout_seconds}s</td>
    </tr>
  `).join('');
}


// ── Helpers ──
function badge(val, cls = 'success') {
  if (val === true || val === 'configured')
    return `<span class="badge ${cls}">● Enabled</span>`;
  return '<span class="badge danger">○ Disabled</span>';
}

function tierClass(tier) {
  return { read: 'success', write: 'warning', destructive: 'danger' }[tier] || 'info';
}

function timeAgo(ts) {
  if (!ts) return '-';
  const diff = (Date.now() - new Date(ts + 'Z').getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}
