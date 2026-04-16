/**
 * JARVIS Dashboard — Neural Link v3.0
 */

const API = '';

// ── State ──
let currentPage = 'overview';

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  setupNav();
  setupTheme();
  navigate('overview');
  setInterval(() => { if (currentPage === 'overview') loadOverview(); }, 15000);
});

// ── Theme (Power Modes) ──
function setupTheme() {
  const toggle = document.getElementById('theme-toggle');
  const html = document.documentElement;
  const saved = localStorage.getItem('jarvis-hud-theme') || 'dark';
  
  const apply = (theme) => {
    html.setAttribute('data-theme', theme);
    localStorage.setItem('jarvis-hud-theme', theme);
    toggle.querySelector('.theme-text').textContent = theme === 'dark' ? 'Full Power' : 'Energy Save';
  };

  apply(saved);
  toggle.onclick = () => {
    const current = html.getAttribute('data-theme');
    apply(current === 'dark' ? 'light' : 'dark');
  };
}

// ── Navigation ──
function setupNav() {
  document.querySelectorAll('.nav-link').forEach(btn => {
    btn.onclick = () => navigate(btn.dataset.page);
  });
}

function navigate(page) {
  currentPage = page;
  document.querySelectorAll('.nav-link').forEach(n =>
    n.classList.toggle('active', n.dataset.page === page));
  document.querySelectorAll('.page-view').forEach(p =>
    p.classList.toggle('visible', p.id === `page-${page}`));

  const loaders = {
    overview: loadOverview,
    sessions: loadSessions,
    memory: loadMemory,
    chat: initChat,
    tools: loadTools,
  };
  (loaders[page] || (() => {}))();
}

// ── Diagnostics ──
async function loadOverview() {
  try {
    const [statsRes, sessionsRes] = await Promise.all([
      fetch(`${API}/api/stats`).then(r => r.json()),
      fetch(`${API}/api/sessions`).then(r => r.json()),
    ]);
    const stats = statsRes.data;
    const sessions = sessionsRes.data;

    document.getElementById('stat-tools').textContent = stats.tools_loaded.toString().padStart(2, '0');
    document.getElementById('stat-sessions').textContent = sessions.sessions.length.toString().padStart(2, '0');

    const llm = stats.llm_cache;
    document.getElementById('stat-cache-hit').textContent = `${(llm.hit_rate * 100).toFixed(0)}%`;
    document.getElementById('stat-cache-size').textContent = llm.size;

    const features = document.getElementById('features-list');
    const s = stats.settings;
    features.innerHTML = `
      <tr><td>Episodic Core</td><td>${badge(s.enable_episodic_memory)}</td></tr>
      <tr><td>Semantic Logic</td><td>${badge(s.enable_semantic_memory)}</td></tr>
      <tr><td>Trajectory Planner</td><td>${badge(s.enable_planner)}</td></tr>
      <tr><td>Remote Sync (Redis)</td><td>${badge(s.redis_url, 'info')}</td></tr>
    `;

    const tbody = document.getElementById('recent-sessions');
    tbody.innerHTML = sessions.sessions.slice(0, 6).map(s => `
      <tr>
        <td><code style="color: var(--accent)">${s.session_id.slice(-8)}</code></td>
        <td>${s.user_id}</td>
        <td><span class="status-badge info">${s.message_count} OPS</span></td>
        <td style="color: var(--text-muted); font-size: 11px; font-family: var(--font-mono)">${timeAgo(s.updated_at).toUpperCase()}</td>
      </tr>
    `).join('');
  } catch (e) { console.error(e); }
}

// ── Archives ──
async function loadSessions() {
  const res = await fetch(`${API}/api/sessions`).then(r => r.json());
  const { sessions } = res.data;
  const tbody = document.getElementById('all-sessions');
  tbody.innerHTML = sessions.map(s => `
    <tr>
      <td><code style="color: var(--accent)">${s.session_id}</code></td>
      <td>${s.user_id}</td>
      <td><span class="status-badge info">${s.message_count} MSGS</span></td>
      <td style="color: var(--text-muted); font-family: var(--font-mono)">${timeAgo(s.updated_at).toUpperCase()}</td>
    </tr>
  `).join('');
}

