// IQ 분석기 (/tools/iq/) — GNU Radio File Sink 등으로 저장한 IQ 파일을 브라우저 안에서만 읽어 살펴본다.
// 파일은 서버로 가지 않는다. 큰 파일은 File.slice 로 필요한 부분만 읽고, 처음에 한 번 전체를 훑어 개요(최소·최대 묶음)를 만든다.
(() => {
	'use strict';
	const $ = (id) => document.getElementById(id);
	const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
	const store = {
		get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
		set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 무시 */ } },
	};

	// ── 샘플 형식 ─────────────────────────────────────────────
	const FORMATS = {
		fc32: { bytes: 8, ext: 'cf32', label: 'complex float32' },
		fc64: { bytes: 16, ext: 'cf64', label: 'complex float64' },
		sc16: { bytes: 4, ext: 'cs16', label: 'complex int16' },
		sc8: { bytes: 2, ext: 'cs8', label: 'complex int8' },
		cu8: { bytes: 2, ext: 'cu8', label: 'complex uint8 (RTL-SDR)' },
		f32: { bytes: 4, ext: 'rf32', label: 'real float32' },
	};
	const HOST_LE = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1;
	const RAW_MAX = 1 << 21;   // 이만큼(샘플)까지는 원본을 읽어서 그림, 더 넓으면 개요로
	const OV_BINS = 1 << 18;   // 개요 칸 수 (파일 전체를 이만큼으로 묶음)
	const MIN_VIEW = 16;

	const S = {
		src: null, name: '', fmt: 'fc32', le: true, skip: 0, len: 0, n: 0,
		fs: 1e6, fc: 0, ov: null, stats: null, notes: [], annos: [],
		v0: 0, v1: 0, raw: null, marks: [], mode: 'iq', show: { i: true, q: true, mag: false },
		drag: 'zoom', fz: null, loadGen: 0, viewGen: 0, hoverX: null, spec: null, sg: null,
	};

	function decode(buf, cnt) {
		const f = S.fmt, le = S.le, out = new Float32Array(cnt * 2);
		const fast = le === HOST_LE;
		if (f === 'fc32') {
			if (fast) return new Float32Array(buf, 0, cnt * 2);
			const dv = new DataView(buf);
			for (let k = 0; k < cnt * 2; k++) out[k] = dv.getFloat32(k * 4, le);
		} else if (f === 'fc64') {
			const dv = new DataView(buf);
			for (let k = 0; k < cnt * 2; k++) out[k] = dv.getFloat64(k * 8, le);
		} else if (f === 'sc16') {
			if (fast) { const a = new Int16Array(buf, 0, cnt * 2); for (let k = 0; k < a.length; k++) out[k] = a[k] / 32768; }
			else { const dv = new DataView(buf); for (let k = 0; k < cnt * 2; k++) out[k] = dv.getInt16(k * 2, le) / 32768; }
		} else if (f === 'sc8') {
			const a = new Int8Array(buf, 0, cnt * 2);
			for (let k = 0; k < a.length; k++) out[k] = a[k] / 128;
		} else if (f === 'cu8') {
			const a = new Uint8Array(buf, 0, cnt * 2);
			for (let k = 0; k < a.length; k++) out[k] = (a[k] - 127.5) / 127.5;
		} else if (f === 'f32') {
			const dv = new DataView(buf);
			for (let k = 0; k < cnt; k++) out[2 * k] = dv.getFloat32(k * 4, le);
		}
		return out;
	}

	async function readSamples(s0, cnt) {
		s0 = clamp(Math.floor(s0), 0, S.n);
		cnt = clamp(Math.floor(cnt), 0, S.n - s0);
		const bs = FORMATS[S.fmt].bytes, a = S.skip + s0 * bs;
		const buf = await S.src.slice(a, a + cnt * bs).arrayBuffer();
		return decode(buf, Math.floor(buf.byteLength / bs));
	}

	// ── 숫자·단위 ─────────────────────────────────────────────
	function si(x, unit, digits = 3) {
		if (!Number.isFinite(x)) return '–';
		const a = Math.abs(x);
		const steps = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n']];
		for (const [m, p] of steps) {
			if (a >= m * 0.9995 || m === 1e-9) return `${+(x / m).toPrecision(digits)} ${p}${unit}`;
		}
		return `0 ${unit}`;
	}
	const fmtT = (t) => (t === 0 ? '0 s' : si(t, 's', 4));
	const fmtF = (f) => si(f, 'Hz', 6);
	const fmtDb = (d) => (Number.isFinite(d) ? `${d.toFixed(1)} dB` : '–');
	function niceTicks(lo, hi, want) {
		const span = hi - lo;
		if (!(span > 0)) return [];
		const raw = span / Math.max(1, want), p = Math.pow(10, Math.floor(Math.log10(raw)));
		const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || 10 * p;
		const out = [];
		for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
		return out;
	}
	function tickLabel(v, step, unit, big) {
		// 눈금 간격에 맞춰 단위를 고르고 자릿수를 줄인다 (big: 값이 간격보다 훨씬 크면 값 크기로 단위 — 433.9 MHz·300.05 ms 처럼)
		const a = Math.max(Math.abs(step), 1e-15), ref = Math.abs(big || 0) / a >= 100 ? Math.abs(big) : a;
		const steps = [[1e9, 'G'], [1e6, 'M'], [1e3, 'k'], [1, ''], [1e-3, 'm'], [1e-6, 'µ'], [1e-9, 'n']];
		const [m, p] = steps.find(([mm]) => ref >= mm * 0.999) || steps[steps.length - 1];
		const dec = clamp(Math.ceil(-Math.log10(a / m) + 1e-9), 0, 6);
		return `${(v / m).toFixed(dec)}${p}${unit}`;
	}

	// ── 색 ────────────────────────────────────────────────────
	const isDark = () => document.documentElement.classList.contains('theme-dark');
	function pal() {
		return isDark()
			? { bg: '#111318', grid: 'rgba(255,255,255,0.08)', axis: 'rgba(255,255,255,0.22)', text: '#a1a1a6', i: '#4dabf7', q: '#ffa94d', mag: '#69db7c', mark: '#f783ac', sel: 'rgba(77,171,247,0.18)', win: 'rgba(77,171,247,0.25)', hover: 'rgba(255,255,255,0.45)', anno: 'rgba(255,212,59,0.16)', annoText: '#ffd43b', avg: '#4dabf7', max: 'rgba(255,169,77,0.75)' }
			: { bg: '#ffffff', grid: 'rgba(0,0,0,0.07)', axis: 'rgba(0,0,0,0.2)', text: '#6e6e73', i: '#0066cc', q: '#e8590c', mag: '#2b8a3e', mark: '#d6336c', sel: 'rgba(0,102,204,0.12)', win: 'rgba(0,102,204,0.18)', hover: 'rgba(0,0,0,0.4)', anno: 'rgba(250,176,5,0.16)', annoText: '#b07a00', avg: '#0066cc', max: 'rgba(232,89,12,0.7)' };
	}
	const CMAP = (() => {
		const a = [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]];
		const lut = new Uint8ClampedArray(256 * 3);
		for (let k = 0; k < 256; k++) {
			const x = (k / 255) * (a.length - 1), j = Math.min(a.length - 2, Math.floor(x)), t = x - j;
			for (let c = 0; c < 3; c++) lut[k * 3 + c] = a[j][c] + (a[j + 1][c] - a[j][c]) * t;
		}
		return lut;
	})();

	// ── FFT ──────────────────────────────────────────────────
	const fftCache = new Map();
	function fftPlan(n) {
		let p = fftCache.get(n);
		if (p) return p;
		const bits = Math.round(Math.log2(n)), rev = new Uint32Array(n), cos = new Float64Array(n / 2), sin = new Float64Array(n / 2);
		for (let k = 0; k < n; k++) { let r = 0; for (let b = 0; b < bits; b++) r |= ((k >> b) & 1) << (bits - 1 - b); rev[k] = r; }
		for (let k = 0; k < n / 2; k++) { cos[k] = Math.cos((2 * Math.PI * k) / n); sin[k] = -Math.sin((2 * Math.PI * k) / n); }
		p = { rev, cos, sin };
		fftCache.set(n, p);
		return p;
	}
	function fft(re, im) {
		const n = re.length, { rev, cos, sin } = fftPlan(n);
		for (let k = 0; k < n; k++) { const r = rev[k]; if (r > k) { let t = re[k]; re[k] = re[r]; re[r] = t; t = im[k]; im[k] = im[r]; im[r] = t; } }
		for (let size = 2; size <= n; size <<= 1) {
			const half = size >> 1, step = n / size;
			for (let s = 0; s < n; s += size) {
				for (let j = 0; j < half; j++) {
					const wr = cos[j * step], wi = sin[j * step], a = s + j, b = a + half;
					const tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
					re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
				}
			}
		}
	}
	const winCache = new Map();
	function windowOf(kind, n) {
		const key = `${kind}:${n}`;
		let w = winCache.get(key);
		if (w) return w;
		w = new Float64Array(n);
		for (let k = 0; k < n; k++) {
			const x = (2 * Math.PI * k) / (n - 1);
			w[k] = kind === 'rect' ? 1 : kind === 'blackman' ? 0.35875 - 0.48829 * Math.cos(x) + 0.14128 * Math.cos(2 * x) - 0.01168 * Math.cos(3 * x) : 0.5 - 0.5 * Math.cos(x);
		}
		let sum = 0;
		for (let k = 0; k < n; k++) sum += w[k];
		w.gain = sum;  // 사인파 꼭대기가 진폭 그대로 읽히도록 (dBFS)
		winCache.set(key, w);
		return w;
	}
	// iq[off..] 에서 n 개를 창 씌워 FFT → 전력(선형), 0 Hz 가 가운데 오도록 돌려서 acc 에 더하거나(max) 넣음
	function powerFrame(iq, off, n, w, re, im, acc, mx) {
		for (let k = 0; k < n; k++) { re[k] = iq[2 * (off + k)] * w[k]; im[k] = iq[2 * (off + k) + 1] * w[k]; }
		fft(re, im);
		const g = 1 / (w.gain * w.gain), h = n >> 1;
		for (let k = 0; k < n; k++) {
			const src = (k + h) % n, p = (re[src] * re[src] + im[src] * im[src]) * g;
			acc[k] += p;
			if (mx && p > mx[k]) mx[k] = p;
		}
	}

	// ── 캔버스 ────────────────────────────────────────────────
	const M = { l: 70, r: 12, t: 8, b: 22 };
	function fit(cv) {
		const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
		if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
		const ctx = cv.getContext('2d');
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, w, h);
		return { ctx, w, h, pw: w - M.l - M.r, ph: h - M.t - M.b };
	}
	function frame(g, P) {
		const { ctx, w, h } = g;
		ctx.fillStyle = P.bg;
		ctx.fillRect(0, 0, w, h);
	}
	const tToX = (s, pw) => M.l + ((s - S.v0) / (S.v1 - S.v0)) * pw;
	const xToS = (x, pw) => S.v0 + ((x - M.l) / pw) * (S.v1 - S.v0);
	function timeAxis(g, P, yTop, yBot) {
		const { ctx, pw } = g, t0 = S.v0 / S.fs, t1 = S.v1 / S.fs;
		const ticks = niceTicks(t0, t1, Math.max(2, Math.floor(pw / 90))), step = ticks.length > 1 ? ticks[1] - ticks[0] : t1 - t0;
		ctx.font = '11px system-ui, sans-serif';
		ctx.fillStyle = P.text;
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		for (const t of ticks) {
			const x = M.l + ((t - t0) / (t1 - t0)) * pw;
			ctx.strokeStyle = P.grid;
			ctx.beginPath(); ctx.moveTo(x + 0.5, yTop); ctx.lineTo(x + 0.5, yBot); ctx.stroke();
			ctx.fillText(tickLabel(t, step, 's', Math.max(Math.abs(t0), Math.abs(t1))), x, yBot + 5);
		}
	}
	function yAxis(g, P, lo, hi, unit, y0, h) {
		const { ctx, pw } = g, ticks = niceTicks(lo, hi, Math.max(2, Math.floor(h / 36))), step = ticks.length > 1 ? ticks[1] - ticks[0] : hi - lo;
		ctx.font = '11px system-ui, sans-serif';
		ctx.fillStyle = P.text;
		ctx.textAlign = 'right';
		ctx.textBaseline = 'middle';
		for (const v of ticks) {
			const y = y0 + h - ((v - lo) / (hi - lo)) * h;
			ctx.strokeStyle = P.grid;
			ctx.beginPath(); ctx.moveTo(M.l, y + 0.5); ctx.lineTo(M.l + pw, y + 0.5); ctx.stroke();
			ctx.fillText(tickLabel(v, step, unit, unit === 'Hz' ? Math.max(Math.abs(lo), Math.abs(hi)) : 0), M.l - 6, y);
		}
	}

	// ── 파일 열기 ─────────────────────────────────────────────
	function guessFromName(name) {
		const low = name.toLowerCase(), out = {};
		if (/\.(cs16|sc16|ci16|cshort|s16)$/.test(low) || /_(ci16|cs16|sc16)/.test(low)) out.fmt = 'sc16';
		else if (/\.(cs8|sc8|ci8|s8)$/.test(low) || /_(ci8|cs8|sc8)\b/.test(low)) out.fmt = 'sc8';
		else if (/\.(cu8|u8)$/.test(low) || /_cu8\b/.test(low)) out.fmt = 'cu8';
		else if (/\.(cf64|fc64)$/.test(low)) out.fmt = 'fc64';
		else if (/\.(rf32|f32|float)$/.test(low)) out.fmt = 'f32';
		else if (/\.(cfile|cf32|fc32|complex|iq|bin|dat|raw|fc|c64)$/.test(low)) out.fmt = 'fc32';
		const sps = low.match(/(\d+(?:\.\d+)?)\s*(k|m|g)?\s*(?:sps|s\/s|msps|ksps)/) || low.match(/(?:fs|sr|rate|samp)[=_-]?(\d+(?:\.\d+)?(?:e\d+)?)\s*(k|m|g)?/);
		if (sps) {
			const mul = { k: 1e3, m: 1e6, g: 1e9 }[sps[2]] || (/msps/.test(sps[0]) ? 1e6 : /ksps/.test(sps[0]) ? 1e3 : 1);
			const v = parseFloat(sps[1]) * mul;
			if (v >= 1e3 && v <= 1e10) out.fs = v;
		}
		const fc = low.match(/(\d+(?:\.\d+)?)\s*(k|m|g)hz/);
		if (fc) out.fc = parseFloat(fc[1]) * { k: 1e3, m: 1e6, g: 1e9 }[fc[2]];
		return out;
	}
	async function parseWav(file) {
		const head = new DataView(await file.slice(0, Math.min(file.size, 1 << 16)).arrayBuffer());
		const tag = (o) => String.fromCharCode(head.getUint8(o), head.getUint8(o + 1), head.getUint8(o + 2), head.getUint8(o + 3));
		if (head.byteLength < 12 || tag(0) !== 'RIFF' || tag(8) !== 'WAVE') return null;
		let o = 12, fmt = null;
		while (o + 8 <= head.byteLength) {
			const id = tag(o), size = head.getUint32(o + 4, true);
			if (id === 'fmt ') fmt = { code: head.getUint16(o + 8, true), ch: head.getUint16(o + 10, true), rate: head.getUint32(o + 12, true), bits: head.getUint16(o + 22, true) };
			if (id === 'data') {
				if (!fmt) return null;
				const len = Math.min(size || file.size - o - 8, file.size - o - 8);
				let f = null;
				if (fmt.ch === 2 && fmt.bits === 16) f = 'sc16';
				else if (fmt.ch === 2 && fmt.bits === 32 && fmt.code === 3) f = 'fc32';
				else if (fmt.ch === 2 && fmt.bits === 8) f = 'cu8';
				else if (fmt.ch === 1 && fmt.bits === 32 && fmt.code === 3) f = 'f32';
				if (!f) return { error: `${fmt.ch}채널 ${fmt.bits}비트 WAV 는 아직 못 읽어요 (2채널 16비트·32비트 float 만).` };
				return { fmt: f, fs: fmt.rate, skip: o + 8, len };
			}
			o += 8 + size + (size & 1);
		}
		return null;
	}
	function parseSigmfMeta(text) {
		const meta = JSON.parse(text), g = meta.global || {}, dt = String(g['core:datatype'] || 'cf32_le');
		const m = dt.match(/^([cr])([fiu])(8|16|32|64)(?:_(le|be))?$/);
		const out = { le: !m || m[4] !== 'be', annos: [] };
		if (m) {
			const key = `${m[1]}${m[2]}${m[3]}`;
			out.fmt = { cf32: 'fc32', cf64: 'fc64', ci16: 'sc16', ci8: 'sc8', cu8: 'cu8', rf32: 'f32' }[key];
			if (!out.fmt) out.error = `SigMF 형식 ${dt} 는 아직 못 읽어요.`;
		}
		if (g['core:sample_rate']) out.fs = +g['core:sample_rate'];
		const cap = (meta.captures || [])[0];
		if (cap && cap['core:frequency'] != null) out.fc = +cap['core:frequency'];
		for (const a of meta.annotations || []) {
			out.annos.push({ s: +a['core:sample_start'] || 0, n: +a['core:sample_count'] || 0, label: a['core:label'] || a['core:comment'] || '', fl: a['core:freq_lower_edge'], fh: a['core:freq_upper_edge'] });
		}
		return out;
	}

	async function openFiles(list) {
		const files = Array.from(list || []);
		if (!files.length) return;
		const meta = files.find((f) => /\.sigmf-meta$/i.test(f.name));
		const data = files.find((f) => !/\.sigmf-meta$/i.test(f.name));
		if (!data) { note('SigMF 는 .sigmf-meta 와 .sigmf-data 를 같이 골라 주세요.', 'warn'); return; }
		const opt = { name: data.name, fmt: null, le: true, skip: 0, len: data.size, annos: [], from: '' };
		const guess = guessFromName(data.name);
		Object.assign(opt, guess);
		if (/\.wav$/i.test(data.name)) {
			const w = await parseWav(data);
			if (w && w.error) { note(w.error, 'warn'); return; }
			if (w) { Object.assign(opt, w); opt.from = 'WAV 머리말'; }
		}
		if (meta) {
			try {
				const m = parseSigmfMeta(await meta.text());
				if (m.error) { note(m.error, 'warn'); return; }
				Object.assign(opt, m);
				opt.from = 'SigMF';
			} catch (e) { note('.sigmf-meta 를 읽지 못했어요 (JSON 이 아님).', 'warn'); }
		}
		load(data, opt);
	}

	function load(src, opt) {
		S.src = src;
		S.name = opt.name;
		S.annos = opt.annos || [];
		S.marks = [];
		S.fz = null;
		S.source = opt.from || '';
		const last = store.get('mj:iq:last', {});
		$('iq-fmt').value = opt.fmt || last.fmt || 'fc32';
		$('iq-le').value = opt.le === false ? 'be' : 'le';
		$('iq-fs').value = String(opt.fs || last.fs || 1e6);
		$('iq-fc').value = String(opt.fc != null ? opt.fc / 1e6 : (last.fc != null ? last.fc : 0));
		$('iq-skip').value = String(opt.skip || 0);
		S.len = opt.len != null ? opt.len - (opt.skip || 0) : src.size;
		S.lenFixed = opt.len != null && opt.skip > 0;
		$('iq-name').textContent = `${opt.name} · ${si(src.size, 'B', 3)}${S.source ? ` · ${S.source} 에서 설정 읽음` : ''}`;
		$('iq-empty').classList.add('hidden');
		$('iq-work').classList.remove('hidden');
		applySettings(true);
	}

	function applySettings(fresh) {
		if (!S.src) return;
		S.fmt = $('iq-fmt').value;
		S.le = $('iq-le').value !== 'be';
		S.fs = Math.max(1, parseFloat($('iq-fs').value) || 1);
		S.fc = (parseFloat($('iq-fc').value) || 0) * 1e6;
		const skip = Math.max(0, Math.floor(parseFloat($('iq-skip').value) || 0));
		if (!S.lenFixed || skip !== S.skip) S.len = S.src.size - skip;
		S.skip = skip;
		store.set('mj:iq:last', { fmt: S.fmt, fs: S.fs, fc: S.fc / 1e6 });
		const bs = FORMATS[S.fmt].bytes;
		S.n = Math.floor(Math.max(0, S.len) / bs);
		S.notes = [];
		if (S.len % bs) S.notes.push(`파일 크기가 한 샘플(${bs} 바이트)의 배수가 아니에요 — 형식이 맞는지 확인해 보세요.`);
		if (S.n < MIN_VIEW) { note('샘플이 너무 적어요.', 'warn'); return; }
		if (fresh || S.v1 > S.n || S.v1 - S.v0 < MIN_VIEW) { S.v0 = 0; S.v1 = S.n; }
		S.ov = null;
		S.raw = null;
		buildOverview();
	}

	// ── 전체 훑기: 개요 + 파일 통계 ─────────────────────────
	async function buildOverview() {
		const gen = ++S.loadGen, n = S.n, bins = Math.min(n, OV_BINS);
		const ov = { bins, imin: new Float32Array(bins).fill(Infinity), imax: new Float32Array(bins).fill(-Infinity), qmin: new Float32Array(bins).fill(Infinity), qmax: new Float32Array(bins).fill(-Infinity), mmax: new Float32Array(bins), msum: new Float64Array(bins), cnt: new Uint32Array(bins) };
		let si_ = 0, sq = 0, sii = 0, sqq = 0, siq = 0, peak = 0, bad = 0;
		const chunk = 1 << 22, t0 = performance.now();
		const bar = $('iq-progress');
		bar.classList.remove('hidden');
		for (let s0 = 0; s0 < n; s0 += chunk) {
			const iq = await readSamples(s0, Math.min(chunk, n - s0));
			if (gen !== S.loadGen) return;
			const cnt = iq.length / 2;
			let b = Math.floor((s0 * bins) / n), next = Math.ceil(((b + 1) * n) / bins);
			for (let k = 0; k < cnt; k++) {
				const idx = s0 + k;
				while (idx >= next) { b++; next = Math.ceil(((b + 1) * n) / bins); }
				const I = iq[2 * k], Q = iq[2 * k + 1], p = I * I + Q * Q;
				if (!Number.isFinite(p)) { bad++; continue; }
				if (I < ov.imin[b]) ov.imin[b] = I;
				if (I > ov.imax[b]) ov.imax[b] = I;
				if (Q < ov.qmin[b]) ov.qmin[b] = Q;
				if (Q > ov.qmax[b]) ov.qmax[b] = Q;
				if (p > ov.mmax[b]) ov.mmax[b] = p;
				ov.msum[b] += p;
				ov.cnt[b]++;
				si_ += I; sq += Q; sii += I * I; sqq += Q * Q; siq += I * Q;
				if (p > peak) peak = p;
			}
			const done = Math.min(n, s0 + chunk) / n;
			bar.style.setProperty('--p', `${(done * 100).toFixed(1)}%`);
			$('iq-progress-text').textContent = `전체 훑는 중 ${(done * 100).toFixed(0)}%`;
			if (s0 === 0) { S.ov = ov; scheduleView(0); }  // 첫 조각만 읽어도 바로 그리기 시작
		}
		bar.classList.add('hidden');
		$('iq-progress-text').textContent = '';
		const good = n - bad, mi = si_ / good, mq = sq / good;
		const vi = sii / good - mi * mi, vq = sqq / good - mq * mq, cv = siq / good - mi * mq;
		S.stats = { power: (sii + sqq) / good, peak, mi, mq, ampDb: 10 * Math.log10(vi / vq), phaseDeg: (Math.asin(clamp(cv / Math.sqrt(vi * vq), -1, 1)) * 180) / Math.PI, bad, real: S.fmt === 'f32', secs: (performance.now() - t0) / 1000 };
		if (bad) S.notes.push(`숫자가 아닌 값(NaN·∞)이 ${bad.toLocaleString()}개 있어요 — 형식(바이트 순서 포함)이 맞는지 확인해 보세요.`);
		if (S.fmt === 'fc32' && peak > 1e8) S.notes.push('값이 너무 커요 — complex float32 가 아니라 int16(short) 으로 저장된 파일일 수 있어요.');
		if ((S.fmt === 'sc16' || S.fmt === 'sc8' || S.fmt === 'cu8') && Math.sqrt(peak) > 0.99) S.notes.push('최대값이 정수 범위 끝까지 닿아요 — 입력이 잘렸을(클리핑) 수 있어요.');
		S.ov = ov;
		renderFileInfo();
		scheduleView(0);
	}

	function note(text, kind) {
		const el = $('iq-msg');
		el.textContent = text;
		el.className = `mt-3 text-[13px] ${kind === 'warn' ? 'text-[#c92a2a]' : 'text-[#6e6e73]'}`;
	}

	function renderFileInfo() {
		const st = S.stats, rows = [
			['샘플 수', S.n.toLocaleString()],
			['길이', fmtT(S.n / S.fs)],
			['평균 전력', st ? `${(10 * Math.log10(st.power)).toFixed(1)} dBFS` : '…'],
			['최대 크기', st ? `${(10 * Math.log10(st.peak)).toFixed(1)} dBFS` : '…'],
		];
		if (st && !st.real) {
			rows.push(['DC 치우침', `I ${st.mi.toExponential(2)} · Q ${st.mq.toExponential(2)} (${(10 * Math.log10((st.mi * st.mi + st.mq * st.mq) / st.power)).toFixed(1)} dBc)`]);
			rows.push(['IQ 불균형', `진폭 ${st.ampDb.toFixed(2)} dB · 위상 ${st.phaseDeg.toFixed(2)}°`]);
		}
		$('iq-info').innerHTML = rows.map(([k, v]) => `<div class="iq-stat"><p>${k}</p><p>${v}</p></div>`).join('');
		$('iq-notes').innerHTML = S.notes.map((t) => `<li>⚠️ ${t}</li>`).join('');
		$('iq-msg').textContent = '';
	}

	// ── 보기 갱신 ─────────────────────────────────────────────
	let viewTimer = 0;
	function scheduleView(delay = 70) {
		drawOverview();
		drawTime();
		drawOverlay();
		clearTimeout(viewTimer);
		viewTimer = setTimeout(refreshView, delay);
	}
	function setView(a, b) {
		let w = clamp(Math.round(b - a), MIN_VIEW, S.n);
		a = clamp(Math.round(a), 0, S.n - w);
		S.v0 = a;
		S.v1 = a + w;
		scheduleView();
	}
	function zoomAt(s, factor) {
		const w = (S.v1 - S.v0) * factor;
		const t = (s - S.v0) / (S.v1 - S.v0);
		setView(s - t * w, s - t * w + w);
	}

	async function refreshView() {
		if (!S.ov) return;
		const gen = ++S.viewGen, v0 = S.v0, cnt = S.v1 - S.v0;
		if (cnt <= RAW_MAX) {
			if (!S.raw || S.raw.v0 !== v0 || S.raw.cnt !== cnt || S.raw.key !== cfgKey()) {
				const data = await readSamples(v0, cnt);
				if (gen !== S.viewGen) return;
				S.raw = { v0, cnt, data, key: cfgKey() };
			}
		} else S.raw = null;
		drawTime();
		await computeSpectrogram(gen);
		if (gen !== S.viewGen) return;
		drawSpectrogram();
		await computeSpectrum(gen);
		if (gen !== S.viewGen) return;
		drawSpectrum();
		await computeConstellation(gen);
		if (gen !== S.viewGen) return;
		drawConstellation();
		renderViewInfo();
		drawOverlay();
	}
	const cfgKey = () => `${S.fmt}|${S.le}|${S.skip}|${S.n}`;
	const rawFor = (v0, cnt) => (S.raw && S.raw.v0 === v0 && S.raw.cnt === cnt ? S.raw.data : null);

	// ── 개요 띠 ───────────────────────────────────────────────
	function drawOverview() {
		const cv = $('iq-ov'), g = fit(cv), P = pal(), { ctx, w, h } = g;
		frame(g, P);
		if (!S.ov) return;
		const ov = S.ov, pw = w - M.l - M.r, top = 4, ph = h - 8;
		let lo = Infinity, hi = -Infinity;
		const col = new Float32Array(Math.max(1, Math.floor(pw)));
		for (let x = 0; x < col.length; x++) {
			const b0 = Math.floor((x / col.length) * ov.bins), b1 = Math.max(b0 + 1, Math.floor(((x + 1) / col.length) * ov.bins));
			let m = 0;
			for (let b = b0; b < b1; b++) if (ov.mmax[b] > m) m = ov.mmax[b];
			const d = m > 0 ? 10 * Math.log10(m) : -200;
			col[x] = d;
			if (m > 0) { lo = Math.min(lo, d); hi = Math.max(hi, d); }
		}
		lo = Math.max(lo, hi - 80);
		drawAnnos(ctx, P, top, ph, (s) => M.l + (s / S.n) * pw, true);
		ctx.fillStyle = P.i;
		for (let x = 0; x < col.length; x++) {
			const v = clamp((col[x] - lo) / Math.max(1e-9, hi - lo), 0, 1);
			ctx.globalAlpha = 0.85;
			ctx.fillRect(M.l + x, top + ph - v * ph, 1, Math.max(1, v * ph));
		}
		ctx.globalAlpha = 1;
		const x0 = M.l + (S.v0 / S.n) * pw, x1 = M.l + (S.v1 / S.n) * pw;
		ctx.fillStyle = P.win;
		ctx.fillRect(x0, 0, Math.max(2, x1 - x0), h);
		ctx.strokeStyle = P.i;
		ctx.lineWidth = 1.5;
		ctx.strokeRect(x0 + 0.5, 0.5, Math.max(2, x1 - x0) - 1, h - 1);
		ctx.lineWidth = 1;
		ctx.font = '10px system-ui, sans-serif';
		ctx.fillStyle = P.text;
		ctx.textAlign = 'right';
		ctx.textBaseline = 'middle';
		ctx.fillText('전체', M.l - 6, h / 2);
	}
	function drawAnnos(ctx, P, y, hgt, xOf, compact) {
		if (!S.annos.length) return;
		ctx.font = '10px system-ui, sans-serif';
		ctx.textAlign = 'left';
		ctx.textBaseline = 'top';
		for (const a of S.annos) {
			const x0 = xOf(a.s), x1 = xOf(a.s + a.n);
			if (x1 < M.l || x0 > M.l + 4000) continue;
			ctx.fillStyle = P.anno;
			ctx.fillRect(x0, y, Math.max(1, x1 - x0), hgt);
			if (!compact && a.label && x1 - x0 > 24) { ctx.fillStyle = P.annoText; ctx.fillText(a.label, Math.max(M.l, x0) + 3, y + 2); }
		}
	}

	// ── 시간 그래프 ───────────────────────────────────────────
	function drawTime() {
		const cv = $('iq-time'), g = fit(cv), P = pal(), { ctx, pw, ph } = g;
		frame(g, P);
		if (!S.ov || S.v1 <= S.v0) return;
		const cnt = S.v1 - S.v0, raw = rawFor(S.v0, cnt), cols = Math.max(1, Math.floor(pw));
		const mode = S.mode;
		$('iq-time-note').textContent = '';
		// 트레이스: [{color, lo:Float32Array, hi:Float32Array}] 또는 점·선
		let traces = [], ylo = Infinity, yhi = -Infinity, unit = '';
		const wantI = mode === 'iq' && S.show.i, wantQ = mode === 'iq' && S.show.q && !S.stats?.real, wantM = mode === 'iq' && S.show.mag;
		if (raw) {
			const N = raw.length / 2, vals = [];
			const pick = (fn, color) => {
				const arr = new Float32Array(N);
				for (let k = 0; k < N; k++) arr[k] = fn(k);
				vals.push({ arr, color });
			};
			if (wantI) pick((k) => raw[2 * k], P.i);
			if (wantQ) pick((k) => raw[2 * k + 1], P.q);
			if (wantM) pick((k) => Math.hypot(raw[2 * k], raw[2 * k + 1]), P.mag);
			if (mode === 'db') { pick((k) => 10 * Math.log10(raw[2 * k] ** 2 + raw[2 * k + 1] ** 2 + 1e-20), P.mag); unit = ''; }
			if (mode === 'phase') pick((k) => Math.atan2(raw[2 * k + 1], raw[2 * k]) * 180 / Math.PI, P.i);
			if (mode === 'freq') {
				pick((k) => {
					if (k === 0 && S.v0 === 0) return NaN;
					const a = k ? 2 * (k - 1) : -2;
					const pi = k ? raw[a] : raw[0], pq = k ? raw[a + 1] : raw[1];
					const I = raw[2 * k], Q = raw[2 * k + 1];
					return (Math.atan2(Q * pi - I * pq, I * pi + Q * pq) * S.fs) / (2 * Math.PI);
				}, P.i);
			}
			for (const v of vals) {
				const lo = new Float32Array(cols).fill(Infinity), hi = new Float32Array(cols).fill(-Infinity);
				for (let k = 0; k < N; k++) {
					const x = v.arr[k];
					if (!Number.isFinite(x)) continue;
					const c = Math.min(cols - 1, Math.floor((k / N) * cols));
					if (x < lo[c]) lo[c] = x;
					if (x > hi[c]) hi[c] = x;
					if (x < ylo) ylo = x;
					if (x > yhi) yhi = x;
				}
				traces.push({ ...v, lo, hi, N });
			}
		} else {
			if (mode === 'phase' || mode === 'freq') { $('iq-time-note').textContent = `위상·순간 주파수는 ${si(RAW_MAX, '', 3).trim()} 샘플 이하로 확대하면 보여요.`; }
			const ov = S.ov, b0 = (S.v0 * ov.bins) / S.n, b1 = (S.v1 * ov.bins) / S.n;
			const make = (lof, hif, color) => {
				const lo = new Float32Array(cols).fill(Infinity), hi = new Float32Array(cols).fill(-Infinity);
				for (let c = 0; c < cols; c++) {
					const a = Math.floor(b0 + ((b1 - b0) * c) / cols), b = Math.max(a + 1, Math.floor(b0 + ((b1 - b0) * (c + 1)) / cols));
					for (let j = a; j < Math.min(b, ov.bins); j++) {
						if (!ov.cnt[j]) continue;
						const l = lof(j), u = hif(j);
						if (l < lo[c]) lo[c] = l;
						if (u > hi[c]) hi[c] = u;
					}
					if (lo[c] < ylo) ylo = lo[c];
					if (hi[c] > yhi && Number.isFinite(hi[c])) yhi = hi[c];
				}
				traces.push({ color, lo, hi, N: 0 });
			};
			if (wantI) make((j) => ov.imin[j], (j) => ov.imax[j], P.i);
			if (wantQ) make((j) => ov.qmin[j], (j) => ov.qmax[j], P.q);
			if (wantM) make(() => 0, (j) => Math.sqrt(ov.mmax[j]), P.mag);
			if (mode === 'db') make((j) => 10 * Math.log10(ov.msum[j] / ov.cnt[j] + 1e-20), (j) => 10 * Math.log10(ov.mmax[j] + 1e-20), P.mag);
		}
		if (!Number.isFinite(ylo) || !Number.isFinite(yhi)) { ylo = -1; yhi = 1; }
		if (mode === 'iq') { const a = Math.max(Math.abs(ylo), Math.abs(yhi)) || 1; ylo = wantM && !wantI && !wantQ ? 0 : -a * 1.05; yhi = a * 1.05; }
		else if (mode === 'phase') { ylo = -190; yhi = 190; unit = '°'; }
		else if (mode === 'freq') { ylo = -S.fs / 2; yhi = S.fs / 2; unit = 'Hz'; }
		else { ylo = Math.max(ylo, yhi - 100) - 3; yhi += 3; }
		if (yhi - ylo < 1e-12) { yhi += 1; ylo -= 1; }
		const yOf = (v) => M.t + ph - ((v - ylo) / (yhi - ylo)) * ph;
		yAxis(g, P, ylo, yhi, mode === 'db' ? '' : unit, M.t, ph);
		timeAxis(g, P, M.t, M.t + ph);
		drawAnnos(ctx, P, M.t, ph, (s) => tToX(s, pw), false);
		ctx.save();
		ctx.beginPath();
		ctx.rect(M.l, M.t, pw, ph);
		ctx.clip();
		const pxPer = traces[0]?.N ? pw / traces[0].N : 0;
		for (const t of traces) {
			ctx.strokeStyle = t.color;
			ctx.fillStyle = t.color;
			if (t.N && pxPer >= 1.5) {
				// 샘플이 성길 때는 선으로 잇고 점을 찍는다
				ctx.lineWidth = 1.3;
				ctx.beginPath();
				let pen = false;
				for (let k = 0; k < t.N; k++) {
					const v = t.arr[k];
					if (!Number.isFinite(v)) { pen = false; continue; }
					const x = M.l + (k + 0.5) * pxPer, y = yOf(v);
					if (pen && !(mode === 'phase' && Math.abs(v - t.arr[k - 1]) > 180)) ctx.lineTo(x, y);
					else ctx.moveTo(x, y);
					pen = true;
				}
				ctx.stroke();
				if (pxPer >= 5) for (let k = 0; k < t.N; k++) { const v = t.arr[k]; if (Number.isFinite(v)) ctx.fillRect(M.l + (k + 0.5) * pxPer - 1.5, yOf(v) - 1.5, 3, 3); }
			} else {
				ctx.globalAlpha = traces.length > 1 ? 0.75 : 0.9;
				ctx.lineWidth = 1;
				for (let c = 0; c < t.lo.length; c++) {
					if (!Number.isFinite(t.lo[c])) continue;
					const y0 = yOf(t.hi[c]), y1 = yOf(t.lo[c]);
					ctx.fillRect(M.l + c, y0, 1, Math.max(1, y1 - y0));
				}
				ctx.globalAlpha = 1;
			}
		}
		ctx.restore();
		$('iq-view-label').textContent = `${fmtT(S.v0 / S.fs)} ~ ${fmtT(S.v1 / S.fs)} · ${cnt.toLocaleString()} 샘플${raw ? '' : ' (개요로 그림 — 더 확대하면 원본)'}`;
	}

	// ── 스펙트로그램 ─────────────────────────────────────────
	async function computeSpectrogram(gen) {
		const cv = $('iq-sg'), cols = Math.max(16, Math.min(1400, Math.floor(cv.clientWidth - M.l - M.r)));
		const cnt = S.v1 - S.v0, raw = rawFor(S.v0, cnt);
		let N = +$('iq-sg-n').value;
		if (!N) N = clamp(2 ** Math.round(Math.log2(Math.sqrt(cnt / 2))), 64, 1024);  // 자동: 시간·주파수 칸이 고르게
		N = Math.min(N, 1 << Math.floor(Math.log2(Math.max(64, S.n))));
		const w = windowOf('hann', N), re = new Float64Array(N), im = new Float64Array(N), out = new Float32Array(cols * N);
		const span = cnt / cols;
		const acc = new Float64Array(N);
		const doCol = (c, iq, base) => {
			acc.fill(0);
			const start = S.v0 + c * span, end = start + span;
			let frames = Math.max(1, Math.min(16, Math.floor(span / N)));
			let used = 0;
			for (let f = 0; f < frames; f++) {
				let s = frames === 1 ? Math.round((start + end) / 2 - N / 2) : Math.round(start + (f * (span - N)) / Math.max(1, frames - 1));
				s = clamp(s, base, base + iq.length / 2 - N);
				if (s < base) continue;
				powerFrame(iq, s - base, N, w, re, im, acc, null);
				used++;
			}
			for (let k = 0; k < N; k++) out[c * N + k] = 10 * Math.log10(acc[k] / Math.max(1, used) + 1e-20);
		};
		if (raw || cnt + N <= RAW_MAX) {
			const a = clamp(S.v0 - N, 0, S.n), b = clamp(S.v1 + N, 0, S.n);
			const iq = raw && N > 0 && a === S.v0 && b === S.v1 ? raw : await readSamples(a, b - a);
			if (gen !== S.viewGen) return;
			if (iq.length / 2 < N) { S.sg = null; return; }
			for (let c = 0; c < cols; c++) doCol(c, iq, a);
		} else {
			// 넓은 구간: 칸마다 앞부분만 조금씩 읽음 (최대 프레임 8개)
			const per = Math.min(Math.floor(span), N * 8);
			for (let c0 = 0; c0 < cols; c0 += 64) {
				const jobs = [];
				for (let c = c0; c < Math.min(cols, c0 + 64); c++) {
					const s = clamp(Math.round(S.v0 + c * span + span / 2 - per / 2), 0, S.n - per);
					jobs.push(readSamples(s, per).then((iq) => ({ c, s, iq })));
				}
				const got = await Promise.all(jobs);
				if (gen !== S.viewGen) return;
				for (const { c, s, iq } of got) {
					acc.fill(0);
					const frames = Math.max(1, Math.floor(iq.length / 2 / N));
					for (let f = 0; f < frames; f++) powerFrame(iq, f * N, N, w, re, im, acc, null);
					for (let k = 0; k < N; k++) out[c * N + k] = 10 * Math.log10(acc[k] / frames + 1e-20);
				}
			}
		}
		S.sg = { cols, N, out };
		$('iq-sg-info').textContent = `FFT ${N} · 칸당 ${fmtT(span / S.fs)} · 주파수 칸 ${fmtF(S.fs / N)}`;
	}
	function sgRange() {
		const out = S.sg.out, tmp = [];
		const step = Math.max(1, Math.floor(out.length / 20000));
		for (let k = 0; k < out.length; k += step) tmp.push(out[k]);
		tmp.sort((a, b) => a - b);
		const auto = [tmp[Math.floor(tmp.length * 0.05)], tmp[tmp.length - 1]];
		const lo = parseFloat($('iq-sg-lo').value), hi = parseFloat($('iq-sg-hi').value);
		return [Number.isFinite(lo) ? lo : auto[0], Number.isFinite(hi) ? hi : auto[1]];
	}
	const fzRange = () => S.fz || [-S.fs / 2, S.fs / 2];
	function drawSpectrogram() {
		const cv = $('iq-sg'), g = fit(cv), P = pal(), { ctx, pw, ph } = g;
		frame(g, P);
		if (!S.sg) return;
		const { cols, N, out } = S.sg, [lo, hi] = sgRange(), [f0, f1] = fzRange();
		const k0 = clamp(Math.floor(((f0 + S.fs / 2) / S.fs) * N), 0, N - 1), k1 = clamp(Math.ceil(((f1 + S.fs / 2) / S.fs) * N), k0 + 1, N);
		const rows = k1 - k0, img = new ImageData(cols, rows), d = img.data, sc = 255 / Math.max(1e-9, hi - lo);
		for (let c = 0; c < cols; c++) {
			for (let r = 0; r < rows; r++) {
				const k = k1 - 1 - r, v = clamp(Math.round((out[c * N + k] - lo) * sc), 0, 255), o = (r * cols + c) * 4;
				d[o] = CMAP[v * 3]; d[o + 1] = CMAP[v * 3 + 1]; d[o + 2] = CMAP[v * 3 + 2]; d[o + 3] = 255;
			}
		}
		const tmp = document.createElement('canvas');
		tmp.width = cols;
		tmp.height = rows;
		tmp.getContext('2d').putImageData(img, 0, 0);
		ctx.imageSmoothingEnabled = cols < pw * 0.75 || rows < ph * 0.5;
		const fa = -S.fs / 2 + (k0 / N) * S.fs, fb = -S.fs / 2 + (k1 / N) * S.fs;
		ctx.drawImage(tmp, M.l, M.t, pw, ph);
		yAxis(g, P, fa + S.fc, fb + S.fc, 'Hz', M.t, ph);
		ctx.drawImage(tmp, M.l, M.t, pw, ph);  // 눈금선이 그림을 가리지 않게 다시
		timeAxis(g, P, M.t + ph, M.t + ph);
		$('iq-sg-scale').textContent = `색: ${lo.toFixed(0)} ~ ${hi.toFixed(0)} dBFS`;
	}

	// ── 스펙트럼 ─────────────────────────────────────────────
	async function computeSpectrum(gen) {
		const cnt = S.v1 - S.v0, raw = rawFor(S.v0, cnt);
		let N = +$('iq-sp-n').value;
		N = Math.min(N, 1 << Math.floor(Math.log2(cnt)));
		const w = windowOf($('iq-sp-win').value, N), re = new Float64Array(N), im = new Float64Array(N);
		const acc = new Float64Array(N), mx = new Float64Array(N);
		let frames = 0;
		if (raw) {
			const total = Math.max(1, Math.floor((cnt - N) / (N / 2)) + 1), use = Math.min(total, 1024);
			for (let f = 0; f < use; f++) {
				const off = use === 1 ? 0 : Math.round((f * (cnt - N)) / (use - 1));
				powerFrame(raw, off, N, w, re, im, acc, mx);
				frames++;
			}
		} else {
			const use = 256;
			for (let f0 = 0; f0 < use; f0 += 32) {
				const jobs = [];
				for (let f = f0; f < f0 + 32; f++) jobs.push(readSamples(S.v0 + Math.round((f * (cnt - N)) / (use - 1)), N));
				const got = await Promise.all(jobs);
				if (gen !== S.viewGen) return;
				for (const iq of got) { if (iq.length / 2 === N) { powerFrame(iq, 0, N, w, re, im, acc, mx); frames++; } }
			}
		}
		const avg = new Float32Array(N), max = new Float32Array(N);
		let total = 0;
		for (let k = 0; k < N; k++) { avg[k] = 10 * Math.log10(acc[k] / frames + 1e-20); max[k] = 10 * Math.log10(mx[k] + 1e-20); total += acc[k] / frames; }
		// 피크와 99% 점유 대역폭
		let pk = 0;
		for (let k = 1; k < N; k++) if (avg[k] > avg[pk]) pk = k;
		let cum = 0, kl = 0, kh = N - 1;
		const lin = Array.from(acc, (v) => v / frames);
		for (let k = 0; k < N; k++) { cum += lin[k]; if (cum >= total * 0.005) { kl = k; break; } }
		cum = 0;
		for (let k = N - 1; k >= 0; k--) { cum += lin[k]; if (cum >= total * 0.005) { kh = k; break; } }
		const sorted = Array.from(avg).sort((a, b) => a - b);
		S.spec = { N, avg, max, frames, peak: pk, obw: ((kh - kl + 1) * S.fs) / N, floor: sorted[Math.floor(N * 0.2)] };
	}
	const binF = (k, N) => -S.fs / 2 + (k * S.fs) / N;
	function drawSpectrum() {
		const cv = $('iq-sp'), g = fit(cv), P = pal(), { ctx, pw, ph } = g;
		frame(g, P);
		const sp = S.spec;
		if (!sp) return;
		const [f0, f1] = fzRange(), showMax = $('iq-sp-max').checked;
		let lo = Infinity, hi = -Infinity;
		for (let k = 0; k < sp.N; k++) {
			const f = binF(k, sp.N);
			if (f < f0 || f > f1) continue;
			lo = Math.min(lo, sp.avg[k]);
			hi = Math.max(hi, showMax ? sp.max[k] : sp.avg[k]);
		}
		lo = Math.max(lo, hi - 120) - 3;
		hi += 3;
		const xOf = (f) => M.l + ((f - f0) / (f1 - f0)) * pw, yOf = (v) => M.t + ph - ((v - lo) / (hi - lo)) * ph;
		yAxis(g, P, lo, hi, '', M.t, ph);
		const ticks = niceTicks(f0 + S.fc, f1 + S.fc, Math.max(2, Math.floor(pw / 100))), step = ticks.length > 1 ? ticks[1] - ticks[0] : f1 - f0;
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		for (const f of ticks) {
			const x = xOf(f - S.fc);
			ctx.strokeStyle = P.grid;
			ctx.beginPath(); ctx.moveTo(x + 0.5, M.t); ctx.lineTo(x + 0.5, M.t + ph); ctx.stroke();
			ctx.fillStyle = P.text;
			ctx.fillText(tickLabel(f, step, 'Hz', Math.max(Math.abs(f0 + S.fc), Math.abs(f1 + S.fc))), x, M.t + ph + 5);
		}
		ctx.save();
		ctx.beginPath();
		ctx.rect(M.l, M.t, pw, ph);
		ctx.clip();
		const line = (arr, color, width) => {
			ctx.strokeStyle = color;
			ctx.lineWidth = width;
			ctx.beginPath();
			const per = sp.N / ((sp.N * (f1 - f0)) / S.fs) || 1;
			let first = true;
			for (let k = 0; k < sp.N; k++) {
				const x = xOf(binF(k, sp.N) + S.fs / sp.N / 2);
				if (x < M.l - 2 || x > M.l + pw + 2) continue;
				if (first) { ctx.moveTo(x, yOf(arr[k])); first = false; } else ctx.lineTo(x, yOf(arr[k]));
			}
			ctx.stroke();
			return per;
		};
		if (showMax) line(sp.max, P.max, 1);
		line(sp.avg, P.avg, 1.3);
		ctx.restore();
		ctx.lineWidth = 1;
		const pkF = binF(sp.peak, sp.N) + S.fs / sp.N / 2;
		$('iq-sp-info').textContent = `평균 ${sp.frames}번 · 칸 ${fmtF(S.fs / sp.N)} · 피크 ${fmtF(pkF + S.fc)} (${sp.avg[sp.peak].toFixed(1)} dBFS) · 99% 점유 대역폭 ${fmtF(sp.obw)} · 잡음 바닥 약 ${sp.floor.toFixed(1)} dBFS/칸`;
	}

	// ── 성상도 ───────────────────────────────────────────────
	async function computeConstellation(gen) {
		const cnt = S.v1 - S.v0, LIM = 1 << 20;
		let iq = rawFor(S.v0, cnt), base = S.v0;
		if (!iq) {
			base = Math.round(S.v0 + cnt / 2 - LIM / 2);
			iq = await readSamples(base, LIM);
			if (gen !== S.viewGen) return;
			$('iq-cn-note').textContent = `구간이 넓어서 가운데 ${LIM.toLocaleString()} 샘플만 그렸어요.`;
		} else $('iq-cn-note').textContent = '';
		const df = parseFloat($('iq-cn-df').value) * 1e3 || 0, sps = Math.max(1, parseFloat($('iq-cn-sps').value) || 1), ph0 = parseFloat($('iq-cn-off').value) || 0;
		const N = iq.length / 2, pts = [];
		const w = (-2 * Math.PI * df) / S.fs;
		const at = (t) => {
			// 소수 위치는 앞뒤 샘플을 이어서
			const k = Math.floor(t), a = t - k;
			if (k + 1 >= N) return null;
			let I = iq[2 * k] * (1 - a) + iq[2 * k + 2] * a, Q = iq[2 * k + 1] * (1 - a) + iq[2 * k + 3] * a;
			if (df) { const th = w * (base + t), c = Math.cos(th), s = Math.sin(th); [I, Q] = [I * c - Q * s, I * s + Q * c]; }
			return [I, Q];
		};
		const off = (ph0 / 100) * sps;
		for (let t = off; t < N - 1; t += sps) { const p = at(t); if (p) pts.push(p[0], p[1]); }
		const arr = Float32Array.from(pts);
		const mags = [];
		for (let k = 0; k < arr.length; k += 2 * Math.max(1, Math.floor(arr.length / 40000))) mags.push(Math.hypot(arr[k], arr[k + 1]));
		mags.sort((a, b) => a - b);
		S.cn = { pts: arr, scale: (mags[Math.floor(mags.length * 0.995)] || 1) * 1.15 };
	}
	function drawConstellation() {
		const cv = $('iq-cn'), dpr = window.devicePixelRatio || 1, size = cv.clientWidth;
		cv.width = cv.height = Math.round(size * dpr);
		const ctx = cv.getContext('2d'), P = pal();
		ctx.setTransform(1, 0, 0, 1, 0, 0);
		ctx.fillStyle = P.bg;
		ctx.fillRect(0, 0, cv.width, cv.height);
		if (!S.cn) return;
		const R = cv.width, G = Math.min(R, 400), hist = new Uint32Array(G * G), { pts, scale } = S.cn;
		let max = 0;
		for (let k = 0; k < pts.length; k += 2) {
			const x = Math.floor(((pts[k] / scale + 1) / 2) * G), y = Math.floor(((1 - pts[k + 1] / scale) / 2) * G);
			if (x < 0 || y < 0 || x >= G || y >= G) continue;
			const v = ++hist[y * G + x];
			if (v > max) max = v;
		}
		const img = new ImageData(G, G), d = img.data, lm = Math.log1p(max);
		const dark = isDark();
		for (let k = 0; k < hist.length; k++) {
			const o = k * 4;
			if (!hist[k]) { d[o + 3] = 0; continue; }
			const v = clamp(Math.round(40 + (Math.log1p(hist[k]) / lm) * 215), 0, 255);
			d[o] = CMAP[v * 3]; d[o + 1] = CMAP[v * 3 + 1]; d[o + 2] = CMAP[v * 3 + 2]; d[o + 3] = dark ? 255 : 230;
		}
		const tmp = document.createElement('canvas');
		tmp.width = tmp.height = G;
		tmp.getContext('2d').putImageData(img, 0, 0);
		ctx.strokeStyle = P.axis;
		ctx.beginPath(); ctx.moveTo(R / 2, 0); ctx.lineTo(R / 2, R); ctx.moveTo(0, R / 2); ctx.lineTo(R, R / 2); ctx.stroke();
		ctx.imageSmoothingEnabled = false;
		if (pts.length / 2 < 4000) {
			// 점이 적으면 칸 대신 동그란 점으로 (안 보이지 않게)
			ctx.fillStyle = P.i;
			ctx.globalAlpha = 0.8;
			const r = 2.5 * dpr;
			for (let k = 0; k < pts.length; k += 2) {
				ctx.beginPath();
				ctx.arc(((pts[k] / scale + 1) / 2) * R, ((1 - pts[k + 1] / scale) / 2) * R, r, 0, 2 * Math.PI);
				ctx.fill();
			}
			ctx.globalAlpha = 1;
		} else ctx.drawImage(tmp, 0, 0, R, R);
		ctx.font = `${11 * dpr}px system-ui, sans-serif`;
		ctx.fillStyle = P.text;
		ctx.textAlign = 'left';
		ctx.textBaseline = 'top';
		ctx.fillText(`±${scale.toPrecision(3)} · 점 ${(pts.length / 2).toLocaleString()}개`, 6 * dpr, 6 * dpr);
	}

	// ── 구간 정보 · 마커 ──────────────────────────────────────
	function renderViewInfo() {
		const cnt = S.v1 - S.v0, raw = rawFor(S.v0, cnt);
		let pw = null;
		if (raw) { let s = 0; for (let k = 0; k < raw.length; k++) s += raw[k] * raw[k]; pw = s / cnt; }
		else if (S.ov) {
			const ov = S.ov, b0 = Math.floor((S.v0 * ov.bins) / S.n), b1 = Math.ceil((S.v1 * ov.bins) / S.n);
			let s = 0, c = 0;
			for (let b = b0; b < b1; b++) { s += ov.msum[b]; c += ov.cnt[b]; }
			pw = c ? s / c : null;
		}
		$('iq-view-power').textContent = pw ? `구간 평균 전력 ${(10 * Math.log10(pw)).toFixed(1)} dBFS` : '';
		renderMarks();
	}
	function renderMarks() {
		const el = $('iq-marks');
		if (!S.marks.length) { el.textContent = '그래프를 누르면 마커 A·B 가 찍혀요 (두 점 사이 시간·주기).'; return; }
		const [a, b] = S.marks;
		let t = `A ${fmtT(a / S.fs)} (#${a.toLocaleString()})`;
		if (b != null) {
			const d = Math.abs(b - a) / S.fs;
			t += ` · B ${fmtT(b / S.fs)} (#${b.toLocaleString()}) · Δt ${fmtT(d)} · ${Math.abs(b - a).toLocaleString()} 샘플 · 1/Δt ${fmtF(1 / d)}`;
		}
		el.textContent = t;
	}

	// 마우스 십자선·마커·끌기 영역은 위 덧칠 캔버스에만 그린다 (본 그림은 다시 안 그림)
	let selBox = null;
	function drawOverlay() {
		const P = pal();
		for (const id of ['iq-time-ov', 'iq-sg-ov']) {
			const cv = $(id), g = fit(cv), { ctx, h, pw } = g;
			if (!S.ov) continue;
			if (selBox) { ctx.fillStyle = P.sel; ctx.fillRect(Math.min(selBox.a, selBox.b), M.t, Math.abs(selBox.b - selBox.a), h - M.t - M.b); }
			S.marks.forEach((s, j) => {
				const x = tToX(s, pw);
				if (x < M.l || x > M.l + pw) return;
				ctx.strokeStyle = P.mark;
				ctx.setLineDash([4, 3]);
				ctx.beginPath(); ctx.moveTo(x + 0.5, M.t); ctx.lineTo(x + 0.5, h - M.b); ctx.stroke();
				ctx.setLineDash([]);
				ctx.fillStyle = P.mark;
				ctx.font = 'bold 11px system-ui, sans-serif';
				ctx.textAlign = 'left';
				ctx.textBaseline = 'top';
				ctx.fillText('AB'[j], x + 3, M.t + 2);
			});
			if (S.hoverX != null && S.hoverX >= M.l && S.hoverX <= M.l + pw) {
				ctx.strokeStyle = P.hover;
				ctx.beginPath(); ctx.moveTo(S.hoverX + 0.5, M.t); ctx.lineTo(S.hoverX + 0.5, h - M.b); ctx.stroke();
			}
		}
	}
	function hoverText(x, y, which) {
		const cv = $('iq-time'), pw = cv.clientWidth - M.l - M.r, s = Math.floor(xToS(x, pw));
		if (s < 0 || s >= S.n) return '';
		let t = `${fmtT(s / S.fs)} · #${s.toLocaleString()}`;
		const raw = rawFor(S.v0, S.v1 - S.v0);
		if (raw) {
			const k = s - S.v0, I = raw[2 * k], Q = raw[2 * k + 1];
			t += ` · I ${I.toPrecision(4)} · Q ${Q.toPrecision(4)} · |x| ${(10 * Math.log10(I * I + Q * Q + 1e-20)).toFixed(1)} dBFS`;
		}
		if (which === 'sg' && S.sg) {
			const cv2 = $('iq-sg'), ph = cv2.clientHeight - M.t - M.b, [f0, f1] = fzRange();
			const f = f1 - ((y - M.t) / ph) * (f1 - f0);
			const c = clamp(Math.floor(((x - M.l) / pw) * S.sg.cols), 0, S.sg.cols - 1), k = clamp(Math.floor(((f + S.fs / 2) / S.fs) * S.sg.N), 0, S.sg.N - 1);
			t += ` · ${fmtF(f + S.fc)} · ${S.sg.out[c * S.sg.N + k].toFixed(1)} dBFS`;
		}
		return t;
	}

	// 시간 그래프와 스펙트로그램은 같은 x 축 — 같은 조작
	function bindTimeAxis(id, which) {
		const el = $(id);
		let down = null;
		el.addEventListener('pointerdown', (e) => {
			if (!S.ov) return;
			el.setPointerCapture(e.pointerId);
			const r = el.getBoundingClientRect();
			down = { x: e.clientX - r.left, v0: S.v0, v1: S.v1, moved: false, zoom: (S.drag === 'zoom') !== e.shiftKey };
		});
		el.addEventListener('pointermove', (e) => {
			const r = el.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
			S.hoverX = x;
			$('iq-hover').textContent = S.ov ? hoverText(x, y, which) : '';
			if (down) {
				if (Math.abs(x - down.x) > 4) down.moved = true;
				const pw = r.width - M.l - M.r;
				if (down.moved && down.zoom) selBox = { a: clamp(down.x, M.l, M.l + pw), b: clamp(x, M.l, M.l + pw) };
				else if (down.moved) {
					const ds = ((x - down.x) / pw) * (down.v1 - down.v0);
					setView(down.v0 - ds, down.v1 - ds);
				}
			}
			drawOverlay();
		});
		el.addEventListener('pointerup', (e) => {
			if (!down) return;
			const r = el.getBoundingClientRect(), pw = r.width - M.l - M.r, x = e.clientX - r.left;
			if (!down.moved) {
				const s = Math.round(xToS(x, pw));
				if (s >= 0 && s < S.n) { if (S.marks.length >= 2) S.marks = []; S.marks.push(s); renderMarks(); }
			} else if (selBox) {
				const a = xToS(Math.min(selBox.a, selBox.b), pw), b = xToS(Math.max(selBox.a, selBox.b), pw);
				selBox = null;
				if (b - a >= 2) setView(a, b);
			}
			down = null;
			drawOverlay();
		});
		el.addEventListener('pointerleave', () => { S.hoverX = null; $('iq-hover').textContent = ''; drawOverlay(); });
		el.addEventListener('dblclick', () => zoomAt((S.v0 + S.v1) / 2, 4));
		el.addEventListener('wheel', (e) => {
			if (!S.ov) return;
			e.preventDefault();
			const r = el.getBoundingClientRect(), pw = r.width - M.l - M.r;
			if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || (e.shiftKey && !e.ctrlKey)) {
				const d = (e.deltaX || e.deltaY) / pw;
				setView(S.v0 + d * (S.v1 - S.v0), S.v1 + d * (S.v1 - S.v0));
			} else zoomAt(xToS(e.clientX - r.left, pw), Math.pow(1.0015, clamp(e.deltaY, -300, 300) * (e.ctrlKey ? 4 : 1)));
		}, { passive: false });
	}

	function bindOverview() {
		const el = $('iq-ov');
		let down = null;
		const sOf = (e) => { const r = el.getBoundingClientRect(); return ((e.clientX - r.left - M.l) / (r.width - M.l - M.r)) * S.n; };
		el.addEventListener('pointerdown', (e) => {
			if (!S.ov) return;
			el.setPointerCapture(e.pointerId);
			const s = sOf(e), inside = s >= S.v0 && s <= S.v1;
			down = { s, v0: S.v0, v1: S.v1, inside, moved: false };
		});
		el.addEventListener('pointermove', (e) => {
			if (!down) return;
			const s = sOf(e), r = el.getBoundingClientRect();
			if (Math.abs(((s - down.s) / S.n) * (r.width - M.l - M.r)) > 3) down.moved = true;
			if (!down.moved) return;
			if (down.inside) setView(down.v0 + (s - down.s), down.v1 + (s - down.s));
			else setView(Math.min(s, down.s), Math.max(s, down.s));
		});
		el.addEventListener('pointerup', (e) => {
			if (down && !down.moved && !down.inside) { const w = S.v1 - S.v0, s = sOf(e); setView(s - w / 2, s + w / 2); }
			down = null;
		});
	}

	function bindSpectrum() {
		const el = $('iq-sp');
		el.addEventListener('wheel', (e) => {
			if (!S.spec) return;
			e.preventDefault();
			const r = el.getBoundingClientRect(), pw = r.width - M.l - M.r, [f0, f1] = fzRange();
			const f = f0 + ((e.clientX - r.left - M.l) / pw) * (f1 - f0), k = Math.pow(1.0015, clamp(e.deltaY, -300, 300));
			let a = f - (f - f0) * k, b = f + (f1 - f) * k;
			const min = (S.fs / S.spec.N) * 8;
			if (b - a < min) { a = f - min / 2; b = f + min / 2; }
			a = Math.max(-S.fs / 2, a);
			b = Math.min(S.fs / 2, b);
			S.fz = b - a >= S.fs * 0.999 ? null : [a, b];
			drawSpectrum();
			drawSpectrogram();
		}, { passive: false });
		el.addEventListener('pointermove', (e) => {
			if (!S.spec) return;
			const r = el.getBoundingClientRect(), pw = r.width - M.l - M.r, [f0, f1] = fzRange();
			const f = f0 + ((e.clientX - r.left - M.l) / pw) * (f1 - f0), k = clamp(Math.floor(((f + S.fs / 2) / S.fs) * S.spec.N), 0, S.spec.N - 1);
			$('iq-sp-hover').textContent = `${fmtF(f + S.fc)} (기준에서 ${fmtF(f)}) · 평균 ${S.spec.avg[k].toFixed(1)} · 최대 ${S.spec.max[k].toFixed(1)} dBFS`;
		});
		el.addEventListener('pointerleave', () => { $('iq-sp-hover').textContent = ''; });
		el.addEventListener('dblclick', () => { S.fz = null; drawSpectrum(); drawSpectrogram(); });
	}

	// ── 예시 신호 ─────────────────────────────────────────────
	function makeDemo() {
		const fs = 1e6, n = 1 << 20, iq = new Float32Array(n * 2);
		let seed = 7;
		const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
		const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd());
		const sps = 8, sym = [];
		for (let k = 0; k < n / sps + 2; k++) sym.push([rnd() < 0.5 ? -1 : 1, rnd() < 0.5 ? -1 : 1]);
		for (let k = 0; k < n; k++) {
			const t = k / fs;
			let I = 0.02 * gauss(), Q = 0.02 * gauss();
			// 계속 켜진 약한 톤 (−220 kHz)
			const ph = 2 * Math.PI * -220e3 * t;
			I += 0.05 * Math.cos(ph); Q += 0.05 * Math.sin(ph);
			// QPSK 버스트 (+150 kHz, 125 kbaud) 두 번
			if ((t > 0.2 && t < 0.45) || (t > 0.6 && t < 0.9)) {
				const j = Math.floor(k / sps), a = (k % sps) / sps, s0 = sym[j], s1 = sym[j + 1];
				const blend = a < 0.75 ? 0 : (a - 0.75) / 0.25;  // 심볼 끝에서만 부드럽게 넘어감
				const bi = (s0[0] * (1 - blend) + s1[0] * blend) * 0.21, bq = (s0[1] * (1 - blend) + s1[1] * blend) * 0.21;
				const c = 2 * Math.PI * 150e3 * t, cs = Math.cos(c), sn = Math.sin(c);
				I += bi * cs - bq * sn; Q += bi * sn + bq * cs;
			}
			// 처프 (−450 → −300 kHz)
			if (t > 0.05 && t < 0.15) {
				const tt = t - 0.05, p = 2 * Math.PI * (-450e3 * tt + 0.5 * 1.5e6 * tt * tt);
				I += 0.25 * Math.cos(p); Q += 0.25 * Math.sin(p);
			}
			iq[2 * k] = I; iq[2 * k + 1] = Q;
		}
		load(new Blob([iq.buffer]), { name: 'example_433.92MHz_1Msps.cfile', fmt: 'fc32', fs, fc: 433.92e6, annos: [{ s: 0.2 * fs, n: 0.25 * fs, label: 'QPSK 버스트' }, { s: 0.6 * fs, n: 0.3 * fs, label: 'QPSK 버스트' }, { s: 0.05 * fs, n: 0.1 * fs, label: '처프' }], from: '예시' });
		$('iq-cn-df').value = '';
	}

	// ── 연결 ─────────────────────────────────────────────────
	function seg(id, key, cb) {
		const el = $(id);
		el.addEventListener('click', (e) => {
			const b = e.target.closest('button[data-v]');
			if (!b) return;
			el.querySelectorAll('button').forEach((x) => x.classList.toggle('is-on', x === b));
			S[key] = b.dataset.v;
			cb && cb();
		});
	}
	function init() {
		const drop = $('iq-drop'), input = $('iq-file');
		input.addEventListener('change', () => openFiles(input.files));
		drop.addEventListener('click', (e) => { if (!e.target.closest('button')) input.click(); });
		['dragenter', 'dragover'].forEach((t) => document.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('is-over'); }));
		['dragleave', 'drop'].forEach((t) => document.addEventListener(t, (e) => { e.preventDefault(); if (t === 'drop' || e.target === document.documentElement) drop.classList.remove('is-over'); }));
		document.addEventListener('drop', (e) => { if (e.dataTransfer?.files?.length) openFiles(e.dataTransfer.files); });
		$('iq-demo').addEventListener('click', makeDemo);
		for (const id of ['iq-fmt', 'iq-le', 'iq-fs', 'iq-fc', 'iq-skip']) $(id).addEventListener('change', () => applySettings(id === 'iq-fmt' || id === 'iq-skip' || id === 'iq-le'));
		seg('iq-mode', 'mode', () => { $('iq-show').classList.toggle('hidden', S.mode !== 'iq'); drawTime(); });
		seg('iq-drag', 'drag');
		for (const k of ['i', 'q', 'mag']) $(`iq-show-${k}`).addEventListener('change', (e) => { S.show[k] = e.target.checked; drawTime(); });
		$('iq-all').addEventListener('click', () => setView(0, S.n));
		$('iq-zin').addEventListener('click', () => zoomAt((S.v0 + S.v1) / 2, 0.5));
		$('iq-zout').addEventListener('click', () => zoomAt((S.v0 + S.v1) / 2, 2));
		$('iq-left').addEventListener('click', () => { const w = S.v1 - S.v0; setView(S.v0 - w / 2, S.v1 - w / 2); });
		$('iq-right').addEventListener('click', () => { const w = S.v1 - S.v0; setView(S.v0 + w / 2, S.v1 + w / 2); });
		$('iq-marks-zoom').addEventListener('click', () => { if (S.marks.length === 2) setView(Math.min(...S.marks), Math.max(...S.marks) + 1); });
		$('iq-marks-clear').addEventListener('click', () => { S.marks = []; renderMarks(); drawOverlay(); });
		$('iq-save').addEventListener('click', () => {
			const bs = FORMATS[S.fmt].bytes, a = S.skip + S.v0 * bs, b = S.skip + S.v1 * bs;
			const url = URL.createObjectURL(new Blob([S.src.slice(a, b)]));
			const base = S.name.replace(/\.[^.]+$/, '');
			const link = Object.assign(document.createElement('a'), { href: url, download: `${base}_${S.v0}-${S.v1}.${FORMATS[S.fmt].ext}` });
			document.body.appendChild(link);
			link.click();
			link.remove();
			setTimeout(() => URL.revokeObjectURL(url), 5000);
		});
		for (const id of ['iq-sg-n']) $(id).addEventListener('change', () => scheduleView(0));
		for (const id of ['iq-sg-lo', 'iq-sg-hi']) $(id).addEventListener('input', drawSpectrogram);
		for (const id of ['iq-sp-n', 'iq-sp-win']) $(id).addEventListener('change', async () => { const g = ++S.viewGen; await computeSpectrum(g); drawSpectrum(); });
		$('iq-sp-max').addEventListener('change', drawSpectrum);
		$('iq-sp-reset').addEventListener('click', () => { S.fz = null; drawSpectrum(); drawSpectrogram(); });
		$('iq-sp-peak').addEventListener('click', () => {
			if (!S.spec) return;
			$('iq-cn-df').value = ((binF(S.spec.peak, S.spec.N) + S.fs / S.spec.N / 2) / 1e3).toFixed(3);
			reConst();
		});
		const reConst = async () => { const g = ++S.viewGen; await computeConstellation(g); drawConstellation(); };
		for (const id of ['iq-cn-df', 'iq-cn-sps']) $(id).addEventListener('change', reConst);
		$('iq-cn-off').addEventListener('input', reConst);
		bindTimeAxis('iq-time-ov', 'time');
		bindTimeAxis('iq-sg-ov', 'sg');
		bindOverview();
		bindSpectrum();
		document.addEventListener('keydown', (e) => {
			if (!S.ov || e.target.closest('input, select, textarea, [contenteditable]')) return;
			const w = S.v1 - S.v0, c = (S.v0 + S.v1) / 2;
			if (e.key === 'ArrowLeft') setView(S.v0 - w * 0.2, S.v1 - w * 0.2);
			else if (e.key === 'ArrowRight') setView(S.v0 + w * 0.2, S.v1 + w * 0.2);
			else if (e.key === '+' || e.key === '=') zoomAt(c, 0.5);
			else if (e.key === '-') zoomAt(c, 2);
			else if (e.key === 'Home' || e.key === '0') setView(0, S.n);
			else return;
			e.preventDefault();
		});
		let rt = 0;
		new ResizeObserver(() => { clearTimeout(rt); rt = setTimeout(() => { if (S.ov) scheduleView(0); }, 120); }).observe($('iq-work'));
		new MutationObserver(() => { if (S.ov) { drawOverview(); drawTime(); drawSpectrogram(); drawSpectrum(); drawConstellation(); drawOverlay(); } }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
	}
	init();
	window.__iq = { S, guessFromName, parseSigmfMeta, makeDemo };
})();
