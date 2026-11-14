// IQ 분석기의 "알아보기" 칸: 신호 자동 찾기 · 복조(0·1 비트 뽑기) · ✨AI 분석.
// iq-analyzer.js 가 내보낸 window.__iq 를 쓴다. 복조도 브라우저 안에서만 하고, AI 에는 잰 숫자와 스펙트로그램 그림만 보낸다.
(() => {
	'use strict';
	const IQ = window.__iq;
	if (!IQ) return;
	const { S } = IQ;
	const $ = (id) => document.getElementById(id);
	const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
	const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
	const dbOf = (p) => 10 * Math.log10(p + 1e-20);
	const num = (id) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : null; };

	// ── 1. 신호 찾기 ─────────────────────────────────────────
	// 주파수: 보이는 구간 스펙트럼에서 잡음 바닥보다 10 dB 넘게 솟은 곳을 이어서 띠로
	function findBands() {
		const sp = S.spec;
		if (!sp) return [];
		const thr = sp.floor + 10, out = [];
		let k = 0;
		while (k < sp.N) {
			if (sp.avg[k] <= thr) { k++; continue; }
			let k1 = k, gap = 0, j = k + 1;
			for (; j < sp.N; j++) {
				if (sp.avg[j] > thr) { k1 = j; gap = 0; } else if (++gap > 2) break;
			}
			let pk = k, pw = 0, fw = 0;
			for (let i = k; i <= k1; i++) {
				const p = Math.pow(10, sp.avg[i] / 10);
				pw += p;
				fw += p * IQ.binF(i, sp.N);
				if (sp.avg[i] > sp.avg[pk]) pk = i;
			}
			out.push({ center: fw / pw + S.fs / sp.N / 2, width: ((k1 - k + 1) * S.fs) / sp.N, peak: sp.avg[pk], snr: sp.avg[pk] - sp.floor });
			k = k1 + 1;
		}
		// 센 신호 바로 옆의 10 dB 넘게 약한 띠는 그 신호의 옆 부분(사이드로브)으로 보고 뺌
		// (켜고 끄는 신호는 양옆으로 작은 띠가 줄줄이 생김), 가장 센 것보다 40 dB 넘게 약한 것도 뺌
		const top = Math.max(...out.map((b) => b.peak));
		let keep = out.filter((b) => top - b.peak <= 40 && !(top - b.peak > 30 && b.snr < 15) && !out.some((o) => o !== b && o.peak - b.peak > 10 && Math.abs(o.center - b.center) - (o.width + b.width) / 2 < o.width * 3));
		// 세기가 비슷한 두 봉우리가 가까이 있으면 FSK(주파수 두 개를 오감)일 때가 많아 한 신호로 묶음
		keep.sort((a, b) => a.center - b.center);
		const merged = [];
		for (const b of keep) {
			const p = merged[merged.length - 1];
			if (p && Math.abs(p.peak - b.peak) < 6 && b.center - b.width / 2 - (p.center + p.width / 2) < 3 * Math.max(p.width, b.width)) {
				const lo = p.center - p.width / 2, hi = b.center + b.width / 2;
				merged[merged.length - 1] = { center: (lo + hi) / 2, width: hi - lo, peak: Math.max(p.peak, b.peak), snr: Math.max(p.snr, b.snr), pair: true };
			} else merged.push(b);
		}
		keep = merged;
		return keep.sort((a, b) => b.peak - a.peak).slice(0, 8).sort((a, b) => a.center - b.center);
	}
	// 시간: 파일 전체 개요에서 바닥보다 6 dB 넘게 센 구간
	function findBursts() {
		const ov = S.ov;
		if (!ov) return [];
		const p = new Float32Array(ov.bins);
		for (let b = 0; b < ov.bins; b++) p[b] = ov.cnt[b] ? dbOf(ov.msum[b] / ov.cnt[b]) : -200;
		const sorted = Array.from(p).filter((v) => v > -199).sort((a, b) => a - b);
		if (!sorted.length) return [];
		const floor = sorted[Math.floor(sorted.length * 0.2)], top = sorted[sorted.length - 1];
		if (top - floor < 6) return [];
		const thr = floor + Math.min(6, (top - floor) / 2), gapMax = Math.max(2, Math.round(ov.bins * 0.0005)), out = [];
		let b = 0;
		while (b < ov.bins) {
			if (p[b] <= thr) { b++; continue; }
			let b1 = b, gap = 0, j = b + 1;
			for (; j < ov.bins; j++) {
				if (p[j] > thr) { b1 = j; gap = 0; } else if (++gap > gapMax) break;
			}
			let sum = 0, c = 0;
			for (let i = b; i <= b1; i++) { sum += ov.msum[i]; c += ov.cnt[i]; }
			out.push({ s0: Math.floor((b * S.n) / ov.bins), s1: Math.ceil(((b1 + 1) * S.n) / ov.bins), power: dbOf(sum / Math.max(1, c)) });
			b = b1 + 1;
		}
		// 처음부터 끝까지 다 켜져 있으면 "버스트" 가 아니라 계속 나오는 신호
		if (out.length === 1 && out[0].s1 - out[0].s0 > S.n * 0.95) return [];
		return out;
	}
	let lastBands = [], lastBursts = [];
	function renderFind() {
		lastBands = findBands();
		lastBursts = findBursts();
		$('iq-find-bands').innerHTML = lastBands.length
			? lastBands.map((b, i) => `<li class="iq-row"><span><b>${IQ.fmtF(b.center + S.fc)}</b> <span class="iq-sub">(가운데에서 ${b.center >= 0 ? '+' : ''}${IQ.fmtF(b.center)}) · 폭 ${IQ.fmtF(b.width)} · ${b.peak.toFixed(1)} dBFS · 잡음보다 ${b.snr.toFixed(0)} dB${b.pair ? ' · 봉우리 두 개 (FSK?)' : ''}</span></span><button type="button" class="iq-btn" data-band="${i}">이 신호 고르기</button></li>`).join('')
			: '<li class="iq-sub">보이는 구간에서 잡음보다 10 dB 넘게 솟은 신호가 없어요. 시간을 신호가 있는 곳으로 옮기거나 확대해 보세요.</li>';
		const shown = lastBursts.slice(0, 30);
		$('iq-find-bursts').innerHTML = lastBursts.length
			? shown.map((b, i) => `<li class="iq-row"><span><b>${IQ.fmtT(b.s0 / S.fs)} ~ ${IQ.fmtT(b.s1 / S.fs)}</b> <span class="iq-sub">길이 ${IQ.fmtT((b.s1 - b.s0) / S.fs)} · ${b.power.toFixed(1)} dBFS${i > 0 ? ` · 앞 신호와 ${IQ.fmtT((b.s0 - shown[i - 1].s0) / S.fs)} 간격` : ''}</span></span><button type="button" class="iq-btn" data-burst="${i}">확대</button></li>`).join('') + (lastBursts.length > shown.length ? `<li class="iq-sub">… 모두 ${lastBursts.length}개</li>` : '')
			: '<li class="iq-sub">켜졌다 꺼지는 구간(버스트)이 따로 없어요 — 계속 나오는 신호이거나 잡음만 있어요.</li>';
	}
	function pickBand(b) {
		$('iq-cn-df').value = (b.center / 1e3).toFixed(3);
		$('iq-dm-bw').value = (Math.max(b.width * 1.2, (S.fs / (S.spec?.N || 1024)) * 4) / 1e3).toFixed(3);
		$('iq-cn-df').dispatchEvent(new Event('change'));
		$('iq-dm-msg').textContent = `Δf ${(b.center / 1e3).toFixed(1)} kHz · 대역폭 ${$('iq-dm-bw').value} kHz 로 맞췄어요. 이제 [복조하기] 를 눌러 보세요.`;
	}
	function pickBurst(b) {
		const pad = Math.max(16, Math.round((b.s1 - b.s0) * 0.05));
		IQ.setView(b.s0 - pad, b.s1 + pad);
	}

	// ── 2. 복조 ───────────────────────────────────────────────
	// 원하는 신호만 가운데로 옮기고(Δf) 저역 필터로 거른 뒤 솎아 냄
	function channelize(iq, base, df, bw) {
		const fs = S.fs, N = iq.length / 2;
		const D = Math.max(1, Math.floor(fs / (4 * bw)));
		let L = clamp(Math.round((4 * fs) / bw) | 1, 15, 801);
		if (L % 2 === 0) L++;
		const h = new Float64Array(L), fc = clamp(bw / 2 / fs, 1e-6, 0.5), mid = (L - 1) / 2;
		let hs = 0;
		for (let k = 0; k < L; k++) {
			const t = k - mid, sinc = t === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * t) / (Math.PI * t);
			h[k] = sinc * (0.42 - 0.5 * Math.cos((2 * Math.PI * k) / (L - 1)) + 0.08 * Math.cos((4 * Math.PI * k) / (L - 1)));
			hs += h[k];
		}
		for (let k = 0; k < L; k++) h[k] /= hs;
		const x = new Float32Array(N * 2), w = (-2 * Math.PI * df) / fs;
		for (let k = 0; k < N; k++) {
			const th = w * (base + k), c = Math.cos(th), s = Math.sin(th), I = iq[2 * k], Q = iq[2 * k + 1];
			x[2 * k] = I * c - Q * s;
			x[2 * k + 1] = I * s + Q * c;
		}
		const M = Math.floor((N - L) / D) + 1;
		if (M < 16) return null;
		const y = new Float32Array(M * 2);
		for (let m = 0; m < M; m++) {
			let re = 0, im = 0;
			const o = m * D;
			for (let k = 0; k < L; k++) { re += h[k] * x[2 * (o + k)]; im += h[k] * x[2 * (o + k) + 1]; }
			y[2 * m] = re;
			y[2 * m + 1] = im;
		}
		return { y, fsd: fs / D, D, delay: mid, M };
	}
	// 1차원 값을 두 무리로 (켜짐/꺼짐, 높은 주파수/낮은 주파수)
	function twoMeans(v, mask) {
		const vals = [];
		const step = Math.max(1, Math.floor(v.length / 200000));
		for (let k = 0; k < v.length; k += step) if ((!mask || mask[k]) && Number.isFinite(v[k])) vals.push(v[k]);
		if (vals.length < 8) return null;
		vals.sort((a, b) => a - b);
		let lo = vals[Math.floor(vals.length * 0.1)], hi = vals[Math.floor(vals.length * 0.9)];
		let sl = 0, sh = 0, nl = 0, nh = 0;
		for (let it = 0; it < 20; it++) {
			const t = (lo + hi) / 2;
			sl = sh = nl = nh = 0;
			for (const x of vals) { if (x < t) { sl += x; nl++; } else { sh += x; nh++; } }
			if (!nl || !nh) break;
			lo = sl / nl;
			hi = sh / nh;
		}
		const t = (lo + hi) / 2;
		let vl = 0, vh = 0;
		for (const x of vals) { if (x < t) vl += (x - lo) ** 2; else vh += (x - hi) ** 2; }
		const spread = Math.sqrt((vl + vh) / vals.length) || 1e-12;
		return { lo, hi, thr: t, spread, fracHi: nh / vals.length };
	}
	// 복소 신호 u^m 의 스펙트럼에서 가장 센 줄(선 스펙트럼) — PSK·반송파 알아보기
	function powerLine(y, mask, m) {
		const idx = [];
		for (let k = 0; k < y.length / 2 && idx.length < 65536; k++) if (mask[k]) idx.push(k);
		const P = 1 << Math.floor(Math.log2(Math.max(64, idx.length)));
		if (idx.length < 256) return { ratio: 0, f: 0 };
		const re = new Float64Array(P), im = new Float64Array(P);
		for (let j = 0; j < P; j++) {
			const k = idx[j], a = y[2 * k], b = y[2 * k + 1], r = Math.hypot(a, b) || 1;
			let pr = a / r, pi = b / r, zr = 1, zi = 0;
			for (let q = 0; q < m; q++) { const t = zr * pr - zi * pi; zi = zr * pi + zi * pr; zr = t; }
			re[j] = zr;
			im[j] = zi;
		}
		IQ.fft(re, im);
		let best = 0, bk = 0, sum = 0;
		for (let k = 0; k < P; k++) { const p = re[k] * re[k] + im[k] * im[k]; sum += p; if (p > best) { best = p; bk = k; } }
		return { ratio: best / (sum / P), bin: bk, P, f: bk < P / 2 ? bk : bk - P };
	}
	function symbolRateFromEnvelope(y, mask, fsd) {
		const idx = [];
		for (let k = 0; k < y.length / 2 && idx.length < 65536; k++) if (mask[k]) idx.push(k);
		const P = 1 << Math.floor(Math.log2(Math.max(64, idx.length)));
		if (idx.length < 512) return null;
		const re = new Float64Array(P), im = new Float64Array(P);
		let mean = 0;
		for (let j = 0; j < P; j++) { const k = idx[j]; re[j] = y[2 * k] ** 2 + y[2 * k + 1] ** 2; mean += re[j]; }
		mean /= P;
		for (let j = 0; j < P; j++) re[j] -= mean;
		IQ.fft(re, im);
		let best = 0, bk = 0, sum = 0;
		const k0 = Math.max(3, Math.floor(P / 100)), k1 = Math.floor(P / 2.2);
		for (let k = k0; k < k1; k++) { const p = re[k] * re[k] + im[k] * im[k]; sum += p; if (p > best) { best = p; bk = k; } }
		if (!bk || best / (sum / (k1 - k0)) < 12) return null;
		return (bk * fsd) / P;
	}
	// 0/1 이 이어진 길이(런)로 한 심볼 길이를 찾고 비트로 바꿈 (OOK·FSK)
	function runsOf(hard) {
		const runs = [];
		let v = hard[0], len = 0;
		for (let k = 0; k < hard.length; k++) {
			if (hard[k] === v) len++;
			else { runs.push({ v, len }); v = hard[k]; len = 1; }
		}
		runs.push({ v, len });
		return runs;
	}
	function estimateT(runs) {
		const data = runs.filter((r) => r.v >= 0 && r.len >= 2).map((r) => r.len).sort((a, b) => a - b);
		if (data.length < 4) return null;
		const g = data[Math.floor(data.length * 0.15)];
		let bestT = g, bestE = Infinity;
		for (let i = 0; i <= 240; i++) {
			const T = g * (0.6 + (0.9 * i) / 240);
			let e = 0, c = 0;
			for (const r of data) {
				if (r > 24 * T) continue;
				const q = r / T, n = Math.max(1, Math.round(q));
				e += (q - n) ** 2;
				c++;
			}
			if (c && e / c < bestE - 1e-9) { bestE = e / c; bestT = T; }
		}
		return { T: bestT, err: bestE };
	}
	function runsToPackets(runs, T, gapSyms) {
		// 너무 짧은 런(잡음)은 앞 런에 붙임
		const clean = [];
		for (const r of runs) {
			if (clean.length && (r.len < 0.35 * T || r.v === clean[clean.length - 1].v)) clean[clean.length - 1].len += r.len;
			else clean.push({ ...r });
		}
		const packets = [];
		let cur = null, pos = 0;
		for (const r of clean) {
			const sep = r.v < 0 || (gapSyms && r.v === 0 && r.len > gapSyms * T);
			if (sep) { if (cur && cur.bits.length) packets.push(cur); cur = null; }
			else {
				if (!cur) cur = { start: pos, bits: '' };
				cur.bits += String(r.v).repeat(Math.max(1, Math.round(r.len / T)));
			}
			pos += r.len;
		}
		if (cur && cur.bits.length) packets.push(cur);
		// OOK 은 패킷 끝의 0 들은 꺼진 시간이라 뺌
		return packets;
	}
	function interp(y, t) {
		const k = Math.floor(t), a = t - k;
		if (k < 0 || k + 1 >= y.length / 2) return null;
		return [y[2 * k] * (1 - a) + y[2 * k + 2] * a, y[2 * k + 1] * (1 - a) + y[2 * k + 3] * a];
	}
	function pskPackets(y, mask, fsd, Rs, order) {
		const sps = fsd / Rs, segs = [], pts = [];
		let k = 0;
		const n = y.length / 2;
		while (k < n) {
			if (!mask[k]) { k++; continue; }
			let j = k;
			while (j < n && (mask[j] || (j + 1 < n && mask[j + 1]))) j++;
			if (j - k >= 8 * sps) segs.push([k, j]);
			k = j + 1;
		}
		const packets = [];
		for (const [a, b] of segs) {
			const len = b - a, seg = y.subarray(2 * a, 2 * b), all = new Uint8Array(len).fill(1);
			// 남은 주파수 어긋남: u^order 의 선 스펙트럼 위치 / order
			const line = powerLine(seg, all, order);
			const fo = line.P ? (line.f * fsd) / line.P / order : 0;
			const w = (-2 * Math.PI * fo) / fsd, z = new Float32Array(len * 2);
			for (let i = 0; i < len; i++) { const c = Math.cos(w * i), s = Math.sin(w * i); z[2 * i] = seg[2 * i] * c - seg[2 * i + 1] * s; z[2 * i + 1] = seg[2 * i] * s + seg[2 * i + 1] * c; }
			// 표본 시점: 심볼 안 16군데 중 세기가 가장 큰 곳
			let bestT0 = 0, bestE = -1;
			for (let q = 0; q < 16; q++) {
				const t0 = (q / 16) * sps;
				let e = 0, c = 0;
				for (let t = t0; t < len - 1; t += sps) { const p = interp(z, t); if (p) { e += p[0] * p[0] + p[1] * p[1]; c++; } }
				if (c && e / c > bestE) { bestE = e / c; bestT0 = t0; }
			}
			const sy = [];
			for (let t = bestT0; t < len - 1; t += sps) { const p = interp(z, t); if (p) sy.push(p); }
			if (sy.length < 8) continue;
			let sr = 0, si_ = 0;
			for (const [I, Q] of sy) {
				let zr = I, zi = Q;
				for (let q = 1; q < order; q++) { const t = zr * I - zi * Q; zi = zr * Q + zi * I; zr = t; }
				sr += zr; si_ += zi;
			}
			let ph = order === 4 ? (Math.atan2(si_, sr) - Math.PI) / 4 : Math.atan2(si_, sr) / 2;
			const rms = Math.sqrt(sy.reduce((s, [I, Q]) => s + I * I + Q * Q, 0) / sy.length) || 1;
			let bits = '';
			for (const [I0, Q0] of sy) {
				const c = Math.cos(-ph), s = Math.sin(-ph), I = (I0 * c - Q0 * s) / rms, Q = (I0 * s + Q0 * c) / rms;
				pts.push(I, Q);
				let dI, dQ;
				if (order === 2) { dI = I >= 0 ? 1 : -1; dQ = 0; bits += I >= 0 ? '1' : '0'; }
				else { dI = I >= 0 ? Math.SQRT1_2 : -Math.SQRT1_2; dQ = Q >= 0 ? Math.SQRT1_2 : -Math.SQRT1_2; bits += (I >= 0 ? '0' : '1') + (Q >= 0 ? '0' : '1'); }
				// 결정 지향 위상 추적 (조금씩 도는 것 따라가기)
				ph += 0.05 * Math.atan2(Q * dI - I * dQ, I * dI + Q * dQ);
			}
			packets.push({ start: a, bits, syms: sy.length });
		}
		return { packets, pts };
	}
	function lineCode(bits, code) {
		if (code === 'nrz') return bits;
		if (code === 'inv') return bits.replace(/[01]/g, (b) => (b === '1' ? '0' : '1'));
		const one = code === 'man10' ? '10' : '01', zero = code === 'man10' ? '01' : '10';
		let best = null;
		for (const off of [0, 1]) {
			let out = '', bad = 0;
			for (let k = off; k + 1 < bits.length; k += 2) {
				const pair = bits.substr(k, 2);
				if (pair === one) out += '1';
				else if (pair === zero) out += '0';
				else { out += '?'; bad++; }
			}
			if (!best || bad < best.bad) best = { out, bad };
		}
		return best.out;
	}
	function describeBits(bits) {
		let pre = 0;
		while (pre + 1 < bits.length && bits[pre] !== bits[pre + 1]) pre++;
		// 1010… 이 8비트 넘게 이어지면 프리앰블, 내용이 바이트 단위로 맞도록 8의 배수로 자름
		pre = pre < 7 ? 0 : Math.floor((pre + 1) / 8) * 8;
		const body = bits.slice(pre);
		const bytes = [];
		for (let k = 0; k + 8 <= body.length; k += 8) bytes.push(parseInt(body.substr(k, 8).replace(/\?/g, '0'), 2));
		return {
			preamble: pre,
			sync: body.slice(0, 16),
			hex: bytes.map((b) => b.toString(16).padStart(2, '0')).join(' '),
			ascii: bytes.map((b) => (b >= 32 && b < 127 ? String.fromCharCode(b) : '·')).join(''),
		};
	}

	let lastDemod = null;
	async function demodulate() {
		const msg = $('iq-dm-msg'), cnt = S.v1 - S.v0;
		if (!S.ov) return;
		if (cnt > IQ.RAW_MAX) { msg.textContent = `구간이 너무 넓어요 — ${IQ.RAW_MAX.toLocaleString()} 샘플 이하로 확대해 주세요 (신호 찾기 목록의 [확대] 를 써 보세요).`; return; }
		msg.textContent = '복조하는 중…';
		await new Promise((r) => setTimeout(r, 20));
		const iq = IQ.rawFor(S.v0, cnt) || (await IQ.readSamples(S.v0, cnt));
		const df = (num('iq-cn-df') || 0) * 1e3;
		let bw = (num('iq-dm-bw') || 0) * 1e3;
		if (!bw) {
			const near = lastBands.find((b) => Math.abs(b.center - df) < b.width / 2 + S.fs / 200);
			bw = near ? near.width * 1.2 : S.fs / 4;
		}
		bw = clamp(bw, S.fs / 4000, S.fs);
		const ch = channelize(iq, S.v0, df, bw);
		if (!ch) { msg.textContent = '구간이 너무 짧아요.'; return; }
		const { y, fsd } = ch, n = y.length / 2;
		const env = new Float32Array(n), fm = new Float32Array(n);
		for (let k = 0; k < n; k++) {
			env[k] = Math.hypot(y[2 * k], y[2 * k + 1]);
			if (k) {
				const a = y[2 * k], b = y[2 * k + 1], c = y[2 * k - 2], d = y[2 * k - 1];
				fm[k] = (Math.atan2(b * c - a * d, a * c + b * d) * fsd) / (2 * Math.PI);
			}
		}
		fm[0] = fm[1] || 0;
		// 켜짐/꺼짐: 버스트 구간은 세기를 조금 뭉갠 값으로 (PSK 의 심볼 경계 패임에 속지 않게)
		const W = clamp(Math.round((4 * fsd) / bw), 8, 512), envS = new Float32Array(n);
		let acc = 0;
		for (let k = 0; k < n; k++) {
			acc += env[k];
			if (k >= W) acc -= env[k - W];
			envS[Math.max(0, k - (W >> 1))] = acc / Math.min(k + 1, W);
		}
		for (let k = n - (W >> 1); k < n; k++) envS[k] = envS[Math.max(0, n - (W >> 1) - 1)];
		const gk = twoMeans(envS), ek = twoMeans(env);
		const dbGap = (km) => (km ? 20 * Math.log10(km.hi / Math.max(km.lo, km.hi * 1e-5)) : 0);
		const gated = dbGap(gk) > 10, onoffDb = dbGap(ek);
		const mask = new Uint8Array(n);
		for (let k = 0; k < n; k++) mask[k] = !gated || envS[k] > gk.thr ? 1 : 0;
		let onRuns = 0;
		for (let k = 1; k < n; k++) if (env[k] > ek.thr && env[k - 1] <= ek.thr && mask[k]) onRuns++;
		// FSK: 켜진 곳의 순간 주파수가 두 무리로 뚜렷이 나뉘는지
		const fk = twoMeans(fm, mask);
		const fskScore = fk ? (fk.hi - fk.lo) / fk.spread : 0;
		const l1 = powerLine(y, mask, 1), l2 = powerLine(y, mask, 2), l4 = powerLine(y, mask, 4);
		const feat = { onoffDb: +onoffDb.toFixed(1), onRuns, fskScore: +fskScore.toFixed(1), fskShiftHz: fk ? Math.round(fk.hi - fk.lo) : 0, line1: +l1.ratio.toFixed(0), line2: +l2.ratio.toFixed(0), line4: +l4.ratio.toFixed(0) };
		let auto = 'unknown', why = '';
		const T = 25;
		// 반송파 하나(OOK 켜진 동안·CW)는 x¹ 부터 선이 뚜렷 → PSK 는 x¹ 보다 10배 넘게 뚜렷할 때만
		if (l2.ratio > T && l2.ratio > 10 * l1.ratio && l2.ratio >= l4.ratio * 0.3) { auto = 'bpsk'; why = '제곱하면 선 하나가 생기고(위상 0°/180°), 원래 신호엔 선이 거의 없어요 → BPSK'; }
		else if (l4.ratio > T && l4.ratio > 10 * l1.ratio && l4.ratio > 10 * l2.ratio) { auto = 'qpsk'; why = '네제곱해야 선이 뚜렷해져요(위상 4가지) → QPSK'; }
		else if (fskScore > 4 && fk.hi - fk.lo > fsd * 0.004) { auto = 'fsk'; why = `켜진 동안 순간 주파수가 두 값(${IQ.fmtF(fk.lo)}, ${IQ.fmtF(fk.hi)})을 오가요 → FSK`; }
		else if (onoffDb > 10 && onRuns >= 3) { auto = 'ook'; why = `세기가 ${onoffDb.toFixed(0)} dB 차이로 켜졌다 꺼졌다를 ${onRuns}번 해요 → OOK(ASK)`; }
		else if (onoffDb > 10) { auto = 'ook'; why = `세기가 ${onoffDb.toFixed(0)} dB 차이로 켜졌다 꺼져요 → OOK 로 시도`; }
		else if (l1.ratio > T) { auto = 'cw'; why = '변조 없는 반송파(CW)·톤처럼 보여요 — 비트가 실려 있지 않을 수 있어요'; }
		else why = '디지털 0·1 모양이 뚜렷하지 않아요 — 아날로그(FM·AM), OFDM(와이파이·LTE), 잡음일 수 있어요. 대역폭·Δf 를 다시 맞춰 보세요.';
		let mod = $('iq-dm-mod').value;
		if (mod === 'auto') mod = auto === 'cw' || auto === 'unknown' ? null : auto;
		const result = { df, bw, fsd, auto, why, feat, mod, packets: [], baud: null };
		lastDemod = result;
		if (!mod) { renderDemod(result, null); return; }
		const userBaud = num('iq-dm-baud');
		let soft = null, thr = 0, T0 = null;
		if (mod === 'ook' || mod === 'fsk') {
			soft = mod === 'ook' ? env : fm;
			const km = mod === 'ook' ? ek : fk || twoMeans(fm, mask);
			if (!km) { msg.textContent = '두 값으로 나눌 수가 없어요.'; return; }
			thr = km.thr;
			const hard = new Int8Array(n);
			for (let k = 0; k < n; k++) hard[k] = mod === 'fsk' && !mask[k] ? -1 : soft[k] > thr ? 1 : 0;
			const runs = runsOf(hard);
			if (userBaud) T0 = fsd / userBaud;
			else { const e = estimateT(runs); T0 = e && e.T; }
			if (!T0) { msg.textContent = '심볼 길이를 못 찾았어요 — 심볼 속도(baud)를 직접 넣어 보세요.'; return; }
			result.packets = runsToPackets(runs, T0, mod === 'ook' ? 12 : 0).map((p) => (mod === 'ook' ? { ...p, bits: p.bits.replace(/0+$/, '') } : p)).filter((p) => p.bits.length >= 4);
			result.baud = fsd / T0;
			result.threshold = thr;
		} else {
			const Rs = userBaud || symbolRateFromEnvelope(y, mask, fsd);
			if (!Rs) { msg.textContent = '심볼 속도를 못 찾았어요 — baud 를 직접 넣어 보세요 (성상도에서 sps 를 맞춰 보면 fs ÷ sps 예요).'; return; }
			const r = pskPackets(y, mask, fsd, Rs, mod === 'bpsk' ? 2 : 4);
			result.packets = r.packets;
			result.baud = Rs;
			if (r.pts.length) {
				// 심볼만 성상도에 보여 줌
				let mx = 0;
				for (let k = 0; k < r.pts.length; k++) mx = Math.max(mx, Math.abs(r.pts[k]));
				S.cn = { pts: Float32Array.from(r.pts), scale: Math.min(2, mx) * 1.1 || 1.5 };
				IQ.drawConstellation();
				$('iq-cn-note').textContent = '복조한 심볼(위상 맞춘 뒤)을 보여 주는 중 — 구간을 바꾸면 원래대로.';
			}
		}
		result.soft = soft;
		result.env = env;
		renderDemod(result, ch);
	}
	const MOD_LABEL = { ook: 'OOK (켜짐·꺼짐)', fsk: '2-FSK (주파수 두 개)', bpsk: 'BPSK (위상 2개)', qpsk: 'QPSK (위상 4개)', cw: '반송파만 (CW)', unknown: '모름' };
	function renderDemod(r, ch) {
		const code = $('iq-dm-code').value;
		$('iq-dm-auto').innerHTML = `<b>추정: ${MOD_LABEL[r.auto]}</b> — ${esc(r.why)}<br><span class="iq-sub">켜짐/꺼짐 차 ${r.feat.onoffDb} dB · FSK 점수 ${r.feat.fskScore} · 선 스펙트럼 x¹ ${r.feat.line1} / x² ${r.feat.line2} / x⁴ ${r.feat.line4} (클수록 뚜렷)</span>`;
		const msg = $('iq-dm-msg');
		if (!r.mod) { msg.textContent = '변조를 골라서 다시 눌러 보세요.'; $('iq-dm-out').innerHTML = ''; drawDemod(null); return; }
		msg.textContent = `${MOD_LABEL[r.mod]} · 심볼 속도 약 ${Math.round(r.baud).toLocaleString()} baud · 거른 뒤 ${IQ.si(r.fsd, 'S/s')} · 패킷 ${r.packets.length}개`;
		const counts = new Map();
		const rows = r.packets.slice(0, 40).map((p, i) => {
			const bits = lineCode(p.bits, code), d = describeBits(bits);
			counts.set(bits, (counts.get(bits) || 0) + 1);
			const grouped = bits.replace(/(.{8})/g, '$1 ').trim();
			return `<div class="iq-pkt"><p class="iq-sub">#${i + 1} · ${IQ.fmtT((S.v0 + (p.start * S.fs) / r.fsd) / S.fs)} · ${bits.length} 비트${d.preamble ? ` · 앞 ${d.preamble} 비트는 1010… 프리앰블` : ''}</p><p class="iq-bits">${esc(grouped)}</p><p class="iq-sub">HEX${d.preamble ? ' (프리앰블 뒤)' : ''}: <code>${esc(d.hex || '–')}</code>${d.ascii ? ` · 글자: <code>${esc(d.ascii)}</code>` : ''}</p></div>`;
		});
		const same = [...counts.values()].filter((c) => c > 1).reduce((a, b) => a + b, 0);
		$('iq-dm-out').innerHTML = (same ? `<p class="iq-sub mb-2">🔁 똑같은 패킷이 반복돼요 (${same}개) — 리모컨·센서처럼 같은 내용을 여러 번 보내는 신호일 때가 많아요.</p>` : '') + (rows.join('') || '<p class="iq-sub">비트를 뽑지 못했어요.</p>');
		drawDemod(r);
	}
	function drawDemod(r) {
		const cv = $('iq-dm-plot'), g = IQ.fit(cv), P = IQ.pal(), { ctx, w, h } = g;
		ctx.fillStyle = P.bg;
		ctx.fillRect(0, 0, w, h);
		if (!r || !r.soft) {
			ctx.fillStyle = P.text;
			ctx.font = '12px system-ui, sans-serif';
			ctx.fillText(r && r.mod ? 'PSK 는 위 성상도에서 심볼을 보세요.' : '복조하면 여기에 판정 전 신호(OOK: 세기, FSK: 주파수)가 나와요.', 12, h / 2);
			return;
		}
		const v = r.soft, n = v.length;
		let lo = Infinity, hi = -Infinity;
		for (let k = 0; k < n; k++) { if (v[k] < lo) lo = v[k]; if (v[k] > hi) hi = v[k]; }
		const pad = (hi - lo) * 0.08 || 1, yOf = (x) => 6 + (1 - (x - lo + pad) / (hi - lo + 2 * pad)) * (h - 12);
		ctx.fillStyle = P.i;
		for (let x = 0; x < w; x++) {
			const a = Math.floor((x / w) * n), b = Math.max(a + 1, Math.floor(((x + 1) / w) * n));
			let mn = Infinity, mx = -Infinity;
			for (let k = a; k < b; k++) { if (v[k] < mn) mn = v[k]; if (v[k] > mx) mx = v[k]; }
			if (Number.isFinite(mn)) ctx.fillRect(x, yOf(mx), 1, Math.max(1, yOf(mn) - yOf(mx)));
		}
		ctx.strokeStyle = P.mark;
		ctx.setLineDash([5, 4]);
		ctx.beginPath();
		ctx.moveTo(0, yOf(r.threshold) + 0.5);
		ctx.lineTo(w, yOf(r.threshold) + 0.5);
		ctx.stroke();
		ctx.setLineDash([]);
		ctx.fillStyle = P.mark;
		ctx.font = '11px system-ui, sans-serif';
		ctx.fillText('판정 기준선 (위 = 1, 아래 = 0)', 8, yOf(r.threshold) - 4);
	}

	// ── 3. ✨AI ───────────────────────────────────────────────
	function measure() {
		const sp = S.spec, st = S.stats, curve = [];
		if (sp) {
			const G = 96, per = sp.N / G;
			for (let gI = 0; gI < G; gI++) {
				let m = -Infinity;
				for (let k = Math.floor(gI * per); k < Math.floor((gI + 1) * per); k++) m = Math.max(m, sp.avg[k]);
				curve.push([+((IQ.binF(Math.floor((gI + 0.5) * per), sp.N)) / 1e3).toFixed(1), +m.toFixed(1)]);
			}
		}
		const d = lastDemod;
		return {
			file: { name: S.name.slice(0, 80), format: IQ.FORMATS[S.fmt].label, fs: S.fs, center_mhz: S.fc / 1e6, samples: S.n, seconds: +(S.n / S.fs).toPrecision(5), source: S.source || '' },
			stats: st ? { mean_power_dbfs: +dbOf(st.power).toFixed(1), peak_dbfs: +dbOf(st.peak).toFixed(1), dc_dbc: +dbOf((st.mi * st.mi + st.mq * st.mq) / st.power).toFixed(1), iq_amp_db: +st.ampDb.toFixed(2), iq_phase_deg: +st.phaseDeg.toFixed(2) } : null,
			warnings: S.notes.slice(0, 5),
			view: { start_s: +(S.v0 / S.fs).toPrecision(6), end_s: +(S.v1 / S.fs).toPrecision(6), samples: S.v1 - S.v0 },
			spectrum: sp ? { fft: sp.N, peak_offset_hz: Math.round(IQ.binF(sp.peak, sp.N)), peak_dbfs: +sp.avg[sp.peak].toFixed(1), obw99_hz: Math.round(sp.obw), noise_floor_dbfs_per_bin: +sp.floor.toFixed(1), curve_khz_db: curve } : null,
			bands_in_view: lastBands.map((b) => ({ offset_khz: +(b.center / 1e3).toFixed(2), width_khz: +(b.width / 1e3).toFixed(2), peak_dbfs: +b.peak.toFixed(1), snr_db: +b.snr.toFixed(0) })),
			bursts_in_file: { count: lastBursts.length, first: lastBursts.slice(0, 15).map((b) => ({ start_s: +(b.s0 / S.fs).toPrecision(5), dur_ms: +(((b.s1 - b.s0) / S.fs) * 1e3).toPrecision(4), dbfs: +b.power.toFixed(1) })) },
			demod: d ? { df_khz: +(d.df / 1e3).toFixed(2), bw_khz: +(d.bw / 1e3).toFixed(2), auto_guess: d.auto, reason: d.why, features: d.feat, used: d.mod, baud: d.baud ? Math.round(d.baud) : null, line_code: $('iq-dm-code').value, packets: d.packets.slice(0, 6).map((p) => { const bits = lineCode(p.bits, $('iq-dm-code').value); return { n_bits: bits.length, bits: bits.slice(0, 256), ...describeBits(bits) }; }) } : null,
			constellation_now: { df_khz: num('iq-cn-df'), sps: num('iq-cn-sps') },
		};
	}
	function snapshot() {
		const src = $('iq-sg');
		if (!src.width) return '';
		const W = Math.min(900, src.width), H = Math.round((src.height * W) / src.width);
		const c = document.createElement('canvas');
		c.width = W;
		c.height = H;
		c.getContext('2d').drawImage(src, 0, 0, W, H);
		return c.toDataURL('image/jpeg', 0.82).split(',')[1] || '';
	}
	async function askAI() {
		const btn = $('iq-ai-btn'), out = $('iq-ai-out');
		if (!window.mjAI || !window.mjAI.guard(btn)) return;
		if (!S.ov) { out.innerHTML = '<p class="iq-sub">먼저 IQ 파일을 열어 주세요.</p>'; return; }
		try {
			const d = await window.mjAI.post(btn.dataset.url, { measure: measure(), image: snapshot(), question: $('iq-ai-q').value }, btn);
			renderAI(d);
		} catch (e) {
			out.innerHTML = `<p class="text-[13px] text-[#c92a2a]">${esc(e.message)}</p>`;
		}
	}
	let lastAI = null;
	function renderAI(d) {
		lastAI = d;
		const list = (arr) => arr.map((s) => `<li>${esc(s)}</li>`).join('');
		const st = d.settings || {};
		const hasSet = st.df_khz != null || st.bw_khz != null || st.baud != null || (st.modulation && st.modulation !== 'auto');
		$('iq-ai-out').innerHTML = `
			<div class="ai-panel mt-3 text-[14px] leading-6">
				<p class="font-semibold">${esc(d.signal_type)} <span class="ai-tag" style="background:rgba(110,86,207,.12);color:#6e56cf">확신 ${esc(d.confidence)}</span></p>
				<p class="mt-1">${esc(d.summary)}</p>
				${d.observations.length ? `<p class="iq-h mt-3">🔍 보이는 것</p><ul class="mt-1 list-disc pl-5">${list(d.observations)}</ul>` : ''}
				${d.candidates.length ? `<p class="iq-h mt-3">🤔 후보</p><ul class="mt-1 list-disc pl-5">${d.candidates.map((c) => `<li><b>${esc(c.name)}</b> — ${esc(c.why)}</li>`).join('')}</ul>` : ''}
				${d.bits ? `<p class="iq-h mt-3">🔢 비트 해석</p><p class="mt-1">${esc(d.bits)}</p>` : ''}
				${d.next_steps.length ? `<p class="iq-h mt-3">👉 다음에 해 볼 것</p><ol class="mt-1 list-decimal pl-5">${list(d.next_steps)}</ol>` : ''}
				${hasSet ? `<p class="mt-3"><button type="button" class="iq-btn" id="iq-ai-apply">추천 설정 넣고 복조하기</button> <span class="iq-sub">Δf ${st.df_khz ?? '–'} kHz · 대역폭 ${st.bw_khz ?? '–'} kHz · ${esc(st.modulation)} · ${st.baud ?? '–'} baud</span></p>` : ''}
				${d.caution ? `<p class="iq-sub mt-3">⚠️ ${esc(d.caution)}</p>` : ''}
				<p class="iq-sub mt-2">AI 는 잰 숫자와 스펙트로그램 그림만 봤어요 (IQ 원본은 보내지 않음). 틀릴 수 있으니 근거를 직접 확인해 보세요.</p>
			</div>`;
		const ap = $('iq-ai-apply');
		if (ap) ap.addEventListener('click', () => {
			if (st.df_khz != null) { $('iq-cn-df').value = st.df_khz; $('iq-cn-df').dispatchEvent(new Event('change')); }
			if (st.bw_khz != null) $('iq-dm-bw').value = st.bw_khz;
			if (st.baud != null) $('iq-dm-baud').value = st.baud;
			$('iq-dm-mod').value = st.modulation || 'auto';
			$('iq-dm').scrollIntoView({ behavior: 'smooth', block: 'start' });
			demodulate();
		});
	}

	// ── 연결 ─────────────────────────────────────────────────
	let findTimer = 0;
	document.addEventListener('iq:view', () => { clearTimeout(findTimer); findTimer = setTimeout(renderFind, 50); });
	$('iq-find-bands').addEventListener('click', (e) => { const b = e.target.closest('[data-band]'); if (b) pickBand(lastBands[+b.dataset.band]); });
	$('iq-find-bursts').addEventListener('click', (e) => { const b = e.target.closest('[data-burst]'); if (b) pickBurst(lastBursts[+b.dataset.burst]); });
	$('iq-dm-run').addEventListener('click', () => demodulate().catch((e) => { $('iq-dm-msg').textContent = `복조하지 못했어요: ${e.message}`; }));
	$('iq-dm-code').addEventListener('change', () => { if (lastDemod && lastDemod.mod) renderDemod(lastDemod, null); });
	$('iq-ai-btn').addEventListener('click', askAI);
	// 복조 칸의 Δf 와 성상도의 Δf 는 같은 값
	const dfA = $('iq-dm-df'), dfB = $('iq-cn-df');
	dfA.addEventListener('change', () => { dfB.value = dfA.value; dfB.dispatchEvent(new Event('change')); });
	dfB.addEventListener('change', () => { dfA.value = dfB.value; });
	document.addEventListener('iq:view', () => { if (dfA.value !== dfB.value) dfA.value = dfB.value; });
	new MutationObserver(() => drawDemod(lastDemod)).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
	drawDemod(null);
	window.__iqInsight = { findBands, findBursts, demodulate, measure, lineCode, describeBits, estimateT, runsOf, get last() { return lastDemod; } };
})();
