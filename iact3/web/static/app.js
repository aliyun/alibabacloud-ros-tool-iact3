// === Navigation ===
let currentPage = 'dashboard';
let refreshInterval = null;
let _globalSettings = {};
let _settingsReady = null;  // Promise that resolves when settings are first loaded

document.querySelectorAll('.nav-menu a').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        navigateTo(link.dataset.page);
    });
});

function navigateTo(page) {
    currentPage = page;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-menu a').forEach(a => a.classList.remove('active'));

    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');

    const navLink = document.querySelector(`[data-page="${page}"]`);
    if (navLink) navLink.classList.add('active');

    // Auto-refresh for dashboard
    if (refreshInterval) { clearInterval(refreshInterval); refreshInterval = null; }
    if (page === 'dashboard') {
        refreshRuns();
        loadHistory();
        loadProjectList();
        refreshInterval = setInterval(refreshRuns, 5000);
    }
    if (page === 'reports') { loadReports(); }
    if (page === 'settings') { loadSettings(); }

    // Auto-fill defaults on form pages
    if (page === 'workspace') {
        autoFillDefaults(page);
        _updateWorkspaceCredentialWarning();
    }
}

// === API Helpers ===
async function api(url, options = {}) {
    const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!resp.ok) {
        const text = await resp.text();
        let errMsg = `HTTP ${resp.status}`;
        if (text) {
            try {
                const errData = JSON.parse(text);
                errMsg = errData.error || errData.message || errMsg;
            } catch {
                errMsg = text.substring(0, 200);
            }
        }
        throw new Error(errMsg);
    }
    return resp.json();
}

function showToast(msg, duration = 3000, type = '') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    // Remove previous type classes
    toast.classList.remove('toast-success', 'toast-error', 'toast-warning', 'toast-info');
    if (type) toast.classList.add(`toast-${type}`);
    toast.classList.remove('hidden');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => toast.classList.add('hidden'), duration);
}

function formatTime(isoStr) {
    if (!isoStr) return '-';
    return new Date(isoStr).toLocaleString();
}

function formatDuration(startIso, endIso) {
    if (!startIso) return '-';
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    const diff = Math.max(0, Math.floor((end - start) / 1000));
    if (diff < 60) return diff + 's';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ' + (diff % 60) + 's';
    const h = Math.floor(diff / 3600);
    const m = Math.floor((diff % 3600) / 60);
    return h + 'h ' + m + 'm';
}

function getBadgeClass(status) {
    const map = {
        'running': 'badge-running',
        'completed': 'badge-completed',
        'failed': 'badge-failed',
        'pending': 'badge-pending',
        'cancelled': 'badge-cancelled',
    };
    return map[status] || 'badge-pending';
}

// === Collapsible Sections ===
function toggleCollapsible(header) {
    const section = header.closest('.collapsible-section');
    if (!section) return;
    const body = section.querySelector('.collapsible-body');
    if (!body) return;
    const isOpen = !body.classList.contains('collapsed');
    if (isOpen) {
        body.classList.add('collapsed');
        section.classList.remove('open');
    } else {
        body.classList.remove('collapsed');
        section.classList.add('open');
    }
}

/** Update the summary text shown in a collapsible header for template/config editors */
function _updateEditorSummary(page, type) {
    const textarea = document.getElementById(`${page}-${type}-content`);
    const summaryEl = document.getElementById(`${page}-${type}-summary`);
    if (!textarea || !summaryEl) return;
    const content = textarea.value || '';
    if (!content.trim()) {
        summaryEl.textContent = '';
        return;
    }
    const lines = content.split('\n').length;
    const firstLine = content.trim().split('\n')[0].substring(0, 60);
    // Detect format
    let fmtKey = 'editor.fmt_yaml';
    if (content.trim().startsWith('{')) fmtKey = 'editor.fmt_json';
    else if (content.trim().startsWith('resource ') || content.includes('terraform')) fmtKey = 'editor.fmt_terraform';
    const fmt = t(fmtKey);
    summaryEl.textContent = `${fmt} · ${lines} ${t('editor.lines')} · ${firstLine}${firstLine.length >= 60 ? '...' : ''}`;
}

// === Dashboard ===
let _allRuns = [];  // cached runs data for tag filtering

// --- Card pagination helpers ---
const CARD_PAGE_SIZE = { projects: 5, runs: 5, history: 8 };
const _cardPage = { projects: 0, runs: 0, history: 0 };

function _renderCardPagination(paginationId, total, pageSize, currentPage, setPageFn) {
    const el = document.getElementById(paginationId);
    if (!el) return;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    if (total <= pageSize) { el.innerHTML = ''; return; }
    // Clamp currentPage to valid range
    const page = Math.max(0, Math.min(currentPage, totalPages - 1));
    const start = page * pageSize + 1;
    const end   = Math.min((page + 1) * pageSize, total);
    el.innerHTML = `
        <span class="card-pagination-info">${start}–${end} / ${total}</span>
        <div class="card-pagination-btns">
            <button class="card-pagination-btn" onclick="${setPageFn}(0)" ${page===0?'disabled':''} title="${t('common.first')}">«</button>
            <button class="card-pagination-btn" onclick="${setPageFn}(${page-1})" ${page===0?'disabled':''} title="${t('common.prev')}">‹</button>
            <span class="card-pagination-page">${page+1} / ${totalPages}</span>
            <button class="card-pagination-btn" onclick="${setPageFn}(${page+1})" ${page>=totalPages-1?'disabled':''} title="${t('common.next')}">›</button>
            <button class="card-pagination-btn" onclick="${setPageFn}(${totalPages-1})" ${page>=totalPages-1?'disabled':''} title="${t('common.last')}">»</button>
        </div>`;
}

function _setRunsPage(p)  {
    const totalPages = Math.max(1, Math.ceil((_allRuns.length || 0) / CARD_PAGE_SIZE.runs));
    _cardPage.runs = Math.max(0, Math.min(p, totalPages - 1));
    _renderRunsTags();
}
function _setHistPage(p)  {
    _cardPage.history = Math.max(0, p);
    _renderHistory();
}
function _setProjPage(p)  {
    _cardPage.projects = Math.max(0, p);
    loadProjectList();
}

async function refreshRuns() {
    try {
        const data = await api('/api/runs');
        _allRuns = data.runs || [];
        renderRuns(_allRuns);
        _renderRunsTags();
        _updateRunsFilter();
    } catch (err) {
        console.error('Failed to load runs:', err);
    }
}

function renderRuns(runs) {
    const guide = document.getElementById('quick-start-guide');
    if (!runs.length) {
        if (guide) guide.classList.remove('hidden');
    } else {
        if (guide) guide.classList.add('hidden');
    }
    // Show onboarding card on first visit (no runs + never dismissed)
    const onboarding = document.getElementById('onboarding-card');
    if (onboarding) {
        const dismissed = localStorage.getItem('iact3-onboarding-dismissed');
        if (!runs.length && !dismissed) {
            onboarding.classList.remove('hidden');
        } else {
            onboarding.classList.add('hidden');
        }
    }
    // Render dashboard stats
    _renderDashboardStats(runs);
}

// === Runs Tag List (compact view with filters) ===

// === Onboarding ===
function dismissOnboarding() {
    localStorage.setItem('iact3-onboarding-dismissed', '1');
    const card = document.getElementById('onboarding-card');
    if (card) card.classList.add('hidden');
}

// === Dashboard Stats ===
function _renderDashboardStats(runs) {
    const container = document.getElementById('dashboard-stats');
    if (!container) return;
    const total = runs.length;
    const running = runs.filter(r => r.status === 'running').length;
    const completed = runs.filter(r => r.status === 'completed').length;
    const failed = runs.filter(r => r.status === 'failed').length;
    const projectCount = typeof _projectsCache !== 'undefined' ? _projectsCache.length : 0;
    if (!total && !projectCount) { container.innerHTML = ''; return; }
    container.innerHTML = `
        <div class="stat-card">
            <div class="stat-value">${total}</div>
            <div class="stat-label">${t('dashboard.stats_total')}</div>
        </div>
        <div class="stat-card stat-running">
            <div class="stat-value">${running}</div>
            <div class="stat-label">${t('dashboard.stats_running')}</div>
        </div>
        <div class="stat-card stat-completed">
            <div class="stat-value">${completed}</div>
            <div class="stat-label">${t('dashboard.stats_completed')}</div>
        </div>
        <div class="stat-card stat-failed">
            <div class="stat-value">${failed}</div>
            <div class="stat-label">${t('dashboard.stats_failed')}</div>
        </div>
        <div class="stat-card stat-projects">
            <div class="stat-value">${projectCount}</div>
            <div class="stat-label">${t('dashboard.stats_projects')}</div>
        </div>`;
}

// === Credential Warning in Workspace ===
function _updateWorkspaceCredentialWarning() {
    const warning = document.getElementById('workspace-credential-warning');
    if (!warning) return;
    if (_globalSettings && !_globalSettings.credentials_set) {
        warning.classList.remove('hidden');
    } else {
        warning.classList.add('hidden');
    }
}

// === Nav Credential Dot ===
function _updateNavCredentialDot() {
    const settingsLink = document.querySelector('[data-page="settings"]');
    if (!settingsLink) return;
    let dot = settingsLink.querySelector('.nav-credential-dot');
    if (_globalSettings && !_globalSettings.credentials_set) {
        if (!dot) {
            dot = document.createElement('span');
            dot.className = 'nav-credential-dot';
            dot.title = t('settings.no_credentials');
            settingsLink.appendChild(dot);
        }
    } else {
        if (dot) dot.remove();
    }
}

// === Analysis Result Enhancement ===
function _wrapResultWithBanner(type, isSuccess, contentHtml) {
    if (isSuccess) {
        const successLabels = {
            validate: t('analyze.success_validate'),
            preview: t('analyze.success_preview', {n: '?'}),
            cost: t('analyze.success_cost', {n: '?'}),
            policy: t('analyze.success_policy'),
        };
        return `<div class="result-status-banner result-success">
            <svg class="result-status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            <span>${successLabels[type] || t('analyze.all_done')}</span>
        </div>${contentHtml}`;
    } else {
        return `<div class="result-status-banner result-error">
            <svg class="result-status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            <span>${t('analyze.fail_generic')}</span>
        </div>${contentHtml}`;
    }
}
function filterRunsBy() {
    _cardPage.runs = 0;  // reset to first page on filter change
    _renderRunsTags();
}

function _updateRunsFilter() {
    const select = document.getElementById('runs-project-filter');
    if (!select) return;
    // Use project definitions (not just runs) to build filter options
    const projectNames = new Set();
    _projectsCache.forEach(p => projectNames.add(p.name));
    _allRuns.forEach(r => { if (r.params?.project_name) projectNames.add(r.params.project_name); });
    const sorted = [...projectNames].sort();
    const current = select.value;
    select.innerHTML = `<option value="">${t('dashboard.runs_filter_all_projects')} (${_projectsCache.length})</option>` +
        sorted.map(n => {
            const count = _allRuns.filter(r => r.params?.project_name === n).length;
            return `<option value="${escapeHtml(n)}">${escapeHtml(n)} (${count})</option>`;
        }).join('');
    select.value = current;
}

function _renderRunsTags() {
    const container = document.getElementById('runs-tag-list');
    if (!container) return;
    let runs = _allRuns;
    // Apply project filter
    const projectFilter = document.getElementById('runs-project-filter')?.value || '';
    if (projectFilter) runs = runs.filter(r => r.params?.project_name === projectFilter);
    // Apply status filter
    const statusFilter = document.getElementById('runs-status-filter')?.value || '';
    if (statusFilter) runs = runs.filter(r => r.status === statusFilter);
    // Apply time filter
    const timeFilter = document.getElementById('runs-time-filter')?.value || '';
    if (timeFilter) {
        const now = Date.now();
        const cutoffs = { today: 86400000, week: 604800000, month: 2592000000 };
        const cutoff = cutoffs[timeFilter] || 0;
        if (cutoff) runs = runs.filter(r => (now - new Date(r.created_at).getTime()) < cutoff);
    }
    if (!runs.length) {
        container.innerHTML = `<div class="runs-tag-empty">${t('dashboard.no_runs')}</div>`;
        _renderCardPagination('runs-tag-pagination', 0, CARD_PAGE_SIZE.runs, 0, '_setRunsPage');
        return;
    }
    // Pagination
    const pageSize = CARD_PAGE_SIZE.runs;
    const totalPages = Math.ceil(runs.length / pageSize);
    if (_cardPage.runs >= totalPages) _cardPage.runs = totalPages - 1;
    const pageRuns = runs.slice(_cardPage.runs * pageSize, (_cardPage.runs + 1) * pageSize);
    container.innerHTML = pageRuns.map(run => {
        const p = run.params || {};
        const stacks = run.stacks || [];
        // Use getStackResult() for accurate pass/fail/cleaned calculation
        const results = stacks.map(s => getStackResult(s, p));
        const succeeded = results.filter(r => r === 'pass').length;
        const failed = results.filter(r => r === 'fail').length;
        const cleaned = results.filter(r => r === 'cleaned').length;
        const duration = formatDuration(run.created_at, run.completed_at);
        const createdAt = formatTime(run.created_at);
        // Status badge - use dedicated status keys (not label keys like "创建时间")
        let statusIcon = '', statusText = '';
        if (run.status === 'running') { statusIcon = ''; statusText = t('detail.running'); }
        else if (run.status === 'completed') { statusIcon = ''; statusText = t('detail.run_completed'); }
        else if (run.status === 'failed') { statusIcon = ''; statusText = t('detail.run_failed'); }
        else if (run.status === 'cancelled') { statusIcon = ''; statusText = t('detail.cancelled'); }
        else { statusIcon = ''; statusText = t('detail.pending'); }
        // Sub-tags
        const subTags = [];
        if (p.project_name) subTags.push(`<span class="run-tag run-tag-project">${escapeHtml(p.project_name)}</span>`);
        if (stacks.length) subTags.push(`<span class="run-tag run-tag-stacks">${stacks.length}</span>`);
        const regions = stacks.length
            ? [...new Set(stacks.map(s => s.region).filter(Boolean))]
            : (p.regions ? String(p.regions).split(',').map(r => r.trim()) : []);
        if (regions.length) subTags.push(`<span class="run-tag run-tag-region">${escapeHtml(regions.slice(0, 2).join(', '))}</span>`);
        if (stacks.length && run.status !== 'running' && run.status !== 'pending') {
            if (failed) subTags.push(`<span class="run-tag run-tag-fail">${failed}</span>`);
            if (succeeded) subTags.push(`<span class="run-tag run-tag-pass">${succeeded}</span>`);
            if (cleaned) subTags.push(`<span class="run-tag run-tag-stacks">${cleaned}</span>`);
        }
        // Result summary for completed/failed runs - count pass + cleaned as success
        let resultSummary = '';
        if (stacks.length && (run.status === 'completed' || run.status === 'failed')) {
            const total = stacks.length;
            const successCount = succeeded + cleaned;
            const passRate = total > 0 ? Math.round((successCount / total) * 100) : 0;
            const rateColor = passRate === 100 ? '#16a34a' : (passRate >= 50 ? '#d97706' : '#dc2626');
            resultSummary = `<span class="runs-tag-result" style="color:${rateColor}">${passRate}% ${t('detail.pass_rate')}</span>`;
        }
        return `<div class="runs-tag-item" onclick="showRunDetail('${run.id}')">
            <div class="runs-tag-item-header">
                <span class="runs-tag-status">${statusIcon}</span>
                <span class="runs-tag-item-name">${escapeHtml(run.name)}</span>
                <span class="runs-tag-item-badge badge badge-${run.status}">${statusText}</span>
                ${resultSummary}
                ${run.status !== 'running' ? `<button class="btn-text-danger runs-tag-delete" onclick="event.stopPropagation(); deleteRun('${run.id}')">${t('editor.delete_saved')}</button>` : ''}
            </div>
            <div class="runs-tag-item-meta">
                <span>${t('detail.created')}: ${createdAt}</span>
                ${run.status !== 'pending' ? `<span>${duration}</span>` : ''}
                ${run.status === 'running' ? `<span>${run.progress}%</span>` : ''}
            </div>
            ${subTags.length ? `<div class="runs-tag-item-tags">${subTags.join('')}</div>` : ''}
            ${run.status === 'running' ? `<div class="runs-tag-progress"><div class="runs-tag-progress-fill" style="width:${run.progress}%"></div></div>` : ''}
        </div>`;
    }).join('');
    _renderCardPagination('runs-tag-pagination', runs.length, pageSize, _cardPage.runs, '_setRunsPage');
}

