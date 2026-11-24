let selectedTaskId = null;
let currentFilter = 'all';
let currentViewMode = 'focus';
let currentTimeRange = 'all';
let taskSearchQuery = '';
let autoFollow = true;
let cachedTaskData = null;
let cachedAnalytics = null;
let cachedSessions = null;
let cachedQuota = null;

const VALID_TIME_RANGES = ['today', '7d', '30d', 'all'];

// DSH-Context Session Filters
let sessionSearchQuery = '';
let sessionWorkspaceFilter = 'all';
let sessionArchiveFilter = 'all';
let sessionMonthFilter = 'all';
let sessionDateFilter = '';
let sessionModelFilter = '';
let modelTableSort = 'tokens'; // 'tokens' | 'calls' | 'avg' | 'sessions' | 'cost'
let sessionSortBy = 'updated'; // 'updated' | 'tokens' | 'context'
let sessionVisibleLimit = 60;
let usageChartMode = 'tokens'; // 'tokens' | 'activity'
let heatmapMode = 'tokens'; // 'tokens' | 'sessions'

let activeTabName = 'analytics';
let inspActiveTargetCid = null;
let inspActiveSubagentName = '';
let inspWindowData = null;
let inspHighlightStep = null;

let lastAnalyticsSig = null;
let lastSessionsSig = null;
let lastMultiTaskSig = null;
let lastQuotaSig = null;
let quotaDetailsExpanded = false;
let quotaModelsExpanded = false;
let quotaRefreshing = false;

let syncCycleStart = Date.now();

function escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function formatMemberSummary(t) {
    if (t.swarm && t.swarm.is_swarm) {
        return i18n('task.member_swarm', { active: t.swarm.active_workers, total: t.swarm.total_workers });
    }
    return t.subagents_count > 0 ? '🌿 ' + t.subagents_count : i18n('task.member_single');
}

function setTimeRange(rangeKey) {
    if (!VALID_TIME_RANGES.includes(rangeKey)) rangeKey = 'all';
    currentTimeRange = rangeKey;
    sessionDateFilter = '';
    sessionModelFilter = '';
    document.querySelectorAll('#global-time-range .tr-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-range') === rangeKey);
    });
    const badge = document.getElementById('task-range-badge');
    if (badge) badge.innerText = `🕒 ${getRangeLabel(rangeKey)}`;
    const ind = document.getElementById('sync-indicator');
    if (ind) ind.innerHTML = `<span style="color: var(--primary);">${escHtml(i18n('nav.switching_range', { label: getRangeLabel(rangeKey) }))}</span>`;
    fetchUpdates();
}

function setModelTableSort(col) {
    if (!['tokens', 'calls', 'avg', 'sessions', 'cost'].includes(col)) col = 'tokens';
    modelTableSort = col;
    if (cachedAnalytics && cachedAnalytics.model_usage) {
        renderModelUsage(cachedAnalytics.model_usage);
    }
}

function filterSessionByModel(modelName) {
    if (!modelName) return;
    sessionModelFilter = (sessionModelFilter === modelName) ? '' : modelName;
    sessionVisibleLimit = 60;
    if (cachedAnalytics && cachedAnalytics.model_usage) {
        renderModelUsage(cachedAnalytics.model_usage);
    }
    renderSessionCards();
    if (sessionModelFilter) {
        const sec = document.querySelector('.lc-ov-sessions-section');
        if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function clearSessionModelFilter() {
    sessionModelFilter = '';
    sessionVisibleLimit = 60;
    if (cachedAnalytics && cachedAnalytics.model_usage) {
        renderModelUsage(cachedAnalytics.model_usage);
    }
    renderSessionCards();
}

function toggleTheme() {
    const body = document.body;
    const cur = body.getAttribute('data-theme');
    body.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
}

function switchMainTab(tab) {
    activeTabName = tab;
    document.getElementById('analytics-view').style.display = (tab === 'analytics') ? 'block' : 'none';
    document.getElementById('task-view').style.display = (tab === 'task') ? 'block' : 'none';
    document.getElementById('tab-analytics-btn').className = 'tab-btn' + (tab === 'analytics' ? ' active' : '');
    document.getElementById('tab-task-btn').className = 'tab-btn' + (tab === 'task' ? ' active' : '');
    if (tab === 'task' && cachedTaskData) {
        renderAllTaskViews(cachedTaskData);
    } else if (tab === 'analytics') {
        if (cachedQuota && typeof renderQuota === 'function') renderQuota(cachedQuota);
        if (cachedAnalytics) renderAnalytics(cachedAnalytics);
    }
}

function formatTokens(num) {
    if (num >= 1e9) return (num/1e9).toFixed(1) + 'B';
    if (num >= 1e6) return (num/1e6).toFixed(1) + 'M';
    if (num >= 1e3) return (num/1e3).toFixed(1) + 'k';
    return num;
}

function showToast(msg) {
    const t = document.getElementById('toast-notify');
    t.innerText = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
}
