// USRP 게인·SNR 계산기 — 브라우저 안에서만 계산 (보내는 곳 없음)
(() => {
    const $ = (id) => document.getElementById(id);
    const log10 = Math.log10, dB = (x) => 10 * log10(x), undB = (x) => 10 ** (x / 10);
    const num = (id, d = 0) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : d; };
    const fx = (x, d = 1) => (Number.isFinite(x) ? x.toFixed(d) : '–');
    const sg = (x, d = 1) => (Number.isFinite(x) ? (x > 0 ? '+' : x < 0 ? '−' : '') + Math.abs(x).toFixed(d) : '–');
    const gstr = (g) => String(+g.toFixed(2));
    const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 무시 */ } } };
    const KEY = 'mj:usrp:last';

    // ── 장비 표 (대략값: Ettus 데이터시트·공개 측정, 주파수 MHz / 출력 dBm) ──
    // tx·rx = [최소, 최대, 단위], ptx = 최대 게인·0 dBFS 연속파 출력, fs0 = RX 게인 0 에서 0 dBFS 가 되는 입력
    const AD9361 = { tx: [0, 89.75, 0.25], rx: [0, 76, 1], f: [70, 6000], ptx: [[70, 10], [3000, 10], [4500, 6], [6000, 0]], nf: 8, fs0: -10, adc: 62, cap: 35, rxmax: -15 };
    const DEV = {
        b210: { ...AD9361, name: 'B200 / B210', args: 'type=b200', m: 'B210', mcr: 'b2', note: 'AD9361 · TX 0~89.75 dB (0.25 단위) · RX 0~76 dB · 출력 약 +10 dBm (5 GHz 위로 낮아짐) · NF < 8 dB' },
        b205: { ...AD9361, name: 'B200mini / B205mini', args: 'type=b200', m: 'B200', mcr: 'b2', note: 'AD9364 · B210 과 같은 게인 범위 · 출력 약 +10 dBm · MATLAB 은 B200 으로 잡혀요' },
        e310: { ...AD9361, name: 'E310 / E312', args: '', m: null, note: 'AD9361 · 장비 안에서 UHD 실행 · 출력 약 +10 dBm' },
        sbx: { tx: [0, 31.5, 0.5], rx: [0, 31.5, 0.5], f: [400, 4400], ptx: [[400, 20], [2000, 18], [3500, 15], [4400, 12]], nf: 6, fs0: -15, adc: 70, cap: 38, rxmax: -15, name: 'N210 · X310 + SBX-120', args: 'addr=192.168.10.2', m: 'N200/N210/USRP2', mcr: 100e6, note: 'TX·RX 0~31.5 dB (0.5 단위) · 출력 약 +16~20 dBm · NF 5~10 dB · X310 이면 MATLAB Platform 을 X310 으로' },
        ubx: { tx: [0, 31.5, 0.5], rx: [0, 31.5, 0.5], f: [10, 6000], ptx: [[10, 16], [1000, 20], [3000, 18], [4500, 14], [6000, 8]], nf: 6, fs0: -15, adc: 70, cap: 38, rxmax: -15, name: 'X310 · N210 + UBX-160', args: 'addr=192.168.40.2', m: 'X310', mcr: 200e6, note: 'TX·RX 0~31.5 dB (0.5 단위) · 출력 약 +15~20 dBm, 5 GHz 위로 낮아짐 · NF 4~8 dB' },
        n320: { tx: [0, 60, 1], rx: [0, 60, 1], f: [3, 6000], ptx: [[3, 15], [1000, 18], [3000, 18], [5000, 12], [6000, 8]], nf: 7, fs0: 0, adc: 66, cap: 40, rxmax: -15, name: 'N320 / N321', args: 'addr=192.168.10.2', m: 'N320/N321', mcr: 200e6, note: 'TX·RX 0~60 dB · 출력 최대 약 +18 dBm · NF 약 7 dB' },
        n310: { tx: [0, 65, 0.5], rx: [0, 75, 0.5], f: [10, 6000], ptx: [[10, 10], [3000, 10], [6000, 5]], nf: 8, fs0: 0, adc: 62, cap: 38, rxmax: -15, name: 'N310 / N300', args: 'addr=192.168.10.2', m: 'N310', mcr: 125e6, note: 'AD9371 · TX 0~65 dB · RX 0~75 dB · 출력 약 +10 dBm · N300 이면 MATLAB Platform 을 N300 으로' },
        x410: { tx: [0, 60, 1], rx: [0, 60, 1], f: [1, 7200], ptx: [[1, 15], [3000, 18], [6000, 15], [7200, 10]], nf: 8, fs0: 0, adc: 62, cap: 40, rxmax: -15, name: 'X410 (ZBX)', args: 'addr=192.168.10.2', m: null, note: 'ZBX · TX·RX 0~60 dB · 출력 약 +15~18 dBm' },
        custom: { tx: [0, 90, 0.25], rx: [0, 80, 0.5], f: [1, 100000], ptx: [[1, 10], [100000, 10]], nf: 8, fs0: -10, adc: 62, cap: 35, rxmax: -15, name: '직접 입력 (다른 장비)', args: '', m: null, note: '⚙️ 장비 값을 직접 넣으세요. 게인 범위는 최대 90 dB 로 둬요' },
    };
    const ADV = ['pmax', 'nf', 'fs0', 'adcsnr', 'cap', 'rxmax'];
    const mode = { path: 'cable', code: 'uhd' };
    let cal = { pmax: false, fs0: false };
    let last = null, rec = null;

    const dev = () => DEV[$('dev').value] || DEV.b210;
    $('dev').innerHTML = Object.entries(DEV).map(([k, d]) => `<option value="${k}">${d.name}</option>`).join('');

    function pmaxAt(d, fMHz) {
        const t = d.ptx;
        if (fMHz <= t[0][0]) return t[0][1];
        for (let i = 1; i < t.length; i++) if (fMHz <= t[i][0]) { const [f0, p0] = t[i - 1], [f1, p1] = t[i]; return p0 + (p1 - p0) * (fMHz - f0) / (f1 - f0); }
        return t[t.length - 1][1];
    }
    function fillDevice(keepCal) {
        const d = dev();
        if (!keepCal) cal = { pmax: false, fs0: false };
        if (!cal.pmax) $('pmax').value = fx(pmaxAt(d, num('f')), 1);
        if (!cal.fs0) $('fs0').value = d.fs0;
        $('nf').value = d.nf; $('adcsnr').value = d.adc; $('cap').value = d.cap; $('rxmax').value = d.rxmax;
        setRanges();
    }
    function setRanges() {
        const d = dev();
        for (const [k, r] of [['gtx', d.tx], ['grx', d.rx]]) {
            const s = $(`${k}-r`); s.min = r[0]; s.max = r[1]; s.step = r[2];
            $(k).min = r[0]; $(k).max = r[1]; $(k).step = r[2];
            $(`${k}-range`).textContent = `${r[0]}~${r[1]}, ${r[2]} 단위`;
        }
        $('dev-note').textContent = d.note;
    }
    const snap = (g, r) => Math.min(r[1], Math.max(r[0], r[0] + Math.round((g - r[0]) / r[2]) * r[2]));
    const snapDown = (g, r) => r[0] + Math.floor((g - r[0]) / r[2] + 1e-9) * r[2];

    // ── 계산 ──
    function params() {
        const d = dev(), fMHz = num('f', 1), fHz = fMHz * 1e6;
        const bw = Math.max(num('bw', 1), 1e-6) * 1e6, fs = Math.max(num('fs', 1), 1e-6) * 1e6;
        const amp = num('amp', 0.7), papr = Math.max(0, num('papr'));
        let loss, fspl = NaN;
        if (mode.path === 'cable') loss = num('att') + num('cable');
        else { const dist = Math.max(num('dist', 1), 1e-3); fspl = 20 * log10(dist) + 20 * log10(fHz) - 147.55; loss = fspl - num('gant-t') - num('gant-r') + num('extra'); }
        return { d, fMHz, fHz, bw, fs, amp, papr, loss, fspl, rmsFs: 20 * log10(Math.max(amp, 1e-6)) - papr, pmax: num('pmax'), nf: num('nf'), fs0: num('fs0'), adc: num('adcsnr', 60), cap: num('cap', 99), rxmax: num('rxmax', -15), head: num('head', 3), target: num('target', 20) };
    }
    function at(P, gtx, grx) {
        const ptx = P.pmax - (P.d.tx[1] - gtx) + P.rmsFs;      // TX 평균 출력
        const prx = ptx - P.loss;                                // RX 입력 평균
        const pfs = P.fs0 - grx;                                  // 0 dBFS 가 되는 입력
        const rxFs = prx - pfs, rxPk = rxFs + P.papr;
        const nTh = -174 + dB(P.bw) + P.nf;
        const nAdc = pfs - P.adc - dB(Math.max(P.fs / P.bw, 1));
        const nTot = dB(undB(nTh) + undB(nAdc));
        const snrLink = prx - nTot;
        const snr = -dB(undB(-snrLink) + undB(-P.cap));
        return { gtx, grx, ptx, prx, pfs, rxFs, rxPk, nTh, nAdc, nTot, snrLink, snr };
    }
    // 이 TX 게인에서 클리핑 안 나는 가장 큰 RX 게인 (범위 밑이면 NaN)
    function maxRx(P, gtx) {
        const prx = P.pmax - (P.d.tx[1] - gtx) + P.rmsFs - P.loss;
        const lim = P.fs0 - P.head - P.papr - prx;
        const r = P.d.rx;
        if (lim < r[0]) return NaN;
        return Math.min(r[1], snapDown(lim, r));
    }
    function gains(r) { const out = []; for (let g = r[0]; g <= r[1] + 1e-9; g += r[2]) out.push(+g.toFixed(4)); return out; }

    function recommend(P, cur) {
        const d = P.d, T = gains(d.tx), out = {};
        // ① 지금 RX 게인 그대로 → 필요한 TX 게인
        out.txOnly = T.find((g) => at(P, g, cur.grx).snr >= P.target);
        // ② 클리핑 없이 목표를 맞추는 가장 작은 TX 게인 + 그때 RX 게인 최대
        let best = null;
        for (const g of T) {
            const r = maxRx(P, g);
            if (!Number.isFinite(r)) continue;
            const o = at(P, g, r);
            if (!best || o.snr > best.snr + 1e-9) best = o;
            if (o.snr >= P.target) { out.combo = o; break; }
        }
        out.best = best;
        out.clipAll = !Number.isFinite(maxRx(P, d.tx[0]));
        if (out.clipAll) out.needAtt = (P.pmax - (d.tx[1] - d.tx[0]) + P.rmsFs - P.loss) - (P.fs0 - d.rx[0]) + P.papr + P.head;
        return out;
    }

    function calc() {
        const P = params(), d = P.d;
        const gtx = snap(num('gtx', d.tx[0]), d.tx), grx = snap(num('grx', d.rx[0]), d.rx);
        $('gtx-r').value = gtx; $('grx-r').value = grx;
        const o = at(P, gtx, grx);
        last = { P, o };
        $('o-rmsfs').textContent = `${fx(P.rmsFs, 1)} dBFS`;

        const clip = o.rxPk > 0, mg = o.snr - P.target;
        $('o-snr').textContent = `${fx(o.snr, 1)} dB`;
        $('o-snr').style.color = clip ? '#ef4444' : '';
        $('o-margin').textContent = clip ? '클리핑 ✕' : `${sg(mg)} dB`;
        $('o-margin').style.color = !clip && mg >= 0 ? '#16a34a' : '#ef4444';
        const stats = [
            ['TX 출력 (평균)', `${fx(o.ptx)} dBm`], ['TX 최대 순간', `${fx(o.ptx + P.papr)} dBm`],
            ['RX 입력 (평균)', `${fx(o.prx)} dBm`], ['RX ADC 평균 / 최대', `${fx(o.rxFs)} / ${fx(o.rxPk)} dBFS`],
            ['잡음 바닥 (대역 안)', `${fx(o.nTot)} dBm`], ['열잡음 / ADC 잡음', `${fx(o.nTh)} / ${fx(o.nAdc)}`],
            [mode.path === 'cable' ? '사이 손실' : '경로 손실 (FSPL)', mode.path === 'cable' ? `${fx(P.loss)} dB` : `${fx(P.fspl)} dB`], ['링크만의 SNR', `${fx(o.snrLink)} dB`],
        ];
        $('o-stats').innerHTML = stats.map(([k, v]) => `<div class="ug-stat"><p>${k}</p><p>${v}</p></div>`).join('');

        // 경고
        const W = [];
        if (P.fMHz < d.f[0] || P.fMHz > d.f[1]) W.push(['bad', `이 장비 주파수 범위(${d.f[0]}~${d.f[1]} MHz) 밖이에요.`]);
        if (P.bw > P.fs) W.push(['bad', '신호 대역폭이 샘플레이트보다 넓어요 — 샘플레이트를 대역폭보다 크게 두세요.']);
        if (o.prx + P.papr > P.rxmax) W.push(['bad', `RX 입력 최대 순간 ${fx(o.prx + P.papr)} dBm — 안전값 ${fx(P.rxmax, 0)} dBm 을 넘어요. 수신단이 망가질 수 있으니 감쇠기를 더 넣으세요.`]);
        if (o.rxPk > 0) W.push(['bad', `ADC 클리핑: 최대 순간이 ${sg(o.rxPk)} dBFS. RX 게인을 ${fx(o.rxPk + P.head, 1)} dB 이상 낮추세요 (클리핑이면 실제 SNR 은 이 계산보다 훨씬 나빠요).`]);
        else if (o.rxPk > -P.head) W.push(['mid', `ADC 여유 부족: 최대 순간 ${fx(o.rxPk)} dBFS (여유 ${fx(P.head, 0)} dB 보다 0 dBFS 에 가까움).`]);
        if (P.amp > 1) W.push(['bad', '진폭이 1.0 을 넘으면 fc32 → 정수 변환에서 잘려요.']);
        else if (P.amp > 0.9) W.push(['mid', '진폭이 0.9 넘음 — DAC 가 거의 꽉 차서 찌그러질 수 있어요. 0.5~0.8 + TX 게인으로 키우세요.']);
        if (gtx > d.tx[1] - 3 && P.papr >= 6) W.push(['mid', 'TX 게인 최대 근처 + PAPR 큰 신호 — 출력단이 포화돼 EVM 이 나빠질 수 있어요.']);
        if (o.rxFs < -60 && o.rxPk <= 0) W.push(['mid', `ADC 에 ${fx(o.rxFs)} dBFS 로 아주 작게 들어와요 — RX 게인을 올릴 여유가 커요.`]);
        if (mode.path === 'air') { const lam = 3e8 / P.fHz; if (num('dist') < 2 * lam) W.push(['mid', `거리가 파장(${fx(lam * 100, 1)} cm)의 2배보다 가까워 자유공간 식이 잘 안 맞아요.`]); }
        if (o.snr < P.target && o.snrLink > P.cap - 1) W.push(['mid', `송신기 자체 한계(${fx(P.cap, 0)} dB) 때문에 목표를 못 넘어요.`]);
        if (o.rxPk <= 0) {
            if (o.nAdc > o.nTh + 3) { const room = Number.isFinite(maxRx(P, gtx)) ? maxRx(P, gtx) - grx : 0; W.push(['ok', `지금은 ADC 잡음이 바닥을 정해요 → RX 게인을 올리면 SNR 이 올라요${room > 0 ? ` (클리핑 전까지 ${gstr(room)} dB 더)` : ''}.`]); }
            else if (o.nTh > o.nAdc + 3) W.push(['ok', '열잡음이 바닥을 정해요 → RX 게인을 더 올려도 SNR 은 거의 그대로. 받는 신호(TX 게인·안테나·감쇠)를 키우세요.']);
        }
        $('o-warn').innerHTML = W.map(([c, t]) => `<div class="ug-warn ${c}">${t}</div>`).join('');

        // 추천
        rec = recommend(P, { gtx, grx });
        const R = [];
        if (rec.clipAll) R.push(`⚠ TX·RX 게인을 둘 다 최소로 해도 ADC 가 넘쳐요. <b>감쇠를 ${fx(Math.ceil(rec.needAtt), 0)} dB 이상 더</b> 넣으세요.`);
        if (rec.txOnly !== undefined) R.push(`RX 게인 <b>${gstr(grx)} dB</b> 그대로면 → TX 게인 <b>${gstr(rec.txOnly)} dB</b> 이상 (그때 SNR ${fx(at(P, rec.txOnly, grx).snr)} dB${at(P, rec.txOnly, grx).rxPk > -P.head ? ', ⚠ ADC 여유 부족' : ''})`);
        else R.push(`RX 게인 ${gstr(grx)} dB 로는 TX 게인을 최대로 해도 SNR ${fx(at(P, d.tx[1], grx).snr)} dB 까지예요.`);
        if (rec.combo) R.push(`<b>추천 조합</b>: TX <b>${gstr(rec.combo.gtx)} dB</b> · RX <b>${gstr(rec.combo.grx)} dB</b> → SNR ${fx(rec.combo.snr)} dB, ADC 최대 ${fx(rec.combo.rxPk)} dBFS (TX 는 필요한 만큼만, RX 는 클리핑 안 나는 만큼 최대)`);
        else if (rec.best) {
            const short = P.target - rec.best.snr;
            const capLim = rec.best.snrLink > P.cap - 1;
            R.push(`클리핑 없이 낼 수 있는 최고 SNR 은 <b>${fx(rec.best.snr)} dB</b> (TX ${gstr(rec.best.gtx)} · RX ${gstr(rec.best.grx)}) — 목표보다 ${fx(short)} dB 모자라요. ${capLim ? '송신기 자체 SNR 한계(⚙️ 장비 값)에 걸려서 게인으로는 더 못 올려요 — 장비 실측 EVM 을 확인하세요.' : `받는 세기를 약 ${fx(Math.ceil(short), 0)} dB 키우세요 (${mode.path === 'cable' ? '감쇠기 줄이기' : '안테나 이득·거리 줄이기'}), 또는 대역폭을 줄이면 1/2 마다 3 dB 좋아져요.`}`);
        }
        const show = rec.combo || rec.best;
        $('rec-apply').disabled = !show; $('rec-apply').style.opacity = show ? 1 : 0.4;
        if (show && rec.combo && Math.abs(show.gtx - gtx) < 1e-9 && Math.abs(show.grx - grx) < 1e-9) R.push('✓ 지금 게인이 추천 조합이에요.');
        $('o-rec').innerHTML = R.map((t) => `<p>${t}</p>`).join('');

        drawMap(); drawLevels(); renderCode();
        save();
    }

    // ── 색 지도 ──
    const VIR = ['#440154', '#482878', '#3e4989', '#31688e', '#26828e', '#1f9e89', '#35b779', '#6ece58', '#b5de2b', '#fde725'];
    const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
    function cmap(t) {
        t = Math.min(1, Math.max(0, t)) * (VIR.length - 1);
        const i = Math.min(VIR.length - 2, Math.floor(t)), u = t - i, a = hex(VIR[i]), b = hex(VIR[i + 1]);
        return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * u)).join(',')})`;
    }
    function prep(cv) {
        const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
        cv.width = W * dpr; cv.height = H * dpr;
        const ctx = cv.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, W, H);
        const dark = document.documentElement.classList.contains('theme-dark');
        return { ctx, W, H, dark, ink: dark ? '#c7c7cc' : '#6e6e73', grid: dark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.07)', fg: dark ? '#f3f4f6' : '#1d1d1f' };
    }
    let mapGeo = null, hatch = null;
    function drawMap() {
        if (!last) return;
        const cv = $('ug-map'); const { ctx, W, H, ink, fg } = prep(cv);
        const { P } = last, d = P.d;
        const L = 46, R = 58, T = 10, B = 34, pw = W - L - R, ph = H - T - B;
        if (pw < 40 || ph < 40) return;
        const nx = Math.min(140, Math.round((d.tx[1] - d.tx[0]) / d.tx[2]) + 1), ny = Math.min(110, Math.round((d.rx[1] - d.rx[0]) / d.rx[2]) + 1);
        const gx = (i) => d.tx[0] + (d.tx[1] - d.tx[0]) * i / (nx - 1), gy = (j) => d.rx[0] + (d.rx[1] - d.rx[0]) * j / (ny - 1);
        const grid = [];
        let lo = Infinity, hi = -Infinity;
        for (let i = 0; i < nx; i++) { const col = []; for (let j = 0; j < ny; j++) { const o = at(P, gx(i), gy(j)); col.push(o); lo = Math.min(lo, o.snr); hi = Math.max(hi, o.snr); } grid.push(col); }
        if (hi - lo < 1) hi = lo + 1;
        const X = (g) => L + (g - d.tx[0]) / (d.tx[1] - d.tx[0]) * pw, Y = (g) => T + ph - (g - d.rx[0]) / (d.rx[1] - d.rx[0]) * ph;
        const cw = pw / nx, ch = ph / ny;
        if (!hatch) {
            const pc = document.createElement('canvas'); pc.width = pc.height = 8; const p = pc.getContext('2d');
            p.fillStyle = 'rgba(239,68,68,0.45)'; p.fillRect(0, 0, 8, 8); p.strokeStyle = 'rgba(185,28,28,0.9)'; p.lineWidth = 1.5;
            p.beginPath(); p.moveTo(0, 8); p.lineTo(8, 0); p.moveTo(-2, 2); p.lineTo(2, -2); p.moveTo(6, 10); p.lineTo(10, 6); p.stroke();
            hatch = ctx.createPattern(pc, 'repeat');
        }
        for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) {
            const o = grid[i][j], x0 = L + i * cw, y0 = T + ph - (j + 1) * ch;
            ctx.fillStyle = cmap((o.snr - lo) / (hi - lo)); ctx.fillRect(x0, y0, cw + 0.6, ch + 0.6);
            if (o.rxPk > 0) { ctx.fillStyle = hatch; ctx.fillRect(x0, y0, cw + 0.6, ch + 0.6); }
        }
        // 목표 등고선 (마칭 스퀘어 — 표본 점은 칸 가운데)
        ctx.strokeStyle = '#f97316'; ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.beginPath();
        const cx = (i) => L + (i + 0.5) * cw, cy = (j) => T + ph - (j + 0.5) * ch, tg = P.target;
        for (let i = 0; i < nx - 1; i++) for (let j = 0; j < ny - 1; j++) {
            const v = [grid[i][j].snr, grid[i + 1][j].snr, grid[i + 1][j + 1].snr, grid[i][j + 1].snr];
            const c = [[cx(i), cy(j)], [cx(i + 1), cy(j)], [cx(i + 1), cy(j + 1)], [cx(i), cy(j + 1)]];
            const pts = [];
            for (let k = 0; k < 4; k++) {
                const a = v[k], b = v[(k + 1) % 4];
                if ((a < tg) !== (b < tg)) { const u = (tg - a) / (b - a), p0 = c[k], p1 = c[(k + 1) % 4]; pts.push([p0[0] + (p1[0] - p0[0]) * u, p0[1] + (p1[1] - p0[1]) * u]); }
            }
            for (let k = 0; k + 1 < pts.length; k += 2) { ctx.moveTo(pts[k][0], pts[k][1]); ctx.lineTo(pts[k + 1][0], pts[k + 1][1]); }
        }
        ctx.stroke(); ctx.lineCap = 'butt';
        // 축
        ctx.font = '11px -apple-system, sans-serif'; ctx.fillStyle = ink; ctx.strokeStyle = ink; ctx.lineWidth = 1;
        ctx.strokeRect(L, T, pw, ph);
        const ticks = (a, b) => { const span = b - a, st = [1, 2, 5, 10, 20, 25, 50].find((s) => span / s <= 8) || 50; const t = []; for (let v = Math.ceil(a / st) * st; v <= b + 1e-9; v += st) t.push(v); return t; };
        ctx.textAlign = 'center'; for (const v of ticks(d.tx[0], d.tx[1])) ctx.fillText(v, X(v), T + ph + 14);
        ctx.fillText('TX 게인 (dB)', L + pw / 2, H - 4);
        ctx.textAlign = 'right'; for (const v of ticks(d.rx[0], d.rx[1])) ctx.fillText(v, L - 5, Y(v) + 4);
        ctx.save(); ctx.translate(11, T + ph / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = 'center'; ctx.fillText('RX 게인 (dB)', 0, 0); ctx.restore();
        // 색 막대
        const bx = W - R + 12, bwid = 10;
        for (let k = 0; k < ph; k++) { ctx.fillStyle = cmap(1 - k / ph); ctx.fillRect(bx, T + k, bwid, 1.5); }
        ctx.textAlign = 'left'; ctx.fillStyle = ink;
        ctx.fillText(fx(hi, 0), bx + bwid + 3, T + 9); ctx.fillText(fx(lo, 0), bx + bwid + 3, T + ph);
        if (P.target > lo && P.target < hi) { const ty = T + (hi - P.target) / (hi - lo) * ph; ctx.fillStyle = '#f97316'; ctx.fillRect(bx - 3, ty - 1, bwid + 6, 2); ctx.fillText(fx(P.target, 0), bx + bwid + 3, ty + 4); }
        ctx.fillStyle = ink; ctx.fillText('SNR dB', bx - 8, H - 4);
        // 점
        const dot = (gt, gr, fill, r) => { ctx.beginPath(); ctx.arc(X(gt), Y(gr), r, 0, Math.PI * 2); ctx.fillStyle = fill; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke(); };
        if (rec && (rec.combo || rec.best)) { const c = rec.combo || rec.best; ctx.save(); ctx.translate(X(c.gtx), Y(c.grx)); ctx.rotate(Math.PI / 4); ctx.fillStyle = '#f97316'; ctx.fillRect(-5, -5, 10, 10); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.strokeRect(-5, -5, 10, 10); ctx.restore(); }
        dot(last.o.gtx, last.o.grx, '#ef4444', 6);
        mapGeo = { L, T, pw, ph, d };
        ctx.fillStyle = fg;
    }
    const mapHint = () => document.querySelector('#ug-map').previousElementSibling.querySelector('span');
    let hintText = null;
    function mapGain(e) {
        if (!mapGeo) return null;
        const r = $('ug-map').getBoundingClientRect(), { L, T, pw, ph, d } = mapGeo;
        const x = e.clientX - r.left, y = e.clientY - r.top;
        if (x < L || x > L + pw || y < T || y > T + ph) return null;
        return [snap(d.tx[0] + (x - L) / pw * (d.tx[1] - d.tx[0]), d.tx), snap(d.rx[0] + (T + ph - y) / ph * (d.rx[1] - d.rx[0]), d.rx)];
    }
    $('ug-map').addEventListener('pointermove', (e) => {
        const g = mapGain(e), h = mapHint(); if (hintText === null) hintText = h.textContent;
        if (!g) { h.textContent = hintText; return; }
        const o = at(last.P, g[0], g[1]);
        h.textContent = `TX ${gstr(g[0])} · RX ${gstr(g[1])} → SNR ${fx(o.snr)} dB · ADC 최대 ${fx(o.rxPk)} dBFS${o.rxPk > 0 ? ' (클리핑)' : ''}`;
    });
    $('ug-map').addEventListener('pointerleave', () => { if (hintText !== null) mapHint().textContent = hintText; });
    $('ug-map').addEventListener('click', (e) => { const g = mapGain(e); if (!g) return; $('gtx').value = gstr(g[0]); $('grx').value = gstr(g[1]); calc(); });

    // ── 세기 사다리 ──
    function drawLevels() {
        if (!last) return;
        const cv = $('ug-lvl'); const { ctx, W, H, ink, grid, fg } = prep(cv);
        const { P, o } = last;
        const items = [o.ptx, o.ptx + P.papr, o.prx, o.prx + P.papr, o.pfs, o.nTh, o.nAdc, o.nTot];
        if (P.rxmax < o.prx + P.papr + 25) items.push(P.rxmax);
        let hi = Math.max(...items), lo = Math.min(...items);
        const pad = (hi - lo) * 0.06 + 2; hi += pad; lo -= pad;
        const L = 46, Rr = 8, T = 10, B = 26, ph = H - T - B;
        const Y = (v) => T + (hi - v) / (hi - lo) * ph;
        ctx.font = '11px -apple-system, sans-serif'; ctx.lineWidth = 1;
        const st = [5, 10, 20, 25, 50].find((s) => (hi - lo) / s <= 9) || 50;
        for (let v = Math.ceil(lo / st) * st; v <= hi; v += st) { ctx.strokeStyle = grid; ctx.beginPath(); ctx.moveTo(L, Y(v)); ctx.lineTo(W - Rr, Y(v)); ctx.stroke(); ctx.fillStyle = ink; ctx.textAlign = 'right'; ctx.fillText(v, L - 5, Y(v) + 4); }
        const av = Math.max(120, W - L - Rr - 160), xT = L + 8, wT = Math.min(70, av * 0.24), xR = xT + wT + Math.max(36, av * 0.3), wR = Math.min(96, av * 0.34);
        ctx.textAlign = 'center'; ctx.fillStyle = ink;
        ctx.fillText('TX 출력', xT + wT / 2, H - 8); ctx.fillText('RX 입력', xR + wR / 2, H - 8);
        const labels = [];
        const hline = (x0, x1, v, color, dash, text, w = 2) => { ctx.setLineDash(dash || []); ctx.strokeStyle = color; ctx.lineWidth = w; ctx.beginPath(); ctx.moveTo(x0, Y(v)); ctx.lineTo(x1, Y(v)); ctx.stroke(); ctx.setLineDash([]); if (text) labels.push({ y: Y(v), text, color }); };
        // TX 막대
        ctx.fillStyle = 'rgba(0,102,204,0.18)'; ctx.fillRect(xT, Y(o.ptx), wT, Y(lo) - Y(o.ptx));
        hline(xT, xT + wT, o.ptx, '#0066cc'); hline(xT, xT + wT, o.ptx + P.papr, '#0066cc', [3, 3], null, 1);
        ctx.fillStyle = fg; ctx.textAlign = 'center'; ctx.fillText(`${fx(o.ptx)} dBm`, xT + wT / 2, Y(o.ptx + P.papr) - 5);
        // 손실 화살표
        ctx.strokeStyle = ink; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(xT + wT + 4, Y(o.ptx)); ctx.lineTo(xR - 6, Y(o.prx)); ctx.stroke();
        const ax = xR - 6, ay = Y(o.prx), ang = Math.atan2(Y(o.prx) - Y(o.ptx), xR - 6 - (xT + wT + 4));
        ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(ax - 7 * Math.cos(ang - 0.4), ay - 7 * Math.sin(ang - 0.4)); ctx.lineTo(ax - 7 * Math.cos(ang + 0.4), ay - 7 * Math.sin(ang + 0.4)); ctx.closePath(); ctx.fillStyle = ink; ctx.fill();
        ctx.fillStyle = ink; ctx.textAlign = 'center'; ctx.fillText(`−${fx(P.loss)} dB`, (xT + wT + xR) / 2, (Y(o.ptx) + Y(o.prx)) / 2 - 6);
        // RX
        ctx.fillStyle = 'rgba(0,102,204,0.18)'; ctx.fillRect(xR, Y(o.prx), wR, Y(lo) - Y(o.prx));
        ctx.fillStyle = 'rgba(142,142,147,0.25)'; ctx.fillRect(xR, Y(o.nTot), wR, Y(lo) - Y(o.nTot));
        const xe = Math.max(xR + wR + 16, W - Rr - 154);
        hline(xR, xe, o.pfs, '#ef4444', null, `0 dBFS (ADC 꽉 참) ${fx(o.pfs)}`);
        hline(xR, xe, o.pfs - P.head, '#ef4444', [4, 4], null, 1);
        if (items.includes(P.rxmax) && P.rxmax <= hi) hline(xR, xe, P.rxmax, '#7f1d1d', [6, 3], `RX 안전 한계 ${fx(P.rxmax, 0)}`, 1.5);
        hline(xR, xe, o.prx + P.papr, '#0066cc', [3, 3], `신호 최대 순간 ${fx(o.prx + P.papr)}`, 1);
        hline(xR, xe, o.prx, '#0066cc', null, `신호 평균 ${fx(o.prx)}`);
        hline(xR, xe, o.nTot, '#8e8e93', null, `잡음 합 ${fx(o.nTot)}`);
        hline(xR + wR, xe, o.nTh, '#16a34a', [5, 3], `열잡음 kTB+NF ${fx(o.nTh)}`, 1.3);
        hline(xR + wR, xe, o.nAdc, '#a855f7', [5, 3], `ADC 잡음 ${fx(o.nAdc)}`, 1.3);
        // SNR 괄호 + 막대 안에 글자
        const sx = xR + wR + 7;
        ctx.strokeStyle = fg; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(sx - 4, Y(o.prx)); ctx.lineTo(sx, Y(o.prx)); ctx.lineTo(sx, Y(o.nTot)); ctx.lineTo(sx - 4, Y(o.nTot)); ctx.stroke();
        if (Y(o.nTot) - Y(o.prx) > 30) {
            ctx.fillStyle = fg; ctx.textAlign = 'center'; ctx.font = '600 12px -apple-system, sans-serif';
            const my = (Y(o.prx) + Y(o.nTot)) / 2;
            ctx.fillText('SNR', xR + wR / 2, my - 3); ctx.fillText(`${fx(o.snrLink)} dB`, xR + wR / 2, my + 12);
        } else labels.push({ y: (Y(o.prx) + Y(o.nTot)) / 2, text: `SNR ${fx(o.snrLink)} dB`, color: fg });
        // 이름표 겹침 풀기
        ctx.font = '11px -apple-system, sans-serif';
        labels.sort((a, b) => a.y - b.y);
        for (let i = 1; i < labels.length; i++) if (labels[i].y < labels[i - 1].y + 13) labels[i].y = labels[i - 1].y + 13;
        const over = labels.length ? labels[labels.length - 1].y - (H - B) : 0;
        if (over > 0) labels.forEach((l) => { l.y -= over; });
        for (const l of labels) { ctx.fillStyle = l.color; ctx.textAlign = 'left'; ctx.fillText(l.text, xe + 6, l.y + 4); }
        ctx.fillStyle = ink; ctx.textAlign = 'left'; ctx.fillText('dBm', 4, T + 4);
    }

    // ── 코드 ──
    function renderCode() {
        if (!last) return;
        const { P, o } = last, d = P.d;
        const fc = `${+(P.fHz / 1e6).toFixed(6)}e6`, fs = `${+(P.fs / 1e6).toFixed(6)}e6`;
        const args = d.args || '';
        const gt = gstr(o.gtx), gr = gstr(o.grx);
        const note = `예상: TX 평균 ${fx(o.ptx)} dBm · RX ${fx(o.rxFs)} dBFS (최대 ${fx(o.rxPk)}) · SNR ${fx(o.snr)} dB`;
        let s;
        if (mode.code === 'uhd') {
            s = `import numpy as np