// === Run Detail ===
async function showRunDetail(runId) {
    navigateTo('detail');
    const container = document.getElementById('run-detail');
    container.innerHTML = `<div class="empty-state"><div class="spinner"></div> ${t('detail.loading')}</div>`;

    try {
        const run = await api(`/api/runs/${runId}`);
        renderRunDetail(run);

        // Auto-refresh if running
        if (run.status === 'running') {
            const interval = setInterval(async () => {
                const updated = await api(`/api/runs/${runId}`);
                renderRunDetail(updated);
                if (updated.status !== 'running') clearInterval(interval);
            }, 3000);
        }
    } catch (err) {
        container.innerHTML = `<div class="empty-state">${t('detail.load_failed')}${err.message}</div>`;
    }
}

/** Build a hint text below the progress bar showing phase breakdown */
function _buildProgressHint(phases, params) {
    const parts = [];
    const creating = phases.filter(p => p === 'creating' || p === 'initializing').length;
    const deleting = phases.filter(p => p === 'deleting').length;
    const rollingBack = phases.filter(p => p === 'rolling_back').length;
    const created = phases.filter(p => p === 'created').length;
    if (creating) parts.push(`${t('detail.phase_creating')}: ${creating}`);
    if (created) parts.push(`${t('detail.phase_waiting_delete')}: ${created}`);
    if (deleting) parts.push(`${t('detail.phase_deleting')}: ${deleting}`);
    if (rollingBack) parts.push(`${t('detail.phase_rolling_back')}: ${rollingBack}`);
    return parts.length ? parts.join(' \u00b7 ') : '';
}

function renderRunDetail(run) {
    const container = document.getElementById('run-detail');
    const stacks = run.stacks || [];
    const p = run.params || {};
    // Analyze each stack result considering run options
    const results = stacks.map(s => getStackResult(s, p));
    const succeeded = results.filter(r => r === 'pass').length;
    const failed = results.filter(r => r === 'fail').length;
    const cleaned = results.filter(r => r === 'cleaned').length;
    const inProgress = results.filter(r => r === 'pending' || r === 'deleting').length;
    // Compute phases for each stack
    const phases = stacks.map(s => getStackPhase(s, p));
    const phaseCounts = {};
    phases.forEach(ph => { phaseCounts[ph] = (phaseCounts[ph] || 0) + 1; });
    const isRunning = run.status === 'running';
    const duration = formatDuration(run.created_at, run.completed_at);
    // Only completed runs show 100%; failed/cancelled show actual progress so users
    // can see how far the test got before the failure (e.g. 50% create phase).
    const displayProgress = run.status === 'completed' ? 100 : run.progress;
    // Fix: extract regions and test_names from stacks if not in params
    const regions = p.regions
        ? (Array.isArray(p.regions) ? p.regions.join(', ') : String(p.regions).replace(/,/g, ', '))
        : (stacks.length ? [...new Set(stacks.map(s => s.region).filter(Boolean))].join(', ') : '-');
    const testNames = p.test_names
        ? String(p.test_names).replace(/,/g, ', ')
        : (stacks.length ? [...new Set(stacks.map(s => s.test_name).filter(Boolean))].join(', ') : '-');
    const logFormat = p.log_format || 'txt';

    // Store run globally for showRunReports to use
    window._currentRun = run;

    // Update header buttons dynamically
    const headerActions = document.getElementById('detail-header-actions');
    const hasDeletableStacks = stacks.some(s => s.stack_id && !s.status?.startsWith('DELETE'));
    if (headerActions) {
        headerActions.innerHTML = `
            <div class="detail-actions-left">
                ${run.report_path ? `<button class="btn btn-primary" onclick="showRunReports()">${t('detail.view_reports')}</button>` : ''}
                <button class="btn" onclick="navigateTo('dashboard')" data-i18n="detail.back">${t('detail.back')}</button>
            </div>
            <div class="detail-actions-right">
                ${run.status === 'running' ? `<button class="btn btn-danger" onclick="cancelRun('${run.id}')">${t('detail.cancel')}</button>` : ''}
                ${run.status !== 'running' && hasDeletableStacks ? `<button class="btn btn-danger" onclick="deleteRunStacks('${run.id}')">${t('detail.delete_stacks')}</button>` : ''}
                ${run.status !== 'running' ? `<button class="btn btn-outline-danger" onclick="deleteRun('${run.id}')">${t('detail.delete_record')}</button>` : ''}
            </div>
        `;
    }

    container.innerHTML = `
        <div class="detail-section">
            <h3>${t('detail.overview')}</h3>
            <div class="detail-grid">
                <div class="detail-item"><label>${t('detail.name')}</label><span>${escapeHtml(run.name)}</span></div>
                <div class="detail-item"><label>${t('detail.id')}</label><span style="font-family:monospace">${run.id}</span></div>
                <div class="detail-item"><label>${t('detail.status')}</label><span class="badge ${getBadgeClass(run.status)}">${t('status.' + run.status) || run.status}</span></div>
                <div class="detail-item detail-item-wide"><label>${t('detail.progress')}</label>
                    <div class="detail-progress">
                        <div class="detail-progress-bar">
                            <div class="detail-progress-fill detail-progress-${run.status}" style="width: ${displayProgress}%"></div>
                        </div>
                        <span class="detail-progress-text">${displayProgress}%</span>
                    </div>
                    ${isRunning ? `<div class="detail-progress-hint">${_buildProgressHint(phases, p)}</div>` : ''}
                </div>
                <div class="detail-item"><label>${t('detail.duration')}</label><span>${duration}</span></div>
                <div class="detail-item"><label>${t('detail.created')}</label><span>${formatTime(run.created_at)}</span></div>
                <div class="detail-item"><label>${t('detail.completed')}</label><span>${formatTime(run.completed_at)}</span></div>
            </div>
            ${run.error ? `<div class="detail-error">${escapeHtml(run.error)}</div>` : ''}
        </div>

        ${stacks.length ? `
            <div class="detail-section">
                <div class="detail-summary-cards">
                    <div class="summary-card">
                        <div class="summary-card-value">${stacks.length}</div>
                        <div class="summary-card-label">${t('detail.total_stacks')}</div>
                    </div>
                    <div class="summary-card summary-card-success">
                        <div class="summary-card-value">${succeeded}</div>
                        <div class="summary-card-label">${t('detail.succeeded')}</div>
                    </div>
                    <div class="summary-card summary-card-danger">
                        <div class="summary-card-value">${failed}</div>
                        <div class="summary-card-label">${t('detail.failed')}</div>
                    </div>
                    <div class="summary-card summary-card-info">
                        <div class="summary-card-value">${inProgress}</div>
                        <div class="summary-card-label">${t('detail.in_progress')}</div>
                    </div>
                    ${cleaned > 0 ? `<div class="summary-card summary-card-muted">
                        <div class="summary-card-value">${cleaned}</div>
                        <div class="summary-card-label">${t('detail.cleaned')}</div>
                    </div>` : ''}
                </div>
                <div class="result-content-header" style="margin-top: 16px;">
                    <h3>${t('detail.stacks', {n: stacks.length})}</h3>
                    <button class="btn-result-copy" onclick="copyResultContent(this)">${t('common.copy')}</button>
                </div>
                <table class="data-table detail-stacks-table">
                    <thead>
                        <tr>
                            <th style="width:32px">#</th>
                            <th>${t('detail.col_test')}</th>
                            <th>${t('detail.col_region')}</th>
                            <th>${t('detail.col_stack')}</th>
                            <th style="width:110px">${t('detail.col_phase')}</th>
                            <th>${t('detail.col_status')}</th>
                            <th style="width:80px">${t('detail.col_result')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${stacks.map((s, i) => `
                            <tr>
                                <td style="color:var(--text-muted)">${i + 1}</td>
                                <td><strong>${escapeHtml(s.test_name)}</strong></td>
                                <td>${escapeHtml(s.region)}</td>
                                <td style="font-family: monospace; font-size: 12px;">${s.stack_id
                                    ? `<a href="https://ros.console.aliyun.com/${encodeURIComponent(s.region)}/stacks/${encodeURIComponent(s.stack_id)}" target="_blank" rel="noopener" style="color: var(--primary); text-decoration: none; word-break: break-all;" title="${escapeHtml(s.stack_name)}">${escapeHtml(s.stack_id)}</a>`
                                    : `<span style="color:var(--text-muted);font-style:italic">${escapeHtml(s.stack_name || t('detail.stack_pending_id'))}</span>`}</td>
                                <td>${getStackPhaseHtml(phases[i])}</td>
                                <td><span class="${getStackStatusClass(s.status)}">${escapeHtml(s.status || '-')}</span></td>
                                <td>${getStackResultHtml(results[i])}</td>
                            </tr>
                            ${s.status_reason ? `<tr class="detail-reason-row"><td></td><td colspan="6" style="font-size: 12px; padding-left: 12px;">${t('detail.reason')}: ${escapeHtml(s.status_reason)}</td></tr>` : ''}
                        `).join('')}
                    </tbody>
                </table>
            </div>
        ` : ''}

        ${run.params ? `
            <div class="detail-section">
                <div class="result-content-header">
                    <h3>${t('detail.run_config')}</h3>
                    <button class="btn-result-copy" onclick="copyResultContent(this)">${t('common.copy')}</button>
                </div>
                <div class="detail-grid detail-grid-compact">
                    <div class="detail-item"><label>${t('detail.cfg_regions')}</label><span>${escapeHtml(regions)}</span></div>
                    <div class="detail-item"><label>${t('detail.cfg_test_names')}</label><span>${escapeHtml(testNames)}</span></div>
                    <div class="detail-item"><label>${t('detail.cfg_log_format')}</label><span>${escapeHtml(logFormat)}</span></div>
                    <div class="detail-item"><label>${t('detail.cfg_no_delete')}</label><span>${p.no_delete ? t('common.yes') : t('common.no')}</span></div>
                    <div class="detail-item"><label>${t('detail.cfg_keep_failed')}</label><span>${p.keep_failed ? t('common.yes') : t('common.no')}</span></div>
                    <div class="detail-item"><label>${t('detail.cfg_dont_wait')}</label><span>${p.dont_wait_for_delete ? t('common.yes') : t('common.no')}</span></div>
                    ${p.project_path ? `<div class="detail-item"><label>${t('detail.cfg_project_path')}</label><span style="font-family:monospace;font-size:12px">${escapeHtml(p.project_path)}</span></div>` : ''}
                    ${p.config_file ? `<div class="detail-item"><label>${t('detail.cfg_config_file')}</label><span style="font-family:monospace;font-size:12px;word-break:break-all">${escapeHtml(p.config_file)}</span></div>` : ''}
                    ${p.template ? `<div class="detail-item"><label>${t('detail.cfg_template')}</label><span style="font-family:monospace;font-size:12px;word-break:break-all">${escapeHtml(p.template)}</span></div>` : ''}
                </div>
            </div>
        ` : ''}
    `;
}

// Modal back-stack: when viewing a file from run reports, closing returns to the list
let _modalOnClose = null;

// Show report files list in modal (filtered for current run)
async function showRunReports() {
    const run = window._currentRun;
    const modal = document.getElementById('file-modal');
    const title = document.getElementById('modal-filename');
    const body = document.getElementById('modal-content');
    const loading = document.getElementById('modal-loading');
    const copyBtn = document.getElementById('modal-copy-btn');

    modal.classList.remove('hidden');
    title.textContent = t('detail.report_files');
    body.textContent = '';
    body.classList.add('hidden');
    loading.classList.remove('hidden');
    copyBtn.classList.add('hidden');
    _modalOnClose = null; // No back when viewing the list itself
    document.getElementById('modal-back-btn').classList.add('hidden');

    try {
        const data = await api('/api/reports');
        const allReports = data.reports || [];
        // Filter: only log files whose name starts with a stack_name from this run
        const stacks = (run && run.stacks) || [];
        const stackNames = stacks.map(s => s.stack_name).filter(Boolean);
        const reports = stackNames.length
            ? allReports.filter(r => stackNames.some(sn => r.name.startsWith(sn)))
            : allReports;
        loading.classList.add('hidden');
        if (!reports.length) {
            body.innerHTML = `<div class="empty-state">${t('reports.empty')}</div>`;
        } else {
            body.innerHTML = reports.map(r => {
                const enc = encodeURIComponent(r.name);
                return `<div class="report-list-item" onclick="viewReportFromList('${enc}')">
                    <span class="file-link">${escapeHtml(r.name)}</span>
                    <span style="color: var(--text-muted); font-size: 11px;">${formatSize(r.size)}</span>
                </div>`;
            }).join('');
        }
        body.classList.remove('hidden');
    } catch (err) {
        body.innerHTML = `<div class="empty-state">${t('reports.failed')}</div>`;
        body.classList.remove('hidden');
    } finally {
        loading.classList.add('hidden');
    }
}

// View a file from the run reports list; closing will return to the list
function viewReportFromList(filename) {
    _modalOnClose = showRunReports; // set callback to return to list
    document.getElementById('modal-back-btn').classList.remove('hidden');
    viewReport(filename);
}

function getStackStatusClass(status) {
    if (!status) return '';
    if (status === 'DELETE_COMPLETE') return 'stack-status-cleaned';
    if (status === 'DELETE_IN_PROGRESS') return 'stack-status-deleting';
    if (status.includes('ROLLBACK_COMPLETE') || status.includes('ROLLBACK_FAILED')) return 'stack-status-failed';
    if (status.includes('FAILED')) return 'stack-status-failed';
    if (status.includes('ROLLBACK_IN_PROGRESS')) return 'stack-status-progress';
    if (status === 'CREATE_COMPLETE') return 'stack-status-complete';
    if (status.includes('IN_PROGRESS')) return 'stack-status-progress';
    if (status.includes('COMPLETE') && !status.includes('FAILED') && !status.includes('ROLLBACK')) {
        return 'stack-status-complete';
    }
    return '';
}

/**
 * Determine stack test result considering run options.
 * Returns: 'pass' | 'fail' | 'cleaned' | 'pending' | 'deleting' | 'unknown'
 */
function getStackResult(stack, params) {
    const status = stack.status || '';
    const p = params || {};

    // Explicit success from iact3 — but still check transient delete states
    if (stack.launch_succeeded) {
        // Stack created successfully; deletion is still in flight
        if (status === 'DELETE_IN_PROGRESS') {
            // dont_wait: DELETE_IN_PROGRESS is the expected terminal state → pass
            if (p.dont_wait_for_delete) return 'pass';
            return 'pending';
        }
        // After cleanup, mark as cleaned
        if (status === 'DELETE_COMPLETE' && !p.no_delete) return 'cleaned';
        return 'pass';
    }

    // No status yet
    if (!status) return 'unknown';

    // Failed / Rollback states
    if (status.includes('FAILED') || status.includes('ROLLBACK_COMPLETE') || status.includes('ROLLBACK_FAILED')) {
        return 'fail';
    }

    // DELETE_COMPLETE
    if (status === 'DELETE_COMPLETE') {
        // keep_failed: only failed stacks are kept; a stack that reached DELETE_COMPLETE
        // was a *successful* stack that got cleaned up normally → show cleaned, not fail
        return 'cleaned';
    }

    // DELETE_IN_PROGRESS
    if (status === 'DELETE_IN_PROGRESS') {
        // dont_wait: this is the expected terminal state — treat as pass (cleaned)
        if (p.dont_wait_for_delete) return 'pass';
        return 'pending';
    }

    // Still creating/updating
    if (status.includes('IN_PROGRESS')) return 'pending';

    // CREATE_COMPLETE — success regardless of no_delete
    if (status === 'CREATE_COMPLETE') return 'pass';

    // Other COMPLETE states
    if (status.includes('COMPLETE')) return 'pass';

    return 'unknown';
}

function getStackResultHtml(result) {
    const map = {
        pass:    `<span style="color:var(--success)">\u2713 ${t('detail.stack_pass')}</span>`,
        fail:    `<span style="color:var(--danger)">\u2717 ${t('detail.stack_fail')}</span>`,
        cleaned: `<span class="stack-result-cleaned">${t('detail.stack_cleaned')}</span>`,
        pending: `<span style="color:var(--primary)">\u25CB ${t('detail.stack_pending')}</span>`,
        deleting:`<span style="color:var(--text-muted)">\u21BB ${t('detail.stack_deleting')}</span>`,
        unknown: `<span style="color:var(--text-muted)">-</span>`,
    };
    return map[result] || map.unknown;
}

/**
 * Determine the current phase of a stack for user-friendly display.
 * Returns: 'initializing' | 'creating' | 'created' | 'create_failed' | 'rolling_back' | 'deleting' | 'deleted' | 'delete_failed' | 'unknown'
 */
function getStackPhase(stack, params) {
    const status = stack.status || '';
    const p = params || {};
    if (!status) return 'initializing';
    // Create phase
    if (status === 'CREATE_IN_PROGRESS' || status === 'UPDATE_IN_PROGRESS') return 'creating';
    if (status === 'CREATE_COMPLETE' || status === 'UPDATE_COMPLETE') {
        if (p.no_delete) return 'done';
        return 'created'; // waiting for deletion
    }
    // Create failures / rollbacks
    if (status === 'CREATE_FAILED' || status === 'UPDATE_FAILED') return 'create_failed';
    if (status === 'CREATE_ROLLBACK_IN_PROGRESS' || status === 'ROLLBACK_IN_PROGRESS') return 'rolling_back';
    if (status === 'CREATE_ROLLBACK_COMPLETE' || status === 'ROLLBACK_COMPLETE' || status === 'ROLLBACK_FAILED') return 'create_failed';
    // Delete phase
    if (status === 'DELETE_IN_PROGRESS') {
        // dont_wait: deletion triggered but we don't wait — show as done from this run's perspective
        if (p.dont_wait_for_delete) return 'done';
        return 'deleting';
    }
    if (status === 'DELETE_COMPLETE') return 'deleted';
    if (status === 'DELETE_FAILED') return 'delete_failed';
    return 'unknown';
}

function getStackPhaseHtml(phase) {
    const map = {
        initializing: `<span class="phase-badge phase-init"><span class="phase-dot pulse"></span>${t('detail.phase_init')}</span>`,
        creating:     `<span class="phase-badge phase-creating"><span class="phase-dot pulse"></span>${t('detail.phase_creating')}</span>`,
        created:      `<span class="phase-badge phase-created"><span class="phase-dot"></span>${t('detail.phase_created')}</span>`,
        done:         `<span class="phase-badge phase-done"><span class="phase-dot"></span>${t('detail.phase_done')}</span>`,
        create_failed:`<span class="phase-badge phase-failed"><span class="phase-dot"></span>${t('detail.phase_create_failed')}</span>`,
        rolling_back: `<span class="phase-badge phase-rollback"><span class="phase-dot pulse"></span>${t('detail.phase_rolling_back')}</span>`,
        deleting:     `<span class="phase-badge phase-deleting"><span class="phase-dot pulse"></span>${t('detail.phase_deleting')}</span>`,
        deleted:      `<span class="phase-badge phase-deleted"><span class="phase-dot"></span>${t('detail.phase_deleted')}</span>`,
        delete_failed:`<span class="phase-badge phase-failed"><span class="phase-dot"></span>${t('detail.phase_delete_failed')}</span>`,
        unknown:      `<span class="phase-badge phase-unknown"><span class="phase-dot"></span>-</span>`,
    };
    return map[phase] || map.unknown;
}

async function cancelRun(runId) {
    await api(`/api/runs/${runId}/cancel`, { method: 'POST' });
    showToast(t('detail.run_cancelled'));
    showRunDetail(runId);
}

async function deleteRun(runId) {
    const ok = await confirmDialog(t('detail.delete_record_confirm'));
    if (!ok) return;
    await api(`/api/runs/${runId}`, { method: 'DELETE' });
    showToast(t('detail.run_deleted'));
    navigateTo('dashboard');
}

let _deletingStacks = false;

async function deleteRunStacks(runId) {
    if (_deletingStacks) return;
    const ok = await confirmDialog(t('detail.delete_stacks_confirm'));
    if (!ok) return;
    _deletingStacks = true;
    try {
        const result = await api(`/api/runs/${runId}/delete-stacks`, { method: 'POST' });
        const msg = t('detail.delete_stacks_result', { deleted: result.deleted, errors: result.errors });
        showToast(msg);
        // Optimistically update local state so UI reflects deletion immediately
        if (window._currentRun && window._currentRun.stacks) {
            for (const detail of result.details || []) {
                if (detail.status === 'deleted') {
                    const stack = window._currentRun.stacks.find(s => s.stack_id === detail.stack_id);
                    if (stack) {
                        stack.status = 'DELETE_COMPLETE';
                    }
                }
            }
            renderRunDetail(window._currentRun);
        } else {
            showRunDetail(runId);
        }
    } catch (err) {
        const msg = err.message || '';
        let friendly = t('detail.delete_stacks_failed');
        if (msg.includes('404') || msg.includes('Run not found') || msg.includes('RUN_NOT_FOUND')) {
            friendly = t('detail.delete_stacks_no_run');
        } else if (msg.includes('NO_DELETABLE_STACKS') || msg.includes('No deletable stacks')) {
            friendly = t('detail.delete_stacks_none_left');
        } else if (msg.includes('NO_STACKS') || msg.includes('No stacks found')) {
            friendly = t('detail.delete_stacks_none_left');
        } else {
            friendly = t('detail.delete_stacks_failed') + ': ' + err.message;
        }
        showToast(friendly);
    } finally {
        _deletingStacks = false;
    }
}

// === Run Test Form ===
const _runForm = document.getElementById('workspace-form');
if (_runForm) _runForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    // Block submission while project is loading
    if (_projectLoading['workspace']) {
        showToast(t('project.loading_wait'));
        return;
    }
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');

    // --- Pre-flight validation ---
    const _showRunMsg = (msgs) => {
        const el = document.getElementById('run-validation-msg');
        if (!el) return;
        if (!msgs || !msgs.length) { el.classList.add('hidden'); el.innerHTML = ''; return; }
        el.innerHTML = msgs.map(m => `<div class="run-val-item">${m}</div>`).join('');
        el.classList.remove('hidden');
        el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    const editorOverrides0 = await fileEditor.prepareForm('workspace-form');
    const templateContent0 = editorOverrides0.template_content || '';
    const configContent0 = editorOverrides0.config_content || '';
    const regionHidden = form.querySelector('.region-hidden');
    const regionsVal = regionHidden ? regionHidden.value.trim() : '';
    const valErrors = [];
    if (!templateContent0.trim()) {
        valErrors.push(`${t('run.val_no_template')}`);
    }
    if (!configContent0.trim()) {
        valErrors.push(`${t('run.val_no_config')}`);
    }
    if (!regionsVal) {
        valErrors.push(`${t('run.val_no_regions')}`);
    }
    // Check project name
    const runProjectName = document.getElementById('workspace-project-name')?.value?.trim();
    if (!runProjectName) {
        valErrors.push(t('project.name_required'));
    }
    if (valErrors.length) {
        _showRunMsg(valErrors);
        return;
    }
    // clear any previous message
    _showRunMsg(null);
    // --- End pre-flight ---

    setButtonLoading(btn, true);
    btn.textContent = t('run.starting');

    try {
        // Auto-save project before running test
        const projectName = await _autoSaveProject('workspace');
        if (!projectName) {
            _showRunMsg([t('project.save_failed')]);
            return;
        }

        const editorOverrides = editorOverrides0;
        const params = getFormParams(form);
        // Remove legacy path fields; backend resolves from template_content/config_content
        delete params.template;
        delete params.config_file;
        Object.assign(params, editorOverrides);
        params.project_name = projectName;
        console.log(`[runTest] FINAL: project=${params.project_name} tplLen=${(params.template_content||'').length} cfgLen=${(params.config_content||'').length}`);
        console.log(`[runTest] template[0:80]: ${(params.template_content||'').substring(0, 80)}`);
        console.log(`[runTest] config[0:80]: ${(params.config_content||'').substring(0, 80)}`);
        // Checkboxes (not included in FormData)
        params.no_delete = form.elements.no_delete.checked;
        params.keep_failed = form.elements.keep_failed.checked;
        params.dont_wait_for_delete = form.elements.dont_wait_for_delete.checked;

        const result = await api('/api/runs', { method: 'POST', body: JSON.stringify(params) });
        showToast(t('test.started'), 3000, 'success');
        navigateTo('dashboard');
    } catch (err) {
        showToast(t('test.start_failed') + err.message, 4000, 'error');
    } finally {
        setButtonLoading(btn, false);
        btn.textContent = t('run.start_btn');
    }
});

