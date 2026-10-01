const $ = (id) => document.getElementById(id);
const form = $('createForm');
const createButton = $('createButton');
const emptyState = $('emptyState');
const activeState = $('activeState');
const renderError = $('renderError');
const formError = $('formError');
const preview = $('preview');
const actions = $('actions');
const metadataBox = $('metadataBox');
const creditsBox = $('creditsBox');
const creditsLink = $('creditsLink');
const visualSource = $('visual_source');
const selectionMode = $('stock_selection_mode');
const stockProviders = $('stock_providers');
const stockMaxClips = $('stock_max_clips');
const preferPortrait = $('prefer_portrait');
const stockSelections = $('stock_selections');
const stockCandidates = $('stockCandidates');
const stockSearchError = $('stockSearchError');
const findStockButton = $('findStockButton');
let pollTimer = null;

function fileLabel(id, target, multiple) {
  const input = $(id);
  input.addEventListener('change', function () {
    if (!input.files.length) return;
    $(target).textContent = multiple
      ? input.files.length + ' file' + (input.files.length === 1 ? '' : 's') + ' selected'
      : input.files[0].name;
  });
}
fileLabel('narration', 'narrationName', false);
fileLabel('clips', 'clipsName', true);
fileLabel('music', 'musicName', false);

function esc(value) {
  return String(value == null ? '' : value).replace(/[&<>'"]/g, function (ch) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#039;','"':'&quot;'}[ch];
  });
}

function setActive() {
  emptyState.classList.add('hidden');
  activeState.classList.remove('hidden');
}

function fmtDuration(seconds) {
  if (seconds == null) return '-';
  const m = Math.floor(seconds / 60);
  const s = String(Math.floor(seconds % 60)).padStart(2, '0');
  return m + ':' + s;
}

function providerLabel(name) {
  return name === 'pexels' ? 'Pexels' : name === 'pixabay' ? 'Pixabay' : name;
}

function updateStockControls() {
  const enabled = visualSource.value !== 'upload';
  findStockButton.disabled = !enabled;
  selectionMode.disabled = !enabled;
  stockProviders.disabled = !enabled;
  stockMaxClips.disabled = !enabled;
  preferPortrait.disabled = !enabled;
  if (!enabled || selectionMode.value === 'auto') {
    stockSelections.value = '';
    stockCandidates.classList.add('hidden');
  } else if (stockCandidates.children.length) {
    stockCandidates.classList.remove('hidden');
  }
}
visualSource.addEventListener('change', updateStockControls);
selectionMode.addEventListener('change', updateStockControls);

async function loadStockStatus() {
  try {
    const r = await fetch('/api/stock/status');
    const p = await r.json();
    const c = p.configured || {};
    $('stockStatus').textContent =
      (c.pexels ? 'Pexels ✓' : 'Pexels key missing') + ' · ' +
      (c.pixabay ? 'Pixabay ✓' : 'Pixabay key missing');
    $('stockStatus').classList.toggle('warning', !c.pexels && !c.pixabay);
  } catch (_) {
    $('stockStatus').textContent = 'Could not check API keys';
    $('stockStatus').classList.add('warning');
  }
}

function syncSelections() {
  const selected = [];
  stockCandidates.querySelectorAll('input[type="radio"]:checked').forEach(function (radio) {
    selected.push({
      scene_index: Number(radio.dataset.sceneIndex),
      provider: radio.dataset.provider,
      id: radio.dataset.id,
      query: radio.dataset.query || ''
    });
  });
  stockSelections.value = JSON.stringify(selected);
}