import uhd

usrp = uhd.usrp.MultiUSRP("${args}")   # 자기 장비 주소로 (예: "serial=...", "addr=...")
fc, fs = ${fc}, ${fs}

usrp.set_tx_rate(fs, 0)
usrp.set_tx_freq(uhd.types.TuneRequest(fc), 0)
usrp.set_tx_gain(${gt}, 0)
usrp.set_rx_rate(fs, 0)
usrp.set_rx_freq(uhd.types.TuneRequest(fc), 0)
usrp.set_rx_gain(${gr}, 0)
# ${note}

# 보내기 전에 최대 진폭을 ${P.amp} 로 맞추기 (fc32 는 ±1.0 이 DAC 꽉 참)
# tx = tx / np.max(np.abs(tx)) * ${P.amp}
# usrp.send_waveform(tx, 1.0, fc, fs, [0], ${gt})

# 받은 세기 확인 → 계산기 📏 RX 보정에 넣기
rx = usrp.recv_num_samps(int(fs * 0.1), fc, fs, [0], ${gr})
print("RX 평균 dBFS:", 10 * np.log10(np.mean(np.abs(rx[0]) ** 2)))
print("RX 최대 dBFS:", 20 * np.log10(np.max(np.abs(rx[0]))))

# (UHD 4 이상 + 전력 보정 데이터가 있는 장비만) 게인 대신 dBm 으로:
# if usrp.has_tx_power_reference(0):
#     usrp.set_tx_power_reference(${fx(o.ptx)}, 0)
`;
        } else if (mode.code === 'grc') {
            s = `from gnuradio import uhd