// === Unified Analyze Page === (functions exposed globally for inline onclick)
// --- Cost result table renderer ---
function _parseCostRows(priceDict, region) {
    const rows = [];
    function _parseAssociations(obj, parentType) {
        if (!obj || typeof obj !== 'object') return;
        for (const [key, val] of Object.entries(obj)) {
            if (val && typeof val === 'object' && val.Result) {
                const order = val.Result.Order || {};
                const supp = val.Result.OrderSupplement || {};
                const type = val.Type || parentType;
                rows.push({
                    Resource: key,
                    Region: region,
                    Type: type,
                    ChargeType: supp.ChargeType || '-',
                    PeriodUnit: supp.PriceUnit || '-',
                    Quantity: supp.Quantity ?? '-',
                    Currency: order.Currency || '-',
                    OriginalAmount: order.OriginalAmount ?? null,
                    DiscountAmount: order.DiscountAmount ?? null,
                    TradeAmount: order.TradeAmount ?? null,
                    _hasPrice: !!order.Currency || order.OriginalAmount != null,
                });
            }
            if (val && typeof val === 'object') {
                const nextParent = (val.Type && typeof val.Type === 'string')
                    ? (val.Type.includes('::') ? val.Type.split('::').pop() : val.Type)
                    : parentType;
                _parseAssociations(val, nextParent);
            }
        }
    }
    if (!priceDict) return rows;
    for (const [resourceName, resData] of Object.entries(priceDict)) {
        if (!resData || typeof resData !== 'object') continue;
        try {
            const isSuccess = resData.Success !== false;
            if (!isSuccess) {
                // Resource pricing query failed
                const errResult = resData.Result || {};
                rows.push({
                    Resource: resourceName, Region: region, Type: resData.Type || '-',
                    _hasPrice: false, _error: errResult.Message || errResult.Code || t('cost.query_failed'),
                });
                continue;
            }
            const order = (resData.Result && resData.Result.Order) || {};
            const supp = (resData.Result && resData.Result.OrderSupplement) || {};
            const hasPrice = !!(order.Currency || order.OriginalAmount != null || supp.ChargeType);
            rows.push({
                Resource: resourceName,
                Region: region,
                Type: resData.Type || '-',
                ChargeType: supp.ChargeType || '-',
                PeriodUnit: supp.PriceUnit || '-',
                Quantity: supp.Quantity ?? '-',
                Currency: order.Currency || '-',
                OriginalAmount: order.OriginalAmount ?? null,
                DiscountAmount: order.DiscountAmount ?? null,
                TradeAmount: order.TradeAmount ?? null,
                _hasPrice: hasPrice,
            });
            // Parse association products
            if (resData.Result && resData.Result.AssociationProducts) {
                const shortType = (resData.Type || '').includes('::')
                    ? resData.Type.split('::').pop() : (resData.Type || '');
                _parseAssociations(resData.Result.AssociationProducts, shortType);
            }
        } catch (_) {
            rows.push({ Resource: resourceName, Region: region, Type: resData.Type || '-', _hasPrice: false, _error: t('cost.parse_error') });
        }
    }
    return rows;
}

function renderCostResults(prices) {
    if (!prices || !prices.length) return resultContent(t('analyze.cost_results'), t('analyze.no_result'));
    let html = '';
    let totalOriginal = 0, totalDiscount = 0, totalTrade = 0;
    const ALL_COLUMNS = ['Resource','Region','Type','ChargeType','PeriodUnit','Quantity','Currency','OriginalAmount','DiscountAmount','TradeAmount'];
    const BASE_COLUMNS = ['Resource','Region','Type'];
    const LABELS = { Resource: t('cost.resource'), Region: t('cost.region'), Type: t('cost.type'), ChargeType: t('cost.charge_type'), PeriodUnit: t('cost.period_unit'), Quantity: t('cost.quantity'), Currency: t('cost.currency'), OriginalAmount: t('cost.original'), DiscountAmount: t('cost.discount'), TradeAmount: t('cost.trade') };

    for (const item of prices) {
        // Error stack
        if (item.error || !item.price) {
            html += `<div class="cost-stack"><div class="cost-stack-header cost-stack-error">${escapeHtml(item.test_name)} <span class="cost-region">${escapeHtml(item.region)}</span></div>`;
            html += `<div class="cost-error">${escapeHtml(item.error || item.status || t('common.unknown_error'))}</div></div>`;
            continue;
        }
        const rows = _parseCostRows(item.price, item.region);
        if (!rows.length) {
            html += `<div class="cost-stack"><div class="cost-stack-header">${escapeHtml(item.test_name)} <span class="cost-region">${escapeHtml(item.region)}</span></div>`;
            html += `<div class="cost-empty">${t('cost.no_pricing')}</div></div>`;
            continue;
        }
        // Dynamically determine columns: show price columns only if any row has price data
        const hasAnyPrice = rows.some(r => r._hasPrice);
        const COLUMNS = hasAnyPrice ? ALL_COLUMNS : BASE_COLUMNS;

        // Calculate totals for this stack
        let stackOriginal = 0, stackDiscount = 0, stackTrade = 0;
        rows.forEach(r => {
            stackOriginal += Number(r.OriginalAmount) || 0;
            stackDiscount += Number(r.DiscountAmount) || 0;
            stackTrade += Number(r.TradeAmount) || 0;
        });
        totalOriginal += stackOriginal;
        totalDiscount += stackDiscount;
        totalTrade += stackTrade;

        html += `<div class="cost-stack"><div class="cost-stack-header">${escapeHtml(item.test_name)} <span class="cost-region">${escapeHtml(item.region)}</span></div>`;
        html += `<div class="cost-table-wrap"><table class="cost-table"><thead><tr>`;
        COLUMNS.forEach(c => { html += `<th>${LABELS[c]}</th>`; });
        html += `</tr></thead><tbody>`;
        rows.forEach(r => {
            // If row has error, show it as a special row
            if (r._error) {
                html += '<tr class="cost-error-row">';
                html += `<td>${escapeHtml(String(r.Resource || '-'))}</td>`;
                html += `<td>${escapeHtml(String(r.Region || '-'))}</td>`;
                html += `<td>${escapeHtml(String(r.Type || '-'))}</td>`;
                html += `<td colspan="${Math.max(0, COLUMNS.length - 3)}" class="cost-cell-error">${escapeHtml(r._error)}</td>`;
                html += '</tr>';
                return;
            }
            html += '<tr>';
            COLUMNS.forEach(c => {
                let val = r[c];
                let cls = '';
                if (c === 'OriginalAmount' || c === 'DiscountAmount' || c === 'TradeAmount') {
                    cls = 'cost-num';
                    val = val != null ? Number(val).toFixed(6).replace(/\.?0+$/, '') : '-';
                }
                if (c === 'TradeAmount' && val !== '-') cls += ' cost-trade';
                html += `<td class="${cls}">${escapeHtml(String(val))}</td>`;
            });
            html += '</tr>';
        });
        // Stack subtotal (only if has price data)
        if (hasAnyPrice) {
            const fmt = n => n.toFixed(6).replace(/\.?0+$/, '');
            html += `<tr class="cost-subtotal"><td colspan="${COLUMNS.length - 3}">${t('cost.subtotal')}</td>`;
            html += `<td class="cost-num">${fmt(stackOriginal)}</td><td class="cost-num">${fmt(stackDiscount)}</td><td class="cost-num cost-trade">${fmt(stackTrade)}</td></tr>`;
        }
        html += `</tbody></table></div></div>`;
    }

    // Grand total (only if multiple stacks with prices)
    const stacksCount = prices.filter(p => p.price).length;
    if (stacksCount > 1) {
        const fmt = n => n.toFixed(6).replace(/\.?0+$/, '');
        html += `<div class="cost-total-bar"><strong>${t('cost.total')}</strong>`;
        html += `<span>${LABELS.OriginalAmount}: <b>${fmt(totalOriginal)}</b></span>`;
        html += `<span>${LABELS.DiscountAmount}: <b>${fmt(totalDiscount)}</b></span>`;
        html += `<span>${LABELS.TradeAmount}: <b class="cost-trade">${fmt(totalTrade)}</b></span></div>`;
    }

    // Raw JSON toggle
    const rawId = 'cost-raw-' + Date.now();
    html += `<div class="raw-toggle"><button class="btn-text" onclick="toggleRaw('${rawId}', this)">${t('cost.show_raw')}</button>`;
    html += `<pre id="${rawId}" class="raw-json hidden">${escapeHtml(JSON.stringify(prices, null, 2))}</pre></div>`;

    return `<div class="result-content-header"><h3>${t('analyze.cost_results')}</h3></div>${html}`;
}

