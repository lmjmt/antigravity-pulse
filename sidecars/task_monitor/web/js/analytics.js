// ================= ANALYTICS TAB RENDERING =================
function renderAnalytics(data) {
    if (!data) return;
    cachedAnalytics = data;
    const kpi = data.kpi;
    const sessLabelEl = document.getElementById('kpi-sessions-label');
    if (sessLabelEl && kpi.session_label) sessLabelEl.innerText = kpi.session_label;
    document.getElementById('kpi-sessions').innerText = kpi.total_sessions;
    document.getElementById('kpi-sessions-sub').innerText = `其中已归档 ${kpi.archived_sessions} 个`;
    document.getElementById('kpi-tokens').innerText = kpi.total_tokens_formatted;
    document.getElementById('kpi-turns-sub').innerText = `轮次 ${kpi.total_turns}`;
    document.getElementById('kpi-cost').innerText = `¥${kpi.estimated_cost}`;
    document.getElementById('kpi-cost-sub').innerText = `已计价 ${kpi.priced_sessions} 个会话`;
    document.getElementById('kpi-cache').innerText = `${kpi.cache_hit_rate}%`;
    document.getElementById('kpi-cache-sub').innerText = `含 ${kpi.cache_sessions} 个会话`;
    document.getElementById('kpi-tools').innerText = kpi.tool_calls_formatted;
    document.getElementById('kpi-tools-sub').innerText = `工具执行 ${kpi.tool_exec_duration}`;
    document.getElementById('kpi-duration').innerText = kpi.active_duration;
    document.getElementById('kpi-duration-sub').innerText = `模型调用 ${kpi.model_calls}`;

    document.getElementById('output-speed-val').innerText = `输出速度 ${kpi.output_speed} tok/s`;
    document.getElementById('donut-token-center-val').innerText = kpi.total_tokens_formatted;
    document.getElementById('donut-duration-center-val').innerText = kpi.active_duration;

    renderUsageChart(data.usage_chart || { title: '近 7 天用量', points: data.last_7_days || [] });
    renderDonutSvg('donut-token-svg', data.token_breakdown);
    renderLegendGrid('token-legend-grid', data.token_breakdown, 'token');

    renderDonutSvg('donut-duration-svg', data.duration_breakdown);
    renderLegendGrid('duration-legend-grid', data.duration_breakdown, 'duration');

    renderModelUsage(data.model_usage);

    const hmLbl = document.getElementById('heatmap-months-label');
    if (hmLbl && data.heatmap_months_label) hmLbl.innerText = data.heatmap_months_label;
    renderHeatmap(data.heatmap);
    renderRankings('skills-list', data.top_skills, 'skills-header-count', `${data.top_skills.length} 个技能 · 加载汇总`);
    renderRankings('tools-list', data.top_tools, 'tools-header-count', `${data.top_tools.length} 个工具 · ${kpi.tool_calls_formatted} 次调用`);
    renderRankings('commands-list', data.top_commands, 'commands-header-count', `${data.top_commands.length} 个程序 · 执行汇总`);
}

function setUsageChartMode(mode) {
    usageChartMode = (mode === 'activity') ? 'activity' : 'tokens';
    const btnTok = document.getElementById('chart-mode-tokens');
    const btnAct = document.getElementById('chart-mode-activity');
    if (btnTok) btnTok.classList.toggle('active', usageChartMode === 'tokens');
    if (btnAct) btnAct.classList.toggle('active', usageChartMode === 'activity');
    if (cachedAnalytics) {
        renderUsageChart(cachedAnalytics.usage_chart || { title: '近 7 天用量', points: cachedAnalytics.last_7_days || [] });
    }
}

function setHeatmapMode(mode) {
    heatmapMode = (mode === 'sessions') ? 'sessions' : 'tokens';
    const btnSess = document.getElementById('hm-mode-sessions');
    const btnTok = document.getElementById('hm-mode-tokens');
    if (btnSess) btnSess.classList.toggle('active', heatmapMode === 'sessions');
    if (btnTok) btnTok.classList.toggle('active', heatmapMode === 'tokens');
    if (cachedAnalytics) {
        renderHeatmap(cachedAnalytics.heatmap);
    }
}