fc, fs = ${fc}, ${fs}
sink = uhd.usrp_sink("${args}", uhd.stream_args(cpu_format="fc32", channels=[0]))
sink.set_samp_rate(fs)
sink.set_center_freq(fc, 0)
sink.set_gain(${gt}, 0)

src = uhd.usrp_source("${args}", uhd.stream_args(cpu_format="fc32", channels=[0]))
src.set_samp_rate(fs)
src.set_center_freq(fc, 0)
src.set_gain(${gr}, 0)
# ${note}

# GRC 블록에서는:
#   UHD: USRP Sink   → RF Options → Ch0: Gain Value = ${gt}, Gain Type = Absolute (dB)
#   UHD: USRP Source → RF Options → Ch0: Gain Value = ${gr}, Gain Type = Absolute (dB)
#   Sink 앞에 Multiply Const 로 최대 진폭을 ${P.amp} 로 맞추기
`;
        } else {
            if (!d.m) {
                s = `% ${d.name} 은(는) comm.SDRuTransmitter / comm.SDRuReceiver 가 지원하지 않아요.
% (E310 은 장비 안에서 UHD, X410 은 Wireless Testbench) — UHD Python 코드를 쓰세요.
% 게인: TX ${gt} dB, RX ${gr} dB
% ${note}
`;
            } else {
                let mcr, k, warn = '';
                if (d.mcr === 'b2') { k = Math.max(1, Math.ceil(5e6 / P.fs)); mcr = P.fs * k; if (mcr > 56e6) warn = '% ⚠ 샘플레이트가 B2xx 최대(56 MHz)를 넘어요\n'; }
                else { mcr = d.mcr; k = mcr / P.fs; if (Math.abs(k - Math.round(k)) > 1e-6) warn = `% ⚠ ${mcr / 1e6} MHz / 샘플레이트 가 정수가 아니에요 — 샘플레이트를 나누어떨어지게 바꾸세요\n`; k = Math.round(k); }
                const id = d.mcr === 'b2' ? `'SerialNum', '여기에_시리얼'` : `'IPAddress', '${(d.args.split('=')[1] || '192.168.10.2')}'`;
                s = `fc = ${fc};  fs = ${fs};