function toggleRaw(id, btn) {
    const el = document.getElementById(id);
    if (!el) return;
    const isHidden = el.classList.contains('hidden');
    el.classList.toggle('hidden');
    btn.textContent = isHidden ? t('cost.hide_raw') : t('cost.show_raw');
}

const ANALYSIS_CONFIG = {
    validate: { url: '/api/validate', loading: () => t('analyze.validating'), tabLabel: () => t('analyze.validate'), successKey: 'details', successLabel: () => t('analyze.valid'), failCheck: d => d.result !== 'valid', failKey: 'error', failTitle: () => t('analyze.invalid') },
    preview:  { url: '/api/preview',  loading: () => t('analyze.previewing'),  tabLabel: () => t('analyze.preview'),  successKey: 'previews', successLabel: () => t('analyze.preview_results'), failCheck: d => !!d.error, failKey: 'error', failTitle: () => t('analyze.preview_error') },
    cost:     { url: '/api/cost',     loading: () => t('analyze.estimating'), tabLabel: () => t('analyze.cost'), successKey: 'prices', successLabel: () => t('analyze.cost_results'), failCheck: d => !!d.error, failKey: 'error', failTitle: () => t('analyze.cost_error'), customRender: (data) => renderCostResults(data.prices) },
    policy:   { url: '/api/policy',   loading: () => t('analyze.generating_policy'), tabLabel: () => t('analyze.policy'), successKey: 'policy', successLabel: () => t('analyze.policy_results'), failCheck: d => !!d.error, failKey: 'error', failTitle: () => t('analyze.policy_error') },
};

let _analysisResults = {};  // stores { type: htmlContent } for tab switching
let _activeTab = null;

function switchResultTab(type) {
    _activeTab = type;
    // Update tab active state
    document.querySelectorAll('.result-tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === type);
        // Update badge dot for completed tabs
        const hasResult = _analysisResults[t.dataset.tab] !== undefined;
        t.classList.toggle('has-result', hasResult);
    });
    // Show content
    const body = document.getElementById('result-tab-body');
    body.innerHTML = _analysisResults[type] || `<div class="result-empty">${t('analyze.no_result')}</div>`;
}

async function runAnalysis(type, _prepared) {
    const cfg = ANALYSIS_CONFIG[type];
    if (!cfg) return;
    // Block analysis while project is loading
    if (_projectLoading['workspace']) {
        showToast(t('project.loading_wait'));
        return;
    }

    const form = document.getElementById('workspace-form');
    const resultsEl = document.getElementById('analyze-results');
    const actionBtn = form.querySelector(`[data-action="${type}"]`);

    // Show results area and switch to this tab with loading state
    resultsEl.classList.remove('hidden');
    _analysisResults[type] = `<div class="result-loading"><div class="spinner"></div> ${cfg.loading()}</div>`;
    switchResultTab(type);
    if (actionBtn) setButtonLoading(actionBtn, true);

    try {
        // Use pre-computed overrides if provided (from runAllAnalyses), else prepare now
        const editorOverrides = _prepared || await fileEditor.prepareForm('workspace-form');
        const params = getFormParams(form);
        delete params.template;
        delete params.config_file;
        Object.assign(params, editorOverrides);
        // Ensure project_name is always present (from input field with name="project_name")
        const analyzeProjectName = document.getElementById('workspace-project-name')?.value?.trim();
        if (analyzeProjectName) params.project_name = analyzeProjectName;
        console.log(`[runAnalysis] BEFORE autoSave: project=${params.project_name} tplLen=${(params.template_content||'').length} cfgLen=${(params.config_content||'').length}`);
        console.log(`[runAnalysis] template[0:80]: ${(params.template_content||'').substring(0, 80)}`);
        console.log(`[runAnalysis] config[0:80]: ${(params.config_content||'').substring(0, 80)}`);
        // Auto-save project and get name (may update project_name if content changed)
        const projectName = await _autoSaveProject('workspace');
        if (projectName) params.project_name = projectName;
        console.log(`[runAnalysis] FINAL: project=${params.project_name} tplLen=${(params.template_content||'').length} cfgLen=${(params.config_content||'').length}`);

        const data = await api(cfg.url, { method: 'POST', body: JSON.stringify(params) });
        console.log(`[runAnalysis] API response for ${type}:`, Object.keys(data));
        if (cfg.failCheck(data)) {
            const failHtml = resultContent(cfg.failTitle(), escapeHtml(data[cfg.failKey] || t('common.unknown_error')));
            _analysisResults[type] = _wrapResultWithBanner(type, false, failHtml);
        } else if (cfg.customRender) {
            const customHtml = cfg.customRender(data);
            _analysisResults[type] = _wrapResultWithBanner(type, true, customHtml);
        } else {
            const successHtml = resultContent(cfg.successLabel(), escapeHtml(JSON.stringify(data[cfg.successKey], null, 2)));
            _analysisResults[type] = _wrapResultWithBanner(type, true, successHtml);
        }
    } catch (err) {
        // Build a user-friendly error message
        const msg = err.message || String(err);
        const isEmptyTemplate = msg.includes('模板内容为空') || msg.includes('template_body') || msg.includes('len=0');
        const friendlyTitle = isEmptyTemplate ? (t('analyze.template_empty_title') || '模板未填写') : t('analyze.error');
        const errHtml = `<div class="result-content-header"><h3>${friendlyTitle}</h3></div><div class="result-error-box">${escapeHtml(msg)}</div>`;
        _analysisResults[type] = _wrapResultWithBanner(type, false, errHtml);
    } finally {
        if (actionBtn) setButtonLoading(actionBtn, false);
        // Re-render if still on this tab
        if (_activeTab === type) switchResultTab(type);
    }
}

async function runAllAnalyses() {
    // Block if project is still loading
    if (_projectLoading['workspace']) {
        showToast(t('project.loading_wait'));
        return;
    }
    const allBtn = document.querySelector('.btn-action-all');
    if (allBtn) setButtonLoading(allBtn, true);
    // Prepare editors once, reuse for all analysis types
    const prepared = await fileEditor.prepareForm('workspace-form');
    for (const type of ['validate', 'preview', 'cost', 'policy']) {
        await runAnalysis(type, prepared);
    }
    if (allBtn) setButtonLoading(allBtn, false);
    showToast(t('analyze.all_done'), 3000, 'success');
}

// === Help / Guide ===
function toggleGuide(sectionId) {
    const section = document.getElementById(sectionId);
    if (!section) return;
    section.classList.toggle('collapsed');
}

// === Reports ===
let _reportsData = [];           // cached report list (all data from API)
let _filteredReports = [];       // filtered report list for display
let _selectedFiles = new Set();  // selected filenames for batch delete
let _reportPage = 1;             // current page (1-based)
let _pageSize = 10;              // items per page (changeable)

async function loadReports() {
    const container = document.getElementById('reports-list');
    const totalSizeEl = document.getElementById('reports-total-size');
    _selectedFiles.clear();
    updateBatchToolbar();
    try {
        const data = await api('/api/reports');
        _reportsData = data.reports || [];
        totalSizeEl.textContent = t('reports.total_summary', {n: _reportsData.length, size: formatSize(data.total_size)});

        if (!_reportsData.length) {
            container.innerHTML = `<div class="empty-state">${t('reports.empty')}</div>`;
            return;
        }

        filterReports(); // apply filters and render
    } catch (err) {
        container.innerHTML = `<div class="empty-state">${t('reports.failed')}</div>`;
    }
}

function renderReportTable() {
    const container = document.getElementById('reports-list');
    const totalPages = Math.ceil(_filteredReports.length / _pageSize);
    // Reset to page 1 if current page is out of range
    if (_reportPage > totalPages) _reportPage = Math.max(1, totalPages);
    const start = (_reportPage - 1) * _pageSize;
    const pageData = _filteredReports.slice(start, start + _pageSize);

    const categoryLabels = {
        report: { text: t('reports.cat_report'), cls: 'badge-completed' },
        result: { text: t('reports.cat_result'), cls: 'badge-pending' },
        log:    { text: t('reports.cat_log'), cls: 'badge-running' },
        hook:   { text: t('reports.cat_hook'), cls: 'badge-cancelled' },
        other:  { text: t('reports.cat_other'), cls: 'badge-cancelled' },
    };

    container.innerHTML = `
        <table class="data-table">
            <thead>
                <tr>
                    <th style="width: 36px;">
                        <input type="checkbox" id="select-all-cb" onchange="toggleSelectAll(this.checked)">
                    </th>
                    <th>${t('reports.col_name')}</th>
                    <th>${t('reports.col_category')}</th>
                    <th>${t('reports.col_size')}</th>
                    <th>${t('reports.col_modified')}</th>
                    <th style="width: 80px;">${t('reports.col_actions')}</th>
                </tr>
            </thead>
            <tbody>
                ${pageData.map(r => {
                    const cat = categoryLabels[r.category] || categoryLabels.other;
                    const enc = encodeURIComponent(r.name);
                    return `<tr data-filename="${enc}">
                        <td><input type="checkbox" class="row-cb" data-name="${enc}" onchange="onRowCheckChange()"></td>
                        <td style="font-family: monospace; font-size: 12px; word-break: break-all;">
                            <a href="#" class="file-link" onclick="event.preventDefault(); viewReport('${enc}')">${escapeHtml(r.name)}</a>
                        </td>
                        <td><span class="badge ${cat.cls}">${cat.text}</span></td>
                        <td>${formatSize(r.size)}</td>
                        <td>${formatTime(new Date(r.modified * 1000).toISOString())}</td>
                        <td>
                            <button class="btn-text-danger" onclick="deleteReport('${enc}')">${t('editor.delete_saved')}</button>
                        </td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>
        ${totalPages > 1 ? renderPagination(totalPages) : ''}
        ${renderPageSizeBar()}`;
}

function renderPageSizeBar() {
    const options = [10, 20, 50, 100];
    return `
        <div class="page-size-bar">
            <span>${t('reports.per_page')}</span>
            ${options.map(n => `<button class="page-size-btn ${n === _pageSize ? 'page-size-active' : ''}" onclick="changePageSize(${n})">${n}</button>`).join('')}
        </div>`;
}

function renderPagination(totalPages) {
    const pages = [];
    const cur = _reportPage;

    // Always show first page
    pages.push(1);
    // Show "..." if gap
    if (cur > 3) pages.push('...');
    // Show pages around current
    for (let i = Math.max(2, cur - 1); i <= Math.min(totalPages - 1, cur + 1); i++) {
        pages.push(i);
    }
    if (cur < totalPages - 2) pages.push('...');
    // Always show last page
    if (totalPages > 1) pages.push(totalPages);

    return `
        <div class="pagination">
            <button class="page-btn" onclick="goToPage(${cur - 1})" ${cur <= 1 ? 'disabled' : ''}>&laquo; ${t('reports.prev')}</button>
            ${pages.map(p => p === '...'
                ? '<span class="page-ellipsis">...</span>'
                : `<button class="page-btn ${p === cur ? 'page-active' : ''}" onclick="goToPage(${p})">${p}</button>`
            ).join('')}
            <button class="page-btn" onclick="goToPage(${cur + 1})" ${cur >= totalPages ? 'disabled' : ''}>${t('reports.next')} &raquo;</button>
            <span class="page-info">${t('reports.files_total', {n: _filteredReports.length})}</span>
        </div>`;
}

function goToPage(page) {
    const totalPages = Math.ceil(_filteredReports.length / _pageSize);
    if (page < 1 || page > totalPages) return;
    _reportPage = page;
    _selectedFiles.clear();
    updateBatchToolbar();
    renderReportTable();
    document.getElementById('reports-list').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function filterReports() {
    const category = document.getElementById('reports-category-filter').value;
    const timeFilter = document.getElementById('reports-time-filter').value;
    const typeFilter = document.getElementById('reports-type-filter').value;
    const search = document.getElementById('reports-search').value.trim().toLowerCase();

    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
    const weekStart = todayStart - (now.getDay() || 7) * 86400 + 86400;
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime() / 1000;

    _filteredReports = _reportsData.filter(r => {
        if (category && r.category !== category) return false;
        if (typeFilter && typeFilter !== 'other') {
            if (r.type !== typeFilter) return false;
        } else if (typeFilter === 'other') {
            if (['html', 'json', 'txt'].includes(r.type)) return false;
        }
        if (timeFilter) {
            if (timeFilter === 'today' && r.modified < todayStart) return false;
            if (timeFilter === 'week' && r.modified < weekStart) return false;
            if (timeFilter === 'month' && r.modified < monthStart) return false;
        }
        if (search && !r.name.toLowerCase().includes(search)) return false;
        return true;
    });

    _reportPage = 1;
    _selectedFiles.clear();
    updateBatchToolbar();

    const container = document.getElementById('reports-list');
    if (!_filteredReports.length) {
        container.innerHTML = `<div class="empty-state">${t('reports.filter_empty')}</div>`;
        return;
    }
    renderReportTable();
}

function clearReportFilters() {
    document.getElementById('reports-category-filter').value = '';
    document.getElementById('reports-time-filter').value = '';
    document.getElementById('reports-type-filter').value = '';
    document.getElementById('reports-search').value = '';
    filterReports();
}

function changePageSize(size) {
    _pageSize = size;
    _reportPage = 1;
    _selectedFiles.clear();
    updateBatchToolbar();
    if (_filteredReports.length) renderReportTable();
}

// --- File Viewer Modal ---
async function viewReport(filename) {
    const modal = document.getElementById('file-modal');
    const title = document.getElementById('modal-filename');
    const body = document.getElementById('modal-content');
    const loading = document.getElementById('modal-loading');
    const copyBtn = document.getElementById('modal-copy-btn');

    modal.classList.remove('hidden');
    title.textContent = decodeURIComponent(filename);
    body.textContent = '';
    body.classList.add('hidden');
    loading.classList.remove('hidden');
    copyBtn.disabled = true;
    copyBtn.classList.remove('hidden');

    try {
        const data = await api(`/api/reports/${filename}/raw`);
        if (data.error) throw new Error(data.error);
        body.textContent = data.content;
        body.classList.remove('hidden');
        copyBtn.disabled = false;
    } catch (err) {
        body.textContent = `${t('modal.load_failed')}${err.message}`;
        body.classList.remove('hidden');
    } finally {
        loading.classList.add('hidden');
    }
}

function closeFileModal() {
    const backBtn = document.getElementById('modal-back-btn');
    if (_modalOnClose) {
        const cb = _modalOnClose;
        _modalOnClose = null;
        backBtn.classList.add('hidden');
        cb(); // go back to the file list
    } else {
        document.getElementById('file-modal').classList.add('hidden');
        document.getElementById('modal-copy-btn').classList.remove('hidden');
        backBtn.classList.add('hidden');
    }
}

function closeModalOutside(e) {
    if (e.target === document.getElementById('file-modal')) closeFileModal();
}

// === Shared Clipboard Utility ===
async function copyToClipboard(text, feedbackBtn, originalLabel) {
    if (!originalLabel) originalLabel = t('common.copy');
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        // Fallback for older browsers / non-HTTPS
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;left:-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
    }
    if (feedbackBtn) {
        feedbackBtn.textContent = t('modal.copied');
        setTimeout(() => { feedbackBtn.textContent = originalLabel; }, 1500);
    }
}

async function copyModalContent() {
    const text = document.getElementById('modal-content').textContent;
    await copyToClipboard(text, document.getElementById('modal-copy-btn'));
}

// --- Multi-select ---
function toggleSelectAll(checked) {
    document.querySelectorAll('.row-cb').forEach(cb => { cb.checked = checked; });
    _selectedFiles.clear();
    if (checked) {
        document.querySelectorAll('.row-cb').forEach(cb => _selectedFiles.add(cb.dataset.name));
    }
    updateBatchToolbar();
}

function onRowCheckChange() {
    _selectedFiles.clear();
    document.querySelectorAll('.row-cb:checked').forEach(cb => _selectedFiles.add(cb.dataset.name));
    // update select-all state
    const all = document.querySelectorAll('.row-cb');
    const sa = document.getElementById('select-all-cb');
    if (sa) sa.checked = all.length > 0 && _selectedFiles.size === all.length;
    updateBatchToolbar();
}

function updateBatchToolbar() {
    const toolbar = document.getElementById('batch-toolbar');
    const countEl = document.getElementById('batch-count');
    if (_selectedFiles.size > 0) {
        toolbar.classList.remove('hidden');
        countEl.textContent = t('reports.files_selected', {n: _selectedFiles.size});
    } else {
        toolbar.classList.add('hidden');
    }
}

function clearSelection() {
    _selectedFiles.clear();
    document.querySelectorAll('.row-cb').forEach(cb => { cb.checked = false; });
    const sa = document.getElementById('select-all-cb');
    if (sa) sa.checked = false;
    updateBatchToolbar();
}

async function batchDeleteSelected() {
    if (!_selectedFiles.size) return;
    if (!confirm(t('reports.confirm_batch_delete', {n: _selectedFiles.size}))) return;

    const names = [..._selectedFiles];
    let deleted = 0;
    for (const name of names) {
        try {
            await api(`/api/reports/${name}`, { method: 'DELETE' });
            deleted++;
        } catch (err) {
            console.warn(`Failed to delete ${name}:`, err);
        }
    }
    showToast(t('reports.deleted_count', {d: deleted, n: names.length}));
    _selectedFiles.clear();
    loadReports();
}

// --- Single Delete ---
async function deleteReport(filename) {
    if (!confirm(t('reports.confirm_delete', {name: decodeURIComponent(filename)}))) return;
    try {
        await api(`/api/reports/${filename}`, { method: 'DELETE' });
        showToast(t('reports.file_deleted'));
        loadReports();
    } catch (err) {
        showToast(t('reports.delete_failed'));
    }
}

function formatSize(bytes) {
    if (!bytes && bytes !== 0) return '-';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// === Helpers ===
function getFormParams(form) {
    const params = {};
    const formData = new FormData(form);
    for (const [key, value] of formData.entries()) {
        if (value) params[key] = value;
    }
    return params;
}

function setButtonLoading(btn, loading) {
    if (!btn) return;
    if (loading) {
        btn.dataset._origText = btn.textContent;
        btn.disabled = true;
        btn.classList.add('btn-loading');
    } else {
        btn.disabled = false;
        btn.classList.remove('btn-loading');
        if (btn.dataset._origText) btn.textContent = btn.dataset._origText;
    }
}

// === Connection Check ===
async function checkConnection() {
    const banner = document.getElementById('connection-banner');
    try {
        await fetch('/api/settings', { method: 'GET' });
        banner.classList.add('hidden');
        return true;
    } catch {
        banner.classList.remove('hidden');
        return false;
    }
}

// === Template Upload (legacy, kept for backward compatibility) ===
async function uploadTemplate(fileInput, formId) {
    const file = fileInput.files[0];
    if (!file) return;
    const statusEl = document.getElementById(`${formId}-upload-status`);
    const templateInput = document.querySelector(`#${formId} input[name="template"]`);
    statusEl.className = 'upload-status upload-loading';
    statusEl.textContent = t('common.uploading', {name: file.name});
    const formData = new FormData();
    formData.append('file', file);
    try {
        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await resp.json();
        if (!resp.ok || data.error) {
            statusEl.className = 'upload-status upload-error';
            statusEl.textContent = t('common.upload_failed') + (data.error || 'Unknown error');
            return;
        }
        templateInput.value = data.path;
        statusEl.className = 'upload-status upload-success';
        statusEl.textContent = t('common.upload_success', {name: data.filename, size: (data.size / 1024).toFixed(1)});
    } catch (err) {
        statusEl.className = 'upload-status upload-error';
        statusEl.textContent = t('common.upload_failed') + err.message;
    }
    fileInput.value = '';
}

