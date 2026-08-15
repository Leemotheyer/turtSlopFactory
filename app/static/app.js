const projectsEl = document.getElementById('projects');
const detailEl = document.getElementById('detail');
const detailTitle = document.getElementById('detail-title');
const detailProgress = document.getElementById('detail-progress');
const detailPhase = document.getElementById('detail-phase');
const detailEvents = document.getElementById('detail-events');
const statusPill = document.getElementById('status-pill');
const form = document.getElementById('start-form');

let selectedId = null;
let pollTimer = null;

function phasePill(phase, status) {
  if (phase === 'ready' || status === 'complete') return 'complete';
  if (phase === 'queued') return 'ok';
  return 'active';
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function fetchProjects() {
  const res = await fetch('api/projects');
  if (!res.ok) throw new Error('Failed to load projects');
  return res.json();
}

async function fetchProject(id) {
  const res = await fetch(`api/projects/${id}`);
  if (!res.ok) throw new Error('Project not found');
  return res.json();
}

function renderProjects(items) {
  if (!items.length) {
    projectsEl.innerHTML = '<p class="empty">No projects yet — start one above.</p>';
    statusPill.textContent = 'Agents idle';
    statusPill.className = 'pill ok';
    return;
  }

  const active = items.some((p) => p.phase !== 'ready');
  statusPill.textContent = active ? 'Agents working' : 'All projects ready';
  statusPill.className = `pill ${active ? 'active' : 'complete'}`;

  projectsEl.innerHTML = items
    .map(
      (p) => `
      <article class="project-row" data-id="${p.id}">
        <header>
          <strong>${escapeHtml(p.name)}</strong>
          <span class="pill ${phasePill(p.phase, p.status)}">${p.phase}</span>
        </header>
        <p class="muted">${escapeHtml(p.idea || 'Autonomous build in progress')}</p>
        <div class="progress-bar"><div class="progress-fill" style="width:${p.progress_pct}%"></div></div>
      </article>`
    )
    .join('');

  projectsEl.querySelectorAll('.project-row').forEach((row) => {
    row.addEventListener('click', () => openDetail(Number(row.dataset.id)));
  });
}

function renderDetail(project) {
  detailTitle.textContent = project.name;
  detailProgress.style.width = `${project.progress_pct}%`;
  detailPhase.textContent = `${project.phase} · ${project.progress_pct}%`;
  detailEvents.innerHTML = (project.events || [])
    .slice()
    .reverse()
    .map(
      (e) => `<li>${escapeHtml(e.message)}<time>${formatTime(e.created_at)}</time></li>`
    )
    .join('') || '<li class="muted">Waiting for agent activity…</li>';
  detailEl.classList.remove('hidden');
}

async function openDetail(id) {
  selectedId = id;
  const project = await fetchProject(id);
  renderDetail(project);
}

async function refresh() {
  const items = await fetchProjects();
  renderProjects(items);
  if (selectedId) {
    try {
      const project = await fetchProject(selectedId);
      renderDetail(project);
    } catch {
      selectedId = null;
      detailEl.classList.add('hidden');
    }
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('project-name').value.trim();
  const idea = document.getElementById('project-idea').value.trim();
  const btn = form.querySelector('button');
  btn.disabled = true;
  btn.textContent = 'Starting…';
  try {
    const res = await fetch('api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, idea }),
    });
    if (!res.ok) throw new Error('Could not start project');
    const project = await res.json();
    form.reset();
    await refresh();
    openDetail(project.id);
  } catch (err) {
    alert(err.message || 'Failed to start project');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Start building';
  }
});

document.getElementById('refresh-btn').addEventListener('click', refresh);
document.getElementById('close-detail').addEventListener('click', () => {
  selectedId = null;
  detailEl.classList.add('hidden');
});

refresh();
pollTimer = setInterval(refresh, 8000);
window.addEventListener('beforeunload', () => clearInterval(pollTimer));