// ── Cognition ──
async function loadMemory() {
  try {
    const [epRes, factsRes] = await Promise.all([
      fetch(`${API}/api/memory/episodes`).then(r => r.json()),
      fetch(`${API}/api/memory/facts/default_user`).then(r => r.json()),
    ]);
    const episodes = epRes.data;
    const facts = factsRes.data;

    const epContainer = document.getElementById('episodes-list');
    epContainer.innerHTML = episodes.episodes.length === 0 
      ? '<p class="page-subtitle">ARCHIVE EMPTY</p>'
      : episodes.episodes.map(ep => `
        <div class="memory-card">
          <p style="font-size: 13px;">${escapeHtml(ep.summary)}</p>
          <div class="message-meta">${ep.task_id} // ${timeAgo(ep.created_at).toUpperCase()}</div>
        </div>
      `).join('');

    const factsContainer = document.getElementById('facts-list');
    factsContainer.innerHTML = facts.facts.length === 0
      ? '<p class="page-subtitle">NO SEMANTIC DATA</p>'
      : `
        <div class="data-card">
          <table>
            <thead><tr><th>Key</th><th>Weight</th></tr></thead>
            <tbody>
              ${facts.facts.map(f => `
                <tr>
                  <td><strong>${escapeHtml(f.key)}</strong></td>
                  <td><span class="status-badge ${f.confidence >= 0.8 ? 'success' : 'warning'}">${f.confidence}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
  } catch (e) { console.error(e); }
}

// ── Neural Link ──
let chatSessionId = null;
function initChat() {
  if (chatSessionId) return;
  const input = document.getElementById('chat-input');
  const btn = document.getElementById('chat-send');
  btn.onclick = sendMessage;
  input.onkeydown = e => { if (e.key === 'Enter') sendMessage(); };
}

async function sendMessage() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg) return;

  input.value = '';
  addChatBubble('user', msg);
  const loadingId = addChatBubble('assistant', `
    <div class="typing-loader">
      <div class="dot"></div><div class="dot"></div><div class="dot"></div>
    </div>
  `);

  try {
    const resp = await fetch(`${API}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, session_id: chatSessionId }),
    });
    const res = await resp.json();
    if (!res.success) throw new Error(res.message || 'CONNECTION TERMINATED');
    
    const data = res.data;
    chatSessionId = data.session_id;
    removeChatBubble(loadingId);
    const meta = `STEP:${data.steps_taken} // PROTOCOLS:[${data.tools_used.join(',') || 'NEURAL'}] // STATUS:${data.status}`;
    addChatBubble('assistant', escapeHtml(data.response), meta);
  } catch (e) {
    removeChatBubble(loadingId);
    addChatBubble('assistant', `<span style="color: var(--danger)">CRITICAL ERROR: ${e.message}</span>`);
  }
}

let msgCounter = 0;
function addChatBubble(role, html, meta = '') {
  const area = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = `message-bubble ${role}`;
  div.id = `m-${++msgCounter}`;
  div.innerHTML = html + (meta ? `<div class="message-meta">${meta}</div>` : '');
  area.appendChild(div);
  area.scrollTop = area.scrollHeight;
  return div.id;
}

function removeChatBubble(id) { document.getElementById(id)?.remove(); }

// ── Protocols ──
async function loadTools() {
  const res = await fetch(`${API}/tools`).then(r => r.json());
  const tools = res.data;
  const tbody = document.getElementById('tools-list');
  tbody.innerHTML = tools.map(t => `
    <tr>
      <td><strong style="color: var(--accent)">${t.name.toUpperCase()}</strong></td>
      <td style="color: var(--text-secondary); font-size: 13px;">${escapeHtml(t.description)}</td>
      <td><span class="status-badge ${tierClass(t.permission_tier)}">${t.permission_tier}</span></td>
      <td><span class="status-badge info">${t.rate_limit_per_minute}/M</span></td>
    </tr>
  `).join('');
}

// ── Helpers ──
function badge(val, cls = 'success') {
  return val ? `<span class="status-badge ${cls}">ONLINE</span>` : '<span class="status-badge danger">OFFLINE</span>';
}
function tierClass(t) { return { read: 'success', write: 'warning', destructive: 'danger' }[t] || 'info'; }
function timeAgo(ts) {
  if (!ts) return '-';
  const diff = (Date.now() - new Date(ts + 'Z').getTime()) / 1000;
  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}M ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}H ago`;
  return `${Math.floor(diff / 86400)}D ago`;
}
function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