// === File Editor Module v3 (Simplified) ===
const fileEditor = {

    /** Get wrapper element */
    _get(id) {
        return document.querySelector(`[data-editor-id="${id}"]`);
    },

    /** Get the label for this editor (used in error messages) */
    _getLabel(editorId) {
        const wrapper = this._get(editorId);
        if (!wrapper) return editorId;
        const fg = wrapper.closest('.form-group');
        if (fg) {
            const lbl = fg.querySelector('label');
            if (lbl) {
                const text = lbl.textContent.replace(/\s*\(.*?\)\s*/g, '').trim();
                if (text) return text;
            }
        }
        return wrapper.dataset.editorType === 'template' ? 'Template' : 'Config';
    },

    /** Update empty-content hint visibility */
    _updateEmptyHint(editorId) {
        const textarea = document.getElementById(`${editorId}-content`);
        const hintEl = document.getElementById(`${editorId}-empty-hint`);
        const wrapper = this._get(editorId);
        if (!textarea || !hintEl || !wrapper) return;
        const isEmpty = !textarea.value.trim();
        const type = wrapper.dataset.editorType || 'template';
        if (isEmpty) {
            const key = type === 'config' ? 'editor.empty_hint_config' : 'editor.empty_hint_template';
            hintEl.innerHTML = `<strong>${t('editor.empty_hint_title')}</strong> ${t(key)}`;
            hintEl.classList.add('visible');
        } else {
            hintEl.classList.remove('visible');
        }
    },

    /** Auto-detect format from content */
    _detectFormat(content) {
        const trimmed = content.trim();
        if (!trimmed) return 'yaml';
        // JSON: starts with { or [
        if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json';
        // Terraform: contains resource/data/variable/module blocks
        if (/^(resource|data|variable|module|terraform|provider|output)\s+/m.test(trimmed)) return 'tf';
        // Default YAML
        return 'yaml';
    },

    /** Handle file upload - saves to type-based subdirectory */
    async handleUpload(fileInput, editorId) {
        const file = fileInput.files[0];
        if (!file) return;
        const wrapper = this._get(editorId);
        if (!wrapper) return;
        const infoEl = document.getElementById(`${editorId}-info`);
        const validEl = document.getElementById(`${editorId}-validation`);
        const textarea = document.getElementById(`${editorId}-content`);
        const label = this._getLabel(editorId);
        const type = wrapper.dataset.editorType || 'template';

        if (infoEl) infoEl.textContent = t('common.uploading', {name: file.name});
        const formData = new FormData();
        formData.append('file', file);

        try {
            const resp = await fetch(`/api/upload?type=${encodeURIComponent(type)}`, { method: 'POST', body: formData });
            const data = await resp.json();
            if (!resp.ok || data.error) throw new Error(data.error || 'Upload failed');

            // Load uploaded file content
            const fileData = await api(`/api/file?path=${encodeURIComponent(data.path)}`);
            if (textarea) textarea.value = fileData.content;

            const lineCount = fileData.content.split('\n').length;
            if (infoEl) infoEl.textContent = `${data.filename} | ${lineCount} ${t('editor.lines')} | ${(data.size / 1024).toFixed(1)} KB`;
            if (validEl) validEl.innerHTML = `<span class="fe-val-ok">${label}: ${t('editor.uploaded_ok')}</span>`;

            this.validate(editorId);
            this._updateEmptyHint(editorId);
            // Refresh saved list so the uploaded file appears
            this.loadSavedList(editorId);
        } catch (err) {
            if (infoEl) infoEl.textContent = '';
            showToast(`${label}: ${t('common.upload_failed')} - ${err.message}`);
        }
        fileInput.value = '';
    },

    /** Validate content - auto-detect format, show field name in errors */
    validate(editorId) {
        const wrapper = this._get(editorId);
        if (!wrapper) return;
        const textarea = document.getElementById(`${editorId}-content`);
        const validEl = document.getElementById(`${editorId}-validation`);
        if (!validEl || !textarea) return;

        const content = textarea.value;
        const label = this._getLabel(editorId);

        if (!content.trim()) {
            validEl.innerHTML = '';
            return;
        }

        const fmt = this._detectFormat(content);
        let result = null;
        if (fmt === 'json') result = this._validateJSON(content);
        else if (fmt === 'tf') result = this._validateTF(content);
        else result = this._validateYAML(content);

        const fmtLabel = fmt === 'json' ? 'JSON' : fmt === 'tf' ? 'Terraform' : 'YAML';
        if (result.valid) {
            validEl.innerHTML = `<span class="fe-val-ok">${t('editor.valid_ok')} (${fmtLabel})</span>`;
        } else {
            validEl.innerHTML = `<span class="fe-val-error">${t('editor.valid_fail')} (${fmtLabel}): ${result.error}</span>`;
        }
    },

    /** Save content to server with filename prompt */
    async save(editorId) {
        const wrapper = this._get(editorId);
        const textarea = document.getElementById(`${editorId}-content`);
        if (!textarea || !textarea.value.trim()) {
            showToast(`${this._getLabel(editorId)}: ${t('editor.no_content')}`);
            return;
        }

        // If editor has a fixed save path, skip filename prompt and overwrite directly
        const savePath = wrapper ? wrapper.dataset.savePath : null;
        if (savePath) {
            const path = await this.saveContent(editorId);
            if (path) {
                showToast(`${this._getLabel(editorId)}: ${t('editor.saved_ok')} (${savePath})`, 2500);
            }
            return;
        }

        const type = wrapper ? wrapper.dataset.editorType : 'template';
        const fmt = this._detectFormat(textarea.value);
        const ext = fmt === 'json' ? 'json' : fmt === 'tf' ? 'tf' : 'yaml';
        const defaultName = type === 'template' ? `my-template.${ext}` : `my-config.${ext}`;

        const name = prompt(t('editor.save_name'), defaultName);
        if (!name) return;  // cancelled

        // Ensure extension
        const finalName = name.includes('.') ? name : `${name}.${ext}`;
        const path = await this.saveContent(editorId, finalName);
        if (path) {
            showToast(`${this._getLabel(editorId)}: ${t('editor.saved_ok')} (${finalName})`, 2500);
            // Refresh all saved lists so the new file appears in dropdowns
            this._refreshAllLists();
        }
    },

    /** Save content to server with given filename, return saved path */
    async saveContent(editorId, filename) {
        const wrapper = this._get(editorId);
        if (!wrapper) return null;
        const textarea = document.getElementById(`${editorId}-content`);
        const content = textarea ? textarea.value : '';
        if (!content.trim()) return null;

        const type = wrapper.dataset.editorType;
        // Custom save path (e.g. saves directly to a specific file)
        const savePath = wrapper.dataset.savePath;
        let saveTo;
        if (savePath) {
            saveTo = savePath;
        } else {
            // If no filename given, auto-generate (used by prepareForm)
            if (!filename) {
                const fmt = this._detectFormat(content);
                const ext = fmt === 'json' ? 'json' : fmt === 'tf' ? 'tf' : 'yaml';
                filename = type === 'template' ? `template.${ext}` : `config.${ext}`;
            }
            const subDir = type === 'config' ? 'configs' : 'templates';
            saveTo = `.iact3/${subDir}/${filename}`;
        }

        try {
            const result = await api('/api/file', {
                method: 'POST',
                body: JSON.stringify({ path: saveTo, content }),
            });
            if (result.error) throw new Error(result.error);
            // Auto-update .iact3.yml template_location when saving a template
            if (type === 'template' && !savePath) {
                this._updateTemplatePath(result.path);
            }
            return result.path;
        } catch (err) {
            console.warn(`Failed to save ${filename}:`, err);
            showToast(`${this._getLabel(editorId)}: ${t('editor.save_failed')} ${err.message}`);
            return null;
        }
    },

    /** Refresh all saved-file dropdowns on the page */
    _refreshAllLists() {
        document.querySelectorAll('.file-editor[data-editor-id]').forEach(wrapper => {
            this.loadSavedList(wrapper.dataset.editorId);
        });
    },

    _validateJSON(content) {
        try { JSON.parse(content); return { valid: true }; }
        catch (e) { return { valid: false, error: e.message }; }
    },

    _validateYAML(content) {
        // Use js-yaml for real parsing if available
        if (typeof jsyaml !== 'undefined') {
            try {
                const doc = jsyaml.load(content);
                if (doc === null || doc === undefined) {
                    return { valid: false, error: t('editor.yaml_empty_doc') || 'Empty document' };
                }
                if (typeof doc !== 'object' || Array.isArray(doc)) {
                    return { valid: false, error: t('editor.yaml_bad_structure') };
                }
                return { valid: true };
            } catch (e) {
                // js-yaml throws YAMLException with mark info
                const msg = e.reason || e.message || String(e);
                const line = e.mark ? ` (${t('editor.line')} ${e.mark.line + 1})` : '';
                return { valid: false, error: msg + line };
            }
        }
        // Fallback: basic checks when js-yaml not loaded
        const lines = content.split('\n');
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].match(/^\t/)) {
                return { valid: false, error: `${t('editor.line')} ${i + 1}: ${t('editor.yaml_no_tabs')}` };
            }
        }
        const firstMeaningful = lines.find(l => l.trim() && !l.trim().startsWith('#'));
        if (firstMeaningful && !firstMeaningful.match(/^[\w\-'"]+\s*:/) &&
            firstMeaningful.trim() !== '---' && !firstMeaningful.trim().startsWith('-')) {
            return { valid: false, error: t('editor.yaml_bad_structure') };
        }
        return { valid: true };
    },

    _validateTF(content) {
        if (!content.includes('resource') && !content.includes('data') &&
            !content.includes('variable') && !content.includes('module')) {
            return { valid: false, error: t('editor.tf_bad_structure') };
        }
        return { valid: true };
    },

    /** Load saved files list into dropdown with delete support */
    async loadSavedList(editorId) {
        const wrapper = this._get(editorId);
        if (!wrapper) return;

        const type = wrapper.dataset.editorType;

        try {
            const data = await api(`/api/templates?type=${encodeURIComponent(type)}`);
            const templates = data.templates || [];
            // Build custom dropdown with delete buttons
            this._renderSavedDropdown(editorId, templates, type);
        } catch (err) {
            this._renderSavedDropdown(editorId, [], type);
        }
    },

    /** Render a custom saved-file dropdown with delete buttons */
    _renderSavedDropdown(editorId, files, type) {
        const wrapper = this._get(editorId);
        if (!wrapper) return;
        // Find or create custom dropdown
        let dropdown = wrapper.querySelector('.fe-saved-dropdown');
        if (!dropdown) {
            dropdown = document.createElement('div');
            dropdown.className = 'fe-saved-dropdown';
            const actions = wrapper.querySelector('.fe-actions');
            if (actions) actions.appendChild(dropdown);
            else return;
        }

        if (!files.length) {
            dropdown.innerHTML = `<div class="fe-saved-dropdown-empty">${t('editor.no_saved')}</div>`;
            return;
        }

        // Format mtime to short relative or date string
        const fmtTime = (ts) => {
            if (!ts) return '';
            const d = new Date(ts * 1000);
            const now = Date.now();
            const diff = (now - d.getTime()) / 1000;
            if (diff < 60) return t('editor.just_now') || 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
            return d.toLocaleDateString();
        };

        let html = `<div class="fe-saved-dropdown-header">${t('editor.saved_files')} (${files.length})</div>`;
        for (const f of files) {
            const sizeStr = (f.size / 1024).toFixed(1);
            const encName = encodeURIComponent(f.name);
            const encPath = encodeURIComponent(f.path);
            const ext = f.extension || '';
            const timeStr = fmtTime(f.mtime);
            html += `<div class="fe-saved-item">`;
            html += `<div class="fe-saved-item-info" onclick="fileEditor.loadSaved('${editorId}', decodeURIComponent('${encPath}')); fileEditor._closeSavedDropdown('${editorId}')">`;
            html += `<div class="fe-saved-item-name">${escapeHtml(f.name)}</div>`;
            html += `<div class="fe-saved-item-meta">`;
            if (ext) html += `<span class="fe-ext">${ext.replace('.', '')}</span>`;
            html += `<span class="fe-size">${sizeStr} KB</span>`;
            if (timeStr) html += `<span class="fe-time">${timeStr}</span>`;
            html += `</div></div>`;
            html += `<button type="button" class="fe-saved-item-del" title="${t('editor.delete_saved')}" onclick="event.preventDefault(); event.stopPropagation(); fileEditor.deleteSaved('${editorId}', decodeURIComponent('${encName}'), '${type}')">${t('editor.delete_saved')}</button>`;
            html += `</div>`;
        }
        dropdown.innerHTML = html;
    },

    /** Toggle custom saved dropdown */
    _toggleSavedDropdown(editorId) {
        const wrapper = this._get(editorId);
        if (!wrapper) return;
        // Check if THIS editor's dropdown is currently open
        const dropdown = wrapper.querySelector('.fe-saved-dropdown');
        const wasOpen = dropdown && dropdown.classList.contains('open');
        // Close ALL open dropdowns and active buttons
        document.querySelectorAll('.fe-saved-dropdown.open').forEach(d => d.classList.remove('open'));
        document.querySelectorAll('.fe-saved-btn.active').forEach(b => b.classList.remove('active'));
        // If it was NOT open, load list and open it
        if (!wasOpen) {
            this.loadSavedList(editorId).then(() => {
                const dd = wrapper.querySelector('.fe-saved-dropdown');
                if (dd) {
                    dd.classList.add('open');
                    const btn = wrapper.querySelector('.fe-saved-btn');
                    if (btn) btn.classList.add('active');
                }
            });
        }
    },

    _closeSavedDropdown(editorId) {
        const wrapper = this._get(editorId);
        if (!wrapper) return;
        const dropdown = wrapper.querySelector('.fe-saved-dropdown');
        if (dropdown) dropdown.classList.remove('open');
    },

    /** Delete a saved file */
    async deleteSaved(editorId, filename, type) {
        const ok = await confirmDialog(t('editor.confirm_delete', {name: filename}));
        if (!ok) return;
        try {
            const result = await api(`/api/templates/${encodeURIComponent(filename)}?type=${encodeURIComponent(type)}`, { method: 'DELETE' });
            if (result.error) throw new Error(result.error);
            showToast(t('editor.deleted_ok', {name: filename}));
            this.loadSavedList(editorId);
        } catch (err) {
            showToast(t('editor.delete_failed') + err.message);
        }
    },

    /** Load a saved template by path (from dropdown) */
    async loadSaved(editorId, path) {
        if (!path) return;
        const wrapper = this._get(editorId);
        if (!wrapper) return;
        const textarea = document.getElementById(`${editorId}-content`);
        const infoEl = document.getElementById(`${editorId}-info`);
        const label = this._getLabel(editorId);

        try {
            const data = await api(`/api/file?path=${encodeURIComponent(path)}`);
            if (textarea) textarea.value = data.content;

            const parts = path.split('/');
            const filename = parts[parts.length - 1];
            const lineCount = data.content.split('\n').length;
            if (infoEl) infoEl.textContent = `${filename} | ${lineCount} ${t('editor.lines')} | ${(data.size / 1024).toFixed(1)} KB`;

            this.validate(editorId);
        } catch (err) {
            showToast(`${label}: ${err.message}`);
        }
    },

    /** Prepare all editors in a form for submission. Returns object of overrides. */
    async prepareForm(formId) {
        const result = {};
        const form = document.getElementById(formId);
        if (!form) return result;

        const editors = form.querySelectorAll('.file-editor');
        for (const editor of editors) {
            const id = editor.dataset.editorId;
            if (!id) continue;
            const type = editor.dataset.editorType;
            const textarea = editor.querySelector('.fe-content');
            if (!textarea) continue;
            // Return raw content (not file paths) so backend uses editor content directly
            const fieldName = type === 'template' ? 'template_content' : 'config_content';
            // Always include content when a project is explicitly loaded (even if empty)
            // to prevent backend from falling back to stale saved project data
            const page = formId.replace('-form', '');
            if (_projectExplicitlyLoaded[page] || textarea.value.trim()) {
                result[fieldName] = textarea.value;
            }
        }
        console.log(`[prepareForm] formId=${formId} keys=${Object.keys(result).join(',')} tplLen=${(result.template_content||'').length} cfgLen=${(result.config_content||'').length}`);
        console.log(`[prepareForm] template preview: ${(result.template_content||'').substring(0, 80)}`);
        console.log(`[prepareForm] config preview: ${(result.config_content||'').substring(0, 80)}`);
        return result;
    },

    /** Get path value for backward compatibility */
    getPath(editorId) {
        const wrapper = this._get(editorId);
        if (!wrapper) return '';
        const input = wrapper.querySelector('.fe-path-value');
        return input ? input.value : '';
    },

    /** Update template_location in .iact3.yml after saving a template */
    async _updateTemplatePath(path) {
        if (!path) return;
        try {
            await api('/api/config/template-path', {
                method: 'POST',
                body: JSON.stringify({ template_path: path }),
            });
        } catch (err) {
            console.warn('Failed to update template_location in .iact3.yml:', err);
        }
    },
};

