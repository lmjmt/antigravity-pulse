// ================= CONTEXT INSPECTOR DRAWER LOGIC =================
        let activeDrawerCid = null;
        let cachedTimelineData = null;
        let selectedTurnIndex = null;

        async function openContextDrawer(cid) {
            activeDrawerCid = cid;
            selectedTurnIndex = null;
            document.getElementById('turn-detail-section').style.display = 'none';

            // Find session meta from cachedSessions
            const sMeta = (cachedSessions && cachedSessions.sessions) ? cachedSessions.sessions.find(x => x.id === cid) : null;
            document.getElementById('drawer-title').innerText = sMeta ? sMeta.title : '📈 会话上下文演进与瘦身诊断';
            document.getElementById('drawer-ws').innerText = sMeta ? sMeta.workspace : '-';
            document.getElementById('drawer-cid').innerText = cid;
            const costLabel = !sMeta ? '-' : ((sMeta.cost_cny && sMeta.cost_cny !== '--') ? ('¥' + sMeta.cost_cny) : '旧版无计价');
            document.getElementById('d-cost-val').innerText = costLabel;

            // Show drawer
            document.getElementById('drawer-backdrop').classList.add('active');
            document.getElementById('context-drawer').classList.add('active');

            // Set loading state
            document.getElementById('curve-svg-box').innerHTML = `<div style="text-align: center; color: var(--muted); padding-top: 50px;">正在深度分析上下文演进流水...</div>`;
            document.getElementById('recoms-container').innerHTML = `<div style="color: var(--muted); font-size: 12px;">分析诊断中...</div>`;

            try {
                const res = await fetch('/api/session/context_timeline?cid=' + encodeURIComponent(cid), { cache: 'no-store' });
                const data = await res.json();
                cachedTimelineData = data;
                renderContextDrawerContent(data, sMeta);
            } catch (err) {
                document.getElementById('curve-svg-box').innerHTML = `<div style="color: var(--danger); text-align: center; padding-top: 50px;">分析加载失败: ${escHtml(err.message)}</div>`;
            }
        }

        function closeContextDrawer() {
            document.getElementById('drawer-backdrop').classList.remove('active');
            document.getElementById('context-drawer').classList.remove('active');
            activeDrawerCid = null;
        }

        function renderContextDrawerContent(data, sMeta) {
            if (!data || data.error) {
                document.getElementById('curve-svg-box').innerHTML = `<div style="color: var(--danger); text-align: center; padding-top: 50px;">${escHtml(data ? data.error : '未找到记录')}</div>`;
                return;
            }

            // Hero values
            document.getElementById('d-ctx-val').innerText = data.current_context_formatted || formatTokens(data.current_context_tokens);
            document.getElementById('d-ctx-sub').innerText = `1M 窗口 ${data.occupancy_pct}%`;
            document.getElementById('d-turns-val').innerText = `${data.turns_count} 轮`;
            document.getElementById('d-steps-val').innerText = `${data.total_steps}`;
            document.getElementById('drawer-curve-note').innerText = `共 ${data.turns_count} 轮交互 (耗时 ${data.elapsed_ms}ms)`;

            // Compaction savings
            if (data.compaction_events && data.compaction_events.length > 0) {
                const totalSaved = data.compaction_events.reduce((sum, e) => sum + e.saved_tokens, 0);
                document.getElementById('d-saved-val').innerText = `-${formatTokens(totalSaved)}`;
                document.getElementById('d-saved-sub').innerText = `${data.compaction_events.length} 次压缩裁剪`;
            } else {
                document.getElementById('d-saved-val').innerText = `0`;
                document.getElementById('d-saved-sub').innerText = `未发生压缩`;
            }

            // Render SVG curve
            renderEvolutionSvg(data.turns);

            // Render recommendations
            renderDiagnosticRecoms(data.recommendations);
        }

        function renderEvolutionSvg(turns) {
            const container = document.getElementById('curve-svg-box');
            if (!turns || turns.length === 0) {
                container.innerHTML = `<div style="text-align: center; color: var(--muted); padding-top: 50px;">暂无多轮上下文数据</div>`;
                return;
            }

            const maxTokens = Math.max(...turns.map(t => t.context_tokens), 100000);
            const w = 620;
            const h = 150;
            const padL = 40;
            const padR = 25;
            const padT = 20;
            const padB = 25;
            const chartW = w - padL - padR;
            const chartH = h - padT - padB;

            const n = turns.length;
            const stepX = (n <= 1) ? chartW / 2 : (chartW / (n - 1));

            const points = turns.map((t, i) => {
                const x = padL + i * stepX;
                const y = padT + chartH - (t.context_tokens / maxTokens) * chartH;
                return { x, y, turn: t };
            });

            // Build path d
            let linePath = `M ${points[0].x} ${points[0].y}`;
            points.slice(1).forEach(p => {
                linePath += ` L ${p.x} ${p.y}`;
            });

            const areaPath = `${linePath} L ${points[points.length - 1].x} ${padT + chartH} L ${points[0].x} ${padT + chartH} Z`;

            // Markers and circles
            let nodesHtml = '';
            points.forEach(p => {
                const t = p.turn;
                let circleColor = '#3b82f6';
                let markerIcon = '';

                if (t.has_compaction) {
                    circleColor = '#10b981';
                    markerIcon = `
                        <g transform="translate(${p.x}, ${p.y - 12})" style="cursor: pointer;" onclick="selectTurnNode(${t.turn_index})">
                            <rect x="-24" y="-12" width="48" height="15" rx="3" fill="#10b981" />
                            <text x="0" y="-2" font-size="9" font-weight="700" fill="#ffffff" text-anchor="middle">✂️ 压缩</text>
                        </g>
                    `;
                } else if (t.is_spike) {
                    circleColor = '#f59e0b';
                    markerIcon = `
                        <g transform="translate(${p.x}, ${p.y - 12})" style="cursor: pointer;" onclick="selectTurnNode(${t.turn_index})">
                            <rect x="-24" y="-12" width="48" height="15" rx="3" fill="#f59e0b" />
                            <text x="0" y="-2" font-size="9" font-weight="700" fill="#ffffff" text-anchor="middle">⚠️ 尖峰</text>
                        </g>
                    `;
                }

                nodesHtml += `
                    ${markerIcon}
                    <circle cx="${p.x}" cy="${p.y}" r="4" fill="${circleColor}" stroke="#ffffff" stroke-width="2" style="cursor: pointer;" 
                        onmouseenter="showCurveTip(event, ${t.turn_index})"
                        onmouseleave="hideCurveTip()"
                        onclick="selectTurnNode(${t.turn_index})"
                    />
                    <text x="${p.x}" y="${padT + chartH + 14}" font-size="9" fill="var(--muted)" text-anchor="middle">#${t.turn_index}</text>
                `;
            });

            const svg = `
                <svg viewBox="0 0 ${w} ${h}" style="width: 100%; height: 100%; overflow: visible;">
                    <defs>
                        <linearGradient id="ctx-grad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.25" />
                            <stop offset="100%" stop-color="#3b82f6" stop-opacity="0.0" />
                        </linearGradient>
                    </defs>

                    <!-- Grid lines -->
                    <line x1="${padL}" y1="${padT}" x2="${w - padR}" y2="${padT}" stroke="var(--border)" stroke-dasharray="2 2" />
                    <text x="${padL - 6}" y="${padT + 3}" font-size="8.5" fill="var(--muted)" text-anchor="end">${formatTokens(maxTokens)}</text>

                    <line x1="${padL}" y1="${padT + chartH/2}" x2="${w - padR}" y2="${padT + chartH/2}" stroke="var(--border)" stroke-dasharray="2 2" />
                    <text x="${padL - 6}" y="${padT + chartH/2 + 3}" font-size="8.5" fill="var(--muted)" text-anchor="end">${formatTokens(maxTokens/2)}</text>

                    <line x1="${padL}" y1="${padT + chartH}" x2="${w - padR}" y2="${padT + chartH}" stroke="var(--border)" />
                    <text x="${padL - 6}" y="${padT + chartH + 3}" font-size="8.5" fill="var(--muted)" text-anchor="end">0</text>

                    <!-- Filled Area & Line -->
                    <path d="${areaPath}" fill="url(#ctx-grad)" />
                    <path d="${linePath}" fill="none" stroke="#3b82f6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />

                    <!-- Nodes & Markers -->
                    ${nodesHtml}
                </svg>
            `;
            container.innerHTML = svg;
        }

        function showCurveTip(evt, turnIdx) {
            const tip = document.getElementById('curve-tooltip');
            const wrap = document.getElementById('curve-wrap');
            if (!tip || !wrap || !cachedTimelineData || !cachedTimelineData.turns) return;
            const t = cachedTimelineData.turns.find(x => x.turn_index === turnIdx);
            if (!t) return;
            const rect = wrap.getBoundingClientRect();
            const toolsTxt = (t.tools && t.tools.length) ? t.tools.join(', ') : '无工具';
            tip.style.display = 'block';
            tip.innerHTML = `<b>轮次 #${escHtml(t.turn_index)}</b> · <b>${escHtml(formatTokens(t.context_tokens))}</b> Tokens<br>步骤范围: #${escHtml(t.step_start)} 起 · 工具: ${escHtml(toolsTxt)}`;
            tip.style.left = (evt.clientX - rect.left) + 'px';
            tip.style.top = (evt.clientY - rect.top) + 'px';
        }

        function hideCurveTip() {
            document.getElementById('curve-tooltip').style.display = 'none';
        }

        function selectTurnNode(turnIdx) {
            selectedTurnIndex = turnIdx;
            if (!cachedTimelineData || !cachedTimelineData.turns) return;
            const t = cachedTimelineData.turns.find(x => x.turn_index === turnIdx);
            if (!t) return;

            const sec = document.getElementById('turn-detail-section');
            const box = document.getElementById('turn-detail-content');
            sec.style.display = 'block';

            let tag = '';
            if (t.has_compaction) tag = `<span class="badge badge-success" style="margin-left: 6px;">✂️ 削减 -${escHtml(formatTokens(t.compaction_delta))} Tokens</span>`;
            else if (t.is_spike) tag = `<span class="badge badge-warning" style="margin-left: 6px;">⚠️ 单轮激增 +${escHtml(formatTokens(t.delta))}</span>`;

            box.innerHTML = `
                <div style="font-weight: 700; color: var(--primary); display: flex; align-items: center;">
                    轮次 #${escHtml(t.turn_index)} ${tag}
                    <span style="font-size: 11px; color: var(--muted); margin-left: auto;">步骤 #${escHtml(t.step_start)} ~ #${escHtml(t.step_end)}</span>
                </div>
                <div style="color: var(--text); font-style: italic; margin: 3px 0;">"${escHtml(t.user_prompt || '用户指令输入')}"</div>
                <div style="font-size: 11.5px; color: var(--muted); display: flex; gap: 14px; flex-wrap: wrap;">
                    <span>上下文基数: <b>${escHtml(formatTokens(t.context_tokens))}</b></span>
                    <span>输出消耗: <b>${escHtml(formatTokens(t.output_tokens))}</b></span>
                    <span>调用工具: <code>${escHtml((t.tools && t.tools.length) ? t.tools.join(', ') : '无')}</code></span>
                </div>
            `;
            document.getElementById('btn-jump-step').setAttribute('data-step', t.step_start);
        }

        async function jumpToStepFromDrawer() {
            const btn = document.getElementById('btn-jump-step');
            const rawStep = btn ? btn.getAttribute('data-step') : null;
            const targetCid = activeDrawerCid;
            const targetStep = (rawStep !== null && rawStep !== '' && !isNaN(Number(rawStep))) ? Number(rawStep) : null;
            closeContextDrawer();
            if (targetCid) {
                await openSessionDetail(targetCid, targetStep);
            } else {
                switchMainTab('task');
            }
        }

        function renderDiagnosticRecoms(recoms) {
            const container = document.getElementById('recoms-container');
            const badge = document.getElementById('recom-count-badge');
            if (!recoms || recoms.length === 0) {
                badge.innerText = '0 项诊断';
                container.innerHTML = `<div style="color: var(--success); font-size: 12px; padding: 6px 0;">✔ 上下文结构健康，无严重超载或冗余读取项。</div>`;
                return;
            }

            badge.innerText = `${recoms.length} 项诊断`;
            let html = '';
            recoms.forEach(r => {
                let icon = '💡';
                if (r.type === 'danger') icon = '🚨';
                else if (r.type === 'warning') icon = '⚠️';
                else if (r.type === 'success') icon = '✔';

                html += `
                    <div class="recom-card ${escHtml(r.type)}">
                        <div style="font-size: 16px; line-height: 1;">${icon}</div>
                        <div style="flex: 1 1 auto;">
                            <div style="font-weight: 700; margin-bottom: 2px;">${escHtml(r.title)}</div>
                            <div style="color: var(--muted); line-height: 1.4;">${escHtml(r.desc)}</div>
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html;
        }

        function copyCompactCmd() {
            navigator.clipboard.writeText('/compact').then(() => {
                showToast('已复制 /compact 指令到剪贴板！');
            });
        }

        function copyDiagnosisReport() {
            if (!cachedTimelineData) return;
            const d = cachedTimelineData;
            let md = `# Antigravity 会话上下文诊断分析简报
`;
            md += `会话 ID: ${d.conversation_id}
`;
            md += `当前上下文用量: ${d.current_context_formatted} (${d.occupancy_pct}% / 1M 窗口)
`;
            md += `总轮次: ${d.turns_count} 轮 | 执行总步数: ${d.total_steps} 步

`;
            md += `## 诊断优化建议
`;
            (d.recommendations || []).forEach(r => {
                md += `- **[${r.type.toUpperCase()}] ${r.title}**: ${r.desc}
`;
            });
            navigator.clipboard.writeText(md).then(() => {
                showToast('诊断分析简报 (Markdown) 已复制到剪贴板！');
            });
        }
