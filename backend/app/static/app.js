const form = document.getElementById('createForm');
const createButton = document.getElementById('createButton');
const emptyState = document.getElementById('emptyState');
const activeState = document.getElementById('activeState');
const statusSubtitle = document.getElementById('statusSubtitle');
const statusLabel = document.getElementById('statusLabel');
const progressValue = document.getElementById('progressValue');
const progressBar = document.getElementById('progressBar');
const durationValue = document.getElementById('durationValue');
const scenesValue = document.getElementById('scenesValue');
const generationValue = document.getElementById('generationValue');
const preview = document.getElementById('preview');
const actions = document.getElementById('actions');
const downloadLink = document.getElementById('downloadLink');
const metadataBox = document.getElementById('metadataBox');
const metadataTitle = document.getElementById('metadataTitle');
const metadataDescription = document.getElementById('metadataDescription');
const renderError = document.getElementById('renderError');
const formError = document.getElementById('formError');
const history = document.getElementById('history');
let currentProject = null;
let pollTimer = null;

function fileLabel(input, target, multiple = false) {
  input.addEventListener('change', () => {
    if (!input.files.length) return;
    document.getElementById(target).textContent = multiple
      ? `${input.files.length} file${input.files.length === 1 ? '' : 's'} selected`
      : input.files[0].name;
  });
}
fileLabel(document.getElementById('narration'), 'narrationName');
fileLabel(document.getElementById('clips'), 'clipsName', true);
fileLabel(document.getElementById('music'), 'musicName');

function setActive() {
  emptyState.classList.add('hidden');
  activeState.classList.remove('hidden');
}

function fmtDuration(seconds) {
  if (!seconds && seconds !== 0) return '-';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function applyState(state) {
  setActive();
  currentProject = state.project_id;
  const progress = Number(state.progress || 0);
  statusLabel.textContent = state.status || 'unknown';
  progressValue.textContent = `${progress}%`;
  progressBar.style.width = `${progress}%`;
  statusSubtitle.textContent = state.title || state.project_id;
  durationValue.textContent = fmtDuration(state.duration);
  scenesValue.textContent = Array.isArray(state.scenes) ? state.scenes.length : '-';
  generationValue.textContent = state.generation_budget?.used ?? 0;

  renderError.classList.add('hidden');
  if (state.status === 'failed') {
    renderError.textContent = state.error || 'Render failed.';
    renderError.classList.remove('hidden');
    createButton.disabled = false;
  }

  if (state.status === 'complete') {
    preview.src = `/api/projects/${state.project_id}/video?t=${Date.now()}`;
    preview.classList.remove('hidden');
    actions.classList.remove('hidden');
    downloadLink.href = `/api/projects/${state.project_id}/download`;
    if (state.metadata) {
      metadataTitle.textContent = state.metadata.title || '';
      metadataDescription.textContent = state.metadata.description || '';
      metadataBox.classList.remove('hidden');
    }
    createButton.disabled = false;
    if (pollTimer) clearInterval(pollTimer);
    loadHistory();
  }
}

async function fetchState(projectId) {
  const response = await fetch(`/api/projects/${projectId}`);
  if (!response.ok) throw new Error('Could not read project status');
  return response.json();
}

function startPolling(projectId) {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const state = await fetchState(projectId);
      applyState(state);
    } catch (err) {
      renderError.textContent = err.message;
      renderError.classList.remove('hidden');
    }
  }, 1500);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  formError.classList.add('hidden');
  renderError.classList.add('hidden');
  createButton.disabled = true;
  createButton.textContent = 'Uploading...';

  try {
    const data = new FormData(form);
    const response = await fetch('/api/projects', { method: 'POST', body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || 'Could not create project');

    currentProject = payload.project_id;
    setActive();
    preview.classList.add('hidden');
    actions.classList.add('hidden');
    metadataBox.classList.add('hidden');
    statusSubtitle.textContent = payload.project_id;
    statusLabel.textContent = 'queued';
    progressValue.textContent = '3%';
    progressBar.style.width = '3%';
    createButton.textContent = 'Rendering...';
    startPolling(payload.project_id);
  } catch (err) {
    formError.textContent = err.message;
    formError.classList.remove('hidden');
    createButton.disabled = false;
    createButton.textContent = 'Create Short';
  }
});

async function loadHistory() {
  try {
    const response = await fetch('/api/projects');
    const projects = await response.json();
    if (!projects.length) {
      history.innerHTML = '<p>No projects yet.</p>';
      return;
    }
    history.innerHTML = projects.slice(0, 12).map((project) => {
      const action = project.status === 'complete'
        ? `<a class="history-action" href="/api/projects/${project.project_id}/download">Download</a>`
        : '<span></span>';
      return `
        <div class="history-item">
          <div>
            <div class="history-title">${escapeHtml(project.title || project.project_id)}</div>
            <div class="history-meta">${escapeHtml(project.project_id)} | ${fmtDuration(project.duration)} | ${project.visual_count || 0} visuals</div>
          </div>
          <span class="status-chip">${escapeHtml(project.status || '')}</span>
          ${action}
        </div>`;
    }).join('');
  } catch (_) {
    history.innerHTML = '<p>Could not load project history.</p>';
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;'
  }[char]));
}

document.getElementById('refreshHistory').addEventListener('click', loadHistory);
document.getElementById('copyTitle').addEventListener('click', async () => {
  await navigator.clipboard.writeText(metadataTitle.textContent || '');
});
document.getElementById('copyDescription').addEventListener('click', async () => {
  await navigator.clipboard.writeText(metadataDescription.textContent || '');
});

loadHistory();
