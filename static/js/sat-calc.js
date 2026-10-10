// 🛰 위성 궤도 · NTN 계산기 — 원 궤도 기준 공식 (지구는 반지름 6371km 공, 3GPP TR 38.821 과 같은 가정)
(() => {
    'use strict';
    const R = 6371;                 // 지구 평균 반지름 km (3GPP NTN 계산과 같음)
    const RE = 6378.137;            // 적도 반지름 km (J2·정지궤도 계산)
    const MU = 398600.4418;         // 지구 중력 상수 km³/s²
    const C = 299792.458;           // 빛의 속도 km/s
    const SIDEREAL = 86164.0905;    // 항성일 s (지구가 한 바퀴)
    const J2 = 1.08262668e-3;
    const DEG = Math.PI / 180;

    const SAT = window.MJSat = window.MJSat || {};
    Object.assign(SAT, { R, RE, MU, C, SIDEREAL, DEG });

    // ── 공식
    const slant = (h, e) => Math.sqrt((R * Math.sin(e)) ** 2 + h * h + 2 * R * h) - R * Math.sin(e);  // 경사 거리
    const centralAngle = (h, e) => Math.acos(R * Math.cos(e) / (R + h)) - e;                      // 지구 중심각
    const fspl = (dKm, fGHz) => 20 * Math.log10(dKm) + 20 * Math.log10(fGHz) + 92.45;            // 자유 공간 손실 dB
    function ssoInclination(h) {
        const a = RE + h, n = Math.sqrt(MU / a ** 3);
        const need = 2 * Math.PI / (365.2422 * 86400);  // 궤도면이 1년에 한 바퀴 돌아야 함
        const cosI = -need / (1.5 * J2 * (RE / a) ** 2 * n);
        return Math.abs(cosI) <= 1 ? Math.acos(cosI) / DEG : null;
    }
    function orbit(h) {
        const a = R + h, v = Math.sqrt(MU / a), T = 2 * Math.PI * Math.sqrt(a ** 3 / MU);
        return { a, v, T, w: v / a };
    }
    SAT.formulas = { slant, centralAngle, fspl, orbit, ssoInclination };

    // 머리 위로 똑바로 지나가는 경우의 시간에 따른 앙각·도플러 (지구 자전은 뺌)
    function overheadPass(h, eMin, fGHz) {
        const { a, w } = orbit(h);
        const lam = centralAngle(h, eMin);
        const tMax = lam / w, pts = [];
        for (let i = 0; i <= 240; i++) {
            const t = -tMax + (2 * tMax * i) / 240, th = w * t;
            const d = Math.sqrt(R * R + a * a - 2 * R * a * Math.cos(th));
            const el = Math.asin((a * Math.cos(th) - R) / d);
            const rr = R * a * w * Math.sin(th) / d;               // 거리 변화율 km/s (멀어지면 +)
            pts.push({ t: t / 60, el: el / DEG, dop: -fGHz * 1e9 * rr / C / 1e3, d });
        }
        return pts;
    }

    // ── 숫자 표시
    const fmt = (x, d = 1) => (Number.isFinite(x) ? x.toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d }) : '–');
    const fmtHz = (hz) => Math.abs(hz) >= 1e6 ? `${fmt(hz / 1e6, 2)} MHz` : Math.abs(hz) >= 1e3 ? `${fmt(hz / 1e3, 1)} kHz` : `${fmt(hz, 0)} Hz`;
    const fmtTime = (s) => s >= 3600 ? `${Math.floor(s / 3600)}시간 ${Math.round((s % 3600) / 60)}분` : s >= 60 ? `${Math.floor(s / 60)}분 ${Math.round(s % 60)}초` : `${fmt(s, 1)}초`;
    SAT.fmt = { fmt, fmtHz, fmtTime };

    // ── 그래프 (캔버스, 선 2개까지)
    function isDark() { return document.documentElement.classList.contains('theme-dark'); }
    function chart(canvas, { xs, series, xLabel, xTicks }) {
        const dpr = window.devicePixelRatio || 1;
        const W = canvas.clientWidth, H = canvas.clientHeight;
        canvas.width = W * dpr; canvas.height = H * dpr;
        const g = canvas.getContext('2d');
        g.scale(dpr, dpr);
        g.clearRect(0, 0, W, H);
        const dark = isDark();
        const grid = dark ? 'rgba(255,255,255,0.09)' : 'rgba(0,0,0,0.07)', ink = dark ? '#a1a1a6' : '#6e6e73';
        const padL = 56, padR = series.length > 1 ? 56 : 14, padT = 14, padB = 34;
        const pw = W - padL - padR, ph = H - padT - padB;
        const x0 = xs[0], x1 = xs[xs.length - 1];
        const X = (x) => padL + ((x - x0) / (x1 - x0 || 1)) * pw;
        g.font = '11px -apple-system, BlinkMacSystemFont, sans-serif';
        g.lineWidth = 1;
        // x 눈금
        const ticks = xTicks || niceTicks(x0, x1, 6);
        g.fillStyle = ink; g.textAlign = 'center';
        ticks.forEach((t) => { const x = X(t); g.strokeStyle = grid; g.beginPath(); g.moveTo(x, padT); g.lineTo(x, padT + ph); g.stroke(); g.fillText(fmtTick(t), x, H - padB + 15); });
        g.fillText(xLabel, padL + pw / 2, H - 4);
        series.forEach((s, si) => {
            const vals = s.ys.filter(Number.isFinite);
            let lo = s.min ?? Math.min(...vals), hi = s.max ?? Math.max(...vals);
            if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
            const yt = niceTicks(lo, hi, 5);
            lo = Math.min(lo, yt[0]); hi = Math.max(hi, yt[yt.length - 1]);
            const Y = (y) => padT + ph - ((y - lo) / (hi - lo)) * ph;
            g.textAlign = si === 0 ? 'right' : 'left';
            g.fillStyle = s.color;
            yt.forEach((t) => {
                const y = Y(t);
                if (si === 0) { g.strokeStyle = grid; g.beginPath(); g.moveTo(padL, y); g.lineTo(padL + pw, y); g.stroke(); }
                g.fillText(fmtTick(t), si === 0 ? padL - 6 : padL + pw + 6, y + 4);
            });
            g.save();
            g.translate(si === 0 ? 11 : W - 6, padT + ph / 2);
            g.rotate(-Math.PI / 2);
            g.textAlign = 'center';
            g.fillText(s.label, 0, 0);
            g.restore();
            g.strokeStyle = s.color; g.lineWidth = 2; g.beginPath();
            let started = false;
            xs.forEach((x, i) => { const y = s.ys[i]; if (!Number.isFinite(y)) { started = false; return; } started ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)); started = true; });
            g.stroke();
            g.lineWidth = 1;
        });
    }
    function niceTicks(lo, hi, n) {
        const span = hi - lo || 1, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
        const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) || mag * 10;
        const out = [];
        for (let t = Math.ceil(lo / step - 1e-9) * step; t <= hi + 1e-9; t += step) out.push(Math.abs(t) < 1e-12 ? 0 : t);
        return out.length >= 2 ? out : [lo, hi];
    }
    function fmtTick(t) { const a = Math.abs(t); return a >= 1000 ? fmt(t, 0) : a >= 10 ? fmt(t, 0) : a >= 1 ? fmt(t, 1).replace(/\.0$/, '') : fmt(t, 2).replace(/0$/, ''); }
    SAT.chart = chart;

    // ── 계산기 화면
    const $ = (id) => document.getElementById(id);
    if (!$('sc-h')) return;
    const PRESETS = [
        ['스타링크 LEO 550', 550, 25], ['LEO 600 (TR 38.821)', 600, 10], ['원웹 LEO 1200', 1200, 10], ['ISS 420', 420, 10],
        ['O3b MEO 8062', 8062, 10], ['GPS MEO 20200', 20200, 10], ['GEO 35786', 35786, 10],
    ];
    const FREQS = [['L 1.6', 1.6], ['S 2', 2], ['C 4', 4], ['Ku 12', 12], ['Ka 20', 20], ['Ka 30', 30]];
    $('sc-presets').innerHTML = PRESETS.map((p, i) => `<button type="button" class="sat-chip" data-p="${i}">${p[0]}</button>`).join('');
    $('sc-freqs').innerHTML = FREQS.map((f) => `<button type="button" class="sat-chip" data-f="${f[1]}">${f[0]}</button>`).join('');
    $('sc-presets').addEventListener('click', (e) => { const b = e.target.closest('[data-p]'); if (!b) return; const p = PRESETS[+b.dataset.p]; set({ h: p[1], e: p[2] }); });
    $('sc-freqs').addEventListener('click', (e) => { const b = e.target.closest('[data-f]'); if (!b) return; set({ f: +b.dataset.f }); });

    function set({ h, e, f }) {
        if (h !== undefined) { $('sc-h').value = h; $('sc-h-range').value = Math.log10(h); }
        if (e !== undefined) $('sc-e').value = e;
        if (f !== undefined) $('sc-f').value = f;
        run();
    }
    SAT.setCalc = set;
    $('sc-h-range').addEventListener('input', () => { $('sc-h').value = Math.round(10 ** +$('sc-h-range').value); run(); });
    ['sc-h', 'sc-e', 'sc-f', 'sc-eg'].forEach((id) => $(id).addEventListener('input', () => { if (id === 'sc-h') $('sc-h-range').value = Math.log10(+$('sc-h').value || 1); run(); }));
    $('sc-metric').addEventListener('change', drawElevChart);

    let last = null;
    function card(title, rows, note) {
        return `<div class="sat-card"><p class="sat-card-t">${title}</p><table class="sat-kv">${rows.map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`).join('')}</table>${note ? `<p class="sat-note">${note}</p>` : ''}</div>`;
    }
    function run() {
        const h = +$('sc-h').value, eDeg = +$('sc-e').value, fGHz = +$('sc-f').value, egDeg = +$('sc-eg').value;
        if (!(h >= 100 && h <= 400000) || !(eDeg >= 0 && eDeg < 90) || !(fGHz > 0) || !(egDeg >= 0 && egDeg < 90)) {
            $('sc-out').innerHTML = '<p class="text-[13px] text-[#c4271d]">고도 100~400,000km, 앙각 0~89°, 주파수 0보다 크게 넣어 주세요.</p>';
            return;
        }
        const e = eDeg * DEG, eg = egDeg * DEG;
        const { a, v, T, w } = orbit(h);
        const dMin = h, dMax = slant(h, e), dGw = slant(h, eg);
        const lam = centralAngle(h, e);
        const footR = R * lam, area = 2 * Math.PI * R * R * (1 - Math.cos(lam));
        const sso = ssoInclination(h);
        const geoLike = Math.abs(T - SIDEREAL) < 120;
        const rttT = (d) => 2 * (d + dGw) / C * 1e3, rttR = (d) => 2 * d / C * 1e3;
        // 정지궤도는 땅과 같이 돌아서 상대 속도가 거의 0 (다른 궤도는 지구 자전을 빼고 계산)
        const dopMax = geoLike ? 0 : fGHz * 1e9 * v * R * Math.cos(e) / a / C;
        const dopRate = geoLike ? 0 : fGHz * 1e9 * (R * v * v / (a * h)) / C;
        const passT = 2 * lam / w;
        const shift = 360 * T / SIDEREAL;
        const nCover = Math.ceil(2 / (1 - Math.cos(lam)));
        last = { h, e, fGHz, dMin, dMax, lam, geoLike };

        $('sc-out').innerHTML = [
            card('🌀 궤도', [
                ['궤도 반지름', `${fmt(a, 0)} km`],
                ['속도', `${fmt(v, 2)} km/s <span class="sat-dim">(${fmt(v * 3600, 0)} km/h)</span>`],
                ['한 바퀴(공전 주기)', fmtTime(T)],
                ['하루에 도는 바퀴', `${fmt(86400 / T, 2)} 바퀴`],
                ['한 바퀴 뒤 지상 궤적', geoLike ? '거의 제자리 (정지궤도)' : `서쪽으로 ${fmt(shift, 1)}° 밀림`],
                ['태양 동기 궤도 경사각', sso ? `${fmt(sso, 2)}°` : '이 고도에선 안 됨'],
            ], geoLike ? '공전 주기가 지구 자전(23시간 56분 4초)과 같아서 적도 위에서는 하늘의 한 점에 멈춰 보여요.' : null),
            card('📏 거리 · 지연', [
                ['바로 위(앙각 90°)', `${fmt(dMin, 0)} km · 편도 ${fmt(dMin / C * 1e3, 2)} ms`],
                [`가장 멀 때(앙각 ${eDeg}°)`, `${fmt(dMax, 0)} km · 편도 ${fmt(dMax / C * 1e3, 2)} ms`],
                ['왕복(RTT) — 투명 중계', `${fmt(rttT(dMin), 2)} ~ ${fmt(rttT(dMax), 2)} ms`],
                ['왕복(RTT) — 위성에 기지국', `${fmt(rttR(dMin), 2)} ~ ${fmt(rttR(dMax), 2)} ms`],
                ['지연 차이(가까울 때↔멀 때)', `${fmt((dMax - dMin) / C * 1e3, 2)} ms`],
            ], `투명 중계는 단말 → 위성 → 지상국(게이트웨이)을 거쳐 기지국에 닿아요. 게이트웨이 쪽 거리는 앙각 ${egDeg}°일 때(가장 먼 경우)로 계산했어요. 3GPP TR 38.821 의 최대 RTT(LEO 600 25.77ms, LEO 1200 41.77ms, GEO 541.46ms)는 둘 다 10°일 때예요.`),
            card('〰️ 도플러', [
                ['가장 큰 도플러', `±${fmtHz(dopMax)} <span class="sat-dim">(${fmt(dopMax / (fGHz * 1e9) * 1e6, 1)} ppm)</span>`],
                ['가장 빠른 변화 (바로 위)', `${fmtHz(dopRate)}/s`],
                ['위성 쪽으로 다가오는 속도(최대)', geoLike ? '≈ 0 km/s' : `${fmt(v * R * Math.cos(e) / a, 2)} km/s`],
            ], geoLike ? '정지궤도는 거의 0 이에요 (실제로는 궤도가 조금 기울어 있어 수 Hz~수십 Hz).' : `${fGHz} GHz 기준. 한 번 지나가는 동안 +${fmtHz(dopMax)} → 0 → −${fmtHz(dopMax)} 으로 바뀌어요. 지구 자전은 빼고 계산해서 실제와 몇 % 달라요.`),
            card('📉 경로 손실', [
                ['바로 위', `${fmt(fspl(dMin, fGHz), 1)} dB`],
                [`앙각 ${eDeg}°`, `${fmt(fspl(dMax, fGHz), 1)} dB`],
                ['차이', `${fmt(fspl(dMax, fGHz) - fspl(dMin, fGHz), 1)} dB`],
            ], '자유 공간 손실(FSPL)만이에요. 대기·비·편파 손실은 링크 버짓 계산기에서 더해요.'),
            card('🗺 덮는 범위', [
                ['지구 중심각', `${fmt(lam / DEG, 2)}°`],
                ['한 위성이 덮는 반지름', `${fmt(footR, 0)} km`],
                ['넓이', `${fmt(area / 1e6, 2)} 백만 km² <span class="sat-dim">(지구의 ${fmt(area / (4 * Math.PI * R * R) * 100, 2)}%)</span>`],
                ['머리 위로 지나갈 때 보이는 시간', geoLike ? '계속 보임' : fmtTime(passT)],
                ['지구 전체를 덮는 최소 위성 수', geoLike ? '3기 (극지방 빼고)' : `약 ${nCover.toLocaleString()}기 이상`],
            ], '보이는 시간은 바로 위로 지나는 가장 긴 경우예요. 위성 수는 덮는 원이 겹치지 않는다고 친 이론 하한이라, 실제 군집은 몇 배 더 필요해요.'),
        ].join('');
        drawElevChart();
        drawPassChart();
    }

    function drawElevChart() {
        if (!last) return;
        const { h, fGHz } = last, metric = $('sc-metric').value;
        const xs = [], ys = [];
        for (let el = 0; el <= 90; el += 0.5) {
            const d = slant(h, el * DEG);
            xs.push(el);
            ys.push(metric === 'dist' ? d : metric === 'delay' ? d / C * 1e3 : metric === 'fspl' ? fspl(d, fGHz) : fGHz * 1e6 * orbit(h).v * R * Math.cos(el * DEG) / (R + h) / C);
        }
        const label = { dist: '거리 km', delay: '편도 지연 ms', fspl: '경로 손실 dB', dop: '최대 도플러 kHz' }[metric];
        chart($('sc-chart-el'), { xs, series: [{ ys, label, color: '#0066cc' }], xLabel: '앙각 (°)', xTicks: [0, 10, 20, 30, 45, 60, 75, 90] });
    }
    function drawPassChart() {
        if (!last) return;
        const cv = $('sc-chart-pass');
        if (last.geoLike) {
            const g = cv.getContext('2d'), dpr = window.devicePixelRatio || 1;
            cv.width = cv.clientWidth * dpr; cv.height = cv.clientHeight * dpr;
            g.scale(dpr, dpr);
            g.fillStyle = isDark() ? '#a1a1a6' : '#6e6e73';
            g.font = '14px -apple-system, BlinkMacSystemFont, sans-serif';
            g.textAlign = 'center';
            g.fillText('정지궤도는 하늘에 멈춰 있어서 지나가지 않아요.', cv.clientWidth / 2, cv.clientHeight / 2);
            return;
        }
        const pts = overheadPass(last.h, last.e, last.fGHz);
        chart($('sc-chart-pass'), {
            xs: pts.map((p) => p.t),
            series: [
                { ys: pts.map((p) => p.dop), label: '도플러 kHz', color: '#d0453a' },
                { ys: pts.map((p) => p.el), label: '앙각 °', color: '#0a8f5a', min: 0, max: 90 },
            ],
            xLabel: '가장 가까울 때부터 (분)',
        });
    }
    new MutationObserver(() => { drawElevChart(); drawPassChart(); }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    window.addEventListener('resize', () => { drawElevChart(); drawPassChart(); });
    SAT.redrawCalc = () => { drawElevChart(); drawPassChart(); };

    // ── 정지궤도 위성 바라보는 방향
    function lookAngles(latDeg, lonDeg, satLonDeg) {
        const lat = latDeg * DEG, dl = (satLonDeg - lonDeg) * DEG, r = RE + 35786;
        // 지구 중심 좌표 (적도 반지름 공으로)
        const ox = RE * Math.cos(lat), oz = RE * Math.sin(lat);
        const sx = r * Math.cos(dl), sy = r * Math.sin(dl);
        const rx = sx - ox, ry = sy, rz = -oz;
        const e = ry;                                                        // 동
        const n = -Math.sin(lat) * rx + Math.cos(lat) * rz;                  // 북
        const u = Math.cos(lat) * rx + Math.sin(lat) * rz;                   // 위
        const d = Math.hypot(rx, ry, rz);
        return { az: ((Math.atan2(e, n) / DEG) + 360) % 360, el: Math.asin(u / d) / DEG, d };
    }
    SAT.lookAngles = lookAngles;
    const GEO_PRESETS = [['무궁화 6A·7호 116°E', 116], ['무궁화 5A 113°E', 113], ['천리안 2A·2B 128.2°E', 128.2], ['인텔샛 IS-39 62°E', 62]];
    $('sg-presets').innerHTML = GEO_PRESETS.map((p) => `<button type="button" class="sat-chip" data-g="${p[1]}">${p[0]}</button>`).join('');
    $('sg-presets').addEventListener('click', (e) => { const b = e.target.closest('[data-g]'); if (b) { $('sg-slon').value = b.dataset.g; runGeo(); } });
    ['sg-lat', 'sg-lon', 'sg-slon'].forEach((id) => $(id).addEventListener('input', runGeo));
    $('sg-here').addEventListener('click', () => {
        navigator.geolocation?.getCurrentPosition((p) => { $('sg-lat').value = p.coords.latitude.toFixed(4); $('sg-lon').value = p.coords.longitude.toFixed(4); runGeo(); }, () => { $('sg-out').textContent = '위치를 받지 못했어요.'; });
    });
    function compass(az) { return ['북', '북북동', '북동', '동북동', '동', '동남동', '남동', '남남동', '남', '남남서', '남서', '서남서', '서', '서북서', '북서', '북북서'][Math.round(az / 22.5) % 16]; }
    SAT.compass = compass;
    function runGeo() {
        const lat = +$('sg-lat').value, lon = +$('sg-lon').value, slon = +$('sg-slon').value;
        if (!(Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && Math.abs(slon) <= 180)) { $('sg-out').textContent = '위도 ±90, 경도 ±180 안으로 넣어 주세요.'; return; }
        const r = lookAngles(lat, lon, slon);
        $('sg-out').innerHTML = r.el < 0
            ? '<span class="text-[#c4271d]">지평선 아래라서 이 위성은 안 보여요.</span>'
            : `방위각 <b>${fmt(r.az, 1)}°</b> (${compass(r.az)}) · 앙각 <b>${fmt(r.el, 1)}°</b> · 거리 ${fmt(r.d, 0)} km · 편도 ${fmt(r.d / C * 1e3, 1)} ms`
              + (r.el < 10 ? ' <span class="text-[#b26a00]">— 앙각이 낮아 건물·산에 가리기 쉬워요</span>' : '');
    }

    run();
    runGeo();
})();
