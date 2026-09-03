/* shared voting helpers + drag ranking widget */
(function (global) {
    const CANDIDATES = ['A', 'B', 'C', 'D', 'E'];
    const NAME_POOL = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'.split('');
    const COLOR_LIST = [
        '#d45d5d', '#3d8c7a', '#3b7fa8', '#c9842a', '#7c5cbf',
        '#2f9e8f', '#c45c8a', '#4a7c59', '#b85c38', '#3d6ea8',
        '#8b5e3c', '#5c7a2f'
    ];
    const COLORS = { A: '#d45d5d', B: '#3d8c7a', C: '#3b7fa8', D: '#c9842a', E: '#7c5cbf', F: '#2f9e8f', G: '#c45c8a', H: '#4a7c59', X: '#c9842a' };
    const CYCLE_PALETTE = ['#ff5d7d', '#f9b44a', '#39d3ff', '#c084fc', '#4ade80', '#fb7185', '#22d3ee', '#f472b6'];
    const MEDALS = ['۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸'];
    const IDEA_KEY = 'mentor-ideas';

    function candidateColor(c) {
        if (COLORS[c]) return COLORS[c];
        const i = Math.max(0, NAME_POOL.indexOf(c));
        return COLOR_LIST[i % COLOR_LIST.length];
    }
    function nextCandidate(cands) {
        return NAME_POOL.find(ch => !(cands || []).includes(ch)) || null;
    }
    function parseRanking(str) {
        return String(str || '').split(/\s*>\s*/).map(s => s.trim()).filter(Boolean);
    }
    function pairKey(a, b) {
        return [a, b].sort().join('|||');
    }
    function expandGroups(groups) {
        const out = [];
        (groups || []).forEach(g => {
            const n = Math.max(0, parseInt(g.n, 10) || 0);
            for (let i = 0; i < n; i++) out.push(g.rank);
        });
        return out;
    }
    function cyclicVoters(cands) {
        cands = cands || CANDIDATES;
        return cands.map((_, i) => cands.slice(i).concat(cands.slice(0, i)).join('>'));
    }
    function condorcetWinnerVoters(cands, winner) {
        cands = (cands || CANDIDATES).slice();
        winner = winner || cands[0];
        const rest = cands.filter(c => c !== winner);
        const voters = [];
        const top = [winner].concat(rest).join('>');
        for (let i = 0; i < rest.length + 2; i++) voters.push(top);
        rest.forEach(r => {
            voters.push([r, winner].concat(rest.filter(x => x !== r)).join('>'));
        });
        return voters;
    }
    function emptyCounts(cands) {
        const counts = {};
        for (let i = 0; i < cands.length; i++) {
            for (let j = i + 1; j < cands.length; j++) {
                const key = pairKey(cands[i], cands[j]);
                counts[key] = {};
                counts[key][cands[i]] = 0;
                counts[key][cands[j]] = 0;
            }
        }
        return counts;
    }
    function buildCounts(voters, cands) {
        cands = cands || CANDIDATES;
        const counts = emptyCounts(cands);
        for (const rank of voters) {
            const list = parseRanking(rank).filter(c => cands.includes(c));
            for (let i = 0; i < list.length; i++) {
                for (let j = i + 1; j < list.length; j++) {
                    const w = list[i], l = list[j];
                    const key = pairKey(w, l);
                    if (counts[key]) counts[key][w] = (counts[key][w] || 0) + 1;
                }
            }
        }
        return counts;
    }
    function getResult(counts, a, b) {
        const key = pairKey(a, b);
        const ca = counts[key]?.[a] || 0;
        const cb = counts[key]?.[b] || 0;
        if (ca > cb) return { winner: a, loser: b, ca, cb };
        if (cb > ca) return { winner: b, loser: a, ca, cb };
        return { winner: null, loser: null, ca, cb };
    }
    function getWins(counts, cand, cands) {
        cands = cands || CANDIDATES;
        let w = 0;
        for (const other of cands) {
            if (other === cand) continue;
            if (getResult(counts, cand, other).winner === cand) w++;
        }
        return w;
    }
    function rankingByWins(counts, cands) {
        cands = cands || CANDIDATES;
        return cands.map(c => ({ cand: c, wins: getWins(counts, c, cands) }))
            .sort((a, b) => b.wins - a.wins);
    }
    function hasCondorcet(counts, cands) {
        cands = cands || CANDIDATES;
        for (const c of cands) {
            let beats = true;
            for (const other of cands) {
                if (c === other) continue;
                if (getResult(counts, c, other).winner !== c) { beats = false; break; }
            }
            if (beats) return c;
        }
        return null;
    }
    function cycleKey(nodes) {
        if (!nodes.length) return '';
        let best = nodes.join('>');
        for (let i = 1; i < nodes.length; i++) {
            const rot = nodes.slice(i).concat(nodes.slice(0, i)).join('>');
            if (rot < best) best = rot;
        }
        return best;
    }
    function findCycles(counts, cands) {
        cands = cands || CANDIDATES;
        if (!counts || cands.length < 3) return [];
        const adj = {};
        cands.forEach(c => { adj[c] = []; });
        for (let i = 0; i < cands.length; i++) {
            for (let j = i + 1; j < cands.length; j++) {
                const r = getResult(counts, cands[i], cands[j]);
                if (r.winner && r.loser) adj[r.winner].push(r.loser);
            }
        }
        const seen = new Set();
        const cycles = [];
        function dfs(start, node, path) {
            for (const nxt of adj[node] || []) {
                if (nxt === start && path.length >= 3) {
                    const body = path.slice();
                    const key = cycleKey(body);
                    if (!seen.has(key)) {
                        seen.add(key);
                        cycles.push(body);
                    }
                } else if (!path.includes(nxt) && path.length < cands.length) {
                    path.push(nxt);
                    dfs(start, nxt, path);
                    path.pop();
                }
            }
        }
        cands.forEach(start => dfs(start, start, [start]));
        cycles.sort((a, b) => a.length - b.length || cycleKey(a).localeCompare(cycleKey(b)));
        return cycles.slice(0, 8);
    }
    function hasCycle(counts, cands) {
        return findCycles(counts, cands).length > 0;
    }
    function firstChoices(voters, active) {
        const counts = {};
        for (const c of active) counts[c] = 0;
        for (const rank of voters) {
            for (const c of parseRanking(rank)) {
                if (active.includes(c)) {
                    counts[c] = (counts[c] || 0) + 1;
                    break;
                }
            }
        }
        return counts;
    }
    function plurality(voters, cands) {
        cands = cands || CANDIDATES;
        const counts = firstChoices(voters, cands);
        let best = null, bestN = -1;
        for (const c of cands) {
            const n = counts[c] || 0;
            if (n > bestN) { bestN = n; best = c; }
        }
        return { winner: voters.length ? best : null, counts };
    }
    function borda(voters, cands) {
        cands = cands || CANDIDATES;
        const n = cands.length;
        const scores = {};
        for (const c of cands) scores[c] = 0;
        for (const rank of voters) {
            const list = parseRanking(rank).filter(x => cands.includes(x));
            list.forEach((c, i) => {
                if (scores[c] !== undefined) scores[c] += (n - 1 - i);
            });
        }
        let best = null, bestN = -1;
        for (const c of cands) {
            if (scores[c] > bestN) { bestN = scores[c]; best = c; }
        }
        return { winner: voters.length ? best : null, scores };
    }
    function hare(voters, cands) {
        cands = cands || CANDIDATES;
        if (!voters.length) return { winner: null, rounds: [] };
        let active = cands.slice();
        const rounds = [];
        while (active.length > 1) {
            const counts = firstChoices(voters, active);
            let minVotes = Infinity, mins = [];
            for (const c of active) {
                const v = counts[c] || 0;
                if (v < minVotes) { minVotes = v; mins = [c]; }
                else if (v === minVotes) mins.push(c);
            }
            mins.sort();
            const toEliminate = mins[0];
            rounds.push({
                round: rounds.length + 1,
                counts: { ...counts },
                active: active.slice(),
                eliminatedThis: toEliminate,
                winner: null
            });
            active = active.filter(c => c !== toEliminate);
        }
        const winner = active[0] || null;
        rounds.push({
            round: rounds.length + 1,
            counts: firstChoices(voters, active),
            active: active.slice(),
            eliminatedThis: null,
            winner
        });
        return { winner, rounds };
    }
    function sequential(voters, agenda, cands) {
        cands = cands || CANDIDATES;
        const counts = buildCounts(voters, cands);
        let current = agenda[0];
        const steps = [];
        for (let i = 1; i < agenda.length; i++) {
            const challenger = agenda[i];
            const r = getResult(counts, current, challenger);
            steps.push({ a: current, b: challenger, ...r });
            if (r.winner) current = r.winner;
        }
        return { winner: current, steps, counts };
    }
    function dictator(voters, idx) {
        if (!voters.length || idx < 0 || idx >= voters.length) return { winner: null };
        const list = parseRanking(voters[idx]);
        return { winner: list[0] || null, dictatorIndex: idx };
    }
    function condorcetMethod(voters, cands) {
        const counts = buildCounts(voters, cands);
        const cw = hasCondorcet(counts, cands);
        return { winner: cw, counts, cycle: hasCycle(counts, cands) };
    }
    function unanimityHold(voters, winner, cands) {
        if (!winner || !voters.length) return true;
        cands = cands || CANDIDATES;
        for (const other of cands) {
            if (other === winner) continue;
            let allPreferOther = voters.length > 0;
            for (const rank of voters) {
                const list = parseRanking(rank);
                const io = list.indexOf(other);
                const iw = list.indexOf(winner);
                if (io === -1 || iw === -1 || io >= iw) { allPreferOther = false; break; }
            }
            if (allPreferOther) return false;
        }
        return true;
    }

    function drawArrow(ctx, x1, y1, x2, y2, color, lineWidth) {
        lineWidth = lineWidth || 3.5;
        const dx = x2 - x1, dy = y2 - y1;
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len < 1) return;
        const ux = dx / len, uy = dy / len;
        const shrink = 26;
        const startX = x1 + ux * shrink, startY = y1 + uy * shrink;
        const endX = x2 - ux * shrink, endY = y2 - uy * shrink;
        ctx.save();
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.shadowColor = color + '50';
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.moveTo(startX, startY);
        ctx.lineTo(endX, endY);
        ctx.stroke();
        const angle = Math.atan2(endY - startY, endX - startX);
        const headLen = 14, headAngle = 0.45;
        ctx.fillStyle = color;
        ctx.shadowColor = 'transparent';
        ctx.beginPath();
        ctx.moveTo(endX, endY);
        ctx.lineTo(endX - headLen * Math.cos(angle - headAngle), endY - headLen * Math.sin(angle - headAngle));
        ctx.lineTo(endX - headLen * Math.cos(angle + headAngle), endY - headLen * Math.sin(angle + headAngle));
        ctx.closePath();
        ctx.fill();
        ctx.restore();
    }

    function layoutPositions(cands, cx, cy, radius) {
        const pos = {};
        const n = Math.max(1, cands.length);
        for (let i = 0; i < n; i++) {
            const ang = -Math.PI / 2 + (2 * Math.PI * i) / n;
            pos[cands[i]] = { x: cx + radius * Math.cos(ang), y: cy + radius * Math.sin(ang) };
        }
        return pos;
    }

    function drawGraph(canvas, counts, opts) {
        opts = opts || {};
        const cands = opts.candidates || CANDIDATES;
        const ctx = canvas.getContext('2d');
        const W = canvas.width, H = canvas.height;
        ctx.clearRect(0, 0, W, H);
        if (!counts) {
            ctx.fillStyle = '#93a5c2';
            ctx.font = '16px Vazirmatn, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(opts.emptyText || 'رأی اضافه کنید', W / 2, H / 2);
            return;
        }
        const radius = Math.min(W, H) * (0.30 + Math.min(cands.length, 8) * 0.008);
        const pos = layoutPositions(cands, W / 2, H / 2, radius);
        const cycles = findCycles(counts, cands);
        const edgeCycles = {};
        cycles.forEach((cyc, idx) => {
            for (let i = 0; i < cyc.length; i++) {
                const a = cyc[i], b = cyc[(i + 1) % cyc.length];
                const k = a + '>' + b;
                if (!edgeCycles[k]) edgeCycles[k] = [];
                edgeCycles[k].push(idx);
            }
        });

        for (let i = 0; i < cands.length; i++) {
            for (let j = i + 1; j < cands.length; j++) {
                const a = cands[i], b = cands[j];
                const r = getResult(counts, a, b);
                if (!r.winner) {
                    ctx.beginPath();
                    ctx.setLineDash([5, 5]);
                    ctx.strokeStyle = 'rgba(255,255,255,.28)';
                    ctx.lineWidth = 1.5;
                    ctx.moveTo(pos[a].x, pos[a].y);
                    ctx.lineTo(pos[b].x, pos[b].y);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }
            }
        }
        for (let i = 0; i < cands.length; i++) {
            for (let j = i + 1; j < cands.length; j++) {
                const a = cands[i], b = cands[j];
                const r = getResult(counts, a, b);
                if (!r.winner) continue;
                const from = r.winner, to = r.loser;
                const p1 = pos[from], p2 = pos[to];
                if (!p1 || !p2) continue;
                const k = from + '>' + to;
                const members = edgeCycles[k] || [];
                const isHl = opts.highlightWinner && from === opts.highlightWinner;
                if (!members.length) {
                    const col = isHl ? '#6ee7b7' : candidateColor(from);
                    drawArrow(ctx, p1.x, p1.y, p2.x, p2.y, col, isHl ? 5 : 3.2);
                    continue;
                }
                const dx = p2.x - p1.x, dy = p2.y - p1.y;
                const len = Math.sqrt(dx * dx + dy * dy) || 1;
                const px = -dy / len, py = dx / len;
                members.forEach((ci, m) => {
                    const shift = (m - (members.length - 1) / 2) * 8;
                    drawArrow(
                        ctx,
                        p1.x + px * shift, p1.y + py * shift,
                        p2.x + px * shift, p2.y + py * shift,
                        CYCLE_PALETTE[ci % CYCLE_PALETTE.length],
                        members.length > 1 ? 2.6 : 3.4
                    );
                });
            }
        }
        for (const c of cands) {
            const p = pos[c];
            const isW = opts.highlightWinner === c;
            ctx.beginPath();
            ctx.arc(p.x, p.y, isW ? 26 : 22, 0, 2 * Math.PI);
            ctx.fillStyle = isW ? '#6ee7b7' : candidateColor(c);
            ctx.fill();
            ctx.strokeStyle = 'white';
            ctx.lineWidth = isW ? 4 : 3;
            ctx.stroke();
            ctx.fillStyle = 'white';
            ctx.font = 'bold 16px Vazirmatn, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(c, p.x, p.y + 1);
        }
    }

    function legendHtml(counts, opts) {
        opts = opts || {};
        const cands = opts.candidates || CANDIDATES;
        let html = '';
        for (const c of cands) {
            html += `<span><span class="dot" style="background:${candidateColor(c)};"></span> ${c}</span>`;
        }
        if (counts) {
            const cw = hasCondorcet(counts, cands);
            const cycles = findCycles(counts, cands);
            if (cw) html += `<span style="color:#6ee7b7;">برنده کندورسه: ${cw}</span>`;
            cycles.forEach((cyc, i) => {
                const col = CYCLE_PALETTE[i % CYCLE_PALETTE.length];
                html += `<span class="cycle-chip" style="color:${col};border-color:${col};">چرخه ${cyc.concat(cyc[0]).join(' → ')}</span>`;
            });
        }
        return html;
    }

    function formatRank(str) {
        return parseRanking(str).join(' ≻ ');
    }

    function RankingWidget(el, options) {
        options = options || {};
        this.el = typeof el === 'string' ? document.getElementById(el) : el;
        this.candidates = (options.candidates || CANDIDATES).slice();
        this.order = (options.order || this.candidates).slice();
        this.onChange = options.onChange || function () {};
        this.dragFrom = null;
        this.render();
    }
    RankingWidget.prototype.getOrder = function () { return this.order.slice(); };
    RankingWidget.prototype.getString = function () { return this.order.join('>'); };
    RankingWidget.prototype.setCandidates = function (cands, order) {
        this.candidates = cands.slice();
        this.order = (order || cands).slice();
        this.render();
    };
    RankingWidget.prototype.setOrder = function (order) {
        this.order = order.slice();
        this.render();
        this.onChange(this.getString(), this.getOrder());
    };
    RankingWidget.prototype.move = function (from, to) {
        if (to < 0 || to >= this.order.length || from === to) return;
        const item = this.order.splice(from, 1)[0];
        this.order.splice(to, 0, item);
        this.render();
        this.onChange(this.getString(), this.getOrder());
    };
    RankingWidget.prototype.render = function () {
        const self = this;
        const n = this.order.length;
        let html = `<div class="rank-builder">`;
        this.order.forEach((c, i) => {
            const tag = i === 0 ? 'بهترین' : (i === n - 1 ? 'ضعیف‌ترین' : 'رتبه ' + (i + 1));
            html += `
                <div class="rank-slot" draggable="true" data-idx="${i}" aria-label="رتبه ${i + 1}: نامزد ${c}">
                    <span class="grip" aria-hidden="true">⋮⋮</span>
                    <span class="rank-num">${i + 1}</span>
                    <span class="cand-chip chip-${c}" style="background:${candidateColor(c)};">${c}</span>
                    <span class="cand-label">نامزد ${c} — ${tag}</span>
                    <span class="move-btns">
                        <button type="button" data-act="up" data-idx="${i}" ${i === 0 ? 'disabled' : ''} aria-label="بالاتر بردن ${c}">▲</button>
                        <button type="button" data-act="down" data-idx="${i}" ${i === n - 1 ? 'disabled' : ''} aria-label="پایین آوردن ${c}">▼</button>
                    </span>
                </div>`;
        });
        html += `</div>`;
        html += `<div class="rank-preview" style="margin-top:8px;">${formatRank(this.getString())}</div>`;
        this.el.innerHTML = html;
        this.el.querySelectorAll('[data-act]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const idx = parseInt(btn.dataset.idx, 10);
                if (btn.dataset.act === 'up') self.move(idx, idx - 1);
                if (btn.dataset.act === 'down') self.move(idx, idx + 1);
            });
        });
        this.el.querySelectorAll('.rank-slot').forEach(slot => {
            slot.addEventListener('dragstart', (e) => {
                self.dragFrom = parseInt(slot.dataset.idx, 10);
                slot.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', String(self.dragFrom));
            });
            slot.addEventListener('dragend', () => {
                slot.classList.remove('dragging');
                self.el.querySelectorAll('.rank-slot').forEach(s => s.classList.remove('drag-over'));
            });
            slot.addEventListener('dragover', (e) => {
                e.preventDefault();
                slot.classList.add('drag-over');
            });
            slot.addEventListener('dragleave', () => slot.classList.remove('drag-over'));
            slot.addEventListener('drop', (e) => {
                e.preventDefault();
                slot.classList.remove('drag-over');
                const to = parseInt(slot.dataset.idx, 10);
                const from = self.dragFrom;
                if (from !== null && from !== to) self.move(from, to);
                self.dragFrom = null;
            });
        });
    };

    function mountVoterAdder(el, options) {
        options = options || {};
        el = typeof el === 'string' ? document.getElementById(el) : el;
        const addLabel = options.addLabel || 'افزودن رأی';
        el.innerHTML = `
            <div class="rank-builder-wrap">
                <div id="${el.id}-rank" style="flex:1;"></div>
                <div class="adder-controls">
                    <label>تعداد رأی با این ترتیب
                        <input type="number" id="${el.id}-qty" min="1" max="99" value="1">
                    </label>
                    <button class="primary" id="${el.id}-add" type="button">${addLabel}</button>
                    ${options.extraButtons || ''}
                </div>
            </div>
        `;
        const widget = new RankingWidget(el.querySelector(`#${el.id}-rank`), {
            candidates: options.candidates,
            order: options.order
        });
        const qty = el.querySelector(`#${el.id}-qty`);
        el.querySelector(`#${el.id}-add`).addEventListener('click', () => {
            const n = Math.max(1, parseInt(qty.value, 10) || 1);
            if (options.onAdd) options.onAdd(widget.getString(), n, widget);
        });
        return widget;
    }

    function renderCandidateBar(el, cands, handlers) {
        handlers = handlers || {};
        if (!el) return;
        el.innerHTML = `
            <div class="cand-bar">
                ${cands.map(c => `<span class="cand-pill chip-${c}" style="background:${candidateColor(c)};">${c}</span>`).join('')}
                <button type="button" class="outline" data-act="add" ${cands.length >= 10 ? 'disabled' : ''}>+ نامزد</button>
                <button type="button" class="outline" data-act="remove" ${cands.length <= 3 ? 'disabled' : ''}>حذف آخرین</button>
            </div>`;
        el.querySelector('[data-act="add"]').addEventListener('click', () => handlers.onAdd && handlers.onAdd());
        el.querySelector('[data-act="remove"]').addEventListener('click', () => handlers.onRemove && handlers.onRemove());
    }

    function renderVoterList(container, voters, onRemove, extra) {
        extra = extra || {};
        if (!voters.length) {
            container.innerHTML = `<div class="empty-state">هنوز رأی‌دهنده‌ای اضافه نشده است.</div>`;
            return;
        }
        let html = '';
        voters.forEach((rank, i) => {
            const mark = extra.markIndex === i ? ' style="border-color:#f9b44a;background:rgba(249,180,74,.12);"' : '';
            html += `
                <div class="voter-item"${mark}>
                    <span class="rank">#${i + 1} &nbsp; ${formatRank(rank)}${extra.markIndex === i ? ' <span class="highlight-up">دیکتاتور</span>' : ''}</span>
                    <span style="display:flex;gap:4px;">
                        ${extra.onEdit ? `<button type="button" class="outline edit-btn" data-idx="${i}">ویرایش</button>` : ''}
                        ${extra.onPick ? `<button type="button" class="outline pick-btn" data-idx="${i}">انتخاب</button>` : ''}
                        <button class="remove-btn" data-idx="${i}" type="button">✕</button>
                    </span>
                </div>`;
        });
        container.innerHTML = html;
        container.querySelectorAll('.remove-btn').forEach(btn => {
            btn.addEventListener('click', () => onRemove(parseInt(btn.dataset.idx, 10)));
        });
        if (extra.onPick) {
            container.querySelectorAll('.pick-btn').forEach(btn => {
                btn.addEventListener('click', () => extra.onPick(parseInt(btn.dataset.idx, 10)));
            });
        }
        if (extra.onEdit) {
            container.querySelectorAll('.edit-btn').forEach(btn => {
                btn.addEventListener('click', () => extra.onEdit(parseInt(btn.dataset.idx, 10)));
            });
        }
    }

    function renderMatrixTable(table, counts, cands) {
        cands = cands || CANDIDATES;
        if (!table) return;
        table.innerHTML = `<thead><tr><th></th>${cands.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody></tbody>`;
        renderMatrix(table.querySelector('tbody'), counts, cands);
    }

    function renderMatrix(tbody, counts, cands) {
        cands = cands || CANDIDATES;
        if (!counts) {
            tbody.innerHTML = cands.map(row => {
                const cells = cands.map(col => row === col ? `<td class="diag">—</td>` : `<td class="tie">—</td>`).join('');
                return `<tr><th>${row}</th>${cells}</tr>`;
            }).join('');
            return;
        }
        let html = '';
        for (const row of cands) {
            html += `<tr><th>${row}</th>`;
            for (const col of cands) {
                if (row === col) { html += `<td class="diag">—</td>`; continue; }
                const r = getResult(counts, row, col);
                let cls = 'tie', label = `${r.ca}–${r.cb}`;
                if (r.winner === row) { cls = 'win'; label = `✓ ${r.ca}–${r.cb}`; }
                else if (r.winner === col) { cls = 'loss'; label = `✗ ${r.ca}–${r.cb}`; }
                html += `<td class="${cls}">${label}</td>`;
            }
            html += '</tr>';
        }
        tbody.innerHTML = html;
    }

    function renderWinRanking(container, counts, cands) {
        cands = cands || CANDIDATES;
        if (!counts) {
            container.innerHTML = `<div class="empty-state">هیچ رأی‌دهنده‌ای وجود ندارد.</div>`;
            return { cw: null, cyc: false, cycles: [] };
        }
        const ranking = rankingByWins(counts, cands);
        const cw = hasCondorcet(counts, cands);
        const cycles = findCycles(counts, cands);
        const cyc = cycles.length > 0;
        let html = '<div class="rank-list">';
        ranking.forEach((item, idx) => {
            const isC = cw === item.cand;
            html += `<div class="${isC ? 'rank-item condorcet' : 'rank-item'}">
                <span class="pos">${MEDALS[idx] || (idx + 1)}</span>
                <span class="candidate" style="color:${candidateColor(item.cand)};">${item.cand}</span>
                <span class="wins">${item.wins} پیروزی</span>
                ${isC ? '★' : ''}
            </div>`;
        });
        html += '</div>';
        container.innerHTML = html;
        return { cw, cyc, cycles };
    }

    function renderScoreBars(el, scores, cands) {
        cands = cands || Object.keys(scores || {});
        const max = Math.max(1, ...cands.map(c => scores[c] || 0));
        el.innerHTML = cands.map(c => {
            const n = scores[c] || 0;
            return `<div class="score-bar"><span class="candidate" style="color:${candidateColor(c)};width:24px;">${c}</span>
                <div class="bar"><span style="width:${(n / max) * 100}%;background:${candidateColor(c)};"></span></div>
                <strong>${n}</strong></div>`;
        }).join('');
    }

    function pairTallyHtml(counts, cands) {
        if (!counts) return '';
        let html = '';
        for (let i = 0; i < cands.length; i++) {
            for (let j = i + 1; j < cands.length; j++) {
                const a = cands[i], b = cands[j];
                const r = getResult(counts, a, b);
                const label = r.winner
                    ? `<span class="winner">${r.winner}</span> (${r.ca} در برابر ${r.cb})`
                    : `مساوی (${r.ca} در برابر ${r.cb})`;
                html += `<div class="pair">${a} در برابر ${b}: ${label}</div>`;
            }
        }
        return html;
    }

    function dropCandidateFromVoters(voters, name) {
        return voters.map(rank => parseRanking(rank).filter(c => c !== name).join('>')).filter(Boolean);
    }
    function appendCandidateToVoters(voters, name) {
        return voters.map(rank => {
            const list = parseRanking(rank);
            if (!list.includes(name)) list.push(name);
            return list.join('>');
        });
    }

    function createLab(opts) {
        opts = opts || {};
        const st = {
            candidates: (opts.candidates || CANDIDATES).slice(),
            voters: (opts.voters || []).slice(),
            stepIndex: 0,
            editing: -1,
            widget: null
        };
        function remount() {
            if (!opts.adderId) return;
            st.widget = mountVoterAdder(opts.adderId, {
                candidates: st.candidates,
                addLabel: st.editing >= 0 ? 'جایگزین کردن این رأی' : 'افزودن رأی',
                onAdd(rank, n) {
                    if (st.editing >= 0) {
                        st.voters[st.editing] = rank;
                        st.editing = -1;
                    } else {
                        for (let i = 0; i < n; i++) st.voters.push(rank);
                    }
                    render();
                }
            });
        }
        function countsNow() {
            const list = opts.stepwise
                ? st.voters.slice(0, st.stepIndex)
                : st.voters;
            if (!list.length) return null;
            return buildCounts(list, st.candidates);
        }
        function render() {
            if (opts.candidateBarId) {
                renderCandidateBar(document.getElementById(opts.candidateBarId), st.candidates, {
                    onAdd() {
                        const nxt = nextCandidate(st.candidates);
                        if (!nxt) return;
                        st.candidates.push(nxt);
                        if (opts.keepParadox) st.voters = cyclicVoters(st.candidates);
                        else st.voters = appendCandidateToVoters(st.voters, nxt);
                        if (opts.stepwise) st.stepIndex = st.voters.length;
                        remount();
                        render();
                    },
                    onRemove() {
                        if (st.candidates.length <= 3) return;
                        const gone = st.candidates.pop();
                        if (opts.keepParadox) st.voters = cyclicVoters(st.candidates);
                        else st.voters = dropCandidateFromVoters(st.voters, gone);
                        if (opts.stepwise && st.stepIndex > st.voters.length) st.stepIndex = st.voters.length;
                        remount();
                        render();
                    }
                });
            }
            const shown = opts.stepwise ? st.voters.slice(0, st.stepIndex || st.voters.length) : st.voters;
            if (opts.voterCountId) document.getElementById(opts.voterCountId).textContent = st.voters.length;
            if (opts.voterListId) {
                renderVoterList(document.getElementById(opts.voterListId), st.voters, i => {
                    st.voters.splice(i, 1);
                    if (st.editing === i) st.editing = -1;
                    if (opts.stepwise && st.stepIndex > st.voters.length) st.stepIndex = st.voters.length;
                    remount();
                    render();
                }, {
                    onEdit(i) {
                        st.editing = i;
                        remount();
                        if (st.widget) st.widget.setOrder(parseRanking(st.voters[i]));
                    }
                });
            }
            if (opts.stepwise) {
                const total = st.voters.length;
                if (opts.stepStatusId) document.getElementById(opts.stepStatusId).textContent = `${st.stepIndex} / ${total}`;
                const stepBtn = opts.stepBtnId && document.getElementById(opts.stepBtnId);
                const allBtn = opts.processAllBtnId && document.getElementById(opts.processAllBtnId);
                if (stepBtn) stepBtn.disabled = !total || st.stepIndex >= total;
                if (allBtn) allBtn.disabled = !total || st.stepIndex >= total;
                if (opts.stepDetailId) {
                    const detail = document.getElementById(opts.stepDetailId);
                    if (!total) detail.innerHTML = 'برای شروع حداقل یک رأی اضافه کنید.';
                    else if (st.stepIndex === 0) detail.innerHTML = `${total} رأی ثبت شده. «گام بعدی» را بزنید.`;
                    else {
                        const rank = st.voters[st.stepIndex - 1];
                        const counts = countsNow();
                        detail.innerHTML = `<div class="step-header">گام ${st.stepIndex} از ${total} — ${formatRank(rank)}</div>
                            <div class="pairwise-contrib">${pairTallyHtml(counts, st.candidates)}</div>`;
                    }
                }
            }
            const counts = countsNow();
            if (opts.matrixId) renderMatrixTable(document.getElementById(opts.matrixId), counts, st.candidates);
            if (opts.graphId) {
                const canvas = document.getElementById(opts.graphId);
                const cw = counts ? hasCondorcet(counts, st.candidates) : null;
                drawGraph(canvas, counts, { candidates: st.candidates, highlightWinner: opts.highlightCondorcet ? cw : opts.highlightWinner });
            }
            if (opts.legendId) document.getElementById(opts.legendId).innerHTML = legendHtml(counts, { candidates: st.candidates });
            if (opts.rankingId) renderWinRanking(document.getElementById(opts.rankingId), counts, st.candidates);
            if (typeof opts.onRender === 'function') opts.onRender(counts, st);
        }
        remount();
        if (opts.stepBtnId) {
            document.getElementById(opts.stepBtnId).addEventListener('click', () => {
                if (st.stepIndex < st.voters.length) { st.stepIndex++; render(); }
            });
        }
        if (opts.processAllBtnId) {
            document.getElementById(opts.processAllBtnId).addEventListener('click', () => {
                st.stepIndex = st.voters.length;
                render();
            });
        }
        if (opts.resetStepsBtnId) {
            document.getElementById(opts.resetStepsBtnId).addEventListener('click', () => {
                st.stepIndex = 0;
                render();
            });
        }
        if (opts.resetBtnId) {
            document.getElementById(opts.resetBtnId).addEventListener('click', () => {
                st.voters = [];
                st.stepIndex = 0;
                st.editing = -1;
                remount();
                render();
            });
        }
        return {
            state: st,
            render,
            remount,
            countsNow,
            setVoters(v, process) {
                st.voters = v.slice();
                st.stepIndex = process || !opts.stepwise ? st.voters.length : 0;
                st.editing = -1;
                remount();
                render();
            },
            setCandidates(c) {
                st.candidates = c.slice();
                remount();
                render();
            }
        };
    }

    const CRITERIA = [
        { key: 'AAW', name: 'AAW', title: 'وجود همیشگی برنده' },
        { key: 'CWC', name: 'CWC', title: 'معیار کندورسه' },
        { key: 'UNAN', name: 'UNAN', title: 'اجماع / پارتو' },
        { key: 'MONO', name: 'MONO', title: 'یکنوایی' },
        { key: 'IIA', name: 'IIA', title: 'استقلال از گزینه‌های نامرتبط' }
    ];

    const API_BASES = ['http://127.0.0.1:8765', 'http://localhost:8765'];
    const FETCH_FAIL = 'اتصال به API برقرار نشد. برای اجرای محلی python llm.py را اجرا کنید. روی Vercel متغیر ORCAROUTER_API_KEY را در تنظیمات پروژه بگذارید.';

    function apiBases() {
        const bases = [];
        if (location.protocol === 'http:' || location.protocol === 'https:') {
            bases.push('');
        }
        API_BASES.forEach(b => { if (!bases.includes(b)) bases.push(b); });
        return bases;
    }

    async function postApi(path, payload) {
        let lastErr = FETCH_FAIL;
        for (const base of apiBases()) {
            try {
                const res = await fetch(base + path, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(localStorage.getItem('workshop-token')
                            ? { Authorization: 'Bearer ' + localStorage.getItem('workshop-token') }
                            : {})
                    },
                    body: JSON.stringify(payload)
                });
                let data = {};
                try { data = await res.json(); } catch (e) { data = {}; }
                if (!res.ok) {
                    if (data && data.error) throw new Error(data.error);
                    lastErr = new Error('درخواست ناموفق بود. python llm.py را دوباره اجرا کنید یا استقرار Vercel را بررسی کنید.');
                    continue;
                }
                return data;
            } catch (err) {
                const msg = String((err && err.message) || err || '');
                const network = err instanceof TypeError || /failed to fetch|networkerror|load failed/i.test(msg);
                if (!network) throw err;
                lastErr = err;
            }
        }
        throw new Error(FETCH_FAIL);
    }

    async function evaluateSystem(prompt) {
        const data = await postApi('/api/evaluate', { prompt });
        return { criteria: data.criteria };
    }

    async function fetchExamples(prompt, criteria) {
        const data = await postApi('/api/examples', { prompt, criteria });
        return data.examples || [];
    }

    async function checkBackend() {
        for (const base of apiBases()) {
            try {
                const res = await fetch(base + '/api/health', { method: 'GET' });
                if (res.ok) return true;
            } catch (e) { /* try next */ }
        }
        return false;
    }

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function isStaffUser(user) {
        return user && (user.role === 'admin' || user.role === 'owner');
    }

    function maskedName(name, revealed, isOwn) {
        if (isOwn || revealed) return escapeHtml(name || '');
        return '<span class="masked-name">●●●●</span>';
    }

    function ballotChip(n, rank) {
        const parts = parseRanking(rank);
        const letters = parts.map(c =>
            `<span class="ballot-letter ballot-${c}">${c}</span>`
        ).join('<span class="ballot-sep">≻</span>');
        return `<span class="ballot-group"><span class="ballot-qty">${n}×</span>${letters}</span>`;
    }

    function loadIdeas() {
        try { return JSON.parse(localStorage.getItem(IDEA_KEY) || '[]'); } catch (e) { return []; }
    }
    function saveIdeas(ideas) {
        localStorage.setItem(IDEA_KEY, JSON.stringify(ideas));
    }

    function renderCriteriaChart(el, criteria, opts) {
        opts = opts || {};
        if (!el) return;
        if (!criteria) {
            el.innerHTML = opts.empty || '<div class="empty-state">هنوز ارزیابی‌ای نیست.</div>';
            return;
        }
        const examples = Array.isArray(opts.examples) ? opts.examples : [];
        const failed = CRITERIA.filter(c => !criteria[c.key]);
        const passed = CRITERIA.length - failed.length;
        const summary = failed.length
            ? `${passed} از ۵ برقرار — نقض‌شده: ${failed.map(c => c.name).join('، ')}`
            : 'هر پنج شرط برقرار است';
        const byRule = {};
        CRITERIA.forEach(c => { byRule[c.key] = c; });
        const exampleHtml = examples.length ? `
            <div class="counterexample-list">
                <div class="chart-title" style="margin:16px 0 8px;">مثال‌هایی که این روش را رد می‌کنند</div>
                ${examples.map((ex, i) => {
                    const meta = byRule[ex.rule] || { name: ex.rule, title: '' };
                    const ballots = (ex.ballots || []).map(b => `<li>${escapeHtml(b)}</li>`).join('');
                    return `<div class="violation-demo counterexample-card">
                        <div class="title">${i + 1}. ${escapeHtml(meta.name)} — ${escapeHtml(ex.title || meta.title)}</div>
                        ${ballots ? `<ul class="plain">${ballots}</ul>` : ''}
                        ${ex.result ? `<p>${escapeHtml(ex.result)}</p>` : ''}
                        ${ex.why ? `<p class="text-muted">${escapeHtml(ex.why)}</p>` : ''}
                    </div>`;
                }).join('')}
            </div>` : (failed.length && opts.examplesFailed
            ? '<p class="text-muted" style="margin-top:12px;">برای شرط‌های نقض‌شده مثالی نیست.</p>'
            : '');
        el.innerHTML = `
            <div class="criteria-chart">
                <div class="chart-head">
                    <div class="chart-title">${opts.title || 'ارزیابی پنج معیار'}</div>
                    <div class="chart-summary">${summary}</div>
                </div>
                ${CRITERIA.map(c => {
                    const ok = !!criteria[c.key];
                    return `<div class="criteria-row ${ok ? 'pass' : 'fail'}">
                        <div class="crit-label">${c.name}<small>${c.title}</small></div>
                        <div class="bar"><span></span></div>
                        <div class="crit-status">${ok ? 'برقرار' : 'نقض'}</div>
                    </div>`;
                }).join('')}
                <div class="cond-grid">
                    ${CRITERIA.map(c => {
                        const ok = !!criteria[c.key];
                        return `<div class="cond-card ${ok ? 'pass' : 'fail'}">
                            <div class="cond-name">${c.name} — ${ok ? 'برقرار' : 'نقض'}</div>
                            <div class="text-muted">${c.title}</div>
                        </div>`;
                    }).join('')}
                </div>
                ${exampleHtml}
            </div>`;
    }

    global.Mentor = {
        CANDIDATES, COLORS, CRITERIA, IDEA_KEY, CYCLE_PALETTE,
        candidateColor, nextCandidate, parseRanking, pairKey, buildCounts, getResult, getWins,
        rankingByWins, hasCondorcet, hasCycle, findCycles,
        plurality, borda, hare, sequential, dictator, condorcetMethod,
        firstChoices, unanimityHold, expandGroups, cyclicVoters, condorcetWinnerVoters,
        drawGraph, legendHtml, formatRank, layoutPositions,
        RankingWidget, mountVoterAdder, renderVoterList, renderMatrix, renderMatrixTable,
        renderWinRanking, renderScoreBars, renderCandidateBar, pairTallyHtml, createLab,
        evaluateSystem, fetchExamples, renderCriteriaChart, checkBackend,
        loadIdeas, saveIdeas, escapeHtml, isStaffUser, maskedName, ballotChip
    };
})(window);