function renderCandidates(payload) {
  const results = payload.results || [];
  let html = '';
  results.forEach(function (result) {
    html += '<div class="candidate-scene">';
    html += '<div class="candidate-scene-heading"><span>Scene ' + (Number(result.scene_index) + 1) +
      '</span><strong>' + esc(result.query) + '</strong><small>' + esc(result.text) + '</small></div>';
    if (result.error) html += '<div class="error">' + esc(result.error) + '</div>';
    html += '<div class="candidate-grid">';
    (result.candidates || []).forEach(function (c, index) {
      const id = 's_' + result.scene_index + '_' + c.provider + '_' + c.id;
      const previewHtml = c.preview_url
        ? '<img src="' + esc(c.preview_url) + '" alt="" loading="lazy">'
        : '<div class="candidate-placeholder">VIDEO</div>';
      html += '<label class="candidate-card" for="' + esc(id) + '">';
      html += '<input id="' + esc(id) + '" type="radio" name="scene_stock_' + result.scene_index +
        '" data-scene-index="' + result.scene_index + '" data-provider="' + esc(c.provider) +
        '" data-id="' + esc(c.id) + '" data-query="' + esc(result.query) + '"' +
        (index === 0 ? ' checked' : '') + '>';
      html += previewHtml;
      html += '<div class="candidate-body"><div class="candidate-topline"><strong>' +
        esc(providerLabel(c.provider)) + '</strong><span>' + (c.portrait ? 'Portrait' : 'Landscape') +
        '</span></div><small>' + esc(c.width) + '×' + esc(c.height) + ' · ' +
        (c.duration ? Math.round(c.duration) + 's' : 'duration n/a') +
        '</small><small>' + esc(c.creator || 'Contributor') + '</small>';
      if (c.page_url) html += '<a href="' + esc(c.page_url) + '" target="_blank" rel="noopener">View source</a>';
      html += '</div></label>';
    });
    if (!(result.candidates || []).length) html += '<p>No matching clips found.</p>';
    html += '</div></div>';
  });
  stockCandidates.innerHTML = html || '<p>No stock results returned.</p>';
  stockCandidates.classList.remove('hidden');
  selectionMode.value = 'review';
  stockCandidates.querySelectorAll('input[type="radio"]').forEach(function (radio) {
    radio.addEventListener('change', syncSelections);
  });
  syncSelections();
}

findStockButton.addEventListener('click', async function () {
  stockSearchError.classList.add('hidden');
  const title = $('title').value.trim();
  const script = $('script').value.trim();
  if (!title && !script) {
    stockSearchError.textContent = 'Add a title or narration script first.';
    stockSearchError.classList.remove('hidden');
    return;
  }
  findStockButton.disabled = true;
  findStockButton.textContent = 'Searching free stock...';
  try {
    const data = new FormData();
    data.set('title', title);
    data.set('prompt', $('prompt').value.trim());
    data.set('script', script);
    data.set('stock_providers', stockProviders.value);
    data.set('stock_max_clips', stockMaxClips.value);
    data.set('prefer_portrait', preferPortrait.checked ? 'true' : 'false');
    const r = await fetch('/api/stock/search', {method:'POST', body:data});
    const p = await r.json();
    if (!r.ok) throw new Error(p.detail || 'Stock search failed');
    renderCandidates(p);
  } catch (err) {
    stockSearchError.textContent = err.message;
    stockSearchError.classList.remove('hidden');
  } finally {
    findStockButton.disabled = false;
    findStockButton.textContent = 'Find Matching Clips';
    updateStockControls();
  }
});

function renderCredits(state) {
  const credits = Array.isArray(state.stock_credits) ? state.stock_credits : [];
  $('stockValue').textContent = state.stock_clip_count || credits.length || 0;
  if (!credits.length) {
    creditsBox.classList.add('hidden');
    creditsLink.classList.add('hidden');
    return;
  }
  $('creditsList').innerHTML = credits.map(function (c) {
    const link = c.source_url
      ? '<a href="' + esc(c.source_url) + '" target="_blank" rel="noopener">source</a>'
      : '';
    return '<div class="credit-row"><strong>' + esc(providerLabel(c.provider)) + '</strong><span>' +
      esc(c.creator || 'Contributor') + '</span>' + link + '</div>';
  }).join('');
  creditsBox.classList.remove('hidden');
  creditsLink.href = '/api/projects/' + state.project_id + '/credits';
  creditsLink.classList.remove('hidden');
}