/**
 * Non-blocking confirm dialog (replaces browser confirm() to avoid focus/blur issues).
 * Returns a Promise that resolves to true (OK) or false (Cancel).
 */
function confirmDialog(message) {
    return new Promise((resolve) => {
        // Remove any existing confirm dialog
        const old = document.getElementById('confirm-dialog-overlay');
        if (old) old.remove();

        const overlay = document.createElement('div');
        overlay.id = 'confirm-dialog-overlay';
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `
            <div class="confirm-dialog">
                <p class="confirm-dialog-msg">${escapeHtml(message)}</p>
                <div class="confirm-dialog-btns">
                    <button type="button" class="btn" id="confirm-dialog-cancel">${t('common.cancel') || 'Cancel'}</button>
                    <button type="button" class="btn btn-danger" id="confirm-dialog-ok">${t('common.ok') || 'OK'}</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);

        const cleanup = (result) => { overlay.remove(); resolve(result); };
        overlay.querySelector('#confirm-dialog-ok').onclick = () => cleanup(true);
        overlay.querySelector('#confirm-dialog-cancel').onclick = () => cleanup(false);
        overlay.querySelector('#confirm-dialog-ok').focus();
    });
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

function resultContent(title, preText) {
    return `<div class="result-content-header">
        <h3>${title}</h3>
        <button class="btn-result-copy" onclick="copyResultContent(this)">${t('common.copy')}</button>
    </div><pre>${preText}</pre>`;
}

async function copyResultContent(btn) {
    const container = btn.closest('.result-panel, .detail-section');
    if (!container) return;
    const pre = container.querySelector('pre');
    const text = pre ? pre.textContent : container.textContent;
    await copyToClipboard(text, btn);
}

// === Settings ===

async function loadSettings() {
    if (!_settingsReady) {
        // First call (at init): fetch settings and mark as ready
        _settingsReady = (async () => {
            try {
                const data = await api('/api/settings');
                _globalSettings = data.settings || {};
            } catch (err) {
                console.warn('Failed to load settings:', err);
            }
        })();
        await _settingsReady;
    } else {
        // Subsequent calls (e.g. after saving settings): re-fetch
        try {
            const data = await api('/api/settings');
            _globalSettings = data.settings || {};
        } catch (err) {
            console.warn('Failed to load settings:', err);
        }
    }

    // Update settings form UI (only when on settings page)
    const form = document.getElementById('settings-form');
    if (!form) return;

    form.access_key_id.value     = _globalSettings.access_key_id     || '';
    form.access_key_secret.value = _globalSettings.access_key_secret || '';
    form.security_token.value    = _globalSettings.security_token    || '';
    form.regions.value           = _globalSettings.regions           || '';

    // Set region multi-select values
    if (_globalSettings.regions) {
        regionSelect.setValue('settings-form', _globalSettings.regions);
    }

    updateCredentialsBadge();
}

/** Load file content from server into an editor's textarea */
async function _loadEditorFileContent(editorId, filePath) {
    if (!filePath) return;
    const textarea = document.getElementById(`${editorId}-content`);
    const infoEl = document.getElementById(`${editorId}-info`);
    if (!textarea) return;
    // Only load if textarea is empty (don't override user edits)
    if (textarea.value.trim()) {
        if (infoEl) infoEl.textContent = filePath;
        return;
    }
    try {
        const resp = await fetch(`/api/file?path=${encodeURIComponent(filePath)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.content !== undefined) {
            textarea.value = data.content;
            // Update fe-info to show file path
            if (infoEl) infoEl.textContent = data.path || filePath;
            fileEditor._updateEmptyHint(editorId);
        }
    } catch (err) {
        // Silently ignore - file may not exist anymore
    }
}

function updateCredentialsBadge() {
    const badge = document.getElementById('settings-status-badge');
    if (badge) {
        if (_globalSettings.credentials_set) {
            const ak = _globalSettings.access_key_id || '';
            badge.className = 'settings-badge settings-badge-ok';
            badge.textContent = t('settings.credentials_ok', {ak: ak});
        } else {
            badge.className = 'settings-badge settings-badge-warn';
            badge.textContent = t('settings.no_credentials');
        }
    }
    _updateNavCredentialDot();
    _updateWorkspaceCredentialWarning();
}

async function autoFillDefaults(page) {
    const form = document.getElementById(`${page}-form`);
    if (!form) return;
    // Ensure settings are loaded before applying defaults
    if (_settingsReady) await _settingsReady;
    if (!_globalSettings) return;

    // If a project was explicitly loaded on this page, only apply regions
    // (skip template/config file loading to avoid overwriting project content)
    if (_projectExplicitlyLoaded[page]) {
        const formId = `${page}-form`;
        if (_globalSettings.regions && !regionSelect.getValue(formId)) {
            regionSelect.setValue(formId, _globalSettings.regions);
        }
        return;
    }

    // Set region multi-select from defaults (only if not already set)
    const formId = `${page}-form`;
    if (_globalSettings.regions && !regionSelect.getValue(formId)) {
        regionSelect.setValue(formId, _globalSettings.regions);
    }
    // Update collapsible summaries
    _updateEditorSummary(page, 'template');
    _updateEditorSummary(page, 'config');
}

const _settingsForm = document.getElementById('settings-form');
if (_settingsForm) _settingsForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const btn = form.querySelector('button[type="submit"]');
    setButtonLoading(btn, true);
    btn.textContent = t('settings.saving');
    try {
        const params = {
            access_key_id:     form.access_key_id.value,
            access_key_secret: form.access_key_secret.value,
            security_token:    form.security_token.value,
            regions:           regionSelect.getValue('settings-form'),
        };
        const result = await api('/api/settings', { method: 'POST', body: JSON.stringify(params) });
        if (result.error) throw new Error(result.error);
        showToast(t('settings.saved'), 3000, 'success');
        await loadSettings();  // reload to get masked values
    } catch (err) {
        showToast(t('settings.save_failed') + err.message, 4000, 'error');
    } finally {
        setButtonLoading(btn, false);
        btn.textContent = t('settings.save');
    }
});

// === Region Multi-Select Module ===
const regionSelect = {
    _regions: [],       // all available regions: [{id, name}, ...]
    _selected: {},      // { formId: Set<string> }  (stores region IDs)
    _loaded: false,
    _loading: null,

    /** Fetch regions from server (once per language) */
    async _loadRegions() {
        const lang = getLang();
        if (this._loaded && this._lang === lang) return;
        if (this._loading) { await this._loading; return; }
        this._loading = (async () => {
            try {
                const data = await api(`/api/regions?lang=${lang}`);
                // Support both old format (string[]) and new format ({id,name}[])
                this._regions = (data.regions || []).map(r =>
                    typeof r === 'string' ? {id: r, name: r} : r
                );
                this._loaded = true;
                this._lang = lang;
            } catch (err) {
                console.warn('Failed to load regions:', err);
                this._regions = [
                    {id:'cn-hangzhou',name:'华东1（杭州）'},{id:'cn-beijing',name:'华北2（北京）'},
                    {id:'cn-shanghai',name:'华东2（上海）'},{id:'cn-shenzhen',name:'华南1（深圳）'},
                ];
                this._loaded = true;
                this._lang = lang;
            }
        })();
        await this._loading;
    },

    /** Force re-fetch regions (called on language change) */
    async reload() {
        this._loaded = false;
        this._loading = null;
        await this._loadRegions();
        // Re-render all instances
        for (const formId of Object.keys(this._selected)) {
            this._render(formId);
        }
    },

    /** Look up display name for a region ID */
    _name(id) {
        const r = this._regions.find(r => r.id === id);
        return r ? r.name : id;
    },

    /** Group regions by prefix */
    _groupRegions(regions) {
        const groups = {};
        for (const r of regions) {
            let prefix = r.id.split('-')[0];
            const labels = {
                'cn': t('regions.group_cn'),
                'ap': t('regions.group_ap'),
                'eu': t('regions.group_eu'),
                'us': t('regions.group_us'),
                'me': t('regions.group_me'),
            };
            const label = labels[prefix] || prefix.toUpperCase();
            if (!groups[label]) groups[label] = [];
            groups[label].push(r);
        }
        return groups;
    },

    /** Initialize a region select instance */
    async init(formId) {
        await this._loadRegions();
        if (!this._selected[formId]) {
            this._selected[formId] = new Set();
        }
        this._render(formId);
    },

    /** Get selected regions as comma-separated string */
    getValue(formId) {
        const sel = this._selected[formId];
        return sel ? [...sel].join(',') : '';
    },

    /** Set selected regions from comma-separated string */
    setValue(formId, value) {
        if (!this._selected[formId]) this._selected[formId] = new Set();
        this._selected[formId].clear();
        if (value) {
            value.split(',').map(s => s.trim()).filter(Boolean).forEach(r => {
                this._selected[formId].add(r);
            });
        }
        this._render(formId);
    },

    /** Toggle a region */
    toggle(formId, region) {
        if (!this._selected[formId]) this._selected[formId] = new Set();
        const sel = this._selected[formId];
        if (sel.has(region)) sel.delete(region);
        else sel.add(region);
        this._syncHidden(formId);
        this._renderTrigger(formId);
        this._updateDropdownState(formId, region);
    },

    /** Remove a tag */
    removeTag(formId, region) {
        if (this._selected[formId]) this._selected[formId].delete(region);
        this._syncHidden(formId);
        this._renderTrigger(formId);
        this._updateDropdownState(formId, region);
    },

    /** Sync hidden input value */
    _syncHidden(formId) {
        const hidden = document.querySelector(`#${formId} input[name="regions"].region-hidden`);
        if (hidden) hidden.value = this.getValue(formId);
    },

    /** Update checkbox state for a specific region in dropdown */
    _updateDropdownState(formId, region) {
        const wrap = document.getElementById(`${formId}-region-select`);
        if (!wrap) return;
        const cb = wrap.querySelector(`.region-select-option[data-region="${region}"] input[type="checkbox"]`);
        if (cb) cb.checked = this._selected[formId]?.has(region) || false;
        const opt = wrap.querySelector(`.region-select-option[data-region="${region}"]`);
        if (opt) opt.classList.toggle('selected', this._selected[formId]?.has(region) || false);
    },

    /** Render trigger (tags + placeholder) */
    _renderTrigger(formId) {
        const wrap = document.getElementById(`${formId}-region-select`);
        if (!wrap) return;
        const trigger = wrap.querySelector('.region-select-trigger');
        if (!trigger) return;

        const sel = this._selected[formId] || new Set();
        let html = '';
        if (sel.size === 0) {
            html = `<span class="region-select-placeholder">${t('regions.select_placeholder')}</span>`;
        } else {
            for (const r of sel) {
                const name = this._name(r);
                const display = (name && name !== r) ? `${name} - ${r}` : r;
                html += `<span class="region-tag">${display}<i class="region-tag-remove" onclick="event.stopPropagation(); regionSelect.removeTag('${formId}','${r}')">&times;</i></span>`;
            }
        }
        html += '<span class="arrow">▼</span>';
        trigger.innerHTML = html;
    },

    /** Render dropdown */
    _renderDropdown(formId) {
        const wrap = document.getElementById(`${formId}-region-select`);
        if (!wrap) return;
        const dropdown = wrap.querySelector('.region-select-dropdown');
        if (!dropdown) return;

        const sel = this._selected[formId] || new Set();
        const groups = this._groupRegions(this._regions);

        let html = `<div class="region-select-search"><input type="text" placeholder="${t('regions.search_placeholder')}" oninput="regionSelect._filterDropdown('${formId}', this.value)"></div>`;

        for (const [label, regions] of Object.entries(groups)) {
            html += `<div class="region-select-group" data-group="${label}">`;
            html += `<div class="region-select-group-label">${label}</div>`;
            for (const r of regions) {
                const checked = sel.has(r.id);
                const displayName = (r.name && r.name !== r.id) ? `${r.name} - ${r.id}` : r.id;
                html += `<div class="region-select-option${checked ? ' selected' : ''}" data-region="${r.id}" data-search="${r.id} ${r.name || ''}" onclick="regionSelect.toggle('${formId}','${r.id}')">`;
                html += `<input type="checkbox" ${checked ? 'checked' : ''} onclick="event.stopPropagation(); regionSelect.toggle('${formId}','${r.id}')">`;
                html += `<span class="region-id">${displayName}</span>`;
                html += `</div>`;
            }
            html += `</div>`;
        }

        dropdown.innerHTML = html;
    },

    /** Filter dropdown by search text */
    _filterDropdown(formId, query) {
        const wrap = document.getElementById(`${formId}-region-select`);
        if (!wrap) return;
        const q = query.toLowerCase().trim();
        const groups = wrap.querySelectorAll('.region-select-group');
        let anyVisible = false;

        groups.forEach(group => {
            let groupVisible = false;
            group.querySelectorAll('.region-select-option').forEach(opt => {
                const searchText = (opt.dataset.search || opt.dataset.region).toLowerCase();
                const match = !q || searchText.includes(q);
                opt.style.display = match ? '' : 'none';
                if (match) groupVisible = true;
            });
            group.style.display = groupVisible ? '' : 'none';
            if (groupVisible) anyVisible = true;
        });

        // Show/hide empty state
        let emptyEl = wrap.querySelector('.region-select-empty');
        if (!anyVisible && !emptyEl) {
            emptyEl = document.createElement('div');
            emptyEl.className = 'region-select-empty';
            emptyEl.textContent = t('regions.no_match');
            wrap.querySelector('.region-select-dropdown').appendChild(emptyEl);
        } else if (anyVisible && emptyEl) {
            emptyEl.remove();
        }
    },

    /** Toggle dropdown open/close */
    _toggleDropdown(formId) {
        const wrap = document.getElementById(`${formId}-region-select`);
        if (!wrap) return;
        const trigger = wrap.querySelector('.region-select-trigger');
        const dropdown = wrap.querySelector('.region-select-dropdown');
        const isOpen = dropdown.classList.contains('open');

        // Close all other dropdowns first
        document.querySelectorAll('.region-select-dropdown.open').forEach(d => {
            d.classList.remove('open');
            d.closest('.region-select')?.querySelector('.region-select-trigger')?.classList.remove('open');
        });

        if (!isOpen) {
            dropdown.classList.add('open');
            trigger.classList.add('open');
            const searchInput = dropdown.querySelector('.region-select-search input');
            if (searchInput) setTimeout(() => searchInput.focus(), 50);
        }
    },

    /** Full render */
    _render(formId) {
        this._renderTrigger(formId);
        this._renderDropdown(formId);
        this._syncHidden(formId);
    },
};

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
    if (!e.target.closest('.region-select')) {
        document.querySelectorAll('.region-select-dropdown.open').forEach(d => {
            d.classList.remove('open');
            d.closest('.region-select')?.querySelector('.region-select-trigger')?.classList.remove('open');
        });
    }
    if (!e.target.closest('.fe-saved-dropdown') && !e.target.closest('.fe-saved-btn')) {
        document.querySelectorAll('.fe-saved-dropdown.open').forEach(d => d.classList.remove('open'));
        document.querySelectorAll('.fe-saved-btn.active').forEach(b => b.classList.remove('active'));
    }
});