mcr = ${+(mcr / 1e6).toFixed(6)}e6;   % MasterClockRate (fs 의 정수배)
${warn}tx = comm.SDRuTransmitter('Platform', '${d.m}', ${id}, ...
    'CenterFrequency', fc, 'Gain', ${gt}, ...
    'MasterClockRate', mcr, 'InterpolationFactor', ${k});
rx = comm.SDRuReceiver('Platform', '${d.m}', ${id}, ...
    'CenterFrequency', fc, 'Gain', ${gr}, ...
    'MasterClockRate', mcr, 'DecimationFactor', ${k}, ...
    'OutputDataType', 'double', 'SamplesPerFrame', 20000);
% ${note}

% sig = sig / max(abs(sig)) * ${P.amp};   % 보내기 전에 최대 진폭 맞추기
% tx(sig);  y = rx();
% 10*log10(mean(abs(y).^2))      % 받은 평균 dBFS → 계산기 📏 RX 보정에 넣기
`;
            }
        }
        $('o-code').textContent = s;
    }
    $('code-copy').addEventListener('click', async (e) => {
        const b = e.target, t = $('o-code').textContent;
        try { await navigator.clipboard.writeText(t); const o = b.textContent; b.textContent = '✓ 복사됨'; setTimeout(() => { b.textContent = o; }, 1200); } catch (err) { window.prompt('복사하세요', t); }
    });

    // ── 모드 버튼 ──
    function setSeg(id, v) { document.querySelectorAll(`#${id} button`).forEach((b) => b.classList.toggle('is-on', b.dataset.v === v)); }
    function showPath() {
        setSeg('m-path', mode.path);
        document.querySelectorAll('[data-path]').forEach((el) => { const on = el.dataset.path === mode.path; el.classList.toggle('hidden', !on); el.classList.toggle('grid', on); });
    }
    $('m-path').addEventListener('click', (e) => { const v = e.target.dataset.v; if (!v) return; mode.path = v; showPath(); calc(); });
    $('m-code').addEventListener('click', (e) => { const v = e.target.dataset.v; if (!v) return; mode.code = v; setSeg('m-code', v); renderCode(); save(); });

    // ── 입력 연결 ──
    for (const k of ['gtx', 'grx']) $(`${k}-r`).addEventListener('input', (e) => { $(k).value = e.target.value; calc(); });
    $('papr-p').addEventListener('change', () => { const v = $('papr-p').value; if (v !== 'x') $('papr').value = v; calc(); });
    $('papr').addEventListener('input', () => { const v = $('papr').value, opt = [...$('papr-p').options].find((o) => o.value === v); $('papr-p').value = opt ? v : 'x'; });
    $('dev').addEventListener('change', () => {
        fillDevice(false);
        const d = dev(); $('gtx').value = gstr(snap(num('gtx'), d.tx)); $('grx').value = gstr(snap(num('grx'), d.rx));
        markCal(); calc();
        const c = rec && (rec.combo || rec.best);  // 범위가 달라졌으니 추천 게인으로
        if (c) { $('gtx').value = gstr(c.gtx); $('grx').value = gstr(c.grx); calc(); }
    });
    $('f').addEventListener('input', () => { if (!cal.pmax) $('pmax').value = fx(pmaxAt(dev(), num('f')), 1); });
    $('dev-reset').addEventListener('click', () => { fillDevice(false); markCal(); calc(); });
    $('pmax').addEventListener('input', () => { cal.pmax = true; markCal(); });
    $('fs0').addEventListener('input', () => { cal.fs0 = true; markCal(); });
    function markCal() { $('pmax').classList.toggle('is-cal', cal.pmax); $('fs0').classList.toggle('is-cal', cal.fs0); }
    $('ctx-go').addEventListener('click', () => {
        const g = parseFloat($('ctx-g').value), p = parseFloat($('ctx-p').value);
        if (!Number.isFinite(g) || !Number.isFinite(p)) return;
        const P = params();
        $('pmax').value = fx(p - P.rmsFs + (P.d.tx[1] - g), 1); cal.pmax = true; markCal(); calc();
    });
    $('crx-go').addEventListener('click', () => {
        const g = parseFloat($('crx-g').value), p = parseFloat($('crx-p').value), x = parseFloat($('crx-x').value);
        if (![g, p, x].every(Number.isFinite)) return;
        $('fs0').value = fx(p - x + g, 1); cal.fs0 = true; markCal(); calc();
    });
    $('rec-apply').addEventListener('click', () => { const c = rec && (rec.combo || rec.best); if (!c) return; $('gtx').value = gstr(c.gtx); $('grx').value = gstr(c.grx); calc(); });

    const IDS = ['dev', 'f', 'fs', 'bw', 'target', 'gtx', 'grx', 'amp', 'papr', 'att', 'cable', 'dist', 'gant-t', 'gant-r', 'extra', 'head', ...ADV];
    const CAL_IDS = ['ctx-g', 'ctx-p', 'crx-g', 'crx-p', 'crx-x'];
    document.querySelector('main').addEventListener('input', (e) => { if (IDS.includes(e.target.id) && e.target.id !== 'dev') calc(); });
    function save() { const o = { mode: { ...mode }, cal: { ...cal } }; [...IDS, ...CAL_IDS].forEach((id) => { o[id] = $(id).value; }); store.set(KEY, o); }

    let resizeT = 0;
    window.addEventListener('resize', () => { clearTimeout(resizeT); resizeT = setTimeout(() => { drawMap(); drawLevels(); }, 80); });
    new MutationObserver(() => { drawMap(); drawLevels(); }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });

    // ── 시작 ──
    const saved = store.get(KEY, null);
    if (saved && DEV[saved.dev]) {
        $('dev').value = saved.dev; fillDevice(false);
        [...IDS, ...CAL_IDS].forEach((id) => { if (saved[id] !== undefined && id !== 'dev') $(id).value = saved[id]; });
        Object.assign(mode, saved.mode || {}); cal = { pmax: false, fs0: false, ...(saved.cal || {}) };
        const opt = [...$('papr-p').options].find((o) => o.value === $('papr').value); $('papr-p').value = opt ? opt.value : 'x';
    } else {
        $('dev').value = 'b210'; fillDevice(false);
        $('gtx').value = 60; $('grx').value = 30;
    }
    setRanges(); showPath(); setSeg('m-code', mode.code); markCal(); calc();
    window.__usrp = { DEV, at, params, recommend, maxRx, pmaxAt, get last() { return last; }, get rec() { return rec; } };
})();
