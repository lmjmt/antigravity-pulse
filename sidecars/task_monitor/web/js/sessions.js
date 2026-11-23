// ================= DSH-CONTEXT SESSIONS RENDERING =================
function onSessionSearch(val) {
    sessionSearchQuery = (val || '').trim().toLowerCase();
    sessionVisibleLimit = 60;
    renderSessionCards();
}

function filterSessionByDate(dateStr) {
    if (!dateStr) return;
    sessionDateFilter = (sessionDateFilter === dateStr) ? '' : dateStr;
    sessionVisibleLimit = 60;
    if (activeTabName !== 'analytics') {
        switchMainTab('analytics');
    }
    if (cachedAnalytics && cachedAnalytics.heatmap) {
        renderHeatmap(cachedAnalytics.heatmap);
    }
    renderSessionCards();
    if (sessionDateFilter) {
        const sec = document.querySelector('.lc-ov-sessions-section');
        if (sec) sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function clearSessionDateFilter() {
    sessionDateFilter = '';
    sessionVisibleLimit = 60;
    if (cachedAnalytics && cachedAnalytics.heatmap) {
        renderHeatmap(cachedAnalytics.heatmap);
    }
    renderSessionCards();
}

function renderDateFilterBar(matchedCount) {
    const bar = document.getElementById('session-date-filter-bar');
    if (!bar) return;
    if (!sessionDateFilter && !sessionModelFilter) {
        bar.style.display = 'none';
        bar.innerHTML = '';
        return;
    }
    let chips = '';
    if (sessionDateFilter) {
        chips += `
            <button type="button" class="date-filter-chip" onclick="clearSessionDateFilter()" title="点击取消按日筛选">
                <span>📅 已按热力图筛选日期: <b>${escHtml(sessionDateFilter)}</b> (${matchedCount} 个会话)</span>
                <span>✕ 清除</span>
            </button>
        `;
    }
    if (sessionModelFilter) {
        chips += `
            <button type="button" class="date-filter-chip" onclick="clearSessionModelFilter()" title="点击取消按模型筛选">
                <span>🤖 已按模型筛选: <b>${escHtml(sessionModelFilter)}</b> (${matchedCount} 个会话)</span>
                <span>✕ 清除</span>
            </button>
        `;
    }
    bar.style.display = 'flex';
    bar.style.flexWrap = 'wrap';
    bar.style.gap = '8px';
    bar.innerHTML = chips;
}

function onSessionMonthSelect(val) {
    sessionMonthFilter = val || 'all';
    sessionDateFilter = '';
    sessionVisibleLimit = 60;
    if (cachedAnalytics && cachedAnalytics.heatmap) {
        renderHeatmap(cachedAnalytics.heatmap);
    }
    renderSessionCards();
}

function onSessionArchiveSelect(val) {
    sessionArchiveFilter = val;
    sessionVisibleLimit = 60;
    renderSessionCards();
}

function setSessionSort(sortKey) {
    sessionSortBy = sortKey;
    sessionVisibleLimit = 60;
    document.querySelectorAll('.lc-gran-btn').forEach(b => b.classList.remove('active'));
    const target = document.getElementById('sort-' + sortKey + '-btn');
    if (target) target.classList.add('active');
    renderSessionCards();
}

function filterSessionByWorkspace(wsKey) {
    sessionWorkspaceFilter = wsKey || 'all';
    sessionVisibleLimit = 60;
    document.querySelectorAll('.lc-ov-chip').forEach(c => c.classList.remove('active'));
    const chip = document.getElementById('ws-chip-' + encodeURIComponent(sessionWorkspaceFilter));
    if (chip) chip.classList.add('active');
    renderSessionCards();
}

function showMoreSessions(stepCount) {
    sessionVisibleLimit += stepCount;
    renderSessionCards();
}

function showAllSessionsNow(totalCount) {
    sessionVisibleLimit = Math.max(totalCount || 1000, 10000);
    renderSessionCards();
}

function renderMonthSelect(months) {
    const sel = document.getElementById('sessions-month-select');
    if (!sel || !months || months.length === 0) return;
    const validKeys = months.map(m => m.key);
    if (!validKeys.includes(sessionMonthFilter)) sessionMonthFilter = 'all';
    let html = '';
    months.forEach(m => {
        const selected = (m.key === sessionMonthFilter) ? ' selected' : '';
        html += `<option value="${escHtml(m.key)}"${selected}>${escHtml(m.label)}</option>`;
    });
    sel.innerHTML = html;
}

function renderSessionCards() {
    if (!cachedSessions || !cachedSessions.sessions) return;
    const container = document.getElementById('sessions-cards-grid');
    const pager = document.getElementById('sessions-pagination-bar');
    let list = [...cachedSessions.sessions];

    // Filter archive
    if (sessionArchiveFilter === 'active') {
        list = list.filter(s => !s.archived);
    }

    // Filter date (from Heatmap click)
    if (sessionDateFilter) {
        list = list.filter(s => s.created_day === sessionDateFilter);
    } else if (sessionMonthFilter !== 'all') {
        list = list.filter(s => {
            const m = (s.created_day && s.created_day.length >= 7) ? s.created_day.slice(0, 7) : '未知';
            return m === sessionMonthFilter;
        });
    }

    // Filter workspace
    if (sessionWorkspaceFilter !== 'all') {
        list = list.filter(s => s.workspace === sessionWorkspaceFilter);
    }

    // Filter model
    if (sessionModelFilter) {
        list = list.filter(s => Array.isArray(s.models) && s.models.includes(sessionModelFilter));
    }

    // Search query
    if (sessionSearchQuery) {
        list = list.filter(s =>
            (s.title && s.title.toLowerCase().includes(sessionSearchQuery)) ||
            (s.workspace && s.workspace.toLowerCase().includes(sessionSearchQuery)) ||
            (s.primary_model && s.primary_model.toLowerCase().includes(sessionSearchQuery)) ||
            (Array.isArray(s.models) && s.models.some(m => m.toLowerCase().includes(sessionSearchQuery))) ||
            (s.last_msg && s.last_msg.toLowerCase().includes(sessionSearchQuery)) ||
            (s.created_day && s.created_day.includes(sessionSearchQuery)) ||
            (s.id && s.id.toLowerCase().includes(sessionSearchQuery))
        );
    }

    // Sorting
    if (sessionSortBy === 'tokens') {
        list.sort((a, b) => (b.total_tokens || 0) - (a.total_tokens || 0));
    } else if (sessionSortBy === 'context') {
        list.sort((a, b) => (b.context_tokens || 0) - (a.context_tokens || 0));
    }

    renderDateFilterBar(list.length);

    const countEl = document.getElementById('sessions-total-count');
    if (countEl) {
        const totalAll = cachedSessions.total_count || cachedSessions.sessions.length;
        countEl.innerText = (list.length === totalAll) ? `${totalAll}` : `${list.length} / ${totalAll}`;
    }

    if (list.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--muted); padding: 36px;">暂无匹配会话</div>`;
        if (pager) pager.innerHTML = '';
        return;
    }

    const visibleList = list.slice(0, sessionVisibleLimit);
    let html = '';
    visibleList.forEach(s => {
        const currentBadge = s.current ? `<span class="lc-ov-current">当前</span>` : '';
        const runningDot = s.running ? `<span class="lc-ov-running"></span>` : '';
        const currentClass = s.current ? ' lc-ov-session-current' : '';
        const safeId = escHtml(s.id);
        const safeTitle = escHtml(s.title);
        const safeWs = escHtml(s.workspace);
        const safeLast = escHtml(s.last_msg);

        const r = 24;
        const c = 2 * Math.PI * r;
        const hasBill = s.has_billing_tokens !== false;
        const ctxVal = s.context_tokens || 0;
        const ctxFmt = hasBill
            ? formatTokens(ctxVal)
            : (ctxVal > 0 ? ('~' + formatTokens(ctxVal)) : `${s.steps || 0}步`);
        const totFmt = hasBill
            ? formatTokens(s.total_tokens || 0)
            : ((s.est_tokens || 0) > 0 ? ('~' + formatTokens(s.est_tokens)) : '无Token记录');
        const pct = hasBill ? Math.min(Math.max(s.occupancy_pct || 1, 1), 100) : Math.min(Math.max(s.occupancy_pct || 8, 5), 100);
        const strokeDash = (pct / 100) * c;
        const color = !hasBill ? '#94a3b8' : (pct > 75 ? '#ef4444' : (pct > 40 ? '#f59e0b' : '#3b82f6'));
        const donutSub = hasBill ? `${s.occupancy_pct}%` : '旧版估算';
        const costTxt = (s.cost_cny && s.cost_cny !== '--') ? `¥${escHtml(s.cost_cny)}` : '旧版无计价';

        const modelPill = s.primary_model
            ? `<span class="lc-ov-model-tag" title="主用模型: ${escHtml(s.primary_model)}">🤖 ${escHtml(s.primary_model)}</span>`
            : '';

        html += `
            <div class="lc-ov-session${currentClass}" onclick="openSessionDetail('${safeId}')">
                <div class="lc-ov-session-head">
                    ${runningDot}
                    <span class="lc-ov-session-title" title="${safeTitle}">${safeTitle}</span>
                    ${currentBadge}
                    <div class="lc-ov-session-times">
                        <span class="lc-ov-session-time">${escHtml(s.relative_time)}</span>
                        <span class="lc-ov-session-created">${escHtml(s.created_day)}</span>
                    </div>
                </div>

                <div class="lc-ov-session-crumb" style="display: flex; justify-content: space-between; align-items: center; gap: 6px; flex-wrap: wrap;">
                    <div style="display: flex; align-items: center; gap: 6px; min-width: 0; flex-wrap: wrap;">
                        <span class="lc-ov-crumb-project" title="工作区: ${safeWs}">📁 ${safeWs}</span>
                        ${modelPill}
                    </div>
                    <button type="button" class="btn-icon" style="font-size: 10.5px; padding: 2px 7px; min-height: 22px; color: var(--primary);" onclick="event.stopPropagation(); openContextDrawer('${safeId}')" title="上下文演进走势与瘦身透视">📈 上下文透视</button>
                </div>

                <div class="lc-ov-session-body">
                    <div class="lc-ov-donut-wrap">
                        <svg class="lc-ov-donut-svg" viewBox="0 0 60 60">
                            <circle cx="30" cy="30" r="${r}" fill="none" stroke="rgba(0,0,0,0.06)" stroke-width="6" />
                            <circle cx="30" cy="30" r="${r}" fill="none" stroke="${color}" stroke-width="6" stroke-dasharray="${strokeDash} ${c}" stroke-linecap="round" />
                        </svg>
                        <div class="lc-ov-donut-center">
                            <span class="lc-ov-donut-tokens">${escHtml(ctxFmt)}</span>
                            <span class="lc-ov-donut-pct">${donutSub}</span>
                        </div>
                    </div>

                    <div class="lc-ov-mini-stats">
                        <div class="lc-ov-mini-stat">
                            <span class="lc-ov-mini-label">轮次</span>
                            <span class="lc-ov-mini-value">${s.turns} 轮 ${s.steps} 步</span>
                        </div>
                        <div class="lc-ov-mini-stat">
                            <span class="lc-ov-mini-label">${hasBill ? 'Token 总用量' : '文本估算量'}</span>
                            <span class="lc-ov-mini-value">${escHtml(totFmt)}</span>
                        </div>
                        <div class="lc-ov-mini-stat">
                            <span class="lc-ov-mini-label">总预估费用</span>
                            <span class="lc-ov-mini-value">${costTxt}</span>
                        </div>
                    </div>
                </div>

                <div class="lc-ov-session-preview">
                    <span class="lc-ov-session-preview-label">最后消息</span>
                    <span class="lc-ov-session-preview-text" title="${safeLast}">${safeLast}</span>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;

    if (pager) {
        if (list.length > visibleList.length) {
            const remain = list.length - visibleList.length;
            pager.innerHTML = `
                <div class="lc-ov-pagination">
                    <span>已显示 <b>${visibleList.length}</b> / ${list.length} 个会话</span>
                    <button type="button" class="btn-icon" onclick="showMoreSessions(60)">加载更多 (+${Math.min(60, remain)})</button>
                    <button type="button" class="btn-icon" onclick="showAllSessionsNow(${list.length})">展开全部 ${list.length} 个</button>
                </div>
            `;
        } else {
            pager.innerHTML = `<div class="lc-ov-pagination"><span>已显示全部 ${list.length} 个匹配会话</span></div>`;
        }
    }
}

function renderWorkspaceChips(chips) {
    const container = document.getElementById('sessions-workspace-chips');
    if (!chips || chips.length === 0) return;
    let html = '';
    chips.forEach(c => {
        const active = (c.key === sessionWorkspaceFilter) ? ' active' : '';
        html += `
            <button type="button" class="lc-ov-chip${active}" id="ws-chip-${encodeURIComponent(c.key)}" data-ws="${escHtml(c.key)}" onclick="filterSessionByWorkspace(this.getAttribute('data-ws'))">
                ${escHtml(c.name)} <span class="lc-ov-chip-n">${c.count}</span>
            </button>
        `;
    });
    container.innerHTML = html;
}

async function openSessionDetail(cid, targetStep = null) {
    switchMainTab('task');
    const exists = cachedTaskData && cachedTaskData.all_tasks && cachedTaskData.all_tasks.some(x => x.conversation_id === cid);
    if (!exists) {
        try {
            const res = await fetch(`/api/multi_task?range=${encodeURIComponent(currentTimeRange)}&task_id=${encodeURIComponent(cid)}`, { cache: 'no-store' });
            if (res.ok) {
                const report = await res.json();
                cachedTaskData = report;
                renderAllTaskViews(report);
            }
        } catch (err) {}
    }
    if (targetStep !== null && targetStep !== undefined) {
        selectTask(cid, true, true);
        await loadTaskStepsWindow(cid, Number(targetStep), '');
    } else {
        selectTask(cid, true, false);
    }
}