function applyState(state) {
  setActive();
  renderError.classList.add('hidden');
  $('statusLabel').textContent = state.status || 'unknown';
  $('progressValue').textContent = String(state.progress || 0) + '%';
  $('progressBar').style.width = String(state.progress || 0) + '%';
  $('statusSubtitle').textContent = state.title || state.project_id;
  $('durationValue').textContent = fmtDuration(state.duration);
  $('scenesValue').textContent = Array.isArray(state.scenes) ? state.scenes.length : '-';
  $('generationValue').textContent = state.generation_budget && state.generation_budget.used || 0;
  $('stockValue').textContent = state.stock_clip_count || 0;

  if (state.status === 'failed') {
    renderError.textContent = state.error || 'Render failed.';
    renderError.classList.remove('hidden');
    createButton.disabled = false;
    createButton.textContent = 'Create Short';
    clearInterval(pollTimer);
  }

  if (state.status === 'complete') {
    preview.src = '/api/projects/' + state.project_id + '/video?t=' + Date.now();
    preview.classList.remove('hidden');
    actions.classList.remove('hidden');
    $('downloadLink').href = '/api/projects/' + state.project_id + '/download';
    renderCredits(state);
    if (state.metadata) {
      $('metadataTitle').textContent = state.metadata.title || '';
      $('metadataDescription').textContent = state.metadata.description || '';
      metadataBox.classList.remove('hidden');
    }
    createButton.disabled = false;
    createButton.textContent = 'Create Short';
    clearInterval(pollTimer);
    loadHistory();
  }
}

function startPolling(projectId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async function () {
    try {
      const r = await fetch('/api/projects/' + projectId);
      if (!r.ok) throw new Error('Could not read project status');
      applyState(await r.json());
    } catch (err) {
      renderError.textContent = err.message;
      renderError.classList.remove('hidden');
    }
  }, 1800);
}

form.addEventListener('submit', async function (event) {
  event.preventDefault();
  formError.classList.add('hidden');
  createButton.disabled = true;
  createButton.textContent = 'Uploading...';
  try {
    const data = new FormData(form);
    data.set('prefer_portrait', preferPortrait.checked ? 'true' : 'false');
    if (selectionMode.value === 'review') {
      syncSelections();
      data.set('stock_selections', stockSelections.value);
    } else {
      data.set('stock_selections', '');
    }
    const r = await fetch('/api/projects', {method:'POST', body:data});
    const p = await r.json();
    if (!r.ok) throw new Error(p.detail || 'Could not create project');
    setActive();
    preview.classList.add('hidden');
    actions.classList.add('hidden');
    metadataBox.classList.add('hidden');
    creditsBox.classList.add('hidden');
    $('statusSubtitle').textContent = p.project_id;
    $('statusLabel').textContent = 'queued';
    $('progressValue').textContent = '3%';
    $('progressBar').style.width = '3%';
    createButton.textContent = 'Rendering...';
    startPolling(p.project_id);
  } catch (err) {
    formError.textContent = err.message;
    formError.classList.remove('hidden');
    createButton.disabled = false;
    createButton.textContent = 'Create Short';
  }
});

async function loadHistory() {
  try {
    const r = await fetch('/api/projects');
    const projects = await r.json();
    if (!projects.length) {
      $('history').innerHTML = '<p>No projects yet.</p>';
      return;
    }
    $('history').innerHTML = projects.slice(0, 12).map(function (p) {
      const action = p.status === 'complete'
        ? '<a class="history-action" href="/api/projects/' + p.project_id + '/download">Download</a>'
        : '<span></span>';
      return '<div class="history-item"><div><div class="history-title">' +
        esc(p.title || p.project_id) + '</div><div class="history-meta">' +
        esc(p.project_id) + ' · ' + fmtDuration(p.duration) + ' · ' +
        (p.visual_count || 0) + ' visuals · ' + (p.stock_clip_count || 0) +
        ' stock</div></div><span class="status-chip">' + esc(p.status || '') +
        '</span>' + action + '</div>';
    }).join('');
  } catch (_) {
    $('history').innerHTML = '<p>Could not load project history.</p>';
  }
}

$('refreshHistory').addEventListener('click', loadHistory);
$('copyTitle').addEventListener('click', function () {
  navigator.clipboard.writeText($('metadataTitle').textContent || '');
});
$('copyDescription').addEventListener('click', function () {
  navigator.clipboard.writeText($('metadataDescription').textContent || '');
});

updateStockControls();
loadStockStatus();
loadHistory();
