// 🛰 지금 하늘 — 실제 위성(TLE)을 SGP4(satellite.js)로 돌려서 지도·하늘 그림·지나가는 시각을 보여 줌
(() => {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const root = $('sky-root');
    if (!root) return;
    const SAT = window.MJSat;
    const { fmt, fmtHz } = SAT.fmt;
    const DEG = Math.PI / 180, R = SAT.R, C = SAT.C;
    const tleUrl = root.dataset.tleUrl;
    let sj = null, land = null;   // satellite.js, 육지 모양

    const state = {
        sats: [], sel: -1, pos: [], posAt: 0,
        obs: { lat: 37.5665, lon: 126.978, name: '서울' },
        minEl: 10, fGHz: 2, speed: 1, simBase: Date.now(), realBase: Date.now(),
        passes: null, passesFor: null,
    };
    const now = () => new Date(state.simBase + (Date.now() - state.realBase) * state.speed);
    const isDark = () => document.documentElement.classList.contains('theme-dark');
    const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

    function loadScript(src) {
        return new Promise((ok, no) => { const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = no; document.head.appendChild(s); });
    }
    let booted = null;
    function boot() {
        if (booted) return booted;
        booted = (async () => {
            msg('위성 계산 도구를 불러오는 중…');
            await Promise.all([
                loadScript('https://cdn.jsdelivr.net/npm/satellite.js@5.0.0/dist/satellite.min.js'),
                loadScript('https://cdn.jsdelivr.net/npm/topojson-client@3.1.0/dist/topojson-client.min.js'),
            ]);
            sj = window.satellite;
            try {
                const world = await fetch('https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/land-110m.json').then((r) => r.json());
                land = window.topojson.feature(world, world.objects.land);
            } catch { land = null; }
            await loadGroup($('sky-group').value);
            setInterval(tick, 1000);
        })().catch(() => msg('위성 계산 도구를 불러오지 못했어요. 새로 고침해 주세요.', true));
        return booted;
    }
    SAT.bootSky = boot;

    function msg(text, bad) { $('sky-msg').textContent = text || ''; $('sky-msg').style.color = bad ? '#c4271d' : ''; }

    // ── 위성 자료
    function makeSats(list) {
        const out = [];
        for (const t of list) {
            try {
                const rec = sj.twoline2satrec(t.l1, t.l2);
                if (rec.error) continue;
                out.push({ name: t.name, rec, id: rec.satnum, revDay: rec.no * 1440 / (2 * Math.PI) });
            } catch { /* 깨진 TLE 는 건너뜀 */ }
        }
        return out;
    }
    async function fetchTle(query) {
        const r = await fetch(`${tleUrl}?${query}`);
        const d = await r.json().catch(() => ({ error: '궤도 자료를 받지 못했어요.' }));
        if (!r.ok) throw new Error(d.error || '궤도 자료를 받지 못했어요.');
        state.fetched = d.fetched ? new Date(d.fetched) : null;
        state.source = 'CelesTrak 궤도 자료(TLE)';
        return d.sats;
    }
    async function loadGroup(group) {
        msg('궤도 자료를 받는 중…');
        try {
            setSats(makeSats(await fetchTle(`group=${encodeURIComponent(group)}`)), group === 'stations' ? (s) => /ISS \(ZARYA\)/.test(s.name) : null);
        } catch (e) { msg(e.message, true); }
    }
    function setSats(list, pick) {
        state.sats = list;
        state.sel = pick ? Math.max(0, list.findIndex(pick)) : (list.length ? 0 : -1);
        state.posAt = 0; state.passes = null;
        const when = state.fetched ? ` · ${state.fetched.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} 자료` : '';
        msg(list.length ? `${list.length.toLocaleString()}기 · ${state.source}${when}, SGP4 로 계산` : '위성이 없어요.', !list.length);
        tick(true);
    }
    $('sky-group').addEventListener('change', () => loadGroup($('sky-group').value));
    $('sky-search').addEventListener('submit', async (e) => {
        e.preventDefault();
        const q = $('sky-q').value.trim();
        if (!q) return;
        msg('찾는 중…');
        try {
            const list = makeSats(await fetchTle(/^\d+$/.test(q) ? `catnr=${q}` : `name=${encodeURIComponent(q)}`));
            setSats(list);
        } catch (err) { msg(err.message, true); }
    });
    $('sky-paste-go').addEventListener('click', () => {
        const lines = $('sky-paste').value.split(/\r?\n/).map((l) => l.trimEnd()).filter(Boolean);
        const list = [];
        for (let i = 0; i < lines.length; i++) {
            if (lines[i].startsWith('1 ') && lines[i + 1]?.startsWith('2 ')) {
                const name = i > 0 && !lines[i - 1].startsWith('2 ') ? lines[i - 1].replace(/^0 /, '') : `위성 ${list.length + 1}`;
                list.push({ name, l1: lines[i], l2: lines[i + 1] });
                i++;
            }
        }
        const sats = makeSats(list);
        state.fetched = null;
        state.source = '붙여 넣은 TLE';
        if (!sats.length) { msg('TLE 를 읽지 못했어요. 이름 줄 + "1 …" + "2 …" 세 줄씩 붙여 넣어 주세요.', true); return; }
        setSats(sats);
    });

    // ── 관측 위치 · 설정
    function readObs() {
        const lat = +$('sky-lat').value, lon = +$('sky-lon').value;
        if (Math.abs(lat) <= 90 && Math.abs(lon) <= 180) { state.obs.lat = lat; state.obs.lon = lon; }
        state.minEl = Math.min(80, Math.max(0, +$('sky-minel').value || 0));
        state.fGHz = Math.max(0.001, +$('sky-f').value || 2);
        state.posAt = 0; state.passes = null;
        tick(true);
    }
    ['sky-lat', 'sky-lon', 'sky-minel', 'sky-f'].forEach((id) => $(id).addEventListener('change', readObs));
    $('sky-here').addEventListener('click', () => {
        navigator.geolocation?.getCurrentPosition((p) => {
            $('sky-lat').value = p.coords.latitude.toFixed(4);
            $('sky-lon').value = p.coords.longitude.toFixed(4);
            readObs();
        }, () => msg('위치를 받지 못했어요. 위도·경도를 직접 넣어 주세요.', true));
    });
    $('sky-speed').addEventListener('change', () => {
        state.simBase = now().getTime(); state.realBase = Date.now();
        state.speed = +$('sky-speed').value;
        state.passes = null;
    });
    $('sky-reset').addEventListener('click', () => { state.simBase = Date.now(); state.realBase = Date.now(); state.posAt = 0; state.passes = null; tick(true); });

    // ── 계산
    function observerGd() { return { latitude: state.obs.lat * DEG, longitude: state.obs.lon * DEG, height: 0 }; }
    function where(s, date, gmst) {
        const pv = sj.propagate(s.rec, date);
        if (!pv || !pv.position || typeof pv.position === 'boolean' || !Number.isFinite(pv.position.x)) return null;
        const gd = sj.eciToGeodetic(pv.position, gmst);
        const ecf = sj.eciToEcf(pv.position, gmst);
        const look = sj.ecfToLookAngles(observerGd(), ecf);
        const v = pv.velocity ? Math.hypot(pv.velocity.x, pv.velocity.y, pv.velocity.z) : NaN;
        return { lat: gd.latitude / DEG, lon: sj.degreesLong(gd.longitude), h: gd.height, az: look.azimuth / DEG, el: look.elevation / DEG, range: look.rangeSat, v };
    }
    function at(s, date) { return where(s, date, sj.gstime(date)); }
    function allPositions(date) {
        const gmst = sj.gstime(date);
        state.pos = state.sats.map((s) => where(s, date, gmst));
        state.posAt = Date.now();
    }

    // 다음 24시간 지나가는 시각 (60초 간격으로 찾고 1초까지 좁힘)
    function findPasses(s, from) {
        if (s.revDay < 1.5) return { geo: true };
        const step = 60e3, end = from.getTime() + 24 * 3600e3, out = [];
        const el = (t) => at(s, new Date(t))?.el ?? -90;
        const edge = (a, b, rising) => {
            for (let k = 0; k < 12; k++) { const m = (a + b) / 2; ((el(m) >= state.minEl) === rising) ? (b = m) : (a = m); }
            return b;
        };
        let t = from.getTime(), prev = el(t), cur = null;
        if (prev >= state.minEl) cur = { aos: t, max: prev, maxAt: t, partial: true };
        while (t < end && out.length < 8) {
            const t2 = t + step, e2 = el(t2);
            if (!cur && e2 >= state.minEl && prev < state.minEl) cur = { aos: edge(t, t2, true), max: e2, maxAt: t2 };
            if (cur) {
                if (e2 > cur.max) { cur.max = e2; cur.maxAt = t2; }
                if (e2 < state.minEl) { cur.los = edge(t, t2, false); out.push(cur); cur = null; }
            }
            t = t2; prev = e2;
        }
        return { list: out };
    }

    // ── 그리기: 지도
    const map = $('sky-map'), sky = $('sky-polar');
    let mapPts = [];
    function setupCanvas(cv, w, h) {
        const dpr = window.devicePixelRatio || 1;
        cv.width = w * dpr; cv.height = h * dpr;
        const g = cv.getContext('2d');
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        return g;
    }
    function drawRing(g, X, Y, ring, { fill, stroke, closePole }) {
        // 날짜 변경선을 넘는 고리는 경도를 이어 붙이고 왼쪽·가운데·오른쪽 세 번 그림
        const pts = [];
        let off = 0;
        ring.forEach(([lon, lat], i) => {
            if (i) { const d = lon - ring[i - 1][0]; if (d > 180) off -= 360; else if (d < -180) off += 360; }
            pts.push([lon + off, lat]);
        });
        const span = Math.abs(pts[pts.length - 1][0] - pts[0][0]);
        if (closePole && span > 300) {
            const pole = closePole === 'auto' ? (pts.reduce((s, p) => s + p[1], 0) < 0 ? -90 : 90) : closePole;
            pts.push([pts[pts.length - 1][0], pole], [pts[0][0], pole]);
        }
        for (const shift of [-360, 0, 360]) {
            g.beginPath();
            pts.forEach(([lon, lat], i) => { const x = X(lon + shift), y = Y(lat); i ? g.lineTo(x, y) : g.moveTo(x, y); });
            if (fill) { g.fillStyle = fill; g.fill(); }
            if (stroke) { g.strokeStyle = stroke; g.stroke(); }
        }
    }
    function footprint(p) {
        const e = state.minEl * DEG;
        const lam = Math.acos(R * Math.cos(e) / (R + p.h)) - e;
        if (!(lam > 0)) return null;
        const la1 = p.lat * DEG, lo1 = p.lon * DEG, ring = [];
        for (let b = 0; b <= 360; b += 4) {
            const br = b * DEG;
            const la2 = Math.asin(Math.sin(la1) * Math.cos(lam) + Math.cos(la1) * Math.sin(lam) * Math.cos(br));
            const lo2 = lo1 + Math.atan2(Math.sin(br) * Math.sin(lam) * Math.cos(la1), Math.cos(lam) - Math.sin(la1) * Math.sin(la2));
            ring.push([((lo2 / DEG + 540) % 360) - 180, la2 / DEG]);
        }
        const poleIn = 90 - Math.abs(p.lat) < lam / DEG ? (p.lat > 0 ? 90 : -90) : null;
        return { ring, pole: poleIn };
    }
    function drawMap() {
        const W = map.clientWidth, H = Math.round(W / 2);
        map.style.height = H + 'px';
        const g = setupCanvas(map, W, H), dark = isDark();
        const X = (lon) => ((lon + 180) / 360) * W, Y = (lat) => ((90 - lat) / 180) * H;
        g.fillStyle = dark ? '#0e1622' : '#e8f1fb'; g.fillRect(0, 0, W, H);
        g.strokeStyle = dark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)'; g.lineWidth = 1;
        for (let lon = -150; lon <= 150; lon += 30) { g.beginPath(); g.moveTo(X(lon), 0); g.lineTo(X(lon), H); g.stroke(); }
        for (let lat = -60; lat <= 60; lat += 30) { g.beginPath(); g.moveTo(0, Y(lat)); g.lineTo(W, Y(lat)); g.stroke(); }
        if (land) {
            const fill = dark ? '#2b3445' : '#cfd8e3';
            for (const f of land.features) {
                const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
                for (const poly of polys) drawRing(g, X, Y, poly[0], { fill, closePole: 'auto' });
            }
        }
        const sel = state.sats[state.sel], selPos = state.pos[state.sel];
        // 고른 위성: 덮는 범위 + 지상 궤적
        if (sel && selPos) {
            const fp = footprint(selPos);
            if (fp) drawRing(g, X, Y, fp.ring, { fill: 'rgba(255,149,0,0.16)', stroke: 'rgba(255,149,0,0.8)', closePole: fp.pole });
            const T = 1440 / sel.revDay * 60e3, t0 = now().getTime();
            g.lineWidth = 1.6;
            for (const [from, to, color] of [[-T / 2, 0, 'rgba(255,149,0,0.45)'], [0, T * 1.2, 'rgba(255,149,0,0.95)']]) {
                g.strokeStyle = color; g.beginPath();
                let prev = null;
                for (let t = from; t <= to; t += Math.max(20e3, T / 300)) {
                    const p = at(sel, new Date(t0 + t));
                    if (!p) { prev = null; continue; }
                    if (prev && Math.abs(p.lon - prev.lon) < 180) g.lineTo(X(p.lon), Y(p.lat)); else g.moveTo(X(p.lon), Y(p.lat));
                    prev = p;
                }
                g.stroke();
            }
            g.lineWidth = 1;
        }
        // 위성 점
        mapPts = [];
        const many = state.sats.length > 800;
        state.pos.forEach((p, i) => {
            if (!p || i === state.sel) return;
            const x = X(p.lon), y = Y(p.lat), vis = p.el >= state.minEl;
            g.fillStyle = vis ? '#ff3b30' : (dark ? 'rgba(160,190,255,0.75)' : 'rgba(0,88,176,0.65)');
            const r = many ? (vis ? 2.2 : 1.2) : (vis ? 3.5 : 2.6);
            g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
            mapPts.push([x, y, i]);
        });
        // 관측 위치
        g.fillStyle = '#34c759'; g.strokeStyle = dark ? '#000' : '#fff'; g.lineWidth = 2;
        g.beginPath(); g.arc(X(state.obs.lon), Y(state.obs.lat), 5, 0, 7); g.fill(); g.stroke();
        if (selPos) {
            const x = X(selPos.lon), y = Y(selPos.lat);
            g.fillStyle = '#ff9500'; g.beginPath(); g.arc(x, y, 6, 0, 7); g.fill(); g.stroke();
            g.fillStyle = dark ? '#fff' : '#1d1d1f'; g.font = '600 12px -apple-system, sans-serif';
            g.textAlign = x > W - 120 ? 'right' : 'left';
            g.fillText(sel.name, x + (x > W - 120 ? -10 : 10), y - 8);
            mapPts.push([x, y, state.sel]);
        }
        g.lineWidth = 1;
    }
    map.addEventListener('click', (e) => {
        const r = map.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
        let best = null, bd = 14 * 14;
        for (const [px, py, i] of mapPts) { const d = (px - x) ** 2 + (py - y) ** 2; if (d < bd) { bd = d; best = i; } }
        if (best !== null) select(best);
    });
    function select(i) { state.sel = i; state.passes = null; tick(true); }

    // ── 그리기: 하늘 (가운데가 머리 위, 바깥이 지평선)
    function drawSky() {
        const W = sky.clientWidth, g = setupCanvas(sky, W, W), dark = isDark();
        const cx = W / 2, cy = W / 2, rad = W / 2 - 18;
        const P = (az, el) => { const r = rad * (90 - el) / 90, a = az * DEG; return [cx + r * Math.sin(a), cy - r * Math.cos(a)]; };
        g.fillStyle = dark ? '#0e1622' : '#f3f7fc'; g.beginPath(); g.arc(cx, cy, rad, 0, 7); g.fill();
        g.strokeStyle = dark ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.12)';
        [0, 30, 60].forEach((el) => { g.beginPath(); g.arc(cx, cy, rad * (90 - el) / 90, 0, 7); g.stroke(); });
        g.setLineDash([3, 3]); g.strokeStyle = 'rgba(255,149,0,0.6)';
        g.beginPath(); g.arc(cx, cy, rad * (90 - state.minEl) / 90, 0, 7); g.stroke(); g.setLineDash([]);
        g.fillStyle = dark ? '#a1a1a6' : '#6e6e73'; g.font = '11px -apple-system, sans-serif'; g.textAlign = 'center';
        [['북', 0], ['동', 90], ['남', 180], ['서', 270]].forEach(([t, az]) => { const [x, y] = P(az, -9); g.fillText(t, x, y + 4); });
        state.pos.forEach((p, i) => {
            if (!p || p.el < 0 || i === state.sel) return;
            const [x, y] = P(p.az, p.el);
            g.fillStyle = p.el >= state.minEl ? '#ff3b30' : (dark ? 'rgba(160,190,255,0.6)' : 'rgba(0,88,176,0.5)');
            g.beginPath(); g.arc(x, y, state.sats.length > 800 ? 2 : 3, 0, 7); g.fill();
        });
        // 고른 위성의 다음 통과 길
        const sel = state.sats[state.sel], pass = state.passes?.list?.[0];
        if (sel && pass) {
            g.strokeStyle = 'rgba(255,149,0,0.8)'; g.lineWidth = 1.6; g.beginPath();
            const n = 60;
            for (let k = 0; k <= n; k++) {
                const p = at(sel, new Date(pass.aos + (pass.los - pass.aos) * k / n));
                if (!p) continue;
                const [x, y] = P(p.az, Math.max(0, p.el));
                k ? g.lineTo(x, y) : g.moveTo(x, y);
            }
            g.stroke(); g.lineWidth = 1;
        }
        const sp = state.pos[state.sel];
        if (sp && sp.el >= 0) {
            const [x, y] = P(sp.az, sp.el);
            g.fillStyle = '#ff9500'; g.strokeStyle = dark ? '#000' : '#fff'; g.lineWidth = 2;
            g.beginPath(); g.arc(x, y, 6, 0, 7); g.fill(); g.stroke(); g.lineWidth = 1;
        }
    }

    // ── 글: 고른 위성 정보 · 지금 보이는 위성 · 지나가는 시각
    const timeFmt = (t) => new Date(t).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    function info() {
        const s = state.sats[state.sel], p = state.pos[state.sel];
        if (!s || !p) { $('sky-info').innerHTML = '<p class="sat-dim">위성을 고르면 여기에 나와요.</p>'; return; }
        const t = now(), p2 = at(s, new Date(t.getTime() + 1000));
        const rr = p2 ? p2.range - p.range : NaN;                      // km/s (멀어지면 +)
        const dop = -state.fGHz * 1e9 * rr / C;
        const vis = p.el >= state.minEl;
        const rows = [
            ['NORAD 번호', s.id],
            ['고도 · 속도', `${fmt(p.h, 0)} km · ${fmt(p.v, 2)} km/s`],
            ['위성 아래 지점', `${fmt(p.lat, 2)}°, ${fmt(p.lon, 2)}°`],
            ['한 바퀴', `${fmt(1440 / s.revDay, 1)}분 (하루 ${fmt(s.revDay, 2)}바퀴)`],
            [`${esc(state.obs.name || '관측 위치')}에서 방향`, `방위 ${fmt(p.az, 1)}° (${SAT.compass(p.az)}) · 앙각 <b>${fmt(p.el, 1)}°</b>`],
            ['거리 · 편도 지연', `${fmt(p.range, 0)} km · ${fmt(p.range / C * 1e3, 2)} ms`],
            [`도플러 (${state.fGHz} GHz)`, Number.isFinite(dop) ? `${dop >= 0 ? '+' : '−'}${fmtHz(Math.abs(dop))} <span class="sat-dim">(${rr < 0 ? '다가오는 중' : '멀어지는 중'} ${fmt(Math.abs(rr), 2)} km/s)</span>` : '–'],
        ];
        $('sky-info').innerHTML = `
            <div class="flex items-center gap-2"><b class="text-[16px]">${esc(s.name)}</b>
                <span class="sat-badge ${vis ? 'on' : ''}">${vis ? '지금 보임' : p.el >= 0 ? `지평선 위 (앙각 ${state.minEl}° 아래)` : '지평선 아래'}</span></div>
            <table class="sat-kv mt-2">${rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('')}</table>`;
    }
    function visibleList() {
        const rows = state.pos.map((p, i) => [p, i]).filter(([p]) => p && p.el >= state.minEl).sort((a, b) => b[0].el - a[0].el);
        $('sky-vis-count').textContent = `${rows.length.toLocaleString()}기`;
        $('sky-vis').innerHTML = rows.slice(0, 40).map(([p, i]) => `<button type="button" class="sat-row ${i === state.sel ? 'on' : ''}" data-i="${i}"><span class="truncate">${esc(state.sats[i].name)}</span><span class="sat-dim">앙각 ${fmt(p.el, 0)}° · ${SAT.compass(p.az)}</span></button>`).join('')
            || `<p class="sat-dim px-1 py-2">지금 앙각 ${state.minEl}° 위에 있는 위성이 없어요.</p>`;
    }
    $('sky-vis').addEventListener('click', (e) => { const b = e.target.closest('[data-i]'); if (b) select(+b.dataset.i); });
    function passList() {
        const s = state.sats[state.sel];
        if (!s) { $('sky-passes').innerHTML = ''; return; }
        if (!state.passes || state.passesFor !== s) { state.passes = findPasses(s, now()); state.passesFor = s; }
        const ps = state.passes;
        if (ps.geo) { $('sky-passes').innerHTML = `<p class="sat-dim">정지·느린 궤도라 늘 같은 자리에 있어요. 지금 앙각 ${fmt(state.pos[state.sel]?.el, 1)}°.</p>`; return; }
        $('sky-passes').innerHTML = ps.list.length ? `<table class="sat-kv w-full"><tr><th>뜨는 시각</th><th>가장 높이</th><th>지는 시각</th><th>보이는 시간</th></tr>${ps.list.map((x) => `
            <tr><td>${x.partial ? '지금 보이는 중' : timeFmt(x.aos)}</td><td>${fmt(x.max, 0)}° <span class="sat-dim">${new Date(x.maxAt).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}</span></td><td>${timeFmt(x.los)}</td><td>${Math.round((x.los - x.aos) / 60e3)}분</td></tr>`).join('')}</table>`
            : `<p class="sat-dim">앞으로 24시간 동안 앙각 ${state.minEl}° 위로 지나가지 않아요.</p>`;
    }

    // ── 1초마다
    function tick(force) {
        if (!sj || root.closest('.hidden')) return;
        const t = now();
        const big = state.sats.length > 3000;
        if (force || !state.posAt || !big || state.speed > 1 || Date.now() - state.posAt > 5000) allPositions(t);
        else if (state.sel >= 0) state.pos[state.sel] = at(state.sats[state.sel], t);
        $('sky-clock').textContent = t.toLocaleString('ko-KR') + (state.speed > 1 ? ` (${state.speed}배 빠르게)` : '');
        drawMap(); drawSky(); info(); visibleList();
        if (force || !state.passes) passList();
    }
    SAT.tickSky = () => tick(true);
    new MutationObserver(() => tick(true)).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    window.addEventListener('resize', () => tick(true));
})();
