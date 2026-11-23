// ================= TAB 2: MULTI-TASK MONITOR RENDERING =================
function setTaskFilter(f) {
    currentFilter = f;
    document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
    const target = document.getElementById('chip-' + f);
    if (target) target.classList.add('active');
    if (cachedTaskData) renderAllTaskViews(cachedTaskData);
}

function setViewMode(mode) {
    currentViewMode = mode;
    document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('vbtn-' + mode).classList.add('active');
    document.getElementById('view-focus').style.display = (mode === 'focus') ? 'grid' : 'none';
    document.getElementById('view-grid').style.display = (mode === 'grid') ? 'block' : 'none';
    document.getElementById('view-matrix').style.display = (mode === 'matrix') ? 'block' : 'none';
    if (cachedTaskData) renderAllTaskViews(cachedTaskData);
}

let expandedStepKeys = new Set();

function toggleNarrowQueue() {
    const panel = document.getElementById('task-queue-panel');
    const arrow = document.getElementById('queue-toggle-arrow');
    if (!panel) return;
    const collapsed = panel.classList.toggle('collapsed');
    if (arrow) arrow.innerText = collapsed ? '▸' : '▾';
}

function renderGlobalLiveBanner(report) {
    const banner = document.getElementById('global-live-banner');
    if (!banner) return;
    const tasks = (report && report.all_tasks) ? report.all_tasks : [];
    const stuck = tasks.find(t => t.health === 'STUCK');
    const waiting = tasks.find(t => t.health === 'WAITING_INPUT');
    const runningList = tasks.filter(t => t.is_running);
    const focus = stuck || waiting || (runningList.length > 0 ? runningList[0] : null);

    if (!focus) {
        banner.style.display = 'none';
        banner.className = 'live-alert-banner';
        banner.innerHTML = '';
        return;
    }

    let cls = 'live-banner-running';
    let label = i18n('task.banner_running');
    if (focus.health === 'STUCK') {
        cls = 'live-banner-danger';
        label = i18n('task.banner_stalled');
    } else if (focus.health === 'WAITING_INPUT') {
        cls = 'live-banner-warning';
        label = i18n('task.banner_waiting');
    } else if (focus.swarm && focus.swarm.is_swarm) {
        label = i18n('task.banner_swarm');
    }

    const extra = runningList.length > 1 ? i18n('task.banner_parallel', { count: runningList.length }) : '';
    const safeCid = escHtml(focus.conversation_id);
    banner.style.display = 'flex';
    banner.className = 'live-alert-banner ' + cls;
    banner.innerHTML = `
        <div style="display:flex;align-items:center;gap:10px;min-width:0;flex:1 1 auto;flex-wrap:wrap;">
            <span class="badge badge-${escHtml(focus.alert_level || 'info')}">${label}</span>
            <b style="color:var(--text);">${escHtml(focus.title)}</b>
            <span style="font-size:11px;color:var(--muted);">${i18n('task.banner_meta', { ws: escHtml(focus.workspace), action: escHtml(focus.current_action || '-'), beat: escHtml(focus.inactivity_formatted), extra: escHtml(extra) })}</span>
        </div>
        <button type="button" class="btn-icon" style="color:var(--primary);border-color:var(--primary);font-weight:600;flex-shrink:0;" onclick="openSessionDetail('${safeCid}')">${escHtml(i18n('task.banner_btn'))}</button>
    `;
}

function onTaskSearchInput(val) {
    taskSearchQuery = (val || '').trim().toLowerCase();
    if (cachedTaskData) renderAllTaskViews(cachedTaskData);
}

function onAutoFollowChange() {
    autoFollow = document.getElementById('auto-follow-chk').checked;
}

