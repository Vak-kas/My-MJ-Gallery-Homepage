// IQ 분석기의 "🧩 버스트 모아 비교": 신호 찾기가 찾은 버스트를 한 줄씩 쌓아 N × 샘플 행렬로 보고,
// 줄 맞추기(켜지는 순간·상관)·닮은 것끼리 나누기·버스트마다 복조(비트 줄 세우기)·.mat/.npy/CSV 저장.
// iq-analyzer.js(window.__iq)·iq-insight.js(window.__iqInsight) 를 쓰고, 계산은 브라우저 안에서만.
(() => {
	'use strict';
	const IQ = window.__iq, IN = window.__iqInsight;
	if (!IQ || !IN) return;
	const { S } = IQ;
	const $ = (id) => document.getElementById(id);
	const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
	const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
	const dbOf = (p) => 10 * Math.log10(p + 1e-20);
	const numv = (id) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : null; };
	const BUDGET = 8e6;      // 한 번에 읽을 복소 샘플 수 (모든 버스트 합)
	const MAX_ROWS = 1000;
	const LET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
	const gName = (g) => LET[g % 26] + (g >= 26 ? Math.floor(g / 26) + 1 : '');
	const GCOL = ['#0066cc', '#e8590c', '#2b8a3e', '#d6336c', '#7048e8', '#0c8599', '#b07a00', '#c92a2a', '#5c940d', '#862e9c'];
	const gCol = (g) => GCOL[g % GCOL.length];

	let st = null;   // { key, rows[], rate, nMax, filt:{df,bw}, view, bits? }

	// ── 모으기 ───────────────────────────────────────────────
	function smoothPow(y, n, W) {
		const p = new Float32Array(n), out = new Float32Array(n);
		for (let k = 0; k < n; k++) p[k] = y[2 * k] * y[2 * k] + y[2 * k + 1] * y[2 * k + 1];
		let acc = 0;
		for (let k = 0; k < n; k++) {
			acc += p[k];
			if (k >= W) acc -= p[k - W];
			out[Math.max(0, k - (W >> 1))] = acc / Math.min(k + 1, W);
		}
		for (let k = Math.max(0, n - (W >> 1)); k < n; k++) out[k] = out[Math.max(0, n - (W >> 1) - 1)];
		return out;
	}
	const pct = (arr, q) => { const a = Float32Array.from(arr).sort(); return a[clamp(Math.floor(a.length * q), 0, a.length - 1)]; };
	function instFreq(y, n, rate) {
		const f = new Float32Array(n);
		for (let k = 1; k < n; k++) {
			const a = y[2 * k], b = y[2 * k + 1], c = y[2 * k - 2], d = y[2 * k - 1];
			f[k] = (Math.atan2(b * c - a * d, a * c + b * d) * rate) / (2 * Math.PI);
		}
		f[0] = f[1] || 0;
		return f;
	}
	function filterSettings() {
		if (!$('iq-st-filt').checked) return null;
		const df = (numv('iq-dm-df') ?? numv('iq-cn-df') ?? 0) * 1e3;
		let bw = (numv('iq-dm-bw') || 0) * 1e3;
		if (!bw) { const near = (IN.bands || []).find((b) => Math.abs(b.center - df) < b.width / 2 + S.fs / 200); bw = near ? near.width * 1.2 : S.fs / 4; }
		return { df, bw: clamp(bw, S.fs / 4000, S.fs) };
	}

	// OOK 처럼 패킷 안에서 꺼졌다 켜지는 신호는 조각이 여럿 잡혀서, 가까운 조각을 한 버스트로 합침
	// 자동: 간격을 작은 것부터 늘어놓아 확 벌어지는 곳(3배 넘게)을 찾고, 작은 쪽 간격이 조각 길이의 10배 안일 때만
	function mergeGap(list) {
		const v = $('iq-st-gap').value.trim();
		if (v !== '') return Math.max(0, parseFloat(v) || 0) * 1e-3 * S.fs;
		if (list.length < 4) return 0;
		const gaps = [];
		for (let i = 1; i < list.length; i++) gaps.push(Math.max(1, list[i].s0 - list[i - 1].s1));
		gaps.sort((p, q) => p - q);
		let best = 0, at = -1;
		for (let k = 0; k + 1 < gaps.length; k++) { const r = gaps[k + 1] / gaps[k]; if (r > best) { best = r; at = k; } }
		const lens = list.map((b) => b.s1 - b.s0).sort((p, q) => p - q), med = lens[lens.length >> 1];
		if (best < 3 || at < 0 || gaps[at] > 10 * med) return 0;
		return Math.sqrt(gaps[at] * gaps[at + 1]);
	}
	function merged(list, gap) {
		if (!gap) return list.map((b) => ({ ...b, parts: 1 }));
		const out = [];
		for (const b of list) {
			const p = out[out.length - 1];
			if (p && b.s0 - p.s1 < gap) { p.s1 = Math.max(p.s1, b.s1); p.parts++; } else out.push({ ...b, parts: 1 });
		}
		return out;
	}

	async function collect() {
		const msg = $('iq-st-msg');
		const pieces = IN.bursts || [];
		if (!S.ov || !pieces.length) { msg.textContent = '먼저 파일을 열어 주세요 — 🔎 신호 찾기가 켜졌다 꺼지는 구간(버스트)을 찾아야 모을 수 있어요.'; return; }
		const gap = mergeGap(pieces), all = merged(pieces, gap);
		const list = all.slice(0, MAX_ROWS);
		const filt = filterSettings();
		const pads = list.map((b) => Math.max(64, Math.round((b.s1 - b.s0) * 0.15)));
		const want = list.reduce((s, b, i) => s + (b.s1 - b.s0) + 2 * pads[i], 0);
		const cap = want > BUDGET ? Math.floor(BUDGET / list.length) : Infinity;
		msg.textContent = `버스트 ${list.length}개 읽는 중…`;
		await new Promise((r) => setTimeout(r, 20));
		const rows = [];
		let rate = S.fs;
		for (let i = 0; i < list.length; i++) {
			const b = list[i], a = Math.max(0, b.s0 - pads[i]), cnt = Math.min(Math.min(S.n, b.s1 + pads[i]) - a, cap);
			const raw = await IQ.readSamples(a, cnt);
			let y = raw, step = 1, off = a;
			if (filt) {
				const ch = IN.channelize(raw, a, filt.df, filt.bw);
				if (!ch) continue;
				y = ch.y; step = ch.D; off = a + ch.delay; rate = ch.fsd;
			}
			const n = y.length / 2, W = clamp(Math.round(n / 2000), 2, 256);
			const ps = smoothPow(y, n, W);
			const floor = pct(ps, 0.05), peak = pct(ps, 0.97), thr = Math.sqrt(Math.max(floor, peak * 1e-6) * peak);
			let k0 = 0, k1 = n - 1;
			while (k0 < n && ps[k0] <= thr) k0++;
			while (k1 > k0 && ps[k1] <= thr) k1--;
			if (k1 - k0 < 4) { k0 = 0; k1 = n - 1; }
			const coarse = clamp(Math.round((b.s0 - off) / step), 0, n - 1);
			rows.push({ i, b, y, n, step, off, k0, k1, coarse, thr, ps, a });
			if (i % 20 === 19) { msg.textContent = `버스트 ${i + 1}/${list.length} 읽는 중…`; await new Promise((r) => setTimeout(r, 0)); }
		}
		if (!rows.length) { msg.textContent = '버스트를 읽지 못했어요 (거르기 대역폭이 너무 좁은지 확인해 보세요).'; return; }
		st = { key: `${S.name}|${S.n}`, rows, rate, filt, cut: cap < Infinity, total: all.length, bits: null };
		align();
		features();
		group();
		render();
		const note = [];
		if (all.length < pieces.length) note.push(`찾은 조각 ${pieces.length}개 중 ${IQ.fmtT(gap / S.fs)} 보다 가까운 것끼리 합침`);
		if (all.length > MAX_ROWS) note.push(`앞 ${MAX_ROWS}개만`);
		if (st.cut) note.push(`버스트가 많고 길어서 한 줄에 ${cap.toLocaleString()} 샘플까지만 읽음`);
		msg.textContent = `버스트 ${rows.length}개를 줄 세웠어요 → 행렬 ${rows.length} × ${st.nMax.toLocaleString()} (${IQ.si(rate, 'S/s')}${filt ? ` · Δf ${IQ.fmtF(filt.df)}·대역폭 ${IQ.fmtF(filt.bw)} 로 거름` : ''})${note.length ? ' · ' + note.join(' · ') : ''}. 줄을 누르면 위 그래프가 그 버스트로 가요.`;
	}

	// ── 줄 맞추기 ────────────────────────────────────────────
	function shapeOf(r, start, len, useFm, P) {
		// start 부터 len 샘플을 P 칸으로 줄인 모양 (세기 √p 또는 켜진 곳의 순간 주파수)
		const out = new Float32Array(P), f = useFm ? (r.fm || (r.fm = instFreq(r.y, r.n, st.rate))) : null;
		for (let j = 0; j < P; j++) {
			const a = start + Math.floor((j * len) / P), b = Math.max(a + 1, start + Math.floor(((j + 1) * len) / P));
			let s = 0, c = 0;
			for (let k = a; k < b; k++) {
				if (k < 0 || k >= r.n) continue;
				if (useFm) { if (r.ps[k] > r.thr) { s += f[k]; c++; } } else { s += Math.sqrt(r.ps[k]); c++; }
			}
			out[j] = c ? s / c : 0;
		}
		return out;
	}
	function corr(a, b) {
		const n = Math.min(a.length, b.length);
		let ma = 0, mb = 0;
		for (let k = 0; k < n; k++) { ma += a[k]; mb += b[k]; }
		ma /= n; mb /= n;
		let sab = 0, saa = 0, sbb = 0;
		for (let k = 0; k < n; k++) { const x = a[k] - ma, y = b[k] - mb; sab += x * y; saa += x * x; sbb += y * y; }
		return saa > 0 && sbb > 0 ? sab / Math.sqrt(saa * sbb) : 0;
	}
	function align() {
		const how = $('iq-st-align').value, rows = st.rows, useFm = $('iq-st-view').value === 'fm';
		for (const r of rows) { r.start = how === 'none' ? r.coarse : r.k0; r.len = r.k1 - r.k0 + 1; r.lag = 0; }
		if (how === 'xcorr' && rows.length > 1) {
			// 기준: 길이가 가운데쯤인 버스트. 다른 버스트를 ±25% 안에서 밀어 보며 모양이 가장 잘 겹치는 곳
			const ref = [...rows].sort((p, q) => p.len - q.len)[rows.length >> 1];
			const ds = Math.max(1, Math.floor(ref.len / 2048)), P = Math.ceil(ref.len / ds);
			const rs = shapeOf(ref, ref.start, P * ds, useFm, P);
			for (const r of rows) {
				if (r === ref) continue;
				const maxLag = Math.ceil(P * 0.25);
				const sh = shapeOf(r, r.start - maxLag * ds, (P + 2 * maxLag) * ds, useFm, P + 2 * maxLag);
				let best = -2, bl = 0;
				for (let l = 0; l <= 2 * maxLag; l++) {
					const c = corr(rs, sh.subarray(l, l + P));
					if (c > best) { best = c; bl = l - maxLag; }
				}
				r.lag = bl * ds; r.start += r.lag;
			}
		}
		st.nMax = Math.max(...rows.map((r) => Math.min(r.n - r.start, how === 'none' ? r.n - r.start : r.len + Math.abs(r.lag))));
		st.nMax = Math.max(8, Math.min(st.nMax, Math.max(...rows.map((r) => r.n))));
		st.useFm = useFm;
	}

	// ── 특징 · 나누기 ────────────────────────────────────────
	function features() {
		for (const r of st.rows) {
			let pw = 0, c = 0, fsum = 0, fc = 0;
			const f = r.fm || (r.fm = instFreq(r.y, r.n, st.rate));
			for (let k = r.k0; k <= r.k1; k++) {
				const p = r.y[2 * k] ** 2 + r.y[2 * k + 1] ** 2;
				pw += p; c++;
				if (r.ps[k] > r.thr) { fsum += f[k]; fc++; }
			}
			r.t0 = (r.off + r.k0 * r.step) / S.fs;
			r.dur = ((r.k1 - r.k0 + 1) * r.step) / S.fs;
			r.dbfs = dbOf(pw / Math.max(1, c));
			r.cfo = (fc ? fsum / fc : 0) + (st.filt ? st.filt.df : 0);
		}
	}
	function group() {
		const rows = st.rows, thr = +$('iq-st-thr').value / 100, P = 256;
		const by = $('iq-st-by').value === 'bits' && st.bits ? 'bits' : 'shape';
		for (const r of rows) r.shape = shapeOf(r, r.start, st.nMax, st.useFm, P);
		const groups = [];
		for (const r of rows) {
			let best = -1, bg = -1;
			for (let g = 0; g < groups.length; g++) {
				const s = similarity(groups[g][0], r, by);
				if (s > best) { best = s; bg = g; }
			}
			if (bg >= 0 && best >= thr) { groups[bg].push(r); r.group = bg; } else { r.group = groups.length; groups.push([r]); }
			r.sim = bg >= 0 && best >= thr ? best : 1;
		}
		st.groups = groups;
		st.groupBy = by;
	}
	function similarity(a, b, by) {
		if (by === 'bits') {
			const x = a.bits || '', y = b.bits || '';
			if (!x.length || !y.length) return x === y ? 1 : 0;
			const n = Math.max(x.length, y.length);
			let same = 0;
			for (let k = 0; k < n; k++) if (x[k] !== undefined && x[k] === y[k]) same++;
			return same / n;
		}
		const lr = Math.min(a.len, b.len) / Math.max(a.len, b.len);
		return Math.max(0, corr(a.shape, b.shape)) * Math.sqrt(lr);
	}

	// ── 그리기 ───────────────────────────────────────────────
	const PH_LUT = (() => {
		const lut = new Uint8ClampedArray(256 * 3);
		for (let k = 0; k < 256; k++) {
			const h = (k / 256) * 6, x = 1 - Math.abs((h % 2) - 1), sec = Math.floor(h);
			const [r, g, b] = [[1, x, 0], [x, 1, 0], [0, 1, x], [0, x, 1], [x, 0, 1], [1, 0, x]][sec];
			lut[k * 3] = 40 + r * 200; lut[k * 3 + 1] = 40 + g * 200; lut[k * 3 + 2] = 40 + b * 200;
		}
		return lut;
	})();
	const DIV_LUT = (() => {
		const lut = new Uint8ClampedArray(256 * 3);
		for (let k = 0; k < 256; k++) {
			const t = k / 255 * 2 - 1, a = Math.abs(t);
			const c = t < 0 ? [33, 102, 172] : [178, 24, 43];
			for (let j = 0; j < 3; j++) lut[k * 3 + j] = 247 + (c[j] - 247) * a;
		}
		return lut;
	})();
	function order() {
		const how = $('iq-st-sort').value, rows = [...st.rows];
		if (how === 'group') rows.sort((p, q) => p.group - q.group || p.t0 - q.t0);
		else if (how === 'len') rows.sort((p, q) => q.dur - p.dur);
		else if (how === 'pow') rows.sort((p, q) => q.dbfs - p.dbfs);
		return rows;
	}
	const LM = 58, TM = 4, BM = 22;
	let geo = null;
	function drawImage() {
		const cv = $('iq-st-img');
		if (!st) { cv.style.height = '0px'; return; }
		const rows = order(), N = rows.length;
		const rh = clamp(Math.floor(420 / N), 3, 22);
		const H = N * rh + TM + BM;
		cv.style.height = `${H}px`;
		const dpr = window.devicePixelRatio || 1, W = cv.clientWidth;
		cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
		const ctx = cv.getContext('2d');
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		const P = IQ.pal();
		ctx.fillStyle = P.bg; ctx.fillRect(0, 0, W, H);
		const pw = Math.max(10, Math.floor(W - LM - 8)), view = $('iq-st-view').value, nMax = st.nMax;
		// 값 범위
		let lo, hi;
		if (view === 'mag') {
			const pk = Math.max(...rows.map((r) => dbOf(pct(r.ps, 0.99))));
			hi = pk + 1; lo = pk - (numv('iq-st-dyn') || 40);
		} else if (view === 'fm') {
			const v = [];
			for (const r of rows) { const f = r.fm; for (let k = r.k0; k <= r.k1; k += Math.max(1, Math.floor(r.len / 300))) if (r.ps[k] > r.thr) v.push(f[k]); }
			const s = Float32Array.from(v).sort();
			lo = s.length ? s[Math.floor(s.length * 0.01)] : -1; hi = s.length ? s[Math.floor(s.length * 0.99)] : 1;
			if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
		} else if (view === 'i') {
			const m = Math.max(...rows.map((r) => Math.sqrt(pct(r.ps, 0.99))));
			lo = -m; hi = m;
		} else { lo = -Math.PI; hi = Math.PI; }
		const img = ctx.createImageData(Math.round(pw * dpr), Math.round(N * rh * dpr));
		const iw = img.width, ih = img.height, rhp = ih / N;
		for (let ri = 0; ri < N; ri++) {
			const r = rows[ri], f = r.fm;
			// 위상: 버스트 평균 주파수만큼 돌려서 기울기를 뺌
			const w = view === 'ph' ? (-2 * Math.PI * (r.cfo - (st.filt ? st.filt.df : 0))) / st.rate : 0;
			const y0 = Math.round(ri * rhp), y1 = Math.max(y0 + 1, Math.round((ri + 1) * rhp) - (rhp >= 4 ? 1 : 0));
			for (let x = 0; x < iw; x++) {
				const a = r.start + Math.floor((x * nMax) / iw), b = Math.max(a + 1, r.start + Math.floor(((x + 1) * nMax) / iw));
				let rgb = null;
				if (a >= 0 && a < r.n) {
					let t;
					if (view === 'mag') {
						let s = 0, c = 0;
						for (let k = a; k < b && k < r.n; k++) { s += r.ps[k]; c++; }
						t = (dbOf(s / c) - lo) / (hi - lo);
						const j = clamp(Math.round(t * 255), 0, 255) * 3; rgb = [IQ.CMAP[j], IQ.CMAP[j + 1], IQ.CMAP[j + 2]];
					} else if (view === 'fm') {
						let s = 0, c = 0;
						for (let k = a; k < b && k < r.n; k++) if (r.ps[k] > r.thr) { s += f[k]; c++; }
						if (c) { t = (s / c - lo) / (hi - lo); const j = clamp(Math.round(t * 255), 0, 255) * 3; rgb = [IQ.CMAP[j], IQ.CMAP[j + 1], IQ.CMAP[j + 2]]; }
					} else {
						const k = Math.min(r.n - 1, (a + b) >> 1);
						if (view === 'i') { t = (r.y[2 * k] - lo) / (hi - lo); const j = clamp(Math.round(t * 255), 0, 255) * 3; rgb = [DIV_LUT[j], DIV_LUT[j + 1], DIV_LUT[j + 2]]; }
						else if (r.ps[k] > r.thr * 0.5) {
							const th = w * (k - r.start), c = Math.cos(th), s = Math.sin(th);
							const ph = Math.atan2(r.y[2 * k] * s + r.y[2 * k + 1] * c, r.y[2 * k] * c - r.y[2 * k + 1] * s);
							const j = (Math.floor(((ph + Math.PI) / (2 * Math.PI)) * 256) & 255) * 3; rgb = [PH_LUT[j], PH_LUT[j + 1], PH_LUT[j + 2]];
						}
					}
				}
				if (!rgb) continue;
				for (let yy = y0; yy < y1; yy++) { const o = (yy * iw + x) * 4; img.data[o] = rgb[0]; img.data[o + 1] = rgb[1]; img.data[o + 2] = rgb[2]; img.data[o + 3] = 255; }
			}
		}
		const tmp = document.createElement('canvas'); tmp.width = iw; tmp.height = ih;
		tmp.getContext('2d').putImageData(img, 0, 0);
		ctx.drawImage(tmp, LM, TM, pw, N * rh);
		// 줄 이름
		ctx.font = `${clamp(rh - 2, 8, 11)}px system-ui, sans-serif`; ctx.textBaseline = 'middle';
		const every = Math.ceil(11 / rh);
		rows.forEach((r, ri) => {
			const y = TM + ri * rh + rh / 2;
			ctx.fillStyle = gCol(r.group); ctx.fillRect(LM - 6, TM + ri * rh, 4, Math.max(1, rh - (rh >= 4 ? 1 : 0)));
			if (ri % every) return;
			ctx.fillStyle = P.text; ctx.textAlign = 'right';
			ctx.fillText(`#${r.i + 1} ${gName(r.group)}`, LM - 9, y);
		});
		// 시간축
		ctx.textBaseline = 'alphabetic'; ctx.fillStyle = P.text; ctx.font = '11px system-ui, sans-serif'; ctx.textAlign = 'center';
		const dur = (nMax * (st.rows[0].step)) / S.fs;
		for (let q = 0; q <= 4; q++) { ctx.textAlign = q === 4 ? 'right' : q === 0 ? 'left' : 'center'; ctx.fillText(IQ.fmtT((dur * q) / 4), LM + (pw * q) / 4, H - 6); }
		geo = { rows, rh, pw, nMax };
		$('iq-st-scale').textContent = view === 'mag' ? `색: ${lo.toFixed(0)} ~ ${hi.toFixed(0)} dBFS (어두움 → 밝음)` : view === 'fm' ? `색: 순간 주파수 ${IQ.fmtF(lo + (st.filt ? st.filt.df : 0))} ~ ${IQ.fmtF(hi + (st.filt ? st.filt.df : 0))} (꺼진 곳은 비움)` : view === 'i' ? '색: I 값 (파랑 − · 빨강 +)' : '색: 위상 (버스트마다 평균 주파수를 빼서 기울기 없앰, 색 한 바퀴 = 360°)';
	}
	function rowAt(e) {
		if (!geo) return null;
		const r = $('iq-st-img').getBoundingClientRect(), y = e.clientY - r.top - TM, x = e.clientX - r.left - LM;
		const ri = Math.floor(y / geo.rh);
		if (ri < 0 || ri >= geo.rows.length) return null;
		return { row: geo.rows[ri], t: x >= 0 && x <= geo.pw ? ((x / geo.pw) * geo.nMax * geo.rows[ri].step) / S.fs : null };
	}

	function renderGroups() {
		const g = st.groups;
		$('iq-st-groups').innerHTML = `<p class="iq-sub">${st.groupBy === 'bits' ? '비트가' : '모양(세기' + (st.useFm ? '·순간 주파수' : '') + ')·길이가'} ${$('iq-st-thr').value}% 넘게 닮으면 같은 무리 → <b>${g.length}무리</b></p>` + g.map((m, k) => {
			const dur = m.reduce((s, r) => s + r.dur, 0) / m.length, db = m.reduce((s, r) => s + r.dbfs, 0) / m.length, cfo = m.reduce((s, r) => s + r.cfo, 0) / m.length;
			const ids = m.map((r) => `#${r.i + 1}`);
			return `<div class="iq-row"><span><b style="color:${gCol(k)}">■ ${gName(k)}</b> ${m.length}개 <span class="iq-sub">· 길이 ${IQ.fmtT(dur)} · ${db.toFixed(1)} dBFS · 주파수 ${cfo >= 0 ? '+' : ''}${IQ.fmtF(cfo)}${m[0].bits ? ` · ${m[0].bits.length} 비트` : ''} · ${esc(ids.slice(0, 24).join(' '))}${ids.length > 24 ? ' …' : ''}</span></span><button type="button" class="iq-btn" data-stg="${k}">첫 버스트 보기</button></div>`;
		}).join('');
	}
	function renderTable() {
		const rows = order();
		$('iq-st-tbl').innerHTML = `<thead><tr><th>#</th><th>무리</th><th>시작</th><th>길이</th><th>세기</th><th>주파수 치우침</th><th>${st.groupBy === 'bits' ? '비트 닮음' : '모양 닮음'}</th>${st.rows.some((r) => r.lag) ? '<th>밀림</th>' : ''}</tr></thead><tbody>` + rows.slice(0, 300).map((r) => `<tr data-str="${r.i}" style="cursor:pointer"><td>${r.i + 1}</td><td><b style="color:${gCol(r.group)}">${gName(r.group)}</b></td><td>${IQ.fmtT(r.t0)}</td><td>${IQ.fmtT(r.dur)}</td><td>${r.dbfs.toFixed(1)} dBFS</td><td>${r.cfo >= 0 ? '+' : ''}${IQ.fmtF(r.cfo)}</td><td>${(r.sim * 100).toFixed(0)}%</td>${st.rows.some((q) => q.lag) ? `<td>${IQ.fmtT((r.lag * r.step) / S.fs)}</td>` : ''}</tr>`).join('') + '</tbody>' + (rows.length > 300 ? '<caption class="iq-sub" style="caption-side:bottom">표는 300줄까지 — 전체는 CSV 로</caption>' : '');
	}
	function render() {
		$('iq-st-out').classList.remove('hidden');
		drawImage();
		renderGroups();
		renderTable();
		renderBits();
	}

	// ── 버스트마다 복조 ──────────────────────────────────────
	async function demodAll() {
		const msg = $('iq-st-bmsg');
		if (!st) { msg.textContent = '먼저 [▶ 모으기] 를 눌러 주세요.'; return; }
		const last = IN.last;
		let mod = $('iq-dm-mod').value;
		if (mod === 'auto') mod = last && last.mod;
		const baud = numv('iq-dm-baud') || (last && last.baud);
		if (!mod || !baud) { msg.innerHTML = '먼저 버스트 하나를 <b>[확대]</b> 해서 🔓 복조를 한 번 해 주세요 — 그 변조·심볼 속도·Δf·대역폭으로 모든 버스트를 똑같이 복조해요.'; return; }
		const df = (numv('iq-dm-df') ?? numv('iq-cn-df') ?? 0) * 1e3;
		const bw = clamp(((numv('iq-dm-bw') || 0) * 1e3) || (last && last.bw) || S.fs / 4, S.fs / 4000, S.fs);
		const code = $('iq-dm-code').value;
		msg.textContent = '버스트마다 복조하는 중…';
		await new Promise((r) => setTimeout(r, 20));
		let ok = 0;
		for (const r of st.rows) {
			r.bits = '';
			// 거르지 않은 원본이 필요 → 이 버스트를 다시 읽음 (모을 때 거른 경우 대비)
			const raw = st.filt ? await IQ.readSamples(r.a, Math.min(S.n - r.a, Math.ceil((r.n * r.step) + 4 * r.step + 1024))) : r.y;
			const ch = IN.channelize(raw, r.a, df, bw);
			if (!ch) continue;
			const y = ch.y, n = y.length / 2, fsd = ch.fsd, T0 = fsd / baud;
			const env = new Float32Array(n);
			for (let k = 0; k < n; k++) env[k] = Math.hypot(y[2 * k], y[2 * k + 1]);
			const ek = IN.twoMeans(env);
			const mask = new Uint8Array(n);
			const thrOn = ek ? ek.thr : 0;
			// 켜진 곳: 세기를 조금 뭉갠 값이 기준보다 큰 곳
			const W = clamp(Math.round(T0 * 2), 4, 512);
			let acc = 0;
			for (let k = 0; k < n; k++) { acc += env[k]; if (k >= W) acc -= env[k - W]; mask[Math.max(0, k - (W >> 1))] = acc / Math.min(k + 1, W) > thrOn * 0.7 ? 1 : 0; }
			let packets = [];
			if (mod === 'ook' || mod === 'fsk') {
				const soft = mod === 'ook' ? env : instFreq(y, n, fsd);
				const km = mod === 'ook' ? ek : IN.twoMeans(soft, mask);
				if (!km) continue;
				const hard = new Int8Array(n);
				for (let k = 0; k < n; k++) hard[k] = mod === 'fsk' && !mask[k] ? -1 : soft[k] > km.thr ? 1 : 0;
				// 버스트 하나 = 패킷 하나로 보고 (안의 긴 0 도 비트), 앞뒤 꺼진 시간(0)만 뺌
				packets = IN.runsToPackets(IN.runsOf(hard), T0, 0).map((p) => (mod === 'ook' ? { ...p, bits: p.bits.replace(/^0+|0+$/g, '') } : p));
			} else {
				packets = IN.pskPackets(y, mask, fsd, baud, mod === 'bpsk' ? 2 : 4).packets;
			}
			const best = packets.sort((p, q) => q.bits.length - p.bits.length)[0];
			if (best && best.bits.length >= 4) { r.bits = IN.lineCode(best.bits, code); ok++; }
		}
		st.bits = { mod, baud, code };
		$('iq-st-by').value = 'bits';
		group();
		render();
		msg.textContent = `${ok}/${st.rows.length}개 버스트에서 비트를 뽑았어요 (${mod.toUpperCase()} · ${Math.round(baud).toLocaleString()} baud · 버스트마다 가장 긴 패킷). 무리는 비트로 나눴어요.`;
	}
	function renderBits() {
		const box = $('iq-st-bits');
		if (!st || !st.bits) { box.innerHTML = ''; return; }
		const rows = order().filter((r) => r.bits);
		if (!rows.length) { box.innerHTML = '<p class="iq-sub">비트를 뽑은 버스트가 없어요.</p>'; return; }
		const L = Math.max(...rows.map((r) => r.bits.length));
		// 자리마다: 모두 같은지(고정) / 다른지(바뀌는 칸)
		const vary = new Uint8Array(L);
		for (let k = 0; k < L; k++) { const c = rows[0].bits[k]; for (const r of rows) if (r.bits[k] !== c) { vary[k] = 1; break; } }
		const ranges = [];
		for (let k = 0; k < L; k++) if (vary[k] && (k === 0 || !vary[k - 1])) { let j = k; while (j + 1 < L && vary[j + 1]) j++; ranges.push(j > k ? `${k}–${j}` : `${k}`); }
		const fixed = vary.reduce((s, v) => s + (v ? 0 : 1), 0);
		const ruler = Array.from({ length: Math.ceil(L / 8) }, (_, q) => String(q * 8).padEnd(8, ' ')).join(' ');
		box.innerHTML = `<p class="iq-sub">비트 ${L}자리 중 <b>모두 같은 자리 ${fixed}개</b> (회색), <b>버스트마다 다른 자리 ${L - fixed}개</b> (진하게)${ranges.length ? ` — 다른 자리(0부터): ${esc(ranges.slice(0, 20).join(', '))}${ranges.length > 20 ? ' …' : ''}` : ''}. 늘 같은 칸은 프리앰블·주소(ID), 바뀌는 칸은 카운터·센서 값·버튼일 때가 많아요.</p>
			<div class="mt-2 overflow-x-auto"><pre class="iq-bits" style="white-space:pre;word-break:normal;line-height:1.55;font-size:12px"><span class="iq-sub">        ${esc(ruler)}</span>\n${rows.map((r) => `<span style="color:${gCol(r.group)}">${esc(`#${r.i + 1}`.padEnd(5))}${gName(r.group).padEnd(3)}</span>${[...r.bits].map((c, k) => `${k && k % 8 === 0 ? ' ' : ''}${vary[k] ? `<b style="color:${c === '1' ? '#0066cc' : '#e8590c'}">${c}</b>` : `<span style="opacity:.45">${c}</span>`}`).join('')}`).join('\n')}</pre></div>`;
	}

	// ── 저장 ─────────────────────────────────────────────────
	function matrix() {
		const rows = [...st.rows].sort((p, q) => p.i - q.i), N = rows.length, n = st.nMax;
		return { rows, N, n };
	}
	function download(blob, name) {
		const url = URL.createObjectURL(blob);
		const a = Object.assign(document.createElement('a'), { href: url, download: name });
		document.body.appendChild(a); a.click(); a.remove();
		setTimeout(() => URL.revokeObjectURL(url), 5000);
	}
	const base = () => S.name.replace(/\.[^.]+$/, '') + '_bursts';
	function tooBig(N, n) { if (N * n > 16e6) { $('iq-st-msg').textContent = `행렬이 너무 커요 (${N} × ${n}) — 거르기를 켜서(솎아서) 샘플 수를 줄여 주세요.`; return true; } return false; }
	function saveNpy() {
		const { rows, N, n } = matrix();
		if (tooBig(N, n)) return;
		const data = new Float32Array(N * n * 2);
		rows.forEach((r, i) => { for (let k = 0; k < n; k++) { const s = r.start + k; if (s >= 0 && s < r.n) { data[(i * n + k) * 2] = r.y[2 * s]; data[(i * n + k) * 2 + 1] = r.y[2 * s + 1]; } } });
		let hdr = `{'descr': '<c8', 'fortran_order': False, 'shape': (${N}, ${n}), }`;
		const total = 10 + hdr.length + 1;
		hdr += ' '.repeat((64 - (total % 64)) % 64) + '\n';
		const head = new Uint8Array(10 + hdr.length);
		head.set([0x93, 0x4e, 0x55, 0x4d, 0x50, 0x59, 1, 0, hdr.length & 255, hdr.length >> 8]);
		for (let k = 0; k < hdr.length; k++) head[10 + k] = hdr.charCodeAt(k);
		download(new Blob([head, data.buffer]), `${base()}.npy`);
	}
	function saveMat() {
		const PD = window.PlotData;
		const { rows, N, n } = matrix();
		if (!PD || tooBig(N, n)) return;
		const re = new Float64Array(N * n), im = new Float64Array(N * n);
		rows.forEach((r, i) => { for (let k = 0; k < n; k++) { const s = r.start + k; if (s >= 0 && s < r.n) { re[k * N + i] = r.y[2 * s]; im[k * N + i] = r.y[2 * s + 1]; } } });
		const col = (f) => rows.map(f);
		const vars = [
			{ name: 'X', dims: [N, n], re, im },
			{ name: 'fs', dims: [1, 1], re: [st.rate] },
			{ name: 'len', dims: [N, 1], re: col((r) => Math.min(r.len, n)) },
			{ name: 't0', dims: [N, 1], re: col((r) => r.t0) },
			{ name: 'power_dbfs', dims: [N, 1], re: col((r) => r.dbfs) },
			{ name: 'cfo_hz', dims: [N, 1], re: col((r) => r.cfo) },
			{ name: 'group', dims: [N, 1], re: col((r) => r.group + 1) },
		];
		if (st.bits) {
			const L = Math.max(1, ...rows.map((r) => (r.bits || '').length)), b = new Float64Array(N * L).fill(-1);
			rows.forEach((r, i) => { for (let k = 0; k < (r.bits || '').length; k++) b[k * N + i] = r.bits[k] === '1' ? 1 : r.bits[k] === '0' ? 0 : -1; });
			vars.push({ name: 'bits', dims: [N, L], re: b });
		}
		download(PD.writeMat5(vars), `${base()}.mat`);
	}
	function saveCsv() {
		const { rows } = matrix();
		const head = ['burst', 'group', 'start_s', 'duration_s', 'power_dbfs', 'cfo_hz', 'similarity', 'len_samples'].concat(st.bits ? ['bits'] : []);
		const lines = rows.map((r) => [r.i + 1, gName(r.group), r.t0.toPrecision(9), r.dur.toPrecision(6), r.dbfs.toFixed(2), r.cfo.toFixed(1), r.sim.toFixed(3), r.len].concat(st.bits ? [`'${r.bits || ''}`] : []).join(','));
		download(new Blob(['﻿' + [head.join(','), ...lines].join('\n')], { type: 'text/csv' }), `${base()}.csv`);
	}

	// ── 연결 ─────────────────────────────────────────────────
	function hint() {
		const n = (IN.bursts || []).length;
		$('iq-st-count').textContent = S.ov ? (n ? `찾은 버스트 ${n}개` : '찾은 버스트가 없어요') : '';
		if (st && st.key !== `${S.name}|${S.n}`) { st = null; $('iq-st-out').classList.add('hidden'); $('iq-st-msg').textContent = ''; $('iq-st-bmsg').textContent = ''; }
	}
	let ht = 0;
	document.addEventListener('iq:view', () => { clearTimeout(ht); ht = setTimeout(hint, 120); });
	$('iq-st-run').addEventListener('click', () => collect().catch((e) => { $('iq-st-msg').textContent = `모으지 못했어요: ${e.message}`; }));
	$('iq-st-demod').addEventListener('click', () => demodAll().catch((e) => { $('iq-st-bmsg').textContent = `복조하지 못했어요: ${e.message}`; }));
	$('iq-st-view').addEventListener('change', () => { if (!st) return; if ($('iq-st-align').value === 'xcorr') align(); group(); render(); });
	$('iq-st-align').addEventListener('change', () => { if (!st) return; align(); group(); render(); });
	$('iq-st-filt').addEventListener('change', () => { if (st) collect(); });
	$('iq-st-gap').addEventListener('change', () => { if (st) collect(); });
	for (const id of ['iq-st-thr', 'iq-st-by']) $(id).addEventListener('change', () => { if (!st) return; group(); render(); });
	$('iq-st-thr').addEventListener('input', () => { $('iq-st-thr-v').textContent = `${$('iq-st-thr').value}%`; });
	$('iq-st-sort').addEventListener('change', () => { if (st) render(); });
	$('iq-st-dyn').addEventListener('change', () => { if (st) drawImage(); });
	$('iq-st-npy').addEventListener('click', () => st && saveNpy());
	$('iq-st-mat').addEventListener('click', () => st && saveMat());
	$('iq-st-csv').addEventListener('click', () => st && saveCsv());
	const cv = $('iq-st-img');
	cv.addEventListener('pointermove', (e) => {
		const h = rowAt(e);
		$('iq-st-hover').textContent = h ? `#${h.row.i + 1} · 무리 ${gName(h.row.group)} · 시작 ${IQ.fmtT(h.row.t0)} · 길이 ${IQ.fmtT(h.row.dur)} · ${h.row.dbfs.toFixed(1)} dBFS${h.t != null ? ` · 줄 안 ${IQ.fmtT(h.t)}` : ''} — 누르면 위에서 크게` : '';
	});
	cv.addEventListener('pointerleave', () => { $('iq-st-hover').textContent = ''; });
	const goRow = (r) => { if (!r) return; IN.pickBurst({ s0: r.off + r.start * r.step, s1: r.off + (r.start + Math.min(r.len, st.nMax)) * r.step }); $('iq-work').scrollIntoView({ behavior: 'smooth', block: 'start' }); };
	cv.addEventListener('click', (e) => { const h = rowAt(e); if (h) goRow(h.row); });
	$('iq-st-tbl').addEventListener('click', (e) => { const tr = e.target.closest('[data-str]'); if (tr) goRow(st.rows.find((r) => r.i === +tr.dataset.str)); });
	$('iq-st-groups').addEventListener('click', (e) => { const b = e.target.closest('[data-stg]'); if (b) goRow(st.groups[+b.dataset.stg][0]); });
	let rt = 0;
	new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { if (st) drawImage(); }, 120); }).observe($('iq-st'));
	new MutationObserver(() => { if (st) drawImage(); }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
	window.__iqStack = { collect, demodAll, get st() { return st; } };
})();