// === Projects Module ===
let _projectsCache = [];

async function loadProjectList() {
    const container = document.getElementById('project-list');
    if (!container) return;
    try {
        const data = await api('/api/projects');
        _projectsCache = data.projects || [];
        // Update runs filter with latest project count
        _updateRunsFilter();
        // Update dashboard stats project count
        if (currentPage === 'dashboard') _renderDashboardStats(_allRuns);
        if (!_projectsCache.length) {
            container.innerHTML = `<div class="project-empty">${t('settings.no_projects')}</div>`;
            _renderCardPagination('project-list-pagination', 0, CARD_PAGE_SIZE.projects, 0, '_setProjPage');
            return;
        }
        // Pagination
        const pageSize = CARD_PAGE_SIZE.projects;
        const totalPages = Math.ceil(_projectsCache.length / pageSize);
        if (_cardPage.projects >= totalPages) _cardPage.projects = totalPages - 1;
        const pageProjects = _projectsCache.slice(_cardPage.projects * pageSize, (_cardPage.projects + 1) * pageSize);
        container.innerHTML = pageProjects.map(p => {
            const tplLines = (p.template_preview || '').split('\n').filter(l => l.trim()).length;
            const cfgLines = (p.config_preview || '').split('\n').filter(l => l.trim()).length;
            const tplChars = (p.template_preview || '').length;
            const cfgChars = (p.config_preview || '').length;
            const encName = encodeURIComponent(p.name);
            const hasTemplate = tplChars > 0;
            const hasConfig = cfgChars > 0;
            const tplDesc = hasTemplate ? t('project.meta_lines', {n: tplLines}) : t('project.empty');
            const cfgDesc = hasConfig   ? t('project.meta_lines', {n: cfgLines})  : t('project.empty');
            return `<div class="project-item">
                <div class="project-item-info">
                    <div class="project-item-name project-name-link" onclick="viewProject('${encName}')">${escapeHtml(p.name)}</div>
                    <div class="project-item-meta">
                        <span class="${hasTemplate ? '' : 'meta-empty'}" title="${t('project.meta_template')}">${tplDesc}</span>
                        <span class="${hasConfig ? '' : 'meta-empty'}" title="${t('project.meta_config')}">${cfgDesc}</span>
                    </div>
                </div>
                <div class="project-item-actions">
                    <button class="btn-text-danger" onclick="deleteProject('${encName}')" title="${t('editor.delete_saved')}">${t('editor.delete_saved')}</button>
                </div>
            </div>`;
        }).join('');
        _renderCardPagination('project-list-pagination', _projectsCache.length, pageSize, _cardPage.projects, '_setProjPage');
    } catch (err) {
        container.innerHTML = `<div class="project-empty">${t('project.load_failed')}: ${err.message}</div>`;
    }
}

async function loadProjectSelectors() {
    try {
        const data = await api('/api/projects');
        _projectsCache = data.projects || [];
    } catch (_) { _projectsCache = []; }
    // Do NOT auto-fill project name — user selects or saves explicitly
    // Refresh any open dropdown
    const openDropdown = document.querySelector('.project-dropdown.open');
    if (openDropdown) {
        const page = 'workspace';
        _populateProjectDropdown(page);
    }
    // Also refresh history filter
    _updateHistoryFilter();
}

/** Populate / refresh the project dropdown for a given page */
function _populateProjectDropdown(page) {
    const dropdown = document.getElementById(`${page}-project-dropdown`);
    if (!dropdown) return;
    if (!_projectsCache.length) {
        dropdown.innerHTML = `<div class="project-dropdown-empty">${t('settings.no_projects')}</div>`;
    } else {
        dropdown.innerHTML = _projectsCache.map(p =>
            `<div class="project-dropdown-item" onmousedown="_selectProjectItem(event,'${page}','${escapeHtml(p.name).replace(/'/g, '\\&#39;')}')">${escapeHtml(p.name)}</div>`
        ).join('');
    }
    // Reset any previous filter (show all items)
    dropdown.querySelectorAll('.project-dropdown-item').forEach(i => i.style.display = '');
    dropdown.classList.add('open');
}

/** Handle project input typing: filter dropdown and auto-load matching project */
function _onProjectInput(page) {
    const input = document.getElementById(`${page}-project-name`);
    const dropdown = document.getElementById(`${page}-project-dropdown`);
    if (!input || !dropdown) return;
    // Ensure dropdown items are populated (in case user types before clicking arrow)
    if (!dropdown.children.length) {
        if (!_projectsCache.length) {
            dropdown.innerHTML = `<div class="project-dropdown-empty">${t('settings.no_projects')}</div>`;
        } else {
            dropdown.innerHTML = _projectsCache.map(p =>
                `<div class="project-dropdown-item" onmousedown="_selectProjectItem(event,'${page}','${escapeHtml(p.name).replace(/'/g, '\\&#39;')}')">${escapeHtml(p.name)}</div>`
            ).join('');
        }
    }
    const val = input.value.toLowerCase().trim();
    // Filter visible items
    dropdown.querySelectorAll('.project-dropdown-item').forEach(item => {
        const name = item.textContent.trim().toLowerCase();
        item.style.display = (!val || name.includes(val)) ? '' : 'none';
    });
    const anyVisible = [...dropdown.querySelectorAll('.project-dropdown-item')].some(i => i.style.display !== 'none');
    if (anyVisible) {
        dropdown.classList.add('open');
    } else {
        dropdown.classList.remove('open');
    }
}

/** Close all open project dropdowns */
function _closeAllProjectDropdowns() {
    document.querySelectorAll('.project-dropdown.open').forEach(d => d.classList.remove('open'));
}

/** Toggle project dropdown when clicking the arrow indicator */
function _toggleProjectDropdown(e, page) {
    e.preventDefault();  // prevent input blur
    const dropdown = document.getElementById(`${page}-project-dropdown`);
    if (!dropdown) return;
    const isOpen = dropdown.classList.contains('open');
    _closeAllProjectDropdowns();
    if (!isOpen) {
        _populateProjectDropdown(page);
    }
}

// Global click handler: close dropdown when clicking outside
document.addEventListener('mousedown', (e) => {
    if (!e.target.closest('.project-selector')) _closeAllProjectDropdowns();
});

// Global keydown: Escape closes dropdown
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') _closeAllProjectDropdowns();
});

/** Track which pages have had a project explicitly loaded (prevents autoFillDefaults from overwriting) */
const _projectExplicitlyLoaded = { workspace: false };
/** Track which pages are currently loading a project (blocks form submission) */
const _projectLoading = { workspace: false };
/** Track last loaded project content to detect user edits in _autoSaveProject */
const _projectLastLoaded = { workspace: { template: '', config: '' } };

/** Handle project name change: if matches existing project, load it */
async function onProjectNameChange(page) {
    const nameInput = document.getElementById(`${page}-project-name`);
    if (!nameInput) return;
    const name = (nameInput.value || '').trim();
    if (!name) return;
    // Check if this name matches an existing project
    const existing = _projectsCache.find(p => p.name === name);
    if (!existing) return; // New project name, nothing to load
    // Mark as explicitly loaded IMMEDIATELY to prevent autoFillDefaults from interfering
    _projectExplicitlyLoaded[page] = true;
    _projectLoading[page] = true;
    // Load existing project content
    try {
        const project = await api(`/api/projects/${encodeURIComponent(name)}`);
        const templateContent = project.template || '';
        const configContent = project.config || '';
        console.log(`[onProjectNameChange] page=${page} name=${name} tplLen=${templateContent.length} cfgLen=${configContent.length}`);
        console.log(`[onProjectNameChange] template preview: ${templateContent.substring(0, 80)}`);
        console.log(`[onProjectNameChange] config preview: ${configContent.substring(0, 80)}`);
        const templateTextarea = document.getElementById(`${page}-template-content`);
        const configTextarea = document.getElementById(`${page}-config-content`);
        // ALWAYS set textarea values (use '' if project has no content) to clear old data
        if (templateTextarea) {
            templateTextarea.value = templateContent;
            fileEditor.validate(`${page}-template`);
            fileEditor._updateEmptyHint(`${page}-template`);
        }
        if (configTextarea) {
            configTextarea.value = configContent;
            fileEditor.validate(`${page}-config`);
            fileEditor._updateEmptyHint(`${page}-config`);
        }
        // Clear hidden path fields so they don't carry stale default paths
        const form = document.getElementById(`${page}-form`);
        if (form) {
            const hiddenTemplate = form.querySelector('[data-editor-type="template"] .fe-path-value');
            const hiddenConfig = form.querySelector('[data-editor-type="config"] .fe-path-value');
            if (hiddenTemplate) hiddenTemplate.value = '';
            if (hiddenConfig) hiddenConfig.value = '';
        }
        // Track loaded content so _autoSaveProject can detect user edits
        _projectLastLoaded[page] = { template: templateContent, config: configContent };
        _updateEditorSummary(page, 'template');
        _updateEditorSummary(page, 'config');
        showToast(t('project.loaded', {name}), 3000, 'info');
    } catch (err) {
        showToast(`${t('project.load_failed')}: ${err.message}`);
    } finally {
        _projectLoading[page] = false;
    }
}

/** Handle click on a project dropdown item */
function _selectProjectItem(e, page, name) {
    e.preventDefault();  // prevent input blur
    const input = document.getElementById(`${page}-project-name`);
    if (input) input.value = name;
    _closeAllProjectDropdowns();
    onProjectNameChange(page);
}

async function createProject() {
    const nameInput = document.getElementById('new-project-name');
    if (!nameInput) return;
    const name = (nameInput.value || '').trim();
    if (!name) { showToast(t('project.name_required')); return; }
    // Create project (content can be edited via Run/Analyze pages)
    try {
        await api('/api/projects', {
            method: 'POST',
            body: JSON.stringify({ name, template: '', config: '' }),
        });
        nameInput.value = '';
        showToast(t('project.created', {name}), 3000, 'success');
        loadProjectList();
        loadProjectSelectors();
    } catch (err) {
        showToast(`${t('project.create_failed')}: ${err.message}`);
    }
}

async function deleteProject(encodedName) {
    const name = decodeURIComponent(encodedName);
    const ok = await confirmDialog(t('project.confirm_delete', {name}));
    if (!ok) return;
    try {
        await api(`/api/projects/${encodedName}`, { method: 'DELETE' });
        showToast(t('project.deleted', {name}), 3000, 'success');
        loadProjectList();
        loadProjectSelectors();
    } catch (err) {
        showToast(`${t('project.delete_failed')}: ${err.message}`);
    }
}

async function viewProject(encodedName) {
    const name = decodeURIComponent(encodedName);
    try {
        const project = await api(`/api/projects/${encodedName}`);
        const templateContent = project.template || '';
        const configContent = project.config || '';
        // Mark as explicitly loaded BEFORE navigating to prevent autoFillDefaults race
        _projectExplicitlyLoaded['workspace'] = true;
        _projectLoading['workspace'] = true;
        navigateTo('workspace');
        // Set content immediately (no setTimeout needed since we pre-marked loaded)
        const templateTextarea = document.getElementById('workspace-template-content');
        const configTextarea = document.getElementById('workspace-config-content');
        if (templateTextarea) {
            templateTextarea.value = templateContent;
            fileEditor.validate('workspace-template');
            fileEditor._updateEmptyHint('workspace-template');
        }
        if (configTextarea) {
            configTextarea.value = configContent;
            fileEditor.validate('workspace-config');
            fileEditor._updateEmptyHint('workspace-config');
        }
        // Clear hidden path fields
        const form = document.getElementById('workspace-form');
        if (form) {
            const hiddenTemplate = form.querySelector('[data-editor-type="template"] .fe-path-value');
            const hiddenConfig = form.querySelector('[data-editor-type="config"] .fe-path-value');
            if (hiddenTemplate) hiddenTemplate.value = '';
            if (hiddenConfig) hiddenConfig.value = '';
        }
        _projectLastLoaded['workspace'] = { template: templateContent, config: configContent };
        _updateEditorSummary('workspace', 'template');
        _updateEditorSummary('workspace', 'config');
        const nameInput = document.getElementById('workspace-project-name');
        if (nameInput) nameInput.value = name;
        _projectLoading['workspace'] = false;
        showToast(t('project.loaded', {name}), 3000, 'info');
    } catch (err) {
        _projectLoading['workspace'] = false;
        showToast(`${t('project.load_failed')}: ${err.message}`);
    }
}