function selectTask(cid, fromUserClick=false, skipAutoWindow=false) {
    const changedTask = (selectedTaskId !== cid);
    selectedTaskId = cid;
    if (changedTask || fromUserClick) {
        inspActiveTargetCid = null;
        inspActiveSubagentName = '';
        inspWindowData = null;
        if (!skipAutoWindow) inspHighlightStep = null;
        expandedStepKeys = new Set();
    }
    if (fromUserClick) {
        autoFollow = false;
        document.getElementById('auto-follow-chk').checked = false;
    }
    if (cachedTaskData) {
        const t = cachedTaskData.all_tasks.find(x => x.conversation_id === cid);
        if (t) {
            renderFocusedInspector(t);
            if (!skipAutoWindow && (!t.recent_steps || t.recent_steps.length === 0) && (t.step_count || 0) > 0) {
                loadTaskStepsWindow(cid, null, '');
            }
        }
        highlightSelectedQueueItem(cid);
    }
    if (fromUserClick && window.innerWidth <= 860) {
        const inspEl = document.getElementById('inspector-panel');
        if (inspEl) inspEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function highlightSelectedQueueItem(cid) {
    document.querySelectorAll('.queue-item').forEach(el => {
        if (el.getAttribute('data-cid') === cid) el.classList.add('active');
        else el.classList.remove('active');
    });
}

function filterTasks(tasks) {
    if (!tasks) return [];
    let list = tasks;
    if (currentFilter === 'running') list = list.filter(t => t.is_running);
    else if (currentFilter === 'waiting') list = list.filter(t => t.health === 'WAITING_INPUT');
    else if (currentFilter === 'idle') list = list.filter(t => !t.is_running && t.health !== 'WAITING_INPUT');

    if (taskSearchQuery) {
        list = list.filter(t => 
            (t.title && t.title.toLowerCase().includes(taskSearchQuery)) ||
            (t.workspace && t.workspace.toLowerCase().includes(taskSearchQuery)) ||
            (t.current_action && t.current_action.toLowerCase().includes(taskSearchQuery))
        );
    }
    return list;
}

function renderAllTaskViews(report) {
    if (!report) return;
    cachedTaskData = report;
    renderGlobalLiveBanner(report);

    const sum = report.summary || {};
    document.getElementById('cnt-all').innerText = sum.total_count || report.all_tasks.length;
    document.getElementById('cnt-running').innerText = sum.running_count || 0;
    document.getElementById('cnt-waiting').innerText = sum.waiting_count || 0;
    document.getElementById('cnt-idle').innerText = sum.idle_count || 0;

    const badge = document.getElementById('nav-running-badge');
    badge.innerText = i18n('nav.running_badge', { count: sum.running_count || 0 });
    badge.className = (sum.running_count > 0) ? 'badge badge-success' : 'badge badge-info';

    const autoFocusCid = report.focused_cid || (report.focused_task && report.focused_task.conversation_id) || null;
    if (autoFollow || !selectedTaskId) {
        if (autoFocusCid) {
            selectedTaskId = autoFocusCid;
        } else if (report.all_tasks.length > 0) {
            selectedTaskId = report.all_tasks[0].conversation_id;
        }
    }

    if (activeTabName !== 'task') return;

    if (currentViewMode === 'focus') {
        renderTaskQueue(report.all_tasks);
        const cur = report.all_tasks.find(t => t.conversation_id === selectedTaskId) || report.all_tasks[0];
        if (cur) renderFocusedInspector(cur);
    } else if (currentViewMode === 'grid') {
        renderConcurrentGrid(report.all_tasks);
    } else if (currentViewMode === 'matrix') {
        renderConcurrentMatrix(report.all_tasks);
    }
}

function renderTaskQueue(allTasks) {
    const container = document.getElementById('task-queue-items');
    const filtered = filterTasks(allTasks);

    if (filtered.length === 0) {
        container.innerHTML = `<div style="text-align: center; color: var(--muted); padding: 24px;">${escHtml(i18n('task.queue_empty'))}</div>`;
        return;
    }

    let html = '';
    filtered.forEach(t => {
        const isSelected = (t.conversation_id === selectedTaskId);
        const activeClass = isSelected ? ' active' : '';
        const pulse = t.is_running ? `<span class="pulse-dot" style="width: 7px; height: 7px;"></span> ` : '';
        const safeTitle = escHtml(t.title);
        const safeAction = escHtml(t.current_action);
        html += `
            <div class="queue-item${activeClass}" data-cid="${escHtml(t.conversation_id)}" onclick="selectTask('${escHtml(t.conversation_id)}', true)">
                <div class="queue-top">
                    <span class="queue-ws">📁 ${escHtml(t.workspace)}</span>
                    <span class="badge badge-${escHtml(t.alert_level)}">${escHtml(t.health)}</span>
                </div>
                <div class="queue-title" title="${safeTitle}">${safeTitle}</div>
                <div class="queue-action" title="${safeAction}">${pulse}${safeAction}</div>
                <div class="queue-meta">
                    <span>${i18n('task.steps_inline', { steps: escHtml(t.step_count) })}</span>
                    <span>${escHtml(i18n('task.ago', { time: t.inactivity_formatted }))}</span>
                    <span>${formatMemberSummary(t)}</span>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

async function loadTaskStepsWindow(cid, targetStep=null, subagentName='') {
    inspActiveTargetCid = cid;
    inspActiveSubagentName = subagentName || '';
    inspHighlightStep = (targetStep !== null && targetStep !== undefined && !isNaN(targetStep)) ? Number(targetStep) : null;
    expandedStepKeys = new Set();
    try {
        let url = `/api/task_steps?cid=${encodeURIComponent(cid)}&limit=30&lang=${encodeURIComponent(currentLang)}`;
        if (inspHighlightStep !== null) url += `&step=${encodeURIComponent(inspHighlightStep)}`;
        const res = await fetch(url, { cache: 'no-store' });
        if (res.ok) {
            inspWindowData = await res.json();
            if (cachedTaskData && cachedTaskData.all_tasks) {
                const cur = cachedTaskData.all_tasks.find(x => x.conversation_id === selectedTaskId);
                if (cur) renderFocusedInspector(cur);
            }
            if (inspHighlightStep !== null) {
                setTimeout(() => {
                    const row = document.getElementById('step-row-' + inspHighlightStep);
                    if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 50);
            }
        }
    } catch (err) {}
}

function inspectSubagentSteps(subCid, subName) {
    if (!subCid) return;
    loadTaskStepsWindow(subCid, null, subName || 'Subagent');
}

function resetInspStepsView() {
    inspActiveTargetCid = null;
    inspActiveSubagentName = '';
    inspWindowData = null;
    inspHighlightStep = null;
    expandedStepKeys = new Set();
    if (cachedTaskData && cachedTaskData.all_tasks) {
        const cur = cachedTaskData.all_tasks.find(x => x.conversation_id === selectedTaskId);
        if (cur) renderFocusedInspector(cur);
    }
}

function toggleStepDetail(rowIdx, stepKey) {
    const detailRow = document.getElementById('step-detail-' + rowIdx);
    if (!detailRow) return;
    const open = (detailRow.style.display === 'none' || !detailRow.style.display);
    detailRow.style.display = open ? 'table-row' : 'none';
    if (stepKey) {
        if (open) expandedStepKeys.add(stepKey);
        else expandedStepKeys.delete(stepKey);
    }
}

function renderSubagentNodes(subagents, depth=0) {
    let sHtml = '';
    (subagents || []).forEach(s => {
        const det = s.details || {};
        const meta = det.swarm_member || {};
        const name = s.agent_name || meta.name || det.title || 'Subagent';
        const roleTag = meta.model ? `<span style="color: var(--muted); font-size: 10.5px; margin-left: 6px;"><code>${escHtml(meta.model)}</code></span>` : '';
        const beatText = det.inactivity_formatted ? i18n('task.heartbeat_inline', { time: det.inactivity_formatted }) : '';
        const isActive = (inspActiveTargetCid && inspActiveTargetCid === s.conversation_id) ? ' active-sub' : '';
        const indentPx = depth * 16;
        const safeCid = escHtml(s.conversation_id);
        const safeName = escHtml(name);
        sHtml += `
            <div class="tree-node${isActive}" style="margin-left: ${indentPx}px;" data-subcid="${safeCid}" data-subname="${safeName}" onclick="inspectSubagentSteps(this.getAttribute('data-subcid'), this.getAttribute('data-subname'))" title="${escHtml(i18n('task.subagent_inspect_title'))}">
                <div style="min-width: 0; flex: 1; padding-right: 10px;">
                    <div>
                        <span style="font-weight: 700; color: var(--primary);">${depth > 0 ? '↳ ' : ''}${safeName}</span>
                        <span style="color: var(--muted); font-size: 11px; margin-left: 6px;">${escHtml(i18n('task.subagent_meta', { steps: det.step_count || s.step_count, beat: beatText }))}</span>
                        ${roleTag}
                    </div>
                    <div style="font-size: 11px; margin-top: 2px; word-break: break-word;">${escHtml(i18n('task.subagent_action'))}<code>${escHtml(det.current_action || '-')}</code></div>
                </div>
                <span class="badge badge-${escHtml(det.alert_level || 'info')}" style="flex-shrink: 0;">${escHtml(det.health || 'IDLE')}</span>
            </div>
        `;
        if (s.children && s.children.length > 0) {
            sHtml += renderSubagentNodes(s.children, depth + 1);
        }
    });
    return sHtml;
}

function renderFocusedInspector(t) {
    const winActive = Boolean(inspWindowData && (inspActiveTargetCid === t.conversation_id || inspActiveTargetCid));
    const isViewingSub = Boolean(winActive && inspWindowData.conversation_id !== t.conversation_id);
    const activeNode = (isViewingSub && inspWindowData.node) ? inspWindowData.node : t;

    document.getElementById('insp-title').innerText = t.title || i18n('task.untitled');
    document.getElementById('insp-ws').innerText = t.workspace;
    document.getElementById('insp-cid').innerText = t.conversation_id;

    const badge = document.getElementById('insp-health-badge');
    badge.innerText = activeNode.health;
    badge.className = 'badge badge-' + (activeNode.alert_level || 'info');
    document.getElementById('insp-heartbeat').innerText = i18n('task.heartbeat_status', { health: activeNode.health_desc || i18n('task.health_ok'), inactivity: activeNode.inactivity_formatted });

    const inflightBox = document.getElementById('insp-inflight-box');
    if (activeNode.is_running) {
        inflightBox.style.display = 'block';
        document.getElementById('insp-inflight-label').innerText = isViewingSub
            ? i18n('task.subagent_action_label', { name: inspActiveSubagentName })
            : ((t.swarm && t.swarm.is_swarm) ? i18n('task.swarm_action_label') : i18n('task.default_action_label'));
        document.getElementById('insp-inflight-cmd').innerText = activeNode.current_action;
    } else {
        inflightBox.style.display = 'block';
        document.getElementById('insp-inflight-label').innerText = isViewingSub ? i18n('task.subagent_last_label', { name: inspActiveSubagentName }) : i18n('task.last_action_label');
        document.getElementById('insp-inflight-cmd').innerText = activeNode.current_action || i18n('task.idle_ready');
    }

    const thinkBox = document.getElementById('insp-thinking-box');
    if (activeNode.current_thinking) {
        thinkBox.style.display = 'block';
        document.getElementById('insp-thinking-text').innerText = activeNode.current_thinking;
    } else {
        thinkBox.style.display = 'none';
    }

    const swarmBox = document.getElementById('insp-swarm-board-box');
    if (t.swarm && t.swarm.is_swarm) {
        swarmBox.style.display = 'block';
        const swTitle = t.swarm.swarm_title ? i18n('task.swarm_board_named', { title: t.swarm.swarm_title }) : i18n('task.swarm_board_title');
        document.getElementById('insp-swarm-title').innerText = swTitle;
        document.getElementById('insp-swarm-summary').innerText = i18n('task.swarm_summary', { active: t.swarm.active_workers, waiting: t.swarm.waiting_workers, killed: t.swarm.killed_workers, board: t.swarm.board_count || 0 });
        const postsEl = document.getElementById('insp-swarm-posts');
        const posts = t.swarm.latest_board_posts || [];
        if (posts.length === 0) {
            postsEl.innerHTML = `<div style="font-size: 11px; color: var(--muted); padding-top: 4px;">${escHtml(i18n('task.swarm_empty'))}</div>`;
        } else {
            postsEl.innerHTML = posts.slice(0, 4).map(p => `
                <div class="swarm-post-item">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                        <span><b style="color: var(--primary);">@${escHtml(p.agent)}</b> <span style="color: var(--muted); font-family: monospace;">#${p.seq ?? '-'}</span></span>
                        <span style="color: var(--muted); font-size: 10.5px;">${escHtml(p.time || '')}</span>
                    </div>
                    <div style="color: var(--text); word-break: break-word;">${escHtml(p.text_preview || '')}</div>
                </div>
            `).join('');
        }
    } else {
        swarmBox.style.display = 'none';
    }

    const subTree = document.getElementById('insp-subagents-tree');
    document.getElementById('insp-subagents-count').innerText = i18n('task.subagent_count', { count: t.subagents_count || 0 });
    if (!t.subagents || t.subagents.length === 0) {
        subTree.innerHTML = `<div style="color: var(--muted); font-size: 11.5px; padding: 4px 0;">${escHtml(i18n('task.subagent_empty'))}</div>`;
    } else {
        subTree.innerHTML = renderSubagentNodes(t.subagents, 0);
    }

    const subBanner = document.getElementById('insp-subagent-banner');
    if (subBanner) {
        if (isViewingSub) {
            subBanner.style.display = 'flex';
            subBanner.className = 'subagent-banner';
            subBanner.innerHTML = `
                <span>${i18n('task.subagent_viewing', { name: escHtml(inspActiveSubagentName || inspWindowData.conversation_id.slice(0, 8)), steps: inspWindowData.total_steps || 0 })}</span>
                <button type="button" class="btn-icon" style="padding:2px 8px;font-size:11px;min-height:24px;" onclick="resetInspStepsView()">${escHtml(i18n('task.subagent_back'))}</button>
            `;
        } else if (winActive && inspHighlightStep !== null) {
            subBanner.style.display = 'flex';
            subBanner.className = 'subagent-banner';
            subBanner.innerHTML = `
                <span>${i18n('task.step_window_viewing', { step: escHtml(inspHighlightStep) })}</span>
                <button type="button" class="btn-icon" style="padding:2px 8px;font-size:11px;min-height:24px;" onclick="resetInspStepsView()">${escHtml(i18n('task.step_window_back'))}</button>
            `;
        } else {
            subBanner.style.display = 'none';
            subBanner.innerHTML = '';
        }
    }

    const tbody = document.getElementById('insp-steps-tbody');
    const stepsToShow = (winActive && inspWindowData.steps) ? inspWindowData.steps : (t.recent_steps || []);
    document.getElementById('insp-steps-count').innerText = i18n('task.steps_count', { count: activeNode.step_count || 0 });
    if (!stepsToShow || stepsToShow.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--muted);">${escHtml(i18n('task.steps_empty'))}</td></tr>`;
    } else {
        let rows = '';
        stepsToShow.forEach((st, i) => {
            const idx = (st.step_index !== undefined && st.step_index !== null) ? st.step_index : i;
            const tm = st.created_at ? new Date(st.created_at).toLocaleTimeString() : "-";
            const hasErr = (st.exit_code !== null && st.exit_code !== undefined && st.exit_code !== 0) || st.type === "ERROR_MESSAGE";
            const isHl = (inspHighlightStep !== null && idx === inspHighlightStep);
            const stepKey = `${activeNode.conversation_id}:${idx}:${i}`;
            const isExpanded = expandedStepKeys.has(stepKey);

            let action = "";
            if (st.tool_name) {
                action = `<code>${escHtml(st.tool_name)}</code> <span style="color: var(--muted);">${escHtml(st.preview || st.tool_arg || '')}</span>`;
            } else if (st.is_swarm_wait) {
                action = `<span style="color: var(--primary); font-weight: 600;">${escHtml(i18n('task.step_swarm_wait'))}</span>`;
            } else if (st.exit_code !== null && st.exit_code !== undefined) {
                const codeBadge = (st.exit_code === 0)
                    ? `<span class="badge badge-success">${escHtml(i18n('task.step_exit_ok'))}</span>`
                    : `<span class="badge badge-danger">${escHtml(i18n('task.step_exit_err', { code: st.exit_code }))}</span>`;
                action = `${codeBadge} <span style="color: var(--muted);">${escHtml(st.preview || '')}</span>`;
            } else if (st.type === "GENERIC") {
                action = `<span style="color: var(--success); font-weight: 600;">${escHtml(i18n('task.step_tool_return'))}</span> <span style="color: var(--muted);">${escHtml(st.preview || '')}</span>`;
            } else if (st.type === "USER_INPUT") {
                action = `<span style="color: var(--warning); font-weight: 600;">${escHtml(i18n('task.step_user_input'))}</span> <span style="color: var(--muted);">${escHtml(st.preview || '')}</span>`;
            } else if (st.type === "ERROR_MESSAGE") {
                action = `<span class="badge badge-danger">${escHtml(i18n('task.step_error'))}</span> <span style="color: var(--danger);">${escHtml(st.preview || '')}</span>`;
            } else {
                action = `<span>${escHtml(st.preview || st.type || '')}</span>`;
            }

            const rowClasses = ['step-row'];
            if (hasErr) rowClasses.push('step-row-error');
            if (isHl) rowClasses.push('step-row-highlight');

            rows += `<tr id="step-row-${idx}" class="${rowClasses.join(' ')}" onclick="toggleStepDetail(${i}, '${escHtml(stepKey)}')"><td><b>${idx}</b></td><td>${escHtml(tm)}</td><td>${escHtml(st.type)}</td><td>${action}</td></tr>`;
            rows += `<tr id="step-detail-${i}" style="display: ${isExpanded ? 'table-row' : 'none'};"><td colspan="4"><pre class="step-detail-pre">${escHtml(st.detail || st.preview || i18n('task.step_no_detail'))}</pre></td></tr>`;
        });
        tbody.innerHTML = rows;
    }
}

function renderConcurrentGrid(allTasks) {
    const container = document.getElementById('grid-cards-container');
    const filtered = filterTasks(allTasks);

    if (filtered.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--muted); padding: 32px;">${escHtml(i18n('task.queue_empty'))}</div>`;
        return;
    }

    let html = '';
    filtered.forEach(t => {
        const isRun = t.is_running;
        const pulse = isRun ? `<span class="pulse-dot"></span> ` : '';
        html += `
            <div class="grid-task-card ${isRun ? 'active-run' : ''}">
                <div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <span class="queue-ws">📁 ${escHtml(t.workspace)}</span>
                        <span class="badge badge-${escHtml(t.alert_level)}">${escHtml(t.health)}</span>
                    </div>
                    <div style="font-size: 14px; font-weight: 700; margin-bottom: 6px; color: var(--text);">${escHtml(t.title)}</div>
                    <div style="background: rgba(0,0,0,0.03); padding: 6px 8px; border-radius: 6px; font-family: monospace; font-size: 11px; margin-bottom: 10px;">
                        ${pulse}${escHtml(t.current_action)}
                    </div>
                    ${t.current_thinking ? `<div style="font-size: 11.5px; color: var(--muted); font-style: italic; margin-bottom: 10px; line-height: 1.4;">💭 ${escHtml(t.current_thinking.slice(0, 100))}...</div>` : ''}
                </div>
                <div style="border-top: 1px solid var(--border); padding-top: 10px; margin-top: 8px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 11px; color: var(--muted);">${i18n('task.grid_meta', { steps: escHtml(t.step_count), beat: escHtml(t.inactivity_formatted), members: escHtml(formatMemberSummary(t)) })}</span>
                    <button class="btn-icon" onclick="selectTask('${escHtml(t.conversation_id)}', true); setViewMode('focus');">${escHtml(i18n('task.grid_focus_btn'))}</button>
                </div>
            </div>
        `;
    });
    container.innerHTML = html;
}

function renderConcurrentMatrix(allTasks) {
    const tbody = document.getElementById('matrix-tbody');
    const filtered = filterTasks(allTasks);

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--muted); padding: 24px;">${escHtml(i18n('task.queue_empty'))}</td></tr>`;
        return;
    }

    let rows = '';
    filtered.forEach(t => {
        rows += `
            <tr>
                <td><b>${escHtml(t.title)}</b> <span style="font-size: 10px; color: var(--muted); font-family: monospace;">(${escHtml(t.conversation_id.slice(0, 8))})</span></td>
                <td><code>${escHtml(t.workspace)}</code></td>
                <td><span class="badge badge-${escHtml(t.alert_level)}">${escHtml(t.health)}</span></td>
                <td>${i18n('task.matrix_steps', { steps: escHtml(t.step_count) })}</td>
                <td>${escHtml(i18n('task.ago', { time: t.inactivity_formatted }))}</td>
                <td><code>${escHtml(t.current_action)}</code></td>
                <td>${formatMemberSummary(t)}</td>
                <td><button class="btn-icon" style="padding: 2px 8px;" onclick="selectTask('${escHtml(t.conversation_id)}', true); setViewMode('focus');">${escHtml(i18n('task.matrix_focus_btn'))}</button></td>
            </tr>
        `;
    });
    tbody.innerHTML = rows;
}