function renderUsageChart(chartObj) {
    const container = document.getElementById('chart-7days-container');
    const titleEl = document.getElementById('usage-chart-title');
    if (titleEl && chartObj && chartObj.title) {
        const suffix = (usageChartMode === 'activity') ? ' · 会话/步数' : '';
        titleEl.innerHTML = `<span>📊</span> ${escHtml(chartObj.title + suffix)}`;
    }
    const days = (chartObj && chartObj.points) ? chartObj.points : [];
    if (!days || days.length === 0) {
        container.innerHTML = `<div style="text-align:center;color:var(--muted);padding:36px;">暂无用量记录</div>`;
        return;
    }

    const isAct = (usageChartMode === 'activity');
    const maxLeft = isAct
        ? Math.max(...days.map(d => d.sessions || 0), 1)
        : Math.max(...days.map(d => d.tokens || 0), 1e5);
    const maxRight = isAct
        ? Math.max(...days.map(d => d.steps || 0), 10)
        : Math.max(...days.map(d => d.cost || 0), 0.1);
    const maxStepsRef = Math.max(...days.map(d => d.steps || 0), 1);

    const width = 480, height = 132, leftPad = 36, rightPad = 444, chartHeight = 84;
    const slotW = (rightPad - leftPad) / days.length;
    const barW = Math.max(Math.min(slotW * 0.34, 14), 2.2);
    const innerGap = days.length <= 12 ? 2 : 1;
    const tickStep = days.length <= 10 ? 1 : Math.ceil(days.length / 7);

    let barsHtml = '';
    days.forEach((d, idx) => {
        const cx = leftPad + (idx + 0.5) * slotW;
        const xLeft = cx - barW - innerGap / 2;
        const xRight = cx + innerGap / 2;
        const vLeft = isAct ? (d.sessions || 0) : (d.tokens || 0);
        const vRight = isAct ? (d.steps || 0) : (d.cost || 0);
        const hLeft = vLeft > 0 ? Math.max((vLeft / maxLeft) * chartHeight, 2) : 0;
        const hRight = vRight > 0 ? Math.max((vRight / maxRight) * chartHeight, 2) : 0;
        const yLeft = chartHeight - hLeft + 16;
        const yRight = chartHeight - hRight + 16;
        const showVal = days.length <= 10 && vLeft > 0;
        const showTick = (idx % tickStep === 0) || (idx === days.length - 1 && days.length <= 10);

        barsHtml += `<g>`;
        if (isAct) {
            barsHtml += `<title>${escHtml(d.full_date || d.date)}&#10;活跃会话: ${d.sessions || 0} 个&#10;交互步数: ${d.steps || 0} 步</title>`;
            if (showVal) {
                barsHtml += `<text x="${cx}" y="${yLeft - 3}" font-size="8.5" fill="var(--muted)" text-anchor="middle">${d.sessions || 0}</text>`;
            }
            if (hLeft > 0) {
                barsHtml += `<rect x="${xLeft.toFixed(1)}" y="${yLeft.toFixed(1)}" width="${barW.toFixed(1)}" height="${hLeft.toFixed(1)}" fill="#8b5cf6" rx="1.5" />`;
            }
            if (hRight > 0) {
                barsHtml += `<rect x="${xRight.toFixed(1)}" y="${yRight.toFixed(1)}" width="${barW.toFixed(1)}" height="${hRight.toFixed(1)}" fill="#06b6d4" rx="1.5" />`;
            }
        } else {
            const unbilledHint = (vLeft === 0 && (d.steps || 0) > 0)
                ? `Token: 未记录(旧版日志)&#10;活跃: ${d.sessions || 0} 会话 / ${escHtml(d.steps_formatted || d.steps || 0)} 步`
                : `Token: ${escHtml(d.tokens_formatted)}&#10;费用: ${escHtml(d.cost_formatted)}&#10;活跃: ${d.sessions || 0} 会话 / ${escHtml(d.steps_formatted || d.steps || 0)} 步`;
            barsHtml += `<title>${escHtml(d.full_date || d.date)}&#10;${unbilledHint}</title>`;
            if (showVal) {
                barsHtml += `<text x="${cx}" y="${yLeft - 3}" font-size="8.5" fill="var(--muted)" text-anchor="middle">${escHtml(d.tokens_formatted)}</text>`;
            }
            if (hLeft > 0) {
                barsHtml += `<rect x="${xLeft.toFixed(1)}" y="${yLeft.toFixed(1)}" width="${barW.toFixed(1)}" height="${hLeft.toFixed(1)}" fill="#3b82f6" rx="1.5" />`;
            } else if ((d.steps || 0) > 0 || (d.sessions || 0) > 0) {
                const hGhost = Math.max(((d.steps || 1) / maxStepsRef) * 26, 4);
                const yGhost = chartHeight - hGhost + 16;
                barsHtml += `<rect x="${(cx - barW).toFixed(1)}" y="${yGhost.toFixed(1)}" width="${(barW * 2).toFixed(1)}" height="${hGhost.toFixed(1)}" fill="#94a3b8" opacity="0.55" rx="1.5" />`;
            }
            if (hRight > 0) {
                barsHtml += `<rect x="${xRight.toFixed(1)}" y="${yRight.toFixed(1)}" width="${barW.toFixed(1)}" height="${hRight.toFixed(1)}" fill="#10b981" rx="1.5" />`;
            }
        }
        if (showTick) {
            barsHtml += `<text x="${cx.toFixed(1)}" y="${chartHeight + 30}" font-size="9.5" fill="var(--muted)" text-anchor="middle">${escHtml(d.date)}</text>`;
        }
        barsHtml += `</g>`;
    });

    const leftTop = isAct ? `${maxLeft}会` : formatTokens(maxLeft);
    const leftMid = isAct ? `${Math.round(maxLeft / 2)}` : formatTokens(Math.round(maxLeft / 2));
    const rightTop = isAct ? `${formatTokens(maxRight)}步` : `¥${maxRight.toFixed(1)}`;
    const rightMid = isAct ? `${formatTokens(Math.round(maxRight / 2))}` : `¥${(maxRight / 2).toFixed(1)}`;

    container.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" style="width: 100%; height: 100%;">
            <line x1="${leftPad - 4}" y1="16" x2="${rightPad + 4}" y2="16" stroke="var(--border)" stroke-dasharray="2 2" />
            <line x1="${leftPad - 4}" y1="58" x2="${rightPad + 4}" y2="58" stroke="var(--border)" stroke-dasharray="2 2" />
            <line x1="${leftPad - 4}" y1="${chartHeight + 16}" x2="${rightPad + 4}" y2="${chartHeight + 16}" stroke="var(--border)" />
            <text x="${leftPad - 7}" y="19" font-size="8" fill="var(--muted)" text-anchor="end">${leftTop}</text>
            <text x="${leftPad - 7}" y="61" font-size="8" fill="var(--muted)" text-anchor="end">${leftMid}</text>
            <text x="${leftPad - 7}" y="${chartHeight + 16}" font-size="8" fill="var(--muted)" text-anchor="end">0</text>
            <text x="${rightPad + 7}" y="19" font-size="8" fill="var(--muted)" text-anchor="start">${rightTop}</text>
            <text x="${rightPad + 7}" y="61" font-size="8" fill="var(--muted)" text-anchor="start">${rightMid}</text>
            <text x="${rightPad + 7}" y="${chartHeight + 16}" font-size="8" fill="var(--muted)" text-anchor="start">0</text>
            ${barsHtml}
        </svg>
    `;
}

function renderDonutSvg(svgId, items) {
    const svg = document.getElementById(svgId);
    const r = 40; const c = 2 * Math.PI * r; let offset = 0; let paths = '';
    items.forEach(it => {
        const strokeDash = (it.pct / 100) * c;
        const tipHtml = it.title ? `<title>${escHtml(it.title)}</title>` : '';
        paths += `<circle cx="50" cy="50" r="${r}" fill="none" stroke="${escHtml(it.color)}" stroke-width="12" stroke-dasharray="${strokeDash} ${c}" stroke-dashoffset="-${offset}">${tipHtml}</circle>`;
        offset += strokeDash;
    });
    svg.innerHTML = paths;
}

function renderLegendGrid(containerId, items, type) {
    const grid = document.getElementById(containerId);
    let html = '';
    items.forEach(it => {
        const sub = (type === 'token') ? it.formatted : it.desc;
        html += `
            <div class="legend-row">
                <div class="legend-left">
                    <div class="legend-dot" style="background: ${escHtml(it.color)};"></div>
                    <span class="legend-label">${escHtml(it.label)}</span>
                </div>
                <div class="legend-right">
                    <span class="legend-pct">${escHtml(it.pct)}%</span>
                    <span class="legend-val">${escHtml(sub)}</span>
                </div>
            </div>
        `;
    });
    grid.innerHTML = html;
}

function renderModelUsage(mu) {
    const listEl = document.getElementById('model-usage-list');
    const pillsEl = document.getElementById('model-family-pills');
    const subEl = document.getElementById('model-usage-sub');
    const tokValEl = document.getElementById('donut-model-tokens-val');
    const callsValEl = document.getElementById('donut-model-calls-val');
    const tokSvgEl = document.getElementById('donut-model-tokens-svg');
    const callsSvgEl = document.getElementById('donut-model-calls-svg');
    if (!listEl || !tokSvgEl || !callsSvgEl) return;

    function fmtModelPct(pct, rawVal) {
        if (!rawVal || rawVal <= 0) return '-';
        if (!pct || pct <= 0 || pct < 0.1) return '<0.1%';
        return `${Number(pct).toFixed(1)}%`;
    }

    if (!mu || !Array.isArray(mu.items) || mu.items.length === 0) {
        if (subEl) subEl.innerText = '当前时间范围内暂无模型调用';
        if (tokValEl) tokValEl.innerText = '0';
        if (callsValEl) callsValEl.innerText = '0';
        tokSvgEl.innerHTML = '';
        callsSvgEl.innerHTML = '';
        if (pillsEl) pillsEl.innerHTML = '';
        listEl.innerHTML = `<div style="color: var(--muted); font-size: 11.5px; padding: 24px 0; text-align: center;">暂无模型调用记录</div>`;
        return;
    }

    const totTokens = mu.total_tokens || 0;
    const totCalls = mu.total_calls || 0;
    if (subEl) {
        subEl.innerText = `${mu.range_label || ''} · ${mu.total_models} 类模型 · ${formatTokens(totTokens)} Tokens / ${formatTokens(totCalls)} 次调用`;
    }
    if (tokValEl) tokValEl.innerText = formatTokens(totTokens);
    if (callsValEl) callsValEl.innerText = formatTokens(totCalls);

    function buildDonutSlices(items, pctKey, titleBuilder) {
        const candidates = [...items]
            .sort((a, b) => (b[pctKey] || 0) - (a[pctKey] || 0))
            .map(it => ({ color: it.color, pct: it[pctKey] || 0, title: titleBuilder(it) }))
            .filter(it => it.pct > 0);
        if (candidates.length > 8) {
            const head = candidates.slice(0, 7);
            const tailPct = Math.max(0, 100 - head.reduce((acc, x) => acc + x.pct, 0));
            if (tailPct > 0.05) {
                head.push({ color: '#94a3b8', pct: tailPct, title: `其余模型合计: ${tailPct.toFixed(1)}%` });
            }
            return head;
        }
        return candidates;
    }

    const tokSlices = buildDonutSlices(
        mu.items,
        'tokens_pct',
        it => `${it.name}: ${it.tokens_formatted} (${fmtModelPct(it.tokens_pct, it.tokens)})`
    );
    if (tokSlices.length > 0) {
        renderDonutSvg('donut-model-tokens-svg', tokSlices);
    } else {
        tokSvgEl.innerHTML = `<circle cx="50" cy="50" r="40" fill="none" stroke="var(--border)" stroke-width="12"><title>当前时间范围无 Token 计费记录</title></circle>`;
    }

    const callSlices = buildDonutSlices(
        mu.items,
        'calls_pct',
        it => `${it.name}: ${it.calls_formatted} 次 (${fmtModelPct(it.calls_pct, it.calls)})`
    );
    if (callSlices.length > 0) {
        renderDonutSvg('donut-model-calls-svg', callSlices);
    } else {
        callsSvgEl.innerHTML = `<circle cx="50" cy="50" r="40" fill="none" stroke="var(--border)" stroke-width="12" />`;
    }

    // Render aligned Family Mini-Table
    if (pillsEl) {
        const fams = [...(mu.families || [])].sort((a, b) => (b.tokens - a.tokens) || (b.calls - a.calls));
        let famHtml = `
            <div class="model-family-head">
                <span>系列</span>
                <span>Token</span>
                <span>调用</span>
            </div>
        `;
        fams.forEach(f => {
            const tokShare = fmtModelPct(f.tokens_pct, f.tokens);
            const callShare = fmtModelPct(f.calls_pct, f.calls);
            famHtml += `
                <div class="model-family-row" title="${escHtml(f.family)}: ${escHtml(f.tokens_formatted)} Tokens (${escHtml(tokShare)}) · ${escHtml(f.calls)} 次调用 (${escHtml(callShare)})">
                    <span class="model-family-name">
                        <span class="legend-dot" style="background: ${escHtml(f.color)}; border-radius: 50%;"></span>
                        <span>${escHtml(f.family)}</span>
                    </span>
                    <span class="model-family-num">${escHtml(tokShare)}</span>
                    <span class="model-family-num">${escHtml(callShare)}</span>
                </div>
            `;
        });
        pillsEl.innerHTML = famHtml;
    }

    // Render Sortable 7-Column Data Table
    const getAvg = (it) => (it.has_tokens && (it.calls || 0) > 0) ? ((it.tokens || 0) / it.calls) : -1;
    const sortedItems = [...mu.items].sort((a, b) => {
        if (modelTableSort === 'calls') {
            return (b.calls - a.calls) || (b.tokens - a.tokens) || String(a.name).localeCompare(String(b.name));
        }
        if (modelTableSort === 'avg') {
            return (getAvg(b) - getAvg(a)) || (b.tokens - a.tokens) || (b.calls - a.calls);
        }
        if (modelTableSort === 'sessions') {
            return (b.sessions - a.sessions) || (b.tokens - a.tokens) || (b.calls - a.calls);
        }
        if (modelTableSort === 'cost') {
            return ((b.cost || 0) - (a.cost || 0)) || (b.tokens - a.tokens) || (b.calls - a.calls);
        }
        return (b.tokens - a.tokens) || (b.calls - a.calls) || String(a.name).localeCompare(String(b.name));
    });

    const maxTokens = Math.max(...sortedItems.map(it => it.tokens || 0), 1);
    const maxCalls = Math.max(...sortedItems.map(it => it.calls || 0), 1);
    const sortInd = (col) => (modelTableSort === col ? ' ▾' : '');
    const sortCls = (col) => (modelTableSort === col ? 'sortable active-sort' : 'sortable');

    let tbodyHtml = '';
    sortedItems.forEach(it => {
        const tokBarW = (it.tokens || 0) > 0 ? Math.max(((it.tokens || 0) / maxTokens) * 100, 3) : 0;
        const callBarW = (it.calls || 0) > 0 ? Math.max(((it.calls || 0) / maxCalls) * 100, 3) : 0;
        const rowClasses = [
            (sessionModelFilter && sessionModelFilter === it.name) ? 'active-filter' : '',
            it.is_unknown ? 'row-muted' : '',
        ].filter(Boolean).join(' ');

        const tagHtml = (!it.has_tokens)
            ? `<span class="model-rank-badge">无Token</span>`
            : (it.is_unknown ? `<span class="model-rank-badge">未埋点</span>` : '');

        const tokPctStr = fmtModelPct(it.tokens_pct, it.tokens);
        const callPctStr = fmtModelPct(it.calls_pct, it.calls);
        const tokCellHtml = it.has_tokens
            ? `
                <div class="model-metric-head">
                    <span class="model-metric-val">${escHtml(it.tokens_formatted)}</span>
                    <span class="model-metric-pct">${escHtml(tokPctStr)}</span>
                </div>
                <div class="model-cell-track"><div class="model-cell-bar" style="width: ${tokBarW.toFixed(1)}%; background: ${escHtml(it.color)};"></div></div>
            `
            : `<span style="color: var(--muted); font-size: 11px;">-</span>`;

        const tokCellTitle = it.has_tokens
            ? `输入 ${it.input_formatted} · 缓存读取 ${it.cache_formatted} · 输出 ${it.output_formatted}`
            : '旧版日志未记录 Token 计费字段';

        const avgTxt = it.has_tokens
            ? `${formatTokens(Math.round((it.tokens || 0) / Math.max(it.calls || 1, 1)))}/次`
            : '-';
        const cacheRate = Number(it.cache_hit_rate || 0);
        const cacheCls = !it.has_tokens
            ? 'model-cache-low'
            : (cacheRate >= 85 ? 'model-cache-high' : (cacheRate >= 50 ? 'model-cache-mid' : 'model-cache-low'));
        const cacheTxt = it.has_tokens ? `${cacheRate.toFixed(1)}%` : '-';
        const costTxt = it.has_tokens ? it.cost_formatted : '-';

        tbodyHtml += `
            <tr class="${rowClasses}" data-model="${escHtml(it.name)}" onclick="filterSessionByModel(this.dataset.model)">
                <td>
                    <div class="model-cell-name">
                        <span class="legend-dot" style="background: ${escHtml(it.color)}; border-radius: 50%;"></span>
                        <span class="model-cell-name-txt" title="${escHtml(it.name)}">${escHtml(it.name)}</span>
                        ${tagHtml}
                    </div>
                </td>
                <td class="model-metric-cell" title="${escHtml(tokCellTitle)}">${tokCellHtml}</td>
                <td class="model-metric-cell">
                    <div class="model-metric-head">
                        <span class="model-metric-val">${escHtml(it.calls_formatted)} 次</span>
                        <span class="model-metric-pct">${escHtml(callPctStr)}</span>
                    </div>
                    <div class="model-cell-track"><div class="model-cell-bar" style="width: ${callBarW.toFixed(1)}%; background: ${escHtml(it.color)}; opacity: 0.55;"></div></div>
                </td>
                <td class="num">${escHtml(avgTxt)}</td>
                <td class="num"><span class="${cacheCls}">${escHtml(cacheTxt)}</span></td>
                <td class="num">${escHtml(it.sessions)}</td>
                <td class="num">${escHtml(costTxt)}</td>
            </tr>
        `;
    });

    listEl.innerHTML = `
        <table class="model-table">
            <thead>
                <tr>
                    <th>模型名称</th>
                    <th class="${sortCls('tokens')}" onclick="setModelTableSort('tokens')">Token 消耗${sortInd('tokens')}</th>
                    <th class="${sortCls('calls')}" onclick="setModelTableSort('calls')">调用次数${sortInd('calls')}</th>
                    <th class="num ${sortCls('avg')}" onclick="setModelTableSort('avg')">均耗/次${sortInd('avg')}</th>
                    <th class="num">缓存命中</th>
                    <th class="num ${sortCls('sessions')}" onclick="setModelTableSort('sessions')">会话${sortInd('sessions')}</th>
                    <th class="num ${sortCls('cost')}" onclick="setModelTableSort('cost')">预估费用${sortInd('cost')}</th>
                </tr>
            </thead>
            <tbody>${tbodyHtml}</tbody>
        </table>
    `;
}

function renderHeatmap(days) {
    const container = document.getElementById('heatmap-cells');
    if (!days) return;
    const isSess = (heatmapMode === 'sessions');
    const maxVal = isSess
        ? Math.max(...days.map(d => (d.steps || d.sessions || 0)), 1)
        : Math.max(...days.map(d => (d.tokens || 0)), 1);
    let html = '';
    days.forEach(d => {
        let lvl = 'heat-l0';
        if (isSess) {
            const v = d.steps || d.sessions || 0;
            if (v > 0) {
                const r = v / maxVal;
                if (r > 0.65) lvl = 'heat-l4';
                else if (r > 0.35) lvl = 'heat-l3';
                else if (r > 0.12) lvl = 'heat-l2';
                else lvl = 'heat-l1';
            }
        } else {
            if ((d.tokens || 0) > 0) {
                const r = d.tokens / maxVal;
                if (r > 0.7) lvl = 'heat-l4';
                else if (r > 0.4) lvl = 'heat-l3';
                else if (r > 0.15) lvl = 'heat-l2';
                else lvl = 'heat-l1';
            } else if ((d.sessions || 0) > 0 || (d.steps || 0) > 0) {
                lvl = 'heat-unbilled';
            }
        }
        const selClass = (sessionDateFilter && sessionDateFilter === d.date) ? ' selected-date' : '';
        const outClass = (d.future ? ' heat-future' : '') + (d.in_range === false ? ' out-range' : '') + selClass;
        const tokNote = (d.tokens > 0) ? `${d.tokens_formatted} Tokens` : ((d.sessions > 0 || d.steps > 0) ? '无Token字段(旧版)' : '0 Tokens');
        const clickAttr = d.future ? '' : ` data-date="${escHtml(d.date)}" onclick="filterSessionByDate('${escHtml(d.date)}')"`;
        const tipHint = d.future ? '' : '（点击按该日筛选会话）';
        const tip = `${d.date}: ${tokNote}, ${d.sessions} 会话, ${d.steps || 0} 步${tipHint}`;
        html += `<div class="heat-cell ${lvl}${outClass}"${clickAttr} title="${escHtml(tip)}"></div>`;
    });
    container.innerHTML = html;
}

function renderRankings(listId, items, countHeaderId, countHeaderText) {
    const list = document.getElementById(listId);
    if (countHeaderId) document.getElementById(countHeaderId).innerText = countHeaderText;
    if (!items || items.length === 0) {
        list.innerHTML = `<div style="color: var(--muted); font-size: 11px;">暂无记录</div>`;
        return;
    }
    const maxCount = Math.max(...items.map(i => i.count), 1);
    let html = '';
    items.forEach((it, idx) => {
        const pct = Math.max((it.count / maxCount) * 100, 4);
        const colors = ['#f59e0b', '#3b82f6', '#10b981', '#8b5cf6', '#06b6d4', '#ec4899'];
        const dotColor = colors[idx % colors.length];
        html += `
            <div class="rank-item">
                <div class="rank-bar-bg" style="width: ${pct}%;"></div>
                <div class="rank-left" style="z-index: 1;">
                    <div class="legend-dot" style="background: ${dotColor};"></div>
                    <span class="rank-name">${escHtml(it.name)}</span>
                </div>
                <span class="rank-count" style="z-index: 1;">${escHtml(it.formatted)}</span>
            </div>
        `;
    });
    list.innerHTML = html;
}