/** Generate a timestamp-based project name (e.g. project-20250608-143022) */
function _generateProjectName() {
    const d = new Date();
    const pad = n => String(n).padStart(2, '0');
    return `project-${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

/**
 * Inject/update project.name in config YAML content.
 * Ensures the config file and the UI project name stay in sync.
 */
function _syncProjectNameInConfig(configYaml, projectName) {
    if (!configYaml || !projectName) return configYaml;
    const lines = configYaml.split('\n');
    let inProject = false;
    let nameUpdated = false;
    let nameInserted = false;
    const result = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        // Detect top-level 'project:' (no leading whitespace)
        if (/^project\s*:/.test(line)) {
            inProject = true;
            result.push(line);
            continue;
        }
        // Another top-level key ends the project section
        if (inProject && trimmed && !line.startsWith(' ') && !line.startsWith('\t') && trimmed !== '---') {
            // Insert name if not yet done
            if (!nameInserted) {
                result.push('  name: ' + projectName);
                nameInserted = true;
                nameUpdated = true;
            }
            inProject = false;
        }
        // Update existing name: field inside project section
        if (inProject && /^\s+name\s*:/.test(line)) {
            result.push('  name: ' + projectName);
            nameUpdated = true;
            nameInserted = true;
            continue;
        }
        result.push(line);
    }

    // Handle end-of-file while still in project section
    if (inProject && !nameInserted) {
        result.push('  name: ' + projectName);
        nameUpdated = true;
    }

    // No project: section at all → add one
    if (!nameUpdated) {
        if (result.length > 0 && result[result.length - 1].trim() !== '') {
            result.push('');
        }
        result.push('project:');
        result.push('  name: ' + projectName);
    }

    return result.join('\n');
}

/**
 * Extract project.name from config YAML content.
 * Returns the name string or null if not found.
 */
function _extractProjectNameFromConfig(configYaml) {
    if (!configYaml) return null;
    const lines = configYaml.split('\n');
    let inProject = false;
    for (const line of lines) {
        if (/^project\s*:/.test(line)) { inProject = true; continue; }
        if (inProject && line.trim() && !line.startsWith(' ') && !line.startsWith('\t')) break;
        if (inProject) {
            const m = line.match(/^\s+name\s*:\s*(.+)/);
            if (m) {
                const val = m[1].trim().replace(/^['"]|['"]$/g, '');
                return val || null;
            }
        }
    }
    return null;
}

/** Auto-save is now DISABLED — saving only happens via saveCurrentProject().
 *  This function now just returns the current project name for history tracking,
 *  without creating any new project silently. */
async function _autoSaveProject(page) {
    const nameInput = document.getElementById(`${page}-project-name`);
    const name = (nameInput?.value || '').trim();
    // Only return name if it's an already-saved project (exists in cache)
    // For unsaved/temporary content, auto-save before running test
    if (!name) return null;
    if (_projectExplicitlyLoaded[page]) return name; // was loaded from existing project
    const inCache = _projectsCache.some(p => p.name === name);
    if (inCache) return name;

    // Auto-save new project before running test
    const templateContent = document.getElementById(`${page}-template-content`)?.value || '';
    const configContent = document.getElementById(`${page}-config-content`)?.value || '';
    if (!templateContent.trim() && !configContent.trim()) return null;

    try {
        let configForSave = configContent;
        if (configForSave.trim()) {
            configForSave = _syncProjectNameInConfig(configForSave, name);
        }
        await api('/api/projects', {
            method: 'POST',
            body: JSON.stringify({ name, template: templateContent, config: configForSave }),
        });
        _projectExplicitlyLoaded[page] = true;
        _projectLastLoaded[page] = { template: templateContent, config: configContent };
        loadProjectSelectors();
        loadProjectList();
        return name;
    } catch (err) {
        console.warn('Auto-save project failed:', err);
        return null;
    }
}

/** Clear all editor content and reset project state for a page. */
function clearPageForm(page) {
    // Clear project name input
    const nameInput = document.getElementById(`${page}-project-name`);
    if (nameInput) nameInput.value = '';

    // Clear template & config textareas
    const templateTA = document.getElementById(`${page}-template-content`);
    const configTA   = document.getElementById(`${page}-config-content`);
    if (templateTA) { templateTA.value = ''; fileEditor._updateEmptyHint(`${page}-template`); }
    if (configTA)   { configTA.value = '';   fileEditor._updateEmptyHint(`${page}-config`);   }

    // Clear validation / info spans
    ['template', 'config'].forEach(type => {
        const validEl = document.getElementById(`${page}-${type}-validation`);
        const infoEl  = document.getElementById(`${page}-${type}-info`);
        if (validEl) validEl.innerHTML = '';
        if (infoEl)  infoEl.textContent = '';
    });

    // Clear hidden path values
    const form = document.getElementById(`${page}-form`);
    if (form) {
        form.querySelectorAll('.fe-path-value').forEach(el => { el.value = ''; });
    }

    // Reset region selection
    regionSelect.setValue(`${page}-form`, '');

    // Reset project state flags
    _projectExplicitlyLoaded[page] = false;
    _projectLastLoaded[page] = { template: '', config: '' };

    // Update collapsible summaries if present
    _updateEditorSummary(page, 'template');
    _updateEditorSummary(page, 'config');

    showToast(t('project.cleared') || '已清空', 3000, 'success');
}

/** Save current editor content as a project. Called by the Save button. */
async function saveCurrentProject(page) {
    const nameInput = document.getElementById(`${page}-project-name`);
    let name = (nameInput?.value || '').trim();
    // If empty, generate a name and fill it in
    if (!name) {
        name = _generateProjectName();
        if (nameInput) nameInput.value = name;
    }
    const templateContent = document.getElementById(`${page}-template-content`)?.value || '';
    const configContent = document.getElementById(`${page}-config-content`)?.value || '';
    if (!templateContent.trim() && !configContent.trim()) {
        showToast(t('project.save_empty_warn'));
        return;
    }
    // Sync project name into config YAML (on a COPY, do NOT modify textarea)
    let configForSave = configContent;
    if (configForSave.trim()) {
        configForSave = _syncProjectNameInConfig(configForSave, name);
    }
    try {
        await api('/api/projects', {
            method: 'POST',
            body: JSON.stringify({ name, template: templateContent, config: configForSave }),
        });
        _projectExplicitlyLoaded[page] = true;
        _projectLastLoaded[page] = { template: templateContent, config: configContent };
        showToast(t('project.saved', {name}), 3000, 'success');
        loadProjectSelectors();
        loadProjectList();
    } catch (err) {
        showToast(`${t('project.save_failed')}: ${err.message}`);
    }
}



// === History Module ===
let _historyFilter = '';       // current project filter ('' = all)
let _historyTypeFilter = ''; // current type filter ('' = all)
let _historyEntries = [];

function _updateHistoryFilter() {
    // Update project filter dropdown
    const select = document.getElementById('history-project-filter');
    if (select) {
        const projectNames = new Set();
        _projectsCache.forEach(p => projectNames.add(p.name));
        _historyEntries.forEach(e => { if (e.project_name) projectNames.add(e.project_name); });
        const sorted = [...projectNames].sort();
        const allCount = _historyEntries.length;
        select.innerHTML = `<option value="">${t('dashboard.history_filter_all')} (${allCount})</option>` +
            sorted.map(n => {
                const count = _historyEntries.filter(e => e.project_name === n).length;
                return `<option value="${escapeHtml(n)}"${n === _historyFilter ? ' selected' : ''}>${escapeHtml(n)} (${count})</option>`;
            }).join('');
        const unnamedCount = _historyEntries.filter(e => !e.project_name).length;
        if (unnamedCount > 0) {
            select.innerHTML += `<option value="__unnamed__"${_historyFilter === '__unnamed__' ? ' selected' : ''}>${t('dashboard.unnamed')} (${unnamedCount})</option>`;
        }
    }
    // Update type filter dropdown counts
    const typeSelect = document.getElementById('history-type-filter');
    if (typeSelect) {
        const types = ['validate', 'preview', 'cost', 'policy'];
        const typeIcons = { validate: '', preview: '', cost: '', policy: '' };
        const allCount = _historyEntries.length;
        typeSelect.innerHTML = `<option value="">${t('dashboard.filter_all_types')} (${allCount})</option>` +
            types.map(tp => {
                const count = _historyEntries.filter(e => e.type === tp).length;
                const icon = typeIcons[tp] || '';
                return `<option value="${tp}"${tp === _historyTypeFilter ? ' selected' : ''}>${icon} ${t('analyze.' + tp)} (${count})</option>`;
            }).join('');
    }
}

function filterHistory(projectName) {
    _historyFilter = projectName;
    _cardPage.history = 0;
    _renderHistory();
}

function filterHistoryByType(type) {
    _historyTypeFilter = type;
    _cardPage.history = 0;
    _renderHistory();
}

function _getHistorySummary(entry) {
    if (entry.error) return entry.error.substring(0, 100);
    const r = entry.result;
    if (!r) return '';
    if (entry.type === 'validate') return r.result === 'valid' ? t('analyze.valid') : t('analyze.invalid');
    if (entry.type === 'cost' && r.prices) return t('analyze.cost_resources', { n: r.prices.length });
    if (entry.type === 'preview' && r.previews) return t('analyze.preview_resources', { n: r.previews.length });
    if (entry.type === 'policy' && r.policy) return t('analyze.policy_results');
    return '';
}

function _relativeTime(timestamp) {
    if (!timestamp) return '';
    const now = Date.now();
    const then = parseFloat(timestamp) * 1000;
    const diff = Math.floor((now - then) / 1000);
    if (diff < 60) return t('editor.just_now');
    if (diff < 3600) return Math.floor(diff / 60) + 'm';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h';
    if (diff < 604800) return Math.floor(diff / 86400) + 'd';
    return new Date(then).toLocaleDateString();
}

function _renderHistory() {
    const container = document.getElementById('history-list');
    if (!container) return;
    let entries = _historyEntries;
    // Apply project filter
    if (_historyFilter === '__unnamed__') {
        entries = entries.filter(e => !e.project_name);
    } else if (_historyFilter) {
        entries = entries.filter(e => e.project_name === _historyFilter);
    }
    // Apply type filter
    if (_historyTypeFilter) {
        entries = entries.filter(e => e.type === _historyTypeFilter);
    }
    if (!entries.length) {
        container.innerHTML = `<div class="history-empty">${t('dashboard.no_history')}</div>`;
        _renderCardPagination('history-pagination', 0, CARD_PAGE_SIZE.history, 0, '_setHistPage');
        return;
    }
    // Pagination
    const pageSize = CARD_PAGE_SIZE.history;
    const totalPages = Math.ceil(entries.length / pageSize);
    if (_cardPage.history >= totalPages) _cardPage.history = totalPages - 1;
    const pageEntries = entries.slice(_cardPage.history * pageSize, (_cardPage.history + 1) * pageSize);
    const typeIcons = { validate: '', preview: '', cost: '', policy: '' };
    // Render as table
    container.innerHTML = `
        <table class="history-table">
            <thead>
                <tr>
                    <th class="ht-col-type">${t('dashboard.col_type')}</th>
                    <th class="ht-col-project">${t('dashboard.col_project')}</th>
                    <th class="ht-col-result">${t('dashboard.col_result')}</th>
                    <th class="ht-col-time">${t('dashboard.col_time')}</th>
                    <th class="ht-col-status">${t('dashboard.col_status')}</th>
                    <th class="ht-col-actions">${t('reports.col_actions')}</th>
                </tr>
            </thead>
            <tbody>
                ${pageEntries.map(e => {
                    const type = e.type || 'unknown';
                    const isOk = !e.error;
                    const icon = typeIcons[type] || '';
                    const summary = _getHistorySummary(e);
                    const relTime = _relativeTime(e.timestamp);
                    const fullTime = e.timestamp ? new Date(parseFloat(e.timestamp) * 1000).toLocaleString() : '';
                    const projName = e.project_name || t('dashboard.unnamed');
                    return `<tr class="history-row ${isOk ? '' : 'history-row-error'}" onclick="showHistoryDetail('${e.id}')">
                        <td class="ht-col-type"><span class="history-type-badge history-type-${type}">${t('analyze.' + type)}</span></td>
                        <td class="ht-col-project">${escapeHtml(projName)}</td>
                        <td class="ht-col-result">${escapeHtml(summary)}</td>
                        <td class="ht-col-time" title="${fullTime}">${relTime}</td>
                        <td class="ht-col-status"><span class="history-status-badge ${isOk ? 'status-badge-ok' : 'status-badge-err'}">${isOk ? t('detail.succeeded') : t('detail.failed')}</span></td>
                        <td class="ht-col-actions"><button class="btn-text-danger" onclick="event.stopPropagation(); deleteHistoryEntry('${e.id}')">${t('editor.delete_saved')}</button></td>
                    </tr>`;
                }).join('')}
            </tbody>
        </table>`;
    _renderCardPagination('history-pagination', entries.length, pageSize, _cardPage.history, '_setHistPage');
}

async function loadHistory() {
    const container = document.getElementById('history-list');
    if (!container) return;
    try {
        const data = await api('/api/history');
        _historyEntries = data.history || [];
        _updateHistoryFilter();
        _renderHistory();
    } catch (err) {
        container.innerHTML = `<div class="history-empty">${t('dashboard.history_load_failed')}: ${err.message}</div>`;
    }
}

async function showHistoryDetail(id) {
    try {
        const entry = await api(`/api/history/${id}`);
        const modal = document.getElementById('file-modal');
        const title = document.getElementById('modal-filename');
        const body = document.getElementById('modal-content');
        const loading = document.getElementById('modal-loading');
        const copyBtn = document.getElementById('modal-copy-btn');
        const backBtn = document.getElementById('modal-back-btn');
        modal.classList.remove('hidden');
        title.textContent = `${t('analyze.' + entry.type)} - ${entry.project_name || t('dashboard.unnamed')}`;
        body.classList.remove('hidden');
        loading.classList.add('hidden');
        copyBtn.classList.remove('hidden');
        backBtn.classList.add('hidden');
        _modalOnClose = null;
        const content = entry.error
            ? `${t('common.error_label')}:\n${entry.error}\n\n---\n\nRaw:\n${JSON.stringify(entry.result || entry, null, 2)}`
            : JSON.stringify(entry.result || entry, null, 2);
        body.textContent = content;
    } catch (err) {
        showToast(`${t('common.failed_label')}: ${err.message}`);
    }
}

async function deleteHistoryEntry(id) {
    const ok = await confirmDialog(t('editor.confirm_delete', { name: id.substring(0, 8) }));
    if (!ok) return;
    try {
        await api(`/api/history/${id}`, { method: 'DELETE' });
        showToast(t('editor.deleted_ok', { name: id.substring(0, 8) }));
        loadHistory();
    } catch (err) {
        showToast(`${t('editor.delete_failed')}${err.message}`);
    }
}

async function clearHistory() {
    const ok = await confirmDialog(t('dashboard.clear_history') + '?');
    if (!ok) return;
    try {
        await api('/api/history/cleanup', { method: 'POST' });
        showToast(t('dashboard.history_cleared'), 3000, 'success');
        loadHistory();
    } catch (err) {
        showToast(`${t('common.failed_label')}: ${err.message}`);
    }
}

// === Init ===
setLang(getLang());  // apply translations on page load
refreshRuns();
checkConnection();
loadSettings();  // load settings early so autoFillDefaults can use regions/defaults

// Initialize region multi-selects
regionSelect.init('workspace-form');
regionSelect.init('settings-form');

// Initialize project selectors, project list, and history
loadProjectSelectors();
loadProjectList();
loadHistory();

// Auto-validate editors on blur (when focus leaves textarea)
document.querySelectorAll('.file-editor[data-editor-id]').forEach(wrapper => {
    const editorId = wrapper.dataset.editorId;
    const textarea = wrapper.querySelector('.fe-content');
    if (textarea && editorId) {
        textarea.addEventListener('blur', () => {
            if (textarea.value.trim()) fileEditor.validate(editorId);
        });
        // Update empty hint on input
        textarea.addEventListener('input', () => {
            fileEditor._updateEmptyHint(editorId);
        });
        // Initialize empty hint on page load
        fileEditor._updateEmptyHint(editorId);
    }
});

// ESC to close modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeFileModal();
});

// Global error handler for unhandled promise rejections
window.addEventListener('unhandledrejection', (e) => {
    console.error('Unhandled promise rejection:', e.reason);
    if (e.reason && e.reason.message && e.reason.message.includes('Failed to fetch')) {
        document.getElementById('connection-banner').classList.remove('hidden');
    }
});
