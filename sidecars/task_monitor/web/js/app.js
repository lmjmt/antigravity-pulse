// ================= LIFECYCLE & POLLING =================
const PAGE_CODE_VERSION = (INITIAL_PAYLOAD && INITIAL_PAYLOAD.code_version) ? INITIAL_PAYLOAD.code_version : null;
let hasNewServerCode = false;

function computeMultiTaskSig(mt) {
    if (!mt || !mt.all_tasks) return '';
    const sum = mt.summary || {};
    const head = `${mt.time_range || ''}:${sum.total_count}:${sum.running_count}:${sum.waiting_count}:${sum.stuck_count}:${mt.focused_cid || ''}:${selectedTaskId || ''}`;
    const cur = mt.all_tasks.find(x => x.conversation_id === (selectedTaskId || mt.focused_cid)) || mt.all_tasks[0];
    const curSig = cur ? `${cur.conversation_id}:${cur.health}:${cur.step_count}:${cur.current_action}:${cur.inactivity_formatted}:${(cur.subagents || []).map(s => s.conversation_id + ':' + (s.details ? (s.details.health + ':' + s.details.step_count + ':' + s.details.current_action) : '')).join(',')}` : '';
    const topSig = mt.all_tasks.slice(0, 10).map(x => `${x.conversation_id.slice(0, 8)}:${x.health}:${x.step_count}:${x.inactivity_formatted}`).join('|');
    return `${head}|${curSig}|${topSig}`;
}

function handleServerData(data) {
    if (!data) return;
    if (PAGE_CODE_VERSION && data.code_version && data.code_version !== PAGE_CODE_VERSION) {
        hasNewServerCode = true;
    }
    if (data.time_range && RANGE_LABEL_MAP[data.time_range]) {
        currentTimeRange = data.time_range;
        document.querySelectorAll('#global-time-range .tr-btn').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-range') === currentTimeRange);
        });
        const badge = document.getElementById('task-range-badge');
        if (badge) badge.innerText = `🕒 ${RANGE_LABEL_MAP[currentTimeRange]}`;
    }
    if (data.analytics) {
        const anaSig = data.analytics.sig || data.analytics.timestamp;
        if (anaSig !== lastAnalyticsSig) {
            lastAnalyticsSig = anaSig;
            cachedAnalytics = data.analytics;
            if (activeTabName === 'analytics') renderAnalytics(data.analytics);
        }
    }
    if (data.multi_task) {
        const mtSig = computeMultiTaskSig(data.multi_task);
        if (mtSig !== lastMultiTaskSig) {
            lastMultiTaskSig = mtSig;
            renderAllTaskViews(data.multi_task);
        } else {
            cachedTaskData = data.multi_task;
        }
    }
    if (data.sessions_overview) {
        const sessSig = data.sessions_overview.sig || String(data.sessions_overview.total_count);
        if (sessSig !== lastSessionsSig) {
            lastSessionsSig = sessSig;
            cachedSessions = data.sessions_overview;
            document.getElementById('sessions-total-count').innerText = cachedSessions.total_count || 0;
            const validWs = (cachedSessions.workspaces || []).map(w => w.key);
            if (!validWs.includes(sessionWorkspaceFilter)) sessionWorkspaceFilter = 'all';
            renderMonthSelect(cachedSessions.months || []);
            renderWorkspaceChips(cachedSessions.workspaces);
            if (activeTabName === 'analytics') renderSessionCards();
        }
    }
}

// Instant Hydration
if (INITIAL_PAYLOAD) {
    handleServerData(INITIAL_PAYLOAD);
}

function animateSyncBar() {
    const elapsed = Date.now() - syncCycleStart;
    const pct = Math.min((elapsed / 1500) * 100, 100);
    const el = document.getElementById('sync-bar-progress');
    if (el) el.style.width = pct + '%';
    requestAnimationFrame(animateSyncBar);
}
requestAnimationFrame(animateSyncBar);

async function fetchUpdates() {
    syncCycleStart = Date.now();
    const reqRange = currentTimeRange;
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3500);
        let url = `/api/all?range=${encodeURIComponent(reqRange)}&_t=${Date.now()}`;
        if (selectedTaskId && !autoFollow) url += `&task_id=${encodeURIComponent(selectedTaskId)}`;
        if (lastAnalyticsSig) url += `&known_ana=${encodeURIComponent(lastAnalyticsSig)}`;
        if (lastSessionsSig) url += `&known_sess=${encodeURIComponent(lastSessionsSig)}`;
        const res = await fetch(url, { 
            cache: 'no-store',
            signal: controller.signal
        });
        clearTimeout(timeoutId);

        if (res.ok) {
            const data = await res.json();
            if (reqRange !== currentTimeRange) return;
            handleServerData(data);
            if (hasNewServerCode) {
                document.getElementById('sync-indicator').innerHTML = `
                    <button type="button" class="btn-icon" style="padding:3px 10px;font-size:11.5px;min-height:28px;border-color:var(--primary);color:var(--primary);font-weight:600;" onclick="location.reload()">🆕 新版本可用 · 点此或 Cmd+R 重载</button>
                `;
            } else {
                document.getElementById('sync-indicator').innerHTML = `
                    <span style="color: var(--success);">🟢 同步完成</span> · ${new Date().toLocaleTimeString()}
                `;
            }
        }
    } catch (err) {
        document.getElementById('sync-indicator').innerHTML = `<span style="color: var(--danger);">⚠️ 重连中...</span>`;
    }
}

function manualSync() {
    lastAnalyticsSig = null;
    lastSessionsSig = null;
    lastMultiTaskSig = null;
    fetchUpdates();
}

setInterval(fetchUpdates, 1500);
