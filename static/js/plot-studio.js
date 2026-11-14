/* 그래프 스튜디오 — 데이터를 넣고 GUI 로 모양을 고르면 미리 보여 주고 Python(matplotlib)·MATLAB 코드를 만들어 준다.
 * 파일은 브라우저 안에서만 읽는다 (plot-data.js). 서버로 보내지 않는다.
 */
(function () {
	'use strict';
	const $ = (id) => document.getElementById(id);
	const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
	const LS_KEY = 'mj:plot:last';

	// ───────────────────────── 색 · 글꼴 · 프리셋 ─────────────────────────
	const PALETTES = {
		tab10: { name: 'matplotlib 기본 (tab10)', c: ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'] },
		matlab: { name: 'MATLAB 기본', c: ['#0072bd', '#d95319', '#edb120', '#7e2f8e', '#77ac30', '#4dbeee', '#a2142f'] },
		okabe: { name: '색맹도 구분 (Okabe–Ito)', c: ['#0072b2', '#d55e00', '#009e73', '#cc79a7', '#e69f00', '#56b4e9', '#f0e442', '#000000'] },
		bold: { name: '진한 색', c: ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#a65628', '#f781bf'] },
		gray: { name: '흑백 (선 모양으로 구분)', c: ['#000000', '#555555', '#888888', '#aaaaaa'] },
	};
	const GRAY_LS = ['-', '--', ':', '-.'];
	const CMAPS = {
		viridis: '440154482475414487355f8d2a788e21918c22a88444bf707ad151bddf26fde725',
		parula: '352a87065fdc0f74d90791d70ea6ce06b2b438b9906dbe6ab5b947e7b72efdcf24f9fb0e',
		turbo: '30123b4559cb3e9bfe19d5cd46f884a4fc3ce1dd37fea431f05b12c325037a0403',
		jet: '0000800000f1004cff00b0ff29ffce7dff7aceff29ffc400ff6800f10800800000',
		plasma: '0d088741049d6a00a88f0da4b12a90cc4778e16462f2844bfca636fcce25f0f921',
		inferno: '000004160b39420a686a176e932667bc3754dd513af37819fca50af6d746fcffa4',
		magma: '000004140e363b0f70641a808c2981b73779de4968f7705cfe9f6dfecf92fcfdbf',
		cividis: '00224e08337035456c4f576c6669707d7c78948e77aea371c8b866e5cf52fee838',
		gray: '0000001919193333334c4c4c666666808080999999b3b3b3cccccce6e6e6ffffff',
		hot: '0b00004c0000900000d20000ff1700ff5c00ff9d00ffe100ffff36ffff9dffffff',
		coolwarm: '3b4cc05977e37b9ff99ebeffc0d4f5dddcdcf2cbb7f7ac8eee8468d65244b40426',
		bone: '00000016161e2d2d3e42425d595c79707b90869aa69db9bcb9d2d2dde9e9ffffff',
	};
	const CMAP_PY = { viridis: 1, turbo: 1, jet: 1, plasma: 1, inferno: 1, magma: 1, cividis: 1, gray: 1, hot: 1, coolwarm: 1, bone: 1 };
	const CMAP_M = { parula: 1, turbo: 1, jet: 1, gray: 1, hot: 1, bone: 1 };
	const cmapRGB = {};
	for (const [k, hex] of Object.entries(CMAPS)) cmapRGB[k] = hex.match(/.{6}/g).map((h) => [0, 2, 4].map((i) => parseInt(h.substr(i, 2), 16)));
	function cmapAt(name, t) {
		const a = cmapRGB[name] || cmapRGB.viridis;
		t = Math.min(1, Math.max(0, t)) * (a.length - 1);
		const i = Math.min(a.length - 2, Math.floor(t)), f = t - i;
		return [0, 1, 2].map((k) => a[i][k] + (a[i + 1][k] - a[i][k]) * f);
	}

	const FONTS = {
		cm: { name: 'Computer Modern (LaTeX 기본)', css: "'KaTeX_Main', 'Latin Modern Roman', 'CMU Serif', serif" },
		times: { name: 'Times New Roman (논문)', css: "'Times New Roman', Times, 'STIX Two Text', serif" },
		helvetica: { name: 'Helvetica · Arial', css: 'Helvetica, Arial, sans-serif' },
		dejavu: { name: 'DejaVu Sans (matplotlib 기본)', css: "'DejaVu Sans', Verdana, 'Bitstream Vera Sans', sans-serif" },
	};
	const KO_CSS = ", 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif";

	const PRESETS = {
		mpl: { name: 'matplotlib 기본', fig: { w: 6.4, h: 4.8, font: 'dejavu', fs: 10, fsTitle: 12, fsTick: 10, fsLegend: 10, lw: 1.5, axLw: 0.8, tickDir: 'out', mirror: false, palette: 'tab10', limits: 'pad', titleBold: false, legendFrame: true }, ax: { grid: 'none', box: true } },
		matlab: { name: 'MATLAB 기본', fig: { w: 5.6, h: 4.2, font: 'helvetica', fs: 10, fsTitle: 11, fsTick: 10, fsLegend: 9, lw: 1, axLw: 0.5, tickDir: 'in', mirror: true, palette: 'matlab', limits: 'ticks', titleBold: true, legendFrame: true }, ax: { grid: 'none', box: true } },
		ieee1: { name: '논문 · IEEE 1단 (3.5 in)', fig: { w: 3.5, h: 2.6, font: 'times', fs: 8, fsTitle: 8, fsTick: 8, fsLegend: 7, lw: 1, axLw: 0.5, tickDir: 'in', mirror: true, palette: 'matlab', limits: 'pad', titleBold: false, legendFrame: true }, ax: { grid: 'major', box: true } },
		ieee2: { name: '논문 · IEEE 2단 (7.16 in)', fig: { w: 7.16, h: 2.8, font: 'times', fs: 9, fsTitle: 9, fsTick: 8, fsLegend: 8, lw: 1, axLw: 0.5, tickDir: 'in', mirror: true, palette: 'matlab', limits: 'pad', titleBold: false, legendFrame: true }, ax: { grid: 'major', box: true } },
		thesis: { name: '학위논문 · LaTeX 글꼴', fig: { w: 5.5, h: 3.4, font: 'cm', fs: 11, fsTitle: 11, fsTick: 10, fsLegend: 10, lw: 1.2, axLw: 0.6, tickDir: 'in', mirror: true, palette: 'okabe', limits: 'pad', titleBold: false, legendFrame: false }, ax: { grid: 'major', box: true } },
		slide: { name: '발표 슬라이드 (큰 글씨)', fig: { w: 8, h: 4.5, font: 'helvetica', fs: 16, fsTitle: 18, fsTick: 14, fsLegend: 14, lw: 2.5, axLw: 1.2, tickDir: 'out', mirror: false, palette: 'bold', limits: 'pad', titleBold: true, legendFrame: false }, ax: { grid: 'none', box: false } },
	};

	const SERIES_TYPES = { line: '선', scatter: '점 (산점도)', stem: '줄기 (stem)', step: '계단', bar: '막대', hist: '히스토그램', image: '이미지 (색 지도)' };
	const TF = { none: '그대로', real: '실수부', imag: '허수부', abs: '크기 |x|', db20: '20·log₁₀|x| (dB)', db10: '10·log₁₀(x) (전력 dB)', angle: '위상 (rad)', deg: '위상 (°)', unwrap: '펼친 위상 (rad)' };
	const MARKERS = { '': '없음', o: '● 동그라미', s: '■ 네모', '^': '▲ 세모', v: '▼ 역세모', D: '◆ 마름모', x: '× 엑스', '+': '+ 더하기', '*': '✱ 별', '.': '· 점' };
	const LS = { '-': '── 실선', '--': '- - 점선', ':': '··· 점', '-.': '-·- 일점쇄선', none: '선 없음' };
	const LEGEND_LOC = { best: '자동 (빈 곳)', 'upper right': '오른쪽 위', 'upper left': '왼쪽 위', 'lower right': '오른쪽 아래', 'lower left': '왼쪽 아래', 'center right': '오른쪽 가운데', 'outside right': '그림 밖 오른쪽', 'outside top': '그림 밖 위 (가로)', none: '숨기기' };

	// ───────────────────────── 상태 ─────────────────────────
	const defFig = () => Object.assign({ preset: 'mpl', rows: 1, cols: 1, sharex: false, sharey: false, tex: 'mathtext', gridStyle: ':', minor: false, lang: 'py', out: 'figure', fmtPdf: true, fmtPng: true, fmtSvg: false, dpi: 300, transparent: false }, PRESETS.mpl.fig);
	const defAx = (fig) => ({ title: '', xlabel: '', ylabel: '', xlim: ['', ''], ylim: ['', ''], xscale: 'linear', yscale: 'linear', grid: PRESETS[fig.preset] ? PRESETS[fig.preset].ax.grid : 'none', box: PRESETS[fig.preset] ? PRESETS[fig.preset].ax.box : true, legend: 'best', tightx: false, equal: false });
	let st = { fig: defFig(), axes: [], series: [], nextId: 1 };
	st.axes.push(defAx(st.fig));
	let curAx = 0;
	const files = []; // {name, fmt, vars, meta, notes}
	const varIndex = new Map(); // file::key → Var
	const openSeries = new Set();

	function load() {
		try {
			const s = JSON.parse(localStorage.getItem(LS_KEY) || 'null');
			if (s && s.fig && Array.isArray(s.axes) && Array.isArray(s.series)) {
				st = { fig: Object.assign(defFig(), s.fig), axes: s.axes.map((a) => Object.assign(defAx(s.fig), a)), series: s.series, nextId: s.nextId || 100 };
				if (!st.axes.length) st.axes.push(defAx(st.fig));
			}
		} catch (e) { /* 저장 못 읽으면 처음부터 */ }
	}
	let saveT = 0;
	function save() {
		clearTimeout(saveT);
		saveT = setTimeout(() => { try { localStorage.setItem(LS_KEY, JSON.stringify(st)); } catch (e) { /* 비공개 창 등 */ } }, 300);
	}

	// ───────────────────────── 변수 ─────────────────────────
	const vk = (file, key) => file + '::' + key;
	function indexVars(f) {
		const walk = (vs) => { for (const v of vs) { varIndex.set(vk(f.name, v.key), v); if (v.children) walk(v.children); } };
		walk(f.vars);
	}
	const getVar = (ref) => (ref && ref.v ? varIndex.get(ref.v) : null);
	const fileOf = (v) => files.find((f) => f.name === v.file);
	const nonSingle = (dims) => dims.map((d, i) => [d, i]).filter(([d]) => d > 1).map(([, i]) => i);
	const sizeTxt = (v) => (v.dims && v.dims.length ? v.dims.join('×') : '');
	const vecLen = (v) => (v.kind === 'num' ? Math.max(...v.dims, 0) : 0);
	function isVector(v) { return v.kind === 'num' && nonSingle(v.dims).length === 1; }
	function isMatrix(v) { return v.kind === 'num' && nonSingle(v.dims).length >= 2; }

	// ref = { v: 'file::key', dim: 자유 차원, idx: [차원마다 0-기준 번호], tf, k: 배율 }   (이미지는 rd·cd 두 자유 차원)
	function defaultRef(v, wantImage) {
		const ns = nonSingle(v.dims);
		const idx = v.dims.map(() => 0);
		if (wantImage) return { v: vk(v.file, v.key), rd: ns[0] ?? 0, cd: ns[1] ?? 1, idx, tf: v.im ? 'abs' : 'none', k: 1 };
		let dim = ns[0] ?? 0;
		for (const i of ns) if (v.dims[i] > v.dims[dim]) dim = i;
		return { v: vk(v.file, v.key), dim, idx, tf: v.im ? 'abs' : 'none', k: 1 };
	}

	function applyTf(re, im, tf, k) {
		const n = re.length;
		const out = new Float64Array(n);
		for (let i = 0; i < n; i++) {
			const a = re[i], b = im ? im[i] : 0;
			let y;
			switch (tf) {
				case 'imag': y = b; break;
				case 'abs': y = Math.hypot(a, b); break;
				case 'db20': y = 20 * Math.log10(Math.hypot(a, b)); break;
				case 'db10': y = 10 * Math.log10(a); break;
				case 'angle': case 'unwrap': y = Math.atan2(b, a); break;
				case 'deg': y = Math.atan2(b, a) * 180 / Math.PI; break;
				default: y = a;
			}
			out[i] = y;
		}
		if (tf === 'unwrap') for (let i = 1; i < n; i++) { let d = out[i] - out[i - 1]; const c = Math.round(d / (2 * Math.PI)); if (c) for (let j = i; j < n; j++) out[j] -= c * 2 * Math.PI; }
		if (k != null && +k !== 1 && isFinite(+k)) for (let i = 0; i < n; i++) out[i] *= +k;
		return out;
	}

	const cache = new Map();
	function vecOf(ref) {
		const v = getVar(ref);
		if (!v || v.kind !== 'num') return null;
		const key = JSON.stringify(['v', ref.v, ref.dim, ref.idx, ref.tf, ref.k]);
		if (cache.has(key)) return cache.get(key);
		const dim = ref.dim ?? 0;
		const n = v.dims[dim] || 0;
		let base = 0;
		v.dims.forEach((d, i) => { if (i !== dim) base += Math.min(d - 1, Math.max(0, (ref.idx && ref.idx[i]) || 0)) * v.strides[i]; });
		const s = v.strides[dim];
		const re = new Float64Array(n), im = v.im ? new Float64Array(n) : null;
		for (let i = 0; i < n; i++) { re[i] = v.re[base + i * s]; if (im) im[i] = v.im[base + i * s]; }
		const out = applyTf(re, im, ref.tf, ref.k);
		cache.set(key, out);
		return out;
	}
	function matOf(ref) {
		const v = getVar(ref);
		if (!v || v.kind !== 'num' || v.dims.length < 2) return null;
		const key = JSON.stringify(['m', ref.v, ref.rd, ref.cd, ref.idx, ref.tf, ref.k]);
		if (cache.has(key)) return cache.get(key);
		const rd = ref.rd ?? 0, cd = ref.cd ?? 1;
		const R = v.dims[rd], C = v.dims[cd];
		let base = 0;
		v.dims.forEach((d, i) => { if (i !== rd && i !== cd) base += Math.min(d - 1, Math.max(0, (ref.idx && ref.idx[i]) || 0)) * v.strides[i]; });
		const re = new Float64Array(R * C), im = v.im ? new Float64Array(R * C) : null;
		for (let r = 0; r < R; r++) for (let c = 0; c < C; c++) { const o = base + r * v.strides[rd] + c * v.strides[cd]; re[r * C + c] = v.re[o]; if (im) im[r * C + c] = v.im[o]; }
		const out = { R, C, z: applyTf(re, im, ref.tf, ref.k) };
		cache.set(key, out);
		return out;
	}

	// ───────────────────────── 파일 넣기 ─────────────────────────
	async function addFiles(list) {
		const msg = $('ps-msg');
		for (const file of list) {
			msg.textContent = '읽는 중… ' + file.name;
			try {
				if (/\.(h5|hdf5)$/i.test(file.name) || /\.mat$/i.test(file.name)) msg.textContent = '읽는 중… ' + file.name + ' (v7.3·HDF5 면 읽기 도구를 한 번 내려받아요)';
				const f = await window.PlotData.readFile(file);
				const old = files.findIndex((x) => x.name === f.name);
				if (old >= 0) files.splice(old, 1);
				files.push(f);
				indexVars(f);
				msg.textContent = '';
				if (!st.series.some((s) => getVar(s.y) || getVar(s.x))) autoStart(f);
			} catch (e) {
				msg.textContent = '⚠️ ' + file.name + ': ' + (e && e.message ? e.message : e);
			}
		}
		cache.clear();
		renderVars();
		renderSeries();
		update();
	}

	function removeFile(name) {
		const i = files.findIndex((f) => f.name === name);
		if (i < 0) return;
		files.splice(i, 1);
		for (const k of [...varIndex.keys()]) if (k.startsWith(name + '::')) varIndex.delete(k);
		cache.clear();
		renderVars(); renderSeries(); update();
	}

	// 처음 넣은 파일이면 그럴듯한 그래프 하나 바로 만들어 보여 줌
	function autoStart(f) {
		if (st.series.length) {
			// 저장된 설정의 변수가 이 파일에 있으면 그대로 다시 씀
			if (st.series.some((s) => (s.y && s.y.v || '').startsWith(f.name + '::'))) return;
			st.series = [];
		}
		const nums = flatVars(f).filter((v) => v.kind === 'num');
		const withX = (v) => !!findX(v, isVector(v) ? vecLen(v) : Math.max(...v.dims));
		const cand = nums.filter((v) => isMatrix(v) && v.dims.length === 2 && Math.min(...v.dims) <= 8 && withX(v))[0]
			|| nums.filter((v) => isVector(v) && !xLike(v) && withX(v)).sort((a, b) => vecLen(b) - vecLen(a))[0]
			|| nums.filter((v) => isVector(v) && !xLike(v) && !isMono(v)).sort((a, b) => vecLen(b) - vecLen(a))[0]
			|| nums.filter((v) => isVector(v) && !xLike(v)).sort((a, b) => vecLen(b) - vecLen(a))[0] || nums.filter(isMatrix)[0] || nums.filter(isVector)[0];
		if (!cand) return;
		if (isMatrix(cand) && nonSingle(cand.dims).every((i) => cand.dims[i] > 16)) recipe(cand, 'image');
		else if (isMatrix(cand)) recipe(cand, 'cols');
		else recipe(cand, 'line');
	}

	function flatVars(f) {
		const out = [];
		const walk = (vs) => { for (const v of vs) { out.push(v); if (v.children) walk(v.children); } };
		walk(f.vars);
		return out;
	}
	const X_NAMES = /^(t|time|times|tt|tvec|t_?s|x|xx|xdata|xs|f|freq|freqs|frequency|f_?hz|w|omega|snr|snr_?db|ebn0|ebn0_?db|esn0|n|k|idx|index|lambda|wl|wavelength|theta|angle|az|el|range|r|d|dist|distance|epoch|epochs|iter|step|steps|lag|lags|tau|pos|position)$/i;
	const X_HEAD = /^(t|time|x|f|freq|frequency|snr|ebn0|esn0|sinr|theta|phi|az|el|angle|range|dist|distance|lambda|wl|n|k|idx|index|epoch|iter|step|lag|tau|pos)(?=$|_|\d)/i;
	// 늘 커지는 벡터 (시간·주파수 축일 가능성이 큼)
	function isMono(v) {
		if (!isVector(v) || v.im) return false;
		const n = vecLen(v), s = v.strides[nonSingle(v.dims)[0]];
		if (n < 3) return false;
		const step = Math.max(1, Math.floor(n / 500));
		for (let i = step; i < n; i += step) if (!(v.re[i * s] > v.re[(i - step) * s])) return false;
		return true;
	}
	const xLike = (v) => X_NAMES.test(v.name || '') || X_HEAD.test(v.name || '');
	function findX(v, n) {
		const f = fileOf(v);
		if (!f) return null;
		const cands = flatVars(f).filter((u) => u !== v && isVector(u) && vecLen(u) === n && !u.im);
		return cands.find((u) => /^(t|time|x|f|freq)$/i.test(u.name)) || cands.find((u) => X_NAMES.test(u.name)) || cands.find(xLike) || (isMono(v) ? null : cands.find(isMono)) || null;
	}

	// 변수를 눌렀을 때 고를 수 있는 '바로 그리기'
	function recipesFor(v) {
		const r = [];
		if (v.kind !== 'num') return r;
		if (isVector(v) || nonSingle(v.dims).length === 0) {
			r.push(['line', '📈 선']);
			if (v.im) r.push(['iq', '📈 실수·허수 두 줄'], ['const', '✳️ 성상도 (실수 vs 허수)']);
			r.push(['scatter', '⚬ 점'], ['stem', '⫯ 줄기'], ['bar', '▮ 막대'], ['hist', '▤ 히스토그램']);
		} else {
			r.push(['cols', '📈 열마다 선'], ['rows', '📈 행마다 선'], ['image', '🌈 이미지 (색 지도)']);
		}
		return r;
	}

	function newSeries(type, y, extra) {
		const s = Object.assign({ id: st.nextId++, ax: curAx, type, y, x: null, xv: null, yv: null, label: '', color: '', lw: '', ls: '', marker: type === 'scatter' ? 'o' : type === 'stem' ? 'o' : '', ms: 6, filled: true, alpha: 1, bins: 30, width: 0.8, cmap: 'viridis', clo: '', chi: '', cbar: true, cbarLabel: '' }, extra || {});
		st.series.push(s);
		return s;
	}

	function recipe(v, kind) {
		const ax = st.axes[curAx];
		const base = defaultRef(v);
		const n = v.dims[base.dim] || 0;
		const xv = findX(v, n);
		const xref = xv ? defaultRef(xv) : null;
		const name = v.name || v.key;
		const added = [];
		if (kind === 'line' || kind === 'scatter' || kind === 'stem' || kind === 'bar' || kind === 'step') {
			added.push(newSeries(kind, base, { x: xref, label: texSafe(name) }));
		} else if (kind === 'hist') {
			added.push(newSeries('hist', base, { label: texSafe(name) }));
		} else if (kind === 'iq') {
			added.push(newSeries('line', Object.assign({}, base, { tf: 'real' }), { x: xref, label: 'I (실수)' }));
			added.push(newSeries('line', Object.assign({}, base, { tf: 'imag' }), { x: xref, label: 'Q (허수)' }));
		} else if (kind === 'const') {
			added.push(newSeries('scatter', Object.assign({}, base, { tf: 'imag' }), { x: Object.assign({}, base, { tf: 'real' }), label: '', ms: 3, alpha: 0.6 }));
			ax.equal = true;
			if (!ax.xlabel) ax.xlabel = 'I (실수)';
			if (!ax.ylabel) ax.ylabel = 'Q (허수)';
		} else if (kind === 'cols' || kind === 'rows') {
			const ns = nonSingle(v.dims);
			const free = kind === 'cols' ? ns[0] : ns[1];
			const other = kind === 'cols' ? ns[1] : ns[0];
			if (free == null || other == null) return;
			const m = Math.min(8, v.dims[other]);
			const xv2 = findX(v, v.dims[free]);
			for (let j = 0; j < m; j++) {
				const idx = v.dims.map(() => 0); idx[other] = j;
				const lbl = st.fig.tex === 'none' ? name + ' ' + (j + 1) : '$' + texName(name) + '_{' + (j + 1) + '}$';
				added.push(newSeries('line', { v: vk(v.file, v.key), dim: free, idx, tf: v.im ? 'abs' : 'none', k: 1 }, { x: xv2 ? defaultRef(xv2) : null, label: lbl }));
			}
		} else if (kind === 'image') {
			const ref = defaultRef(v, true);
			const xs = findX(v, v.dims[ref.cd]), ys = findX(v, v.dims[ref.rd]);
			added.push(newSeries('image', ref, { xv: xs ? defaultRef(xs) : null, yv: ys && ys !== xs ? defaultRef(ys) : null, label: '', cbarLabel: texSafe(name) }));
			if (ax.legend === 'best') ax.legend = 'none';
		}
		if (!added.length) return;
		const s0 = added[0];
		if (!ax.ylabel && kind !== 'const' && kind !== 'hist' && kind !== 'image') ax.ylabel = added.length > 1 ? texSafe(name) : (v.im && s0.y.tf === 'db20' ? '크기 [dB]' : texSafe(name));
		if (!ax.xlabel && s0.x && kind !== 'const') ax.xlabel = texSafe(getVar(s0.x).name);
		if (!ax.xlabel && kind === 'hist') ax.xlabel = texSafe(name);
		if (!ax.ylabel && kind === 'hist') ax.ylabel = '개수';
		for (const s of added) openSeries.add(s.id);
		renderSeries(); renderAxes(); update();
	}
	const texName = (n) => n.replace(/_/g, '\\_').replace(/([#%&{}$])/g, '\\$1');
	// 변수 이름을 그대로 글자로 쓸 때 — usetex 면 _ 같은 글자가 오류를 내니 미리 막음
	const texSafe = (n) => (st.fig.tex === 'usetex' ? n.replace(/([_#%&$])/g, '\\$1') : n);

	// ───────────────────────── UI: 데이터 ─────────────────────────
	function renderVars() {
		const box = $('ps-vars');
		if (!files.length) { box.innerHTML = '<p class="ps-sub">아직 파일이 없어요. 위에 끌어 놓거나 예시 데이터를 눌러 보세요.</p>'; return; }
		const row = (v, depth) => {
			const tag = v.kind === 'num' ? `${sizeTxt(v)} ${v.cls}${v.im ? ' <b class="ps-cx">복소수</b>' : ''}` : v.kind === 'char' ? `글자 "${esc((v.text || '').slice(0, 30))}${(v.text || '').length > 30 ? '…' : ''}"` : v.kind === 'struct' ? `구조체 · ${v.children.length}개` : v.kind === 'cell' ? `셀 ${sizeTxt(v)}` : `⚠️ ${esc(v.note || v.cls)}`;
			const rc = recipesFor(v).map(([k, t]) => `<button type="button" class="ps-chip" data-recipe="${esc(k)}" data-v="${esc(vk(v.file, v.key))}">${t}</button>`).join('');
			let html = `<div class="ps-var" style="padding-left:${depth * 14}px"><div class="flex flex-wrap items-baseline gap-x-2"><span class="ps-vname">${esc(v.name || v.key)}</span><span class="ps-sub">${tag}</span></div>${rc ? `<div class="ps-chips">${rc}</div>` : ''}</div>`;
			if (v.children && v.children.length) html += v.children.slice(0, 200).map((c) => row(c, depth + 1)).join('');
			return html;
		};
		const fmtName = { mat: 'MATLAB .mat', mat73: 'MATLAB v7.3 (HDF5)', npy: 'NumPy .npy', npz: 'NumPy .npz', csv: '표 (CSV·TXT)', h5: 'HDF5' };
		box.innerHTML = files.map((f) => `<div class="ps-file"><div class="flex items-center gap-2"><p class="ps-h break-all">📄 ${esc(f.name)}</p><span class="ps-sub">${fmtName[f.fmt] || f.fmt} · 변수 ${f.vars.length}개</span><button type="button" class="ps-x ml-auto" data-rmfile="${esc(f.name)}" title="이 파일 빼기">✕</button></div>${(f.notes || []).map((n) => `<p class="ps-sub">ℹ️ ${esc(n)}</p>`).join('')}${f.vars.map((v) => row(v, 0)).join('')}</div>`).join('');
	}

	// ───────────────────────── UI: 그릴 것 (시리즈) ─────────────────────────
	function varOptions(cur, filter) {
		let html = '';
		for (const f of files) {
			const vs = flatVars(f).filter((v) => v.kind === 'num' && (!filter || filter(v)));
			if (!vs.length) continue;
			html += `<optgroup label="${esc(f.name)}">` + vs.map((v) => `<option value="${esc(vk(v.file, v.key))}"${cur === vk(v.file, v.key) ? ' selected' : ''}>${esc(v.key)}  (${sizeTxt(v)}${v.im ? ' 복소' : ''})</option>`).join('') + '</optgroup>';
		}
		if (cur && !varIndex.has(cur)) html = `<option value="${esc(cur)}" selected>⚠️ ${esc(cur.split('::')[1])} — 파일을 다시 넣어 주세요</option>` + html;
		return html;
	}
	const opts = (o, cur) => Object.entries(o).map(([k, v]) => `<option value="${esc(k)}"${String(cur) === String(k) ? ' selected' : ''}>${esc(v)}</option>`).join('');

	function refEditor(s, which, label, image) {
		const ref = s[which];
		const isX = which !== 'y';
		const v = getVar(ref);
		let html = `<div class="ps-f ps-span2"><label>${label}</label><select class="ps-in w-full" data-ref="${s.id}.${which}" data-rebuild="1">`;
		if (isX) html += `<option value="">${which === 'x' ? '번호 (0,1,2… / MATLAB 은 1,2,3…)' : '번호'}</option>`;
		html += varOptions(ref && ref.v, image ? (u) => u.dims.length >= 2 && nonSingle(u.dims).length >= 2 : null) + '</select></div>';
		if (!v) return html;
		const ns = nonSingle(v.dims);
		const p = `${s.id}.${which}`;
		if (image) {
			if (ns.length > 2 || ns.length === 2 && (ref.rd !== ns[0] || ref.cd !== ns[1])) {
				html += `<div class="ps-f"><label>세로(행) 축</label><select class="ps-in w-full" data-b="se.${p}.rd" data-num="1" data-rebuild="1">${ns.map((i) => `<option value="${i}"${ref.rd === i ? ' selected' : ''}>${i + 1}번째 차원 (${v.dims[i]})</option>`).join('')}</select></div>`;
				html += `<div class="ps-f"><label>가로(열) 축</label><select class="ps-in w-full" data-b="se.${p}.cd" data-num="1" data-rebuild="1">${ns.map((i) => `<option value="${i}"${ref.cd === i ? ' selected' : ''}>${i + 1}번째 차원 (${v.dims[i]})</option>`).join('')}</select></div>`;
			} else {
				html += `<div class="ps-f ps-span2"><button type="button" class="ps-btn" data-swap="${s.id}">↔ 가로·세로 바꾸기 (전치)</button></div>`;
			}
			for (const i of ns) if (i !== ref.rd && i !== ref.cd) html += idxInput(p, i, v, ref);
		} else if (ns.length >= 2) {
			html += `<div class="ps-f"><label>따라 그릴 축</label><select class="ps-in w-full" data-b="se.${p}.dim" data-num="1" data-rebuild="1">${ns.map((i) => `<option value="${i}"${ref.dim === i ? ' selected' : ''}>${dimName(v, i)} 방향 (${v.dims[i]}개)</option>`).join('')}</select></div>`;
			for (const i of ns) if (i !== ref.dim) html += idxInput(p, i, v, ref);
		}
		html += `<div class="ps-f"><label>바꾸기</label><select class="ps-in w-full" data-b="se.${p}.tf">${opts(v.im ? TF : { none: TF.none, abs: TF.abs, db20: TF.db20, db10: TF.db10 }, ref.tf)}</select></div>`;
		html += `<div class="ps-f"><label>곱하기 <span class="ps-tip" title="단위 바꾸기: 초→ms 는 1000, Hz→MHz 는 1e-6">ⓘ</span></label><input class="ps-in w-full" type="number" step="any" data-b="se.${p}.k" data-num="1" value="${esc(ref.k ?? 1)}"></div>`;
		html += `<p class="ps-sub ps-span2">→ <code>${esc(exprPreview(s, which))}</code></p>`;
		return html;
	}
	const dimName = (v, i) => (v.dims.length === 2 ? (i === 0 ? '세로(행)' : '가로(열)') : `${i + 1}번째 차원`);
	function idxInput(p, i, v, ref) {
		const name = v.dims.length === 2 ? (i === 1 ? '몇 번째 열' : '몇 번째 행') : `${i + 1}번째 차원 번호`;
		return `<div class="ps-f"><label>${name} (1~${v.dims[i]})</label><input class="ps-in w-full" type="number" min="1" max="${v.dims[i]}" step="1" data-idx="${p}.${i}" value="${((ref.idx && ref.idx[i]) || 0) + 1}"></div>`;
	}

	function seriesColor(s) {
		if (s.color) return s.color;
		const pal = PALETTES[st.fig.palette] || PALETTES.tab10;
		const sib = st.series.filter((u) => u.ax === s.ax && u.type !== 'image');
		const i = Math.max(0, sib.indexOf(s));
		return pal.c[i % pal.c.length];
	}
	function seriesLs(s) {
		if (s.ls) return s.ls;
		if (s.type === 'scatter') return 'none';
		if (st.fig.palette === 'gray') {
			const sib = st.series.filter((u) => u.ax === s.ax && u.type !== 'image');
			return GRAY_LS[Math.floor(Math.max(0, sib.indexOf(s)) / 1) % GRAY_LS.length];
		}
		return '-';
	}
	const seriesLw = (s) => (s.lw !== '' && s.lw != null && isFinite(+s.lw) ? +s.lw : st.fig.lw);

	function seriesTitle(s) {
		const y = getVar(s.y);
		return `${SERIES_TYPES[s.type] || s.type} · ${y ? esc(y.key) : '⚠️ 변수 없음'}${s.label ? ' · ' + esc(s.label) : ''}`;
	}

	function renderSeries() {
		const box = $('ps-series');
		if (!st.series.length) { box.innerHTML = '<p class="ps-sub">데이터 목록에서 <b>📈 선</b> 같은 버튼을 누르거나 아래 <b>＋ 추가</b> 를 눌러요.</p>'; return; }
		box.innerHTML = st.series.map((s, i) => {
			const open = openSeries.has(s.id);
			const c = s.type === 'image' ? 'linear-gradient(90deg,' + cmapRGB[s.cmap || 'viridis'].map((r) => `rgb(${r})`).join(',') + ')' : seriesColor(s);
			let body = '';
			if (open) {
				const axOpt = st.axes.map((a, k) => `<option value="${k}"${s.ax === k ? ' selected' : ''}>${axName(k)}</option>`).join('');
				body += `<div class="ps-grid mt-2">`;
				body += `<div class="ps-f"><label>종류</label><select class="ps-in w-full" data-b="se.${s.id}.type" data-rebuild="1">${opts(SERIES_TYPES, s.type)}</select></div>`;
				body += `<div class="ps-f"><label>어느 칸</label><select class="ps-in w-full" data-b="se.${s.id}.ax" data-num="1" data-rebuild="1">${axOpt}</select></div>`;
				if (s.type === 'image') {
					body += refEditor(s, 'y', 'Z (색으로 나타낼 행렬)', true);
					body += refEditor(s, 'xv', 'X 눈금 (가로, 선택)');
					body += refEditor(s, 'yv', 'Y 눈금 (세로, 선택)');
					body += `<div class="ps-f"><label>색 지도</label><select class="ps-in w-full" data-b="se.${s.id}.cmap" data-rebuild="1">${opts(Object.fromEntries(Object.keys(CMAPS).map((k) => [k, k])), s.cmap)}</select></div>`;
					body += `<div class="ps-f"><label>색 범위 (비우면 자동)</label><div class="flex gap-1"><input class="ps-in w-full" type="number" step="any" placeholder="최소" data-b="se.${s.id}.clo" value="${esc(s.clo)}"><input class="ps-in w-full" type="number" step="any" placeholder="최대" data-b="se.${s.id}.chi" value="${esc(s.chi)}"></div></div>`;
					body += `<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="se.${s.id}.cbar"${s.cbar ? ' checked' : ''}> 색 막대 보이기</label></div>`;
					body += `<div class="ps-f"><label>색 막대 이름</label><input class="ps-in w-full" data-b="se.${s.id}.cbarLabel" value="${esc(s.cbarLabel)}" placeholder="예: 크기 [dB]"></div>`;
				} else {
					body += refEditor(s, 'y', s.type === 'hist' ? '값 (나눠 셀 데이터)' : 'Y (세로)');
					if (s.type !== 'hist') body += refEditor(s, 'x', 'X (가로)');
					body += `<div class="ps-f ps-span2"><label>범례 이름 <span class="ps-tip" title="$…$ 사이는 LaTeX 수식: $\\sin(2\\pi f t)$, $E_b/N_0$, $\\alpha=0.5$">ⓘ</span></label><input class="ps-in w-full" data-b="se.${s.id}.label" value="${esc(s.label)}" placeholder="비우면 범례에 안 나와요 · 예: $\\sin(\\omega t)$"></div>`;
					body += `<div class="ps-f"><label>색</label><div class="flex items-center gap-1"><input type="color" class="ps-color" data-b="se.${s.id}.color" value="${esc(seriesColor(s))}"><button type="button" class="ps-btn" data-b-clear="se.${s.id}.color" title="팔레트 순서대로">자동</button></div></div>`;
					if (s.type !== 'hist' && s.type !== 'bar') {
						body += `<div class="ps-f"><label>선 굵기 (pt)</label><input class="ps-in w-full" type="number" min="0" step="0.1" data-b="se.${s.id}.lw" value="${esc(s.lw)}" placeholder="${st.fig.lw}"></div>`;
						if (s.type !== 'scatter') body += `<div class="ps-f"><label>선 모양</label><select class="ps-in w-full" data-b="se.${s.id}.ls"><option value="">자동</option>${opts(LS, s.ls)}</select></div>`;
						body += `<div class="ps-f"><label>점 모양</label><select class="ps-in w-full" data-b="se.${s.id}.marker">${opts(MARKERS, s.marker)}</select></div>`;
						body += `<div class="ps-f"><label>점 크기 (pt)</label><input class="ps-in w-full" type="number" min="0" step="0.5" data-b="se.${s.id}.ms" data-num="1" value="${esc(s.ms)}"></div>`;
						body += `<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="se.${s.id}.filled"${s.filled ? ' checked' : ''}> 점 속 채우기</label></div>`;
					}
					if (s.type === 'hist') body += `<div class="ps-f"><label>칸 수 (bins)</label><input class="ps-in w-full" type="number" min="1" max="1000" step="1" data-b="se.${s.id}.bins" data-num="1" value="${esc(s.bins)}"></div>`;
					if (s.type === 'bar') body += `<div class="ps-f"><label>막대 폭 (간격 대비)</label><input class="ps-in w-full" type="number" min="0.05" max="1" step="0.05" data-b="se.${s.id}.width" data-num="1" value="${esc(s.width)}"></div>`;
					body += `<div class="ps-f"><label>불투명도</label><input class="ps-in w-full" type="number" min="0" max="1" step="0.05" data-b="se.${s.id}.alpha" data-num="1" value="${esc(s.alpha)}"></div>`;
				}
				body += `</div>`;
			}
			return `<div class="ps-se${open ? ' is-open' : ''}"><div class="flex items-center gap-2"><span class="ps-sw" style="background:${c}"></span><button type="button" class="ps-se-h min-w-0 flex-1 truncate text-left" data-toggle="${s.id}">${open ? '▾' : '▸'} <b>${i + 1}</b> ${seriesTitle(s)}${st.axes.length > 1 ? ` <span class="ps-sub">· ${axName(s.ax)}</span>` : ''}</button><button type="button" class="ps-x" data-mv="${s.id}:-1" title="위로">↑</button><button type="button" class="ps-x" data-mv="${s.id}:1" title="아래로">↓</button><button type="button" class="ps-x" data-dup="${s.id}" title="복제">⧉</button><button type="button" class="ps-x" data-del="${s.id}" title="지우기">✕</button></div>${body}</div>`;
		}).join('');
	}

	// ───────────────────────── UI: 칸 (subplot) ─────────────────────────
	const axName = (k) => (st.axes.length > 1 ? `칸 ${k + 1} (${Math.floor(k / st.fig.cols) + 1}행 ${k % st.fig.cols + 1}열)` : '그래프');
	function syncAxes() {
		const n = Math.max(1, st.fig.rows * st.fig.cols);
		while (st.axes.length < n) st.axes.push(defAx(st.fig));
		if (st.axes.length > n) st.axes.length = n;
		for (const s of st.series) if (s.ax >= n) s.ax = n - 1;
		if (curAx >= n) curAx = n - 1;
	}
	function renderAxes() {
		syncAxes();
		const a = st.axes[curAx];
		const tabs = st.axes.length > 1 ? `<div class="ps-seg mb-2">${st.axes.map((_, k) => `<button type="button" data-curax="${k}" class="${k === curAx ? 'is-on' : ''}">${k + 1}</button>`).join('')}</div><p class="ps-sub mb-2">새로 추가하는 그래프는 <b>${axName(curAx)}</b> 에 들어가요.</p>` : '';
		const p = `ax.${curAx}`;
		$('ps-axes').innerHTML = tabs + `<div class="ps-grid">
			<div class="ps-f ps-span2"><label>제목</label><input class="ps-in w-full" data-b="${p}.title" value="${esc(a.title)}" placeholder="비우면 없음"></div>
			<div class="ps-f ps-span2"><label>X 축 이름 <span class="ps-tip" title="예: 시간 $t$ [ms] · $f$ [MHz] · $E_b/N_0$ [dB]">ⓘ</span></label><input class="ps-in w-full" data-b="${p}.xlabel" value="${esc(a.xlabel)}" placeholder="예: 시간 $t$ [s]"></div>
			<div class="ps-f ps-span2"><label>Y 축 이름</label><input class="ps-in w-full" data-b="${p}.ylabel" value="${esc(a.ylabel)}" placeholder="예: 진폭 [V]"></div>
			<div class="ps-f"><label>X 범위 (비우면 자동)</label><div class="flex gap-1"><input class="ps-in w-full" type="number" step="any" placeholder="처음" data-b="${p}.xlim.0" value="${esc(a.xlim[0])}"><input class="ps-in w-full" type="number" step="any" placeholder="끝" data-b="${p}.xlim.1" value="${esc(a.xlim[1])}"></div></div>
			<div class="ps-f"><label>Y 범위</label><div class="flex gap-1"><input class="ps-in w-full" type="number" step="any" placeholder="아래" data-b="${p}.ylim.0" value="${esc(a.ylim[0])}"><input class="ps-in w-full" type="number" step="any" placeholder="위" data-b="${p}.ylim.1" value="${esc(a.ylim[1])}"></div></div>
			<div class="ps-f"><label>X 눈금</label><select class="ps-in w-full" data-b="${p}.xscale">${opts({ linear: '보통', log: '로그 (10ⁿ)' }, a.xscale)}</select></div>
			<div class="ps-f"><label>Y 눈금</label><select class="ps-in w-full" data-b="${p}.yscale">${opts({ linear: '보통', log: '로그 (10ⁿ)' }, a.yscale)}</select></div>
			<div class="ps-f"><label>격자</label><select class="ps-in w-full" data-b="${p}.grid">${opts({ none: '없음', major: '큰 눈금', both: '큰·작은 눈금' }, a.grid)}</select></div>
			<div class="ps-f"><label>범례</label><select class="ps-in w-full" data-b="${p}.legend">${opts(LEGEND_LOC, a.legend)}</select></div>
			<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="${p}.box"${a.box ? ' checked' : ''}> 네 테두리 (끄면 위·오른쪽 없음)</label></div>
			<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="${p}.tightx"${a.tightx ? ' checked' : ''}> X 를 데이터에 딱 맞춤</label></div>
			<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="${p}.equal"${a.equal ? ' checked' : ''}> X·Y 같은 비율</label></div>
		</div><p class="ps-sub mt-2">💡 미리보기에서 <b>끌면</b> 그 부분으로 범위가 정해지고, <b>두 번 누르면</b> 자동으로 돌아가요.</p>`;
	}

	// ───────────────────────── UI: 그림 전체 ─────────────────────────
	function renderFig() {
		const f = st.fig;
		const cm = (v) => (v * 2.54).toFixed(1);
		$('ps-fig').innerHTML = `<div class="ps-grid">
			<div class="ps-f ps-span2"><label>스타일 한 번에 고르기</label><select class="ps-in w-full" id="ps-preset">${opts(Object.fromEntries(Object.entries(PRESETS).map(([k, p]) => [k, p.name])), f.preset)}<option value="custom"${f.preset === 'custom' ? ' selected' : ''}>직접 고침</option></select></div>
			<div class="ps-f"><label>가로 (inch) <span class="ps-sub">${cm(f.w)} cm</span></label><input class="ps-in w-full" type="number" min="1" max="30" step="0.05" data-b="fig.w" data-num="1" data-rebuild-fig="1" value="${f.w}"></div>
			<div class="ps-f"><label>세로 (inch) <span class="ps-sub">${cm(f.h)} cm</span></label><input class="ps-in w-full" type="number" min="1" max="30" step="0.05" data-b="fig.h" data-num="1" data-rebuild-fig="1" value="${f.h}"></div>
			<div class="ps-f"><label>칸 나누기 (행 × 열)</label><div class="flex items-center gap-1"><input class="ps-in w-full" type="number" min="1" max="6" step="1" data-b="fig.rows" data-num="1" data-rebuild-axes="1" value="${f.rows}">×<input class="ps-in w-full" type="number" min="1" max="6" step="1" data-b="fig.cols" data-num="1" data-rebuild-axes="1" value="${f.cols}"></div></div>
			<div class="ps-f"><label>칸끼리 축 공유</label><div class="flex gap-3 pt-1 text-[13px]"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.sharex"${f.sharex ? ' checked' : ''}> X</label><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.sharey"${f.sharey ? ' checked' : ''}> Y</label></div></div>
			<div class="ps-f ps-span2"><label>글꼴</label><select class="ps-in w-full" data-b="fig.font">${opts(Object.fromEntries(Object.entries(FONTS).map(([k, v]) => [k, v.name])), f.font)}</select></div>
			<div class="ps-f ps-span2"><label>LaTeX 수식</label><select class="ps-in w-full" data-b="fig.tex">${opts({ mathtext: '$…$ 사이만 수식 (설치 필요 없음, 추천)', usetex: '진짜 LaTeX 로 모든 글자 (TeX 설치 필요)', none: '수식 안 씀 ($ 그대로 보임)' }, f.tex)}</select></div>
			<div class="ps-f"><label>글자 크기 (pt)</label><input class="ps-in w-full" type="number" min="4" max="40" step="0.5" data-b="fig.fs" data-num="1" value="${f.fs}"></div>
			<div class="ps-f"><label>제목 크기</label><input class="ps-in w-full" type="number" min="4" max="40" step="0.5" data-b="fig.fsTitle" data-num="1" value="${f.fsTitle}"></div>
			<div class="ps-f"><label>눈금 숫자 크기</label><input class="ps-in w-full" type="number" min="4" max="40" step="0.5" data-b="fig.fsTick" data-num="1" value="${f.fsTick}"></div>
			<div class="ps-f"><label>범례 글자 크기</label><input class="ps-in w-full" type="number" min="4" max="40" step="0.5" data-b="fig.fsLegend" data-num="1" value="${f.fsLegend}"></div>
			<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.titleBold"${f.titleBold ? ' checked' : ''}> 제목 굵게</label></div>
			<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.legendFrame"${f.legendFrame ? ' checked' : ''}> 범례 테두리</label></div>
			<div class="ps-f ps-span2"><label>색 순서</label><select class="ps-in w-full" data-b="fig.palette" data-rebuild="1">${opts(Object.fromEntries(Object.entries(PALETTES).map(([k, v]) => [k, v.name])), f.palette)}</select><div class="mt-1 flex gap-1">${(PALETTES[f.palette] || PALETTES.tab10).c.map((c) => `<span class="ps-sw" style="background:${c}"></span>`).join('')}</div></div>
			<div class="ps-f"><label>기본 선 굵기 (pt)</label><input class="ps-in w-full" type="number" min="0.1" max="10" step="0.1" data-b="fig.lw" data-num="1" value="${f.lw}"></div>
			<div class="ps-f"><label>테두리 굵기 (pt)</label><input class="ps-in w-full" type="number" min="0.1" max="5" step="0.1" data-b="fig.axLw" data-num="1" value="${f.axLw}"></div>
			<div class="ps-f"><label>눈금 방향</label><select class="ps-in w-full" data-b="fig.tickDir">${opts({ out: '바깥', in: '안쪽' }, f.tickDir)}</select></div>
			<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.mirror"${f.mirror ? ' checked' : ''}> 위·오른쪽에도 눈금</label></div>
			<div class="ps-f"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.minor"${f.minor ? ' checked' : ''}> 작은 눈금</label></div>
			<div class="ps-f"><label>격자 선</label><select class="ps-in w-full" data-b="fig.gridStyle">${opts({ ':': '··· 점', '--': '- - 점선', '-': '── 실선' }, f.gridStyle)}</select></div>
			<div class="ps-f ps-span2"><label>자동 범위</label><select class="ps-in w-full" data-b="fig.limits">${opts({ pad: '데이터 + 5% 여유 (matplotlib 식)', ticks: '눈금에 맞춰 반올림 (MATLAB 식)', tight: '데이터에 딱 맞춤' }, f.limits)}</select></div>
			<div class="ps-f ps-span2"><label>저장 파일 이름</label><input class="ps-in w-full" data-b="fig.out" value="${esc(f.out)}"></div>
			<div class="ps-f ps-span2"><label>저장 형식</label><div class="flex flex-wrap gap-3 pt-1 text-[13px]"><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.fmtPdf"${f.fmtPdf ? ' checked' : ''}> PDF (벡터, 논문용)</label><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.fmtSvg"${f.fmtSvg ? ' checked' : ''}> SVG</label><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.fmtPng"${f.fmtPng ? ' checked' : ''}> PNG</label><label class="inline-flex items-center gap-1"><input type="checkbox" data-b="fig.transparent"${f.transparent ? ' checked' : ''}> 배경 투명</label></div></div>
			<div class="ps-f"><label>PNG 해상도 (dpi)</label><input class="ps-in w-full" type="number" min="50" max="1200" step="10" data-b="fig.dpi" data-num="1" value="${f.dpi}"></div>
		</div>`;
	}

	function applyPreset(k) {
		const p = PRESETS[k];
		if (!p) { st.fig.preset = 'custom'; return; }
		Object.assign(st.fig, p.fig, { preset: k });
		for (const a of st.axes) Object.assign(a, p.ax);
	}

	// ───────────────────────── 바인딩 ─────────────────────────
	function setPath(path, val) {
		const parts = path.split('.');
		let o;
		if (parts[0] === 'fig') o = st.fig;
		else if (parts[0] === 'ax') { o = st.axes[+parts[1]]; parts.splice(0, 1); }
		else if (parts[0] === 'se') { o = st.series.find((s) => s.id === +parts[1]); parts.splice(0, 1); }
		if (!o) return;
		for (let i = 1; i < parts.length - 1; i++) { if (o[parts[i]] == null) o[parts[i]] = {}; o = o[parts[i]]; }
		o[parts[parts.length - 1]] = val;
	}

	function onInput(e) {
		const el = e.target;
		if (el.id === 'ps-preset') { applyPreset(el.value); renderFig(); renderAxes(); renderSeries(); update(); return; }
		if (el.dataset.b) {
			let val = el.type === 'checkbox' ? el.checked : el.value;
			if (el.dataset.num && el.type !== 'checkbox') val = val === '' ? '' : Number(val);
			setPath(el.dataset.b, val);
			if (el.dataset.b.startsWith('fig.') && !['fig.out', 'fig.dpi', 'fig.fmtPdf', 'fig.fmtPng', 'fig.fmtSvg', 'fig.transparent', 'fig.lang'].includes(el.dataset.b)) {
				if (st.fig.preset !== 'custom' && /^fig\.(w|h|font|fs|fsTitle|fsTick|fsLegend|lw|axLw|tickDir|mirror|palette|limits|titleBold|legendFrame)$/.test(el.dataset.b)) { st.fig.preset = 'custom'; const ps = $('ps-preset'); if (ps) ps.value = 'custom'; }
			}
			if (el.dataset.rebuildAxes) { syncAxes(); renderAxes(); renderSeries(); }
			else if (el.dataset.rebuild && e.type === 'change') renderSeries();
			if (el.dataset.b === 'fig.palette' && e.type === 'change') renderFig();
			if (el.dataset.b === 'fig.w' || el.dataset.b === 'fig.h') { /* cm 표시는 change 때 */ if (e.type === 'change') renderFig(); }
			update();
			return;
		}
		if (el.dataset.ref && e.type === 'change') {
			const [id, which] = el.dataset.ref.split('.');
			const s = st.series.find((u) => u.id === +id);
			if (!s) return;
			const v = el.value ? varIndex.get(el.value) : null;
			s[which] = v ? defaultRef(v, s.type === 'image' && which === 'y') : null;
			renderSeries(); update();
			return;
		}
		if (el.dataset.idx) {
			const [id, which, dim] = el.dataset.idx.split('.');
			const s = st.series.find((u) => u.id === +id);
			if (!s || !s[which]) return;
			const v = getVar(s[which]);
			const n = Math.max(1, Math.min(v ? v.dims[+dim] : 1, Math.round(+el.value || 1)));
			s[which].idx = (s[which].idx || []).slice();
			s[which].idx[+dim] = n - 1;
			if (e.type === 'change') renderSeries();
			update();
		}
	}

	function onClick(e) {
		const t = e.target.closest('button');
		if (!t) return;
		const d = t.dataset;
		if (d.recipe) { const v = varIndex.get(d.v); if (v) recipe(v, d.recipe); return; }
		if (d.rmfile) { removeFile(d.rmfile); return; }
		if (d.toggle) { const id = +d.toggle; openSeries.has(id) ? openSeries.delete(id) : openSeries.add(id); renderSeries(); return; }
		if (d.del) { st.series = st.series.filter((s) => s.id !== +d.del); renderSeries(); update(); return; }
		if (d.dup) { const s = st.series.find((u) => u.id === +d.dup); if (s) { const c = JSON.parse(JSON.stringify(s)); c.id = st.nextId++; c.color = ''; st.series.splice(st.series.indexOf(s) + 1, 0, c); openSeries.add(c.id); renderSeries(); update(); } return; }
		if (d.mv) { const [id, dir] = d.mv.split(':').map(Number); const i = st.series.findIndex((s) => s.id === id); const j = i + dir; if (i >= 0 && j >= 0 && j < st.series.length) { [st.series[i], st.series[j]] = [st.series[j], st.series[i]]; renderSeries(); update(); } return; }
		if (d.curax != null) { curAx = +d.curax; renderAxes(); return; }
		if (d.swap) { const s = st.series.find((u) => u.id === +d.swap); if (s && s.y) { [s.y.rd, s.y.cd] = [s.y.cd, s.y.rd]; [s.xv, s.yv] = [s.yv, s.xv]; renderSeries(); update(); } return; }
		if (d.bClear) { setPath(d.bClear, ''); renderSeries(); update(); return; }
	}

	// ───────────────────────── 눈금 계산 ─────────────────────────
	const STEPS = [1, 2, 2.5, 5, 10];
	function niceStep(range, nbins) {
		const raw = range / Math.max(1, nbins);
		const mag = Math.pow(10, Math.floor(Math.log10(raw)));
		for (const s of STEPS) if (s * mag >= raw * (1 - 1e-9)) return s * mag;
		return 10 * mag;
	}
	function linTicks(lo, hi, nbins) {
		const step = niceStep(hi - lo, nbins);
		const out = [];
		const a = Math.ceil(lo / step - 1e-9), b = Math.floor(hi / step + 1e-9);
		for (let k = a; k <= b && out.length < 50; k++) out.push(Math.abs(k * step) < step * 1e-9 ? 0 : k * step);
		return { ticks: out, step };
	}
	function fmtTicks(ticks, step, mathFont) {
		const amax = Math.max(0, ...ticks.map(Math.abs));
		let exp = 0;
		if (amax > 0) { const oom = Math.floor(Math.log10(amax) + 1e-9); if (oom >= 5 || oom <= -4) exp = oom; }
		const sc = Math.pow(10, -exp);
		let dec = 0;
		for (; dec < 12; dec++) { const p = Math.pow(10, dec); if (ticks.every((t) => Math.abs(Math.round(t * sc * p) / p - t * sc) < Math.abs(step * sc) * 1e-6)) break; }
		const minus = mathFont ? '-' : '−';
		return { labels: ticks.map((t) => { let s = (t * sc).toFixed(dec); if (/^-0(\.0*)?$/.test(s)) s = s.slice(1); return s.replace('-', minus); }), exp };
	}
	function logTicks(lo, hi, nbins) {
		const a = Math.ceil(Math.log10(lo) - 1e-9), b = Math.floor(Math.log10(hi) + 1e-9);
		let stride = 1;
		while ((b - a) / stride + 1 > Math.max(2, nbins + 1)) stride++;
		const ticks = [], minor = [];
		for (let k = a; k <= b; k++) if ((k - a) % stride === 0) ticks.push(Math.pow(10, k));
		if (stride === 1) for (let k = Math.floor(Math.log10(lo)); k <= b; k++) for (let m = 2; m < 10; m++) { const v = m * Math.pow(10, k); if (v >= lo && v <= hi) minor.push(v); }
		return { ticks, minor, labels: ticks.map((t) => '$10^{' + Math.round(Math.log10(t)) + '}$') };
	}

	// ───────────────────────── 글자 (KaTeX) ─────────────────────────
	function texHTML(s) {
		s = String(s || '');
		if (st.fig.tex === 'none' || typeof katex === 'undefined' || !s.includes('$')) return esc(st.fig.tex === 'usetex' ? s.replace(/\\([_#%&$])/g, '$1') : s);
		const parts = s.split(/(?<!\\)\$/);
		let html = '';
		parts.forEach((p, i) => {
			if (i % 2 === 0) html += esc(p.replace(/\\\$/g, '$').replace(/\\([_#%&])/g, '$1'));
			else if (i === parts.length - 1) html += esc('$' + p);
			else {
				try { html += katex.renderToString(p, { throwOnError: false, output: 'html', strict: 'ignore' }); } catch (e) { html += esc('$' + p + '$'); }
			}
		});
		return html;
	}
	const hasKo = (s) => /[\u3131-\u318e\uac00-\ud7a3]/.test(s || '');

	// ───────────────────────── 미리보기 그리기 ─────────────────────────
	const stage = () => $('ps-stage');
	let layoutCache = null; // 끌어서 확대할 때 쓸 칸 위치

	function seriesData(s) {
		if (s.type === 'image') {
			const m = matOf(s.y);
			if (!m) return null;
			const base = st.fig.lang === 'm' ? 1 : 0;
			const xv = s.xv ? vecOf(s.xv) : null, yv = s.yv ? vecOf(s.yv) : null;
			const centers = (v, n) => (v && v.length === n ? v : Float64Array.from({ length: n }, (_, i) => i + base));
			return { img: m, xc: centers(xv, m.C), yc: centers(yv, m.R), bad: (xv && xv.length !== m.C) || (yv && yv.length !== m.R) };
		}
		const y = vecOf(s.y);
		if (!y) return null;
		if (s.type === 'hist') return { y };
		let x = s.x ? vecOf(s.x) : null;
		let bad = false;
		if (x && x.length !== y.length) bad = true;
		const n = x ? Math.min(x.length, y.length) : y.length;
		if (!x) { const base = st.fig.lang === 'm' ? 1 : 0; x = Float64Array.from({ length: n }, (_, i) => i + base); }
		return { x: x.length === n ? x : x.subarray(0, n), y: y.length === n ? y : y.subarray(0, n), bad };
	}

	function histBins(y, bins) {
		let lo = Infinity, hi = -Infinity;
		for (const v of y) if (isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
		if (!isFinite(lo)) return null;
		if (lo === hi) { lo -= 0.5; hi += 0.5; }
		bins = Math.max(1, Math.min(1000, Math.round(bins) || 30));
		const counts = new Float64Array(bins);
		const w = (hi - lo) / bins;
		for (const v of y) if (isFinite(v)) counts[Math.min(bins - 1, Math.floor((v - lo) / w))]++;
		return { lo, hi, w, counts };
	}

	function draw() {
		const box = stage();
		if (!box) return;
		const f = st.fig;
		const avail = Math.max(200, box.parentElement.clientWidth);
		const zsel = $('ps-zoom').value;
		const natural = f.w * 96;
		const zoom = zsel === 'fit' ? Math.min(2.5, avail / natural) : +zsel;
		const P = zoom * 96 / 72; // pt → 화면 px
		const W = f.w * 72 * P, H = f.h * 72 * P;
		box.style.width = W + 'px'; box.style.height = H + 'px';
		const cv = $('ps-canvas'), ov = $('ps-ov');
		const dpr = window.devicePixelRatio || 1;
		cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
		cv.style.width = W + 'px'; cv.style.height = H + 'px';
		const g = cv.getContext('2d');
		g.setTransform(dpr, 0, 0, dpr, 0, 0);
		g.fillStyle = '#fff'; g.fillRect(0, 0, W, H);
		ov.innerHTML = '';
		const fontCSS = FONTS[f.font] ? FONTS[f.font].css + KO_CSS : 'sans-serif';
		const useCM = f.font === 'cm' || f.tex === 'usetex';
		ov.style.fontFamily = useCM ? FONTS.cm.css + KO_CSS : fontCSS;
		const mkText = (html, pt, extra) => {
			const el = document.createElement('div');
			el.className = 'ps-t' + (extra || '');
			el.style.fontSize = pt * P + 'px';
			el.innerHTML = html;
			ov.appendChild(el);
			return el;
		};
		const textSize = (el) => ({ w: el.offsetWidth, h: el.offsetHeight });

		// 1) 칸마다 데이터 모으기
		const AX = st.axes.map((a, k) => ({ a, k, series: st.series.filter((s) => s.ax === k).map((s) => ({ s, d: seriesData(s) })).filter((o) => o.d) }));
		for (const A of AX) {
			let xl = Infinity, xh = -Infinity, yl = Infinity, yh = -Infinity;
			let stickyY0 = false, stickyX = false, stickyY = false;
			const xlog = A.a.xscale === 'log', ylog = A.a.yscale === 'log';
			const take = (arr, log, isX) => {
				for (const v of arr) if (isFinite(v) && (!log || v > 0)) { if (isX) { if (v < xl) xl = v; if (v > xh) xh = v; } else { if (v < yl) yl = v; if (v > yh) yh = v; } }
			};
			for (const { s, d } of A.series) {
				if (s.type === 'image') {
					const ex = (c) => { const n = c.length; const h0 = n > 1 ? (c[1] - c[0]) / 2 : 0.5, h1 = n > 1 ? (c[n - 1] - c[n - 2]) / 2 : 0.5; return [c[0] - h0, c[n - 1] + h1]; };
					d.xe = ex(d.xc); d.ye = ex(d.yc);
					take(d.xe, xlog, true); take(d.ye, ylog, false); stickyX = stickyY = true;
					let lo = Infinity, hi = -Infinity;
					for (const v of d.img.z) if (isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
					d.clo = s.clo !== '' && isFinite(+s.clo) ? +s.clo : lo; d.chi = s.chi !== '' && isFinite(+s.chi) ? +s.chi : hi;
					if (!(d.chi > d.clo)) d.chi = d.clo + 1;
				} else if (s.type === 'hist') {
					d.h = histBins(d.y, s.bins);
					if (!d.h) continue;
					take([d.h.lo, d.h.hi], xlog, true); take([0, Math.max(...d.h.counts)], ylog, false); stickyY0 = true;
				} else {
					take(d.x, xlog, true); take(d.y, ylog, false);
					if (s.type === 'bar') {
						let dx = Infinity;
						for (let i = 1; i < d.x.length; i++) { const q = Math.abs(d.x[i] - d.x[i - 1]); if (q > 0 && q < dx) dx = q; }
						d.bw = (isFinite(dx) ? dx : 1) * (+s.width || 0.8);
						take([xl - d.bw / 2, xh + d.bw / 2], xlog, true);
						if (!ylog) { take([0], false, false); stickyY0 = true; }
					}
					if (s.type === 'stem' && !ylog) take([0], false, false);
				}
			}
			A.dl = { xl, xh, yl, yh, stickyY0, stickyX, stickyY };
		}
		// 공유 축
		if (f.sharex) shareLimits(AX, 'x');
		if (f.sharey) shareLimits(AX, 'y');

		// 2) 칸 크기 대충 → 눈금 → 글자 재기 → 자리 잡기 (두 번)
		const pad = 4 * P; // 그림 가장자리 여유
		const R = f.rows, C = f.cols;
		const tickLen = 3.5 * P, tickPad = 3.5 * P, labelPad = 4 * P;
		let rects = AX.map(() => ({ w: (W - 2 * pad) / C * 0.75, h: (H - 2 * pad) / R * 0.75 }));
		let deco;
		for (let pass = 0; pass < 2; pass++) {
			ov.innerHTML = '';
			deco = AX.map((A, k) => {
				const r = Math.floor(k / C), c = k % C;
				const a = A.a;
				const xr = finalLimits(A, 'x', rects[k].w / P);
				const yr = finalLimits(A, 'y', rects[k].h / P);
				const hideX = f.sharex && r < R - 1 && AX[k + C];
				const hideY = f.sharey && c > 0;
				const mk = (rng, hide) => {
					const els = rng.labels.map((t) => mkText(rng.log ? texHTML(t) : esc(t), f.fsTick));
					if (hide) els.forEach((e) => (e.style.display = 'none'));
					const off = rng.exp ? mkText(texHTML('$\\times10^{' + rng.exp + '}$'), f.fsTick) : null;
					if (off && hide) off.style.display = 'none';
					return { els, off };
				};
				const xt = mk(xr, hideX), yt = mk(yr, hideY);
				const out = f.tickDir === 'out' ? tickLen : 0;
				const xth = hideX ? 0 : Math.max(0, ...xt.els.map((e) => textSize(e).h));
				const ytw = hideY ? 0 : Math.max(0, ...yt.els.map((e) => textSize(e).w));
				const xlab = a.xlabel && !hideX ? mkText(texHTML(a.xlabel), f.fs) : null;
				const ylab = a.ylabel && !hideY ? mkText(texHTML(a.ylabel), f.fs, ' ps-rot') : null;
				const title = a.title ? mkText(texHTML(a.title), f.fsTitle, f.titleBold ? ' ps-b' : '') : null;
				const xls = xlab ? textSize(xlab) : { w: 0, h: 0 }, yls = ylab ? textSize(ylab) : { w: 0, h: 0 };
				const ts = title ? textSize(title) : { w: 0, h: 0 };
				const yoff = yt.off ? textSize(yt.off) : { w: 0, h: 0 };
				// 범례
				const items = A.series.filter(({ s }) => s.label && s.type !== 'image');
				let leg = null;
				if (items.length && a.legend !== 'none') {
					const els = items.map(({ s }) => mkText(texHTML(s.label), f.fsLegend));
					const fsP = f.fsLegend * P;
					const sizes = els.map(textSize);
					const horiz = a.legend === 'outside top';
					const hl = 2 * fsP, hp = 0.8 * fsP, bp = 0.4 * fsP, ls = 0.5 * fsP, cs = 2 * fsP;
					const rowH = Math.max(fsP * 1.2, ...sizes.map((z) => z.h));
					const lw = horiz ? sizes.reduce((q, z) => q + hl + hp + z.w, 0) + cs * (items.length - 1) + 2 * bp + 2 * 0.4 * fsP : hl + hp + Math.max(...sizes.map((z) => z.w)) + 2 * bp + 2 * 0.4 * fsP;
					const lh = horiz ? rowH + 2 * bp + 2 * 0.2 * fsP : items.length * rowH + (items.length - 1) * ls + 2 * bp + 2 * 0.2 * fsP;
					leg = { items, els, sizes, w: lw, h: lh, rowH, hl, hp, bp, ls, cs, horiz, fsP };
				}
				// 색 막대
				const img = A.series.find(({ s }) => s.type === 'image' && s.cbar);
				let cb = null;
				if (img) {
					const ct = linTicks(img.d.clo, img.d.chi, Math.max(2, Math.min(9, Math.floor(rects[k].h / P / (f.fsTick * 2)))));
					const fl = fmtTicks(ct.ticks, ct.step, useCM);
					const els = fl.labels.map((t) => mkText(esc(t), f.fsTick));
					const lab = img.s.cbarLabel ? mkText(texHTML(img.s.cbarLabel), f.fs, ' ps-rot') : null;
					const off = fl.exp ? mkText(texHTML('$\\times10^{' + fl.exp + '}$'), f.fsTick) : null;
					const bw = Math.max(6 * P, rects[k].h / 20);
					const tw = Math.max(0, ...els.map((e) => textSize(e).w));
					cb = { d: img.d, s: img.s, ticks: ct.ticks, els, lab, off, bw, tw, padL: 0.05 * rects[k].w + 2 * P, w: 0.05 * rects[k].w + 2 * P + bw + tickLen + tickPad + tw + (lab ? labelPad + textSize(lab).h : 0) };
				}
				return {
					xr, yr, xt, yt, xlab, ylab, title, leg, cb, hideX, hideY, xls, yls, ts,
					left: ytw + tickPad + out + (ylab ? labelPad + yls.h : 0),
					bottom: xth + (xth ? tickPad : 0) + out + (xlab ? labelPad + xls.h : 0),
					top: Math.max(title ? ts.h + 6 * P : 0, yoff.h ? yoff.h + 2 * P : 0) + (leg && a.legend === 'outside top' ? leg.h + 4 * P : 0),
					right: (cb ? cb.w : 0) + (leg && a.legend === 'outside right' ? leg.w + 4 * P : 0) + (xt.off ? 0 : 0),
				};
			});
			// 행·열마다 여백 맞추기
			const colL = Array(C).fill(0), colR = Array(C).fill(0), rowT = Array(R).fill(0), rowB = Array(R).fill(0);
			deco.forEach((d, k) => { const r = Math.floor(k / C), c = k % C; colL[c] = Math.max(colL[c], d.left); colR[c] = Math.max(colR[c], d.right); rowT[r] = Math.max(rowT[r], d.top); rowB[r] = Math.max(rowB[r], d.bottom); });
			const gap = 6 * P;
			const aw = Math.max(20, (W - 2 * pad - colL.reduce((q, v) => q + v, 0) - colR.reduce((q, v) => q + v, 0) - gap * (C - 1)) / C);
			const ah = Math.max(20, (H - 2 * pad - rowT.reduce((q, v) => q + v, 0) - rowB.reduce((q, v) => q + v, 0) - gap * (R - 1)) / R);
			rects = AX.map((A, k) => {
				const r = Math.floor(k / C), c = k % C;
				let x = pad; for (let i = 0; i < c; i++) x += colL[i] + aw + colR[i] + gap; x += colL[c];
				let y = pad; for (let i = 0; i < r; i++) y += rowT[i] + ah + rowB[i] + gap; y += rowT[r];
				return { x, y, w: aw, h: ah };
			});
			// 같은 비율: 칸 안에서 줄이기
			AX.forEach((A, k) => {
				if (!A.a.equal) return;
				const d = deco[k];
				const rx = tr(d.xr, d.xr.hi) - tr(d.xr, d.xr.lo), ry = tr(d.yr, d.yr.hi) - tr(d.yr, d.yr.lo);
				if (!(rx > 0 && ry > 0)) return;
				const rc = rects[k];
				const want = rx / ry; // 가로/세로 데이터 비
				if (rc.w / rc.h > want) { const nw = rc.h * want; rc.x += (rc.w - nw) / 2; rc.w = nw; }
				else { const nh = rc.w / want; rc.y += (rc.h - nh) / 2; rc.h = nh; }
			});
		}

		// 3) 그리기
		layoutCache = AX.map((A, k) => ({ rect: rects[k], xr: deco[k].xr, yr: deco[k].yr, k }));
		AX.forEach((A, k) => drawAxes(g, A, rects[k], deco[k], P, tickLen, tickPad, labelPad, textSize));
	}

	function shareLimits(AX, ax) {
		const lo = Math.min(...AX.map((A) => A.dl[ax + 'l'])), hi = Math.max(...AX.map((A) => A.dl[ax + 'h']));
		for (const A of AX) { A.dl[ax + 'l'] = lo; A.dl[ax + 'h'] = hi; }
	}

	const tr = (rng, v) => (rng.log ? Math.log10(v) : v);

	function finalLimits(A, which, lenPt) {
		const a = A.a, f = st.fig;
		const log = (which === 'x' ? a.xscale : a.yscale) === 'log';
		const user = which === 'x' ? a.xlim : a.ylim;
		let lo = A.dl[which + 'l'], hi = A.dl[which + 'h'];
		if (!isFinite(lo) || !isFinite(hi)) { lo = log ? 1 : 0; hi = log ? 10 : 1; }
		if (lo === hi) { const e = log ? 0 : Math.abs(lo) * 0.05 || 0.05; lo = log ? lo / 1.5 : lo - e; hi = log ? hi * 1.5 : hi + e; }
		const fsTick = f.fsTick;
		const nb = Math.max(2, Math.min(9, Math.floor(lenPt / (fsTick * (which === 'x' ? 3 : 2)))));
		const sticky = which === 'x' ? A.dl.stickyX : A.dl.stickyY;
		const T = (v) => (log ? Math.log10(v) : v), iT = (v) => (log ? Math.pow(10, v) : v);
		const mode = which === 'x' && a.tightx ? 'tight' : f.limits;
		let L = T(lo), Hh = T(hi);
		if (!sticky) {
			if (mode === 'pad') { const m = (Hh - L) * 0.05; if (!(which === 'y' && A.dl.stickyY0 && lo === 0)) L -= m; Hh += m; }
			else if (mode === 'ticks') {
				if (log) { L = Math.floor(L + 1e-9); Hh = Math.ceil(Hh - 1e-9); }
				else { const st2 = niceStep(Hh - L, nb); L = Math.floor(L / st2 + 1e-9) * st2; Hh = Math.ceil(Hh / st2 - 1e-9) * st2; }
			}
		}
		lo = iT(L); hi = iT(Hh);
		const u0 = user[0] !== '' && user[0] != null && isFinite(+user[0]) ? +user[0] : null, u1 = user[1] !== '' && user[1] != null && isFinite(+user[1]) ? +user[1] : null;
		if (u0 != null && (!log || u0 > 0)) lo = u0;
		if (u1 != null && (!log || u1 > 0)) hi = u1;
		if (!(hi > lo)) hi = lo + (log ? lo * 9 : 1);
		if (log) {
			const t = logTicks(lo, hi, nb);
			return { lo, hi, log, ticks: t.ticks, minor: t.minor, labels: t.labels, exp: 0 };
		}
		const t = linTicks(lo, hi, nb);
		const fl = fmtTicks(t.ticks, t.step, f.font === 'cm' || f.tex === 'usetex');
		let minor = [];
		if (f.minor || a.grid === 'both') { const ms = t.step / (String(t.step / Math.pow(10, Math.floor(Math.log10(t.step)))).startsWith('2') ? 4 : 5); for (let v = Math.ceil(lo / ms) * ms; v <= hi; v += ms) minor.push(v); }
		return { lo, hi, log, ticks: t.ticks, minor, labels: fl.labels, exp: fl.exp };
	}

	function dashFor(ls, lw) {
		const k = Math.max(lw, 0.5);
		if (ls === '--') return [3.7 * k, 1.6 * k];
		if (ls === ':') return [1 * k, 1.65 * k];
		if (ls === '-.') return [6.4 * k, 1.6 * k, 1 * k, 1.6 * k];
		return [];
	}

	function drawMarker(g, m, x, y, size, color, filled, lw) {
		const r = size / 2;
		g.beginPath();
		switch (m) {
			case 'o': g.arc(x, y, r, 0, 2 * Math.PI); break;
			case '.': g.arc(x, y, r * 0.5, 0, 2 * Math.PI); break;
			case 's': g.rect(x - r * 0.9, y - r * 0.9, r * 1.8, r * 1.8); break;
			case '^': g.moveTo(x, y - r); g.lineTo(x + r, y + r * 0.8); g.lineTo(x - r, y + r * 0.8); g.closePath(); break;
			case 'v': g.moveTo(x, y + r); g.lineTo(x + r, y - r * 0.8); g.lineTo(x - r, y - r * 0.8); g.closePath(); break;
			case 'D': g.moveTo(x, y - r); g.lineTo(x + r * 0.75, y); g.lineTo(x, y + r); g.lineTo(x - r * 0.75, y); g.closePath(); break;
			case 'x': g.moveTo(x - r * 0.75, y - r * 0.75); g.lineTo(x + r * 0.75, y + r * 0.75); g.moveTo(x + r * 0.75, y - r * 0.75); g.lineTo(x - r * 0.75, y + r * 0.75); break;
			case '+': g.moveTo(x - r, y); g.lineTo(x + r, y); g.moveTo(x, y - r); g.lineTo(x, y + r); break;
			case '*': for (let i = 0; i < 5; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / 5; g.moveTo(x, y); g.lineTo(x + r * Math.cos(a), y + r * Math.sin(a)); } break;
			default: return;
		}
		g.setLineDash([]);
		g.lineWidth = lw;
		g.strokeStyle = color;
		if (filled && !'x+*'.includes(m)) { g.fillStyle = color; g.fill(); }
		else if (!'x+*'.includes(m)) { g.fillStyle = '#fff'; g.fill(); }
		g.stroke();
	}

	function drawAxes(g, A, rc, d, P, tickLen, tickPad, labelPad, textSize) {
		const f = st.fig, a = A.a;
		const X = (v) => rc.x + (tr(d.xr, v) - tr(d.xr, d.xr.lo)) / (tr(d.xr, d.xr.hi) - tr(d.xr, d.xr.lo)) * rc.w;
		const Y = (v) => rc.y + rc.h - (tr(d.yr, v) - tr(d.yr, d.yr.lo)) / (tr(d.yr, d.yr.hi) - tr(d.yr, d.yr.lo)) * rc.h;
		const xlog = d.xr.log, ylog = d.yr.log;
		const okX = (v) => isFinite(v) && (!xlog || v > 0), okY = (v) => isFinite(v) && (!ylog || v > 0);
		const place = (el, x, y, ax, ay) => { if (!el) return; const z = textSize(el); el.style.left = (x - z.w * ax) + 'px'; el.style.top = (y - z.h * ay) + 'px'; };

		// 격자
		const gridLine = (minor) => { g.setLineDash(dashFor(f.gridStyle, (minor ? 0.4 : 0.6) * P)); g.lineWidth = (minor ? 0.4 : 0.6) * P; g.strokeStyle = minor ? '#e3e3e3' : '#c8c8c8'; };
		if (a.grid !== 'none') {
			for (const minor of a.grid === 'both' ? [true, false] : [false]) {
				gridLine(minor);
				g.beginPath();
				for (const v of minor ? d.xr.minor : d.xr.ticks) { const x = Math.round(X(v)) + 0.5; g.moveTo(x, rc.y); g.lineTo(x, rc.y + rc.h); }
				for (const v of minor ? d.yr.minor : d.yr.ticks) { const y = Math.round(Y(v)) + 0.5; g.moveTo(rc.x, y); g.lineTo(rc.x + rc.w, y); }
				g.stroke();
			}
		}

		// 데이터 (칸 안으로 자르기)
		g.save();
		g.beginPath(); g.rect(rc.x, rc.y, rc.w, rc.h); g.clip();
		for (const { s, d: sd } of A.series) {
			const color = seriesColor(s), lw = seriesLw(s) * P, ls = seriesLs(s);
			const alpha = isFinite(+s.alpha) ? Math.max(0, Math.min(1, +s.alpha)) : 1;
			g.globalAlpha = alpha;
			if (s.type === 'image') {
				const { img } = sd;
				const oc = document.createElement('canvas');
				oc.width = img.C; oc.height = img.R;
				const og = oc.getContext('2d');
				const id = og.createImageData(img.C, img.R);
				const span = sd.chi - sd.clo;
				for (let r = 0; r < img.R; r++) for (let c = 0; c < img.C; c++) {
					const v = img.z[r * img.C + c];
					const o = ((img.R - 1 - r) * img.C + c) * 4;
					if (!isFinite(v)) { id.data[o + 3] = 0; continue; }
					const col = cmapAt(s.cmap, (v - sd.clo) / span);
					id.data[o] = col[0]; id.data[o + 1] = col[1]; id.data[o + 2] = col[2]; id.data[o + 3] = 255;
				}
				og.putImageData(id, 0, 0);
				g.imageSmoothingEnabled = false;
				const x0 = X(sd.xe[0]), x1 = X(sd.xe[1]), y0 = Y(sd.ye[0]), y1 = Y(sd.ye[1]);
				g.drawImage(oc, Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
				continue;
			}
			if (s.type === 'hist') {
				if (!sd.h) continue;
				g.fillStyle = color;
				for (let i = 0; i < sd.h.counts.length; i++) {
					const c = sd.h.counts[i]; if (!c) continue;
					const x0 = X(sd.h.lo + i * sd.h.w), x1 = X(sd.h.lo + (i + 1) * sd.h.w);
					const yb = ylog ? rc.y + rc.h : Y(0), yt = Y(c);
					g.fillRect(x0, yt, x1 - x0, yb - yt);
				}
				g.strokeStyle = '#fff'; g.lineWidth = 0.5 * P; g.setLineDash([]);
				for (let i = 0; i < sd.h.counts.length; i++) { const c = sd.h.counts[i]; if (!c) continue; const x0 = X(sd.h.lo + i * sd.h.w), x1 = X(sd.h.lo + (i + 1) * sd.h.w); g.strokeRect(x0, Y(c), x1 - x0, (ylog ? rc.y + rc.h : Y(0)) - Y(c)); }
				continue;
			}
			const { x, y } = sd;
			const n = y.length;
			if (s.type === 'bar') {
				g.fillStyle = color;
				for (let i = 0; i < n; i++) { if (!okX(x[i]) || !okY(y[i])) continue; const x0 = X(x[i] - sd.bw / 2), x1 = X(x[i] + sd.bw / 2); const y0 = ylog ? rc.y + rc.h : Y(0); g.fillRect(x0, Math.min(y0, Y(y[i])), x1 - x0, Math.abs(Y(y[i]) - y0)); }
				continue;
			}
			if (s.type === 'stem') {
				g.strokeStyle = color; g.lineWidth = lw; g.setLineDash(dashFor(ls === 'none' ? '-' : ls, lw / P));
				g.beginPath();
				const yb = ylog ? rc.y + rc.h : Y(0);
				const step = Math.max(1, Math.floor(n / 4000));
				for (let i = 0; i < n; i += step) if (okX(x[i]) && okY(y[i])) { g.moveTo(X(x[i]), yb); g.lineTo(X(x[i]), Y(y[i])); }
				g.stroke();
				g.setLineDash([]); g.strokeStyle = '#000'; g.lineWidth = 0.8 * P;
				if (!ylog) { g.beginPath(); g.moveTo(rc.x, yb); g.lineTo(rc.x + rc.w, yb); g.stroke(); }
				if (s.marker) for (let i = 0; i < n; i += step) if (okX(x[i]) && okY(y[i])) drawMarker(g, s.marker, X(x[i]), Y(y[i]), (+s.ms || 6) * P, color, s.filled, Math.max(0.5, lw / 1.5));
				continue;
			}
			// 선·계단
			if (s.type !== 'scatter' && ls !== 'none') {
				g.strokeStyle = color; g.lineWidth = lw; g.setLineDash(dashFor(ls, lw / P)); g.lineJoin = 'round'; g.lineCap = ls === '-' ? 'round' : 'butt';
				g.beginPath();
				let mono = true;
				for (let i = 1; i < n && mono; i++) if (x[i] < x[i - 1]) mono = false;
				let pen = false;
				if (mono && n > rc.w * 4 && s.type === 'line') {
					// 픽셀 열마다 최소·최대만 (모양은 그대로, 빨리 그림)
					let col = -1, mn = 0, mx = 0, first = 0, last = 0;
					const flush = () => { if (col < 0) return; const px = rc.x + col + 0.5; if (!pen) { g.moveTo(px, first); pen = true; } else g.lineTo(px, first); g.lineTo(px, mn); g.lineTo(px, mx); g.lineTo(px, last); };
					for (let i = 0; i < n; i++) {
						if (!okX(x[i]) || !okY(y[i])) { flush(); col = -1; pen = false; continue; }
						const c = Math.floor(X(x[i]) - rc.x), py = Y(y[i]);
						if (c !== col) { flush(); col = c; mn = mx = first = last = py; }
						else { if (py < mn) mn = py; if (py > mx) mx = py; last = py; }
					}
					flush();
				} else {
					for (let i = 0; i < n; i++) {
						if (!okX(x[i]) || !okY(y[i])) { pen = false; continue; }
						const px = X(x[i]), py = Y(y[i]);
						if (!pen) { g.moveTo(px, py); pen = true; }
						else if (s.type === 'step') { g.lineTo(px, Y(y[i - 1])); g.lineTo(px, py); }
						else g.lineTo(px, py);
					}
				}
				g.stroke();
				g.setLineDash([]);
			}
			const mk = s.type === 'scatter' ? (s.marker || 'o') : s.marker;
			if (mk) {
				const step = s.type === 'scatter' ? Math.max(1, Math.floor(n / 50000)) : Math.max(1, Math.floor(n / 5000));
				for (let i = 0; i < n; i += step) if (okX(x[i]) && okY(y[i])) drawMarker(g, mk, X(x[i]), Y(y[i]), (+s.ms || 6) * P, color, s.filled, s.type === 'scatter' ? 0.5 * P : Math.max(0.5 * P, lw / 1.5));
			}
		}
		g.globalAlpha = 1;
		g.restore();

		// 테두리 · 눈금
		const axLw = f.axLw * P;
		g.strokeStyle = '#000'; g.lineWidth = axLw; g.setLineDash([]);
		g.beginPath();
		g.moveTo(rc.x, rc.y + rc.h); g.lineTo(rc.x + rc.w, rc.y + rc.h);
		g.moveTo(rc.x, rc.y); g.lineTo(rc.x, rc.y + rc.h);
		if (a.box) { g.moveTo(rc.x, rc.y); g.lineTo(rc.x + rc.w, rc.y); g.moveTo(rc.x + rc.w, rc.y); g.lineTo(rc.x + rc.w, rc.y + rc.h); }
		g.stroke();
		const dir = f.tickDir === 'in' ? -1 : 1;
		const mirror = f.mirror && a.box;
		const tick = (len, list, axis) => {
			g.beginPath();
			for (const v of list) {
				if (axis === 'x') { const x = X(v); if (x < rc.x - 0.5 || x > rc.x + rc.w + 0.5) continue; g.moveTo(x, rc.y + rc.h); g.lineTo(x, rc.y + rc.h + dir * len); if (mirror) { g.moveTo(x, rc.y); g.lineTo(x, rc.y - dir * len); } }
				else { const y = Y(v); if (y < rc.y - 0.5 || y > rc.y + rc.h + 0.5) continue; g.moveTo(rc.x, y); g.lineTo(rc.x - dir * len, y); if (mirror) { g.moveTo(rc.x + rc.w, y); g.lineTo(rc.x + rc.w + dir * len, y); } }
			}
			g.stroke();
		};
		g.lineWidth = axLw;
		tick(tickLen, d.xr.ticks, 'x'); tick(tickLen, d.yr.ticks, 'y');
		if (f.minor || d.xr.log) { g.lineWidth = axLw * 0.75; tick(tickLen * 0.57, d.xr.minor, 'x'); }
		if (f.minor || d.yr.log) { g.lineWidth = axLw * 0.75; tick(tickLen * 0.57, d.yr.minor, 'y'); }

		// 눈금 숫자 · 이름 자리
		const out = f.tickDir === 'out' ? tickLen : 0;
		d.xr.ticks.forEach((v, i) => { const el = d.xt.els[i]; const x = X(v); if (x < rc.x - 1 || x > rc.x + rc.w + 1) { el.style.display = 'none'; return; } place(el, x, rc.y + rc.h + out + tickPad, 0.5, 0); });
		d.yr.ticks.forEach((v, i) => { const el = d.yt.els[i]; const y = Y(v); if (y < rc.y - 1 || y > rc.y + rc.h + 1) { el.style.display = 'none'; return; } place(el, rc.x - out - tickPad, y, 1, 0.5); });
		const xth = d.hideX ? 0 : Math.max(0, ...d.xt.els.map((e) => (e.style.display === 'none' ? 0 : textSize(e).h)));
		const ytw = d.hideY ? 0 : Math.max(0, ...d.yt.els.map((e) => (e.style.display === 'none' ? 0 : textSize(e).w)));
		if (d.xt.off) place(d.xt.off, rc.x + rc.w, rc.y + rc.h + out + tickPad + xth, 1, 0);
		if (d.yt.off) place(d.yt.off, rc.x, rc.y - 2 * P, 0, 1);
		if (d.xlab) place(d.xlab, rc.x + rc.w / 2, rc.y + rc.h + out + (xth ? tickPad + xth : 0) + labelPad, 0.5, 0);
		if (d.ylab) {
			const z = textSize(d.ylab);
			const cx = rc.x - out - (ytw ? tickPad + ytw : 0) - labelPad - z.h / 2;
			d.ylab.style.left = (cx - z.w / 2) + 'px'; d.ylab.style.top = (rc.y + rc.h / 2 - z.h / 2) + 'px';
		}
		if (d.title) place(d.title, rc.x + rc.w / 2, rc.y - 6 * P - (d.leg && a.legend === 'outside top' ? d.leg.h + 4 * P : 0), 0.5, 1);

		// 색 막대
		if (d.cb) {
			const cb = d.cb;
			const bx = rc.x + rc.w + cb.padL;
			const grad = g.createLinearGradient(0, rc.y + rc.h, 0, rc.y);
			for (let i = 0; i <= 20; i++) { const c = cmapAt(cb.s.cmap, i / 20); grad.addColorStop(i / 20, `rgb(${c.map(Math.round)})`); }
			g.fillStyle = grad; g.fillRect(bx, rc.y, cb.bw, rc.h);
			g.lineWidth = axLw; g.strokeStyle = '#000'; g.strokeRect(bx, rc.y, cb.bw, rc.h);
			const CY = (v) => rc.y + rc.h - (v - cb.d.clo) / (cb.d.chi - cb.d.clo) * rc.h;
			g.beginPath();
			cb.ticks.forEach((v, i) => { const y = CY(v); if (y < rc.y - 0.5 || y > rc.y + rc.h + 0.5) { cb.els[i].style.display = 'none'; return; } g.moveTo(bx + cb.bw, y); g.lineTo(bx + cb.bw + tickLen, y); place(cb.els[i], bx + cb.bw + tickLen + tickPad, y, 0, 0.5); });
			g.stroke();
			if (cb.off) place(cb.off, bx, rc.y - 2 * P, 0, 1);
			if (cb.lab) { const z = textSize(cb.lab); const cx = bx + cb.bw + tickLen + tickPad + cb.tw + labelPad + z.h / 2; cb.lab.style.left = (cx - z.w / 2) + 'px'; cb.lab.style.top = (rc.y + rc.h / 2 - z.h / 2) + 'px'; }
		}

		// 범례
		if (d.leg) drawLegend(g, A, rc, d, P, X, Y);
	}

	function drawLegend(g, A, rc, d, P, X, Y) {
		const L = d.leg, a = A.a, f = st.fig;
		const pad = 0.5 * L.fsP;
		let lx, ly;
		const pos = (loc) => {
			const [v, h] = loc === 'center' ? ['center', 'center'] : loc.split(' ');
			const x = h === 'right' ? rc.x + rc.w - pad - L.w : h === 'center' ? rc.x + (rc.w - L.w) / 2 : rc.x + pad;
			const y = v === 'upper' ? rc.y + pad : v === 'lower' ? rc.y + rc.h - pad - L.h : rc.y + (rc.h - L.h) / 2;
			return [x, y];
		};
		if (a.legend === 'outside right') { lx = rc.x + rc.w + (d.cb ? d.cb.w : 0) + 4 * P; ly = rc.y; }
		else if (a.legend === 'outside top') { lx = rc.x + (rc.w - L.w) / 2; ly = rc.y - 4 * P - L.h; }
		else if (a.legend === 'best') {
			// matplotlib 'best' 와 같은 순서·같은 셈 (상자 안 점 + 상자를 지나는 선분)
			const cands = ['upper right', 'upper left', 'lower left', 'lower right', 'center right', 'center left', 'center right', 'lower center', 'upper center', 'center'];
			const pts = A.series.filter(({ d: sd }) => sd.x).map(({ s, d: sd }) => {
				const step = Math.max(1, Math.floor(sd.y.length / 4000));
				const xs = [], ys = [];
				for (let i = 0; i < sd.y.length; i += step) { xs.push(X(sd.x[i])); ys.push(Y(sd.y[i])); }
				return { xs, ys, w: step, line: s.type !== 'scatter' && seriesLs(s) !== 'none' };
			});
			const segHit = (x0, y0, x1, y1, bx, by, bw, bh) => {
				if (Math.max(x0, x1) < bx || Math.min(x0, x1) > bx + bw || Math.max(y0, y1) < by || Math.min(y0, y1) > by + bh) return false;
				const side = (px, py) => Math.sign((x1 - x0) * (py - y0) - (y1 - y0) * (px - x0));
				const a = side(bx, by), b = side(bx + bw, by), c = side(bx, by + bh), e = side(bx + bw, by + bh);
				return !(a === b && b === c && c === e && a !== 0);
			};
			let best = null, bestN = Infinity;
			for (const c of cands) {
				const [x, y] = pos(c);
				let cnt = 0;
				for (const p of pts) {
					for (let i = 0; i < p.xs.length; i++) {
						if (p.xs[i] >= x && p.xs[i] <= x + L.w && p.ys[i] >= y && p.ys[i] <= y + L.h) cnt += p.w;
						if (p.line && i && segHit(p.xs[i - 1], p.ys[i - 1], p.xs[i], p.ys[i], x, y, L.w, L.h)) cnt += p.w;
					}
				}
				if (cnt < bestN) { bestN = cnt; best = [x, y]; }
				if (!cnt) break;
			}
			[lx, ly] = best;
		} else [lx, ly] = pos(a.legend);
		if (f.legendFrame) {
			g.save();
			g.globalAlpha = 0.85; g.fillStyle = '#fff';
			roundRect(g, lx, ly, L.w, L.h, 0.2 * L.fsP); g.fill();
			g.globalAlpha = 1; g.strokeStyle = '#cccccc'; g.lineWidth = 0.8 * P; g.setLineDash([]);
			roundRect(g, lx, ly, L.w, L.h, 0.2 * L.fsP); g.stroke();
			g.restore();
		}
		let cx = lx + L.bp + 0.4 * L.fsP, cy = ly + L.bp + 0.2 * L.fsP;
		L.items.forEach(({ s }, i) => {
			const z = L.sizes[i];
			const midY = cy + L.rowH / 2;
			const color = seriesColor(s), lw = seriesLw(s) * P, ls = seriesLs(s);
			g.globalAlpha = isFinite(+s.alpha) ? +s.alpha : 1;
			if (s.type === 'bar' || s.type === 'hist') { g.fillStyle = color; g.fillRect(cx, midY - 0.35 * L.fsP, L.hl, 0.7 * L.fsP); }
			else {
				if (s.type !== 'scatter' && ls !== 'none') { g.strokeStyle = color; g.lineWidth = lw; g.setLineDash(dashFor(ls, lw / P)); g.beginPath(); g.moveTo(cx, midY); g.lineTo(cx + L.hl, midY); g.stroke(); g.setLineDash([]); }
				const mk = s.type === 'scatter' ? (s.marker || 'o') : s.marker;
				if (mk) drawMarker(g, mk, cx + L.hl / 2, midY, (+s.ms || 6) * P, color, s.filled, Math.max(0.5 * P, lw / 1.5));
			}
			g.globalAlpha = 1;
			const el = L.els[i];
			el.style.left = (cx + L.hl + L.hp) + 'px'; el.style.top = (midY - z.h / 2) + 'px';
			if (L.horiz) cx += L.hl + L.hp + z.w + L.cs;
			else cy += L.rowH + L.ls;
		});
	}
	function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }

	// ───────────────────────── 끌어서 범위 정하기 ─────────────────────────
	function hookStage() {
		const box = stage(), sel = $('ps-sel'), hov = $('ps-hover');
		let drag = null;
		const at = (e) => { const r = box.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
		const hit = (x, y) => (layoutCache || []).find((L) => x >= L.rect.x && x <= L.rect.x + L.rect.w && y >= L.rect.y && y <= L.rect.y + L.rect.h);
		const inv = (L, px, axis) => {
			const r = axis === 'x' ? L.xr : L.yr;
			const t = axis === 'x' ? (px - L.rect.x) / L.rect.w : 1 - (px - L.rect.y) / L.rect.h;
			const a = tr(r, r.lo), b = tr(r, r.hi);
			const v = a + t * (b - a);
			return r.log ? Math.pow(10, v) : v;
		};
		const fmt = (v) => (Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(3) : +v.toPrecision(5) + '');
		box.addEventListener('pointerdown', (e) => {
			const [x, y] = at(e);
			const L = hit(x, y);
			if (!L) return;
			drag = { L, x0: x, y0: y };
			box.setPointerCapture(e.pointerId);
		});
		box.addEventListener('pointermove', (e) => {
			const [x, y] = at(e);
			const L = hit(x, y);
			hov.textContent = L ? `${st.axes.length > 1 ? axName(L.k) + ' · ' : ''}x = ${fmt(inv(L, x, 'x'))}, y = ${fmt(inv(L, y, 'y'))}` : '';
			if (!drag) return;
			const R = drag.L.rect;
			const cx = Math.max(R.x, Math.min(R.x + R.w, x)), cy = Math.max(R.y, Math.min(R.y + R.h, y));
			Object.assign(sel.style, { display: 'block', left: Math.min(drag.x0, cx) + 'px', top: Math.min(drag.y0, cy) + 'px', width: Math.abs(cx - drag.x0) + 'px', height: Math.abs(cy - drag.y0) + 'px' });
		});
		box.addEventListener('pointerup', (e) => {
			if (!drag) return;
			const [x, y] = at(e);
			const { L, x0, y0 } = drag;
			drag = null; sel.style.display = 'none';
			const R = L.rect;
			const cx = Math.max(R.x, Math.min(R.x + R.w, x)), cy = Math.max(R.y, Math.min(R.y + R.h, y));
			const a = st.axes[L.k];
			const round = (v) => +v.toPrecision(4);
			if (Math.abs(cx - x0) > 6) { const p = [inv(L, Math.min(x0, cx), 'x'), inv(L, Math.max(x0, cx), 'x')].map(round); a.xlim = p; }
			if (Math.abs(cy - y0) > 6) { const p = [inv(L, Math.max(y0, cy), 'y'), inv(L, Math.min(y0, cy), 'y')].map(round); a.ylim = p; }
			if (Math.abs(cx - x0) > 6 || Math.abs(cy - y0) > 6) { curAx = L.k; renderAxes(); update(); }
		});
		box.addEventListener('dblclick', (e) => {
			const [x, y] = at(e);
			const L = hit(x, y);
			if (!L) return;
			st.axes[L.k].xlim = ['', '']; st.axes[L.k].ylim = ['', ''];
			curAx = L.k; renderAxes(); update();
		});
		box.addEventListener('pointerleave', () => { hov.textContent = ''; });
	}

	// ───────────────────────── 코드 만들기 ─────────────────────────
	const PY_RESERVED = new Set(['np', 'plt', 'pd', 'h5py', 'loadmat', 'fig', 'ax', 'axs', 'cb', 'pc', 'im', 'mat73', 'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while', 'with', 'yield', 'print', 'len', 'range', 'list', 'dict', 'str', 'type', 'max', 'min', 'abs', 'sum', 'id', 'map', 'filter']);
	const M_RESERVED = new Set(['ax', 'fig', 'tl', 'cb', 'S', 'T', 'M', 'i', 'j', 'pi', 'eps', 'end', 'function', 'if', 'else', 'elseif', 'for', 'while', 'switch', 'case', 'otherwise', 'try', 'catch', 'return', 'break', 'continue', 'global', 'persistent', 'parfor', 'spmd', 'classdef', 'methods', 'properties', 'events', 'plot', 'figure', 'title', 'xlabel', 'ylabel', 'legend', 'load', 'max', 'min', 'abs', 'sum', 'size', 'length', 'numel', 'zeros', 'ones', 'cmap', 'axs', 'ans', 'line', 'image', 'text', 'axis', 'grid', 'box', 'hold', 'colormap', 'colorbar', 'real', 'imag', 'angle', 'log10', 'histogram']);

	function codegen() {
		const f = st.fig;
		const warn = [];
		const live = st.series.filter((s) => getVar(s.y));
		const usedVars = new Map(); // vkey → {v, py, m}
		const fileIds = new Map();
		const takenPy = new Set(), takenM = new Set();
		const ident = (raw, taken, reserved) => {
			let n = String(raw).replace(/[{(]/g, '_').replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') || 'v';
			if (/^\d/.test(n)) n = 'v' + n;
			if (n.length > 40) n = n.slice(0, 40);
			let k = n, i = 2;
			while (taken.has(k) || reserved.has(k)) k = n + '_' + i++;
			taken.add(k);
			return k;
		};
		const fileOrder = [];
		const useVar = (ref) => {
			const v = getVar(ref);
			if (!v) return null;
			const key = vk(v.file, v.key);
			if (!usedVars.has(key)) {
				const fobj = fileOf(v);
				if (!fileIds.has(v.file)) { fileIds.set(v.file, fileIds.size); fileOrder.push(fobj); }
				const nm = v.key.replace(/^.*\//, (m) => m).replace(/\//g, '_');
				usedVars.set(key, { v, f: fobj, py: ident(nm, takenPy, PY_RESERVED), m: ident(nm, takenM, M_RESERVED) });
			}
			return usedVars.get(key);
		};
		for (const s of live) for (const w of ['y', 'x', 'xv', 'yv']) if (s[w]) useVar(s[w]);
		const multi = fileOrder.length > 1;
		const fid = (fobj, base) => base + (multi ? fileIds.get(fobj.name) + 1 : '');

		// 파이썬 쪽 이름 조각
		const pyStr = (s) => {
			s = String(s);
			if (!s.includes('\\') && !s.includes("'")) return "'" + s + "'";
			if (!s.includes("'") && !/\\$/.test(s)) return "r'" + s + "'";
			if (!s.includes('"') && !/\\$/.test(s)) return 'r"' + s + '"';
			return "'" + s.replace(/\\/g, '\\\\').replace(/'/g, "\\'") + "'";
		};
		const mStr = (s) => "'" + String(s).replace(/'/g, "''") + "'";
		const num = (v) => { const x = +v; return Number.isInteger(x) ? String(x) : String(+x.toPrecision(6)); };
		const rgbM = (hex) => '[' + [1, 3, 5].map((i) => +(parseInt(hex.substr(i, 2), 16) / 255).toFixed(3)).join(' ') + ']';

		// ── 데이터 읽기 ──
		const py = [], m = [];
		const pyImp = new Set(['import numpy as np', 'import matplotlib.pyplot as plt']);
		const pyLoad = [], mLoad = [];
		let needMat73 = false;
		for (const fobj of fileOrder) {
			const fn = fobj.name;
			if (fobj.fmt === 'mat') { pyImp.add('from scipy.io import loadmat'); pyLoad.push(`${fid(fobj, 'd')} = loadmat(${pyStr(fn)}, simplify_cells=True)`); mLoad.push(`${fid(fobj, 'S')} = load(${mStr(fn)});`); }
			else if (fobj.fmt === 'mat73') { pyImp.add('import h5py'); needMat73 = true; pyLoad.push(`${fid(fobj, 'f')} = h5py.File(${pyStr(fn)}, 'r')  # MATLAB v7.3 = HDF5`); mLoad.push(`${fid(fobj, 'S')} = load(${mStr(fn)});`); }
			else if (fobj.fmt === 'npz') { pyLoad.push(`${fid(fobj, 'd')} = np.load(${pyStr(fn)})`); const dir = fn.replace(/\.npz$/i, '') + '_npz'; mLoad.push(`unzip(${mStr(fn)}, ${mStr(dir)});  % npz 는 .npy 묶음 — 풀어서 readNPY 로 읽어요`); warn.push('MATLAB 에서 .npy 를 읽으려면 npy-matlab 의 readNPY 가 필요해요 (github.com/kwikteam/npy-matlab).'); }
			else if (fobj.fmt === 'npy') { warn.push('MATLAB 에서 .npy 를 읽으려면 npy-matlab 의 readNPY 가 필요해요 (github.com/kwikteam/npy-matlab).'); }
			else if (fobj.fmt === 'csv') {
				const md = fobj.meta || {};
				const sep = md.delim === 'ws' ? null : md.delim;
				if (md.header) { pyImp.add('import pandas as pd'); pyLoad.push(`${fid(fobj, 'df')} = pd.read_csv(${pyStr(fn)}${sep === null ? ", sep=r'\\s+'" : sep !== ',' ? ', sep=' + pyStr(sep === '\t' ? '\\t' : sep) : ''}, comment='#')`); mLoad.push(`${fid(fobj, 'T')} = readtable(${mStr(fn)}, 'VariableNamingRule', 'preserve');`); }
				else { pyLoad.push(`${fid(fobj, 'M')} = np.loadtxt(${pyStr(fn)}${sep ? ', delimiter=' + pyStr(sep === '\t' ? '\\t' : sep) : ''}, comments=['#', '%'])`); mLoad.push(`${fid(fobj, 'M')} = readmatrix(${mStr(fn)});`); }
			} else if (fobj.fmt === 'h5') { pyImp.add('import h5py'); pyLoad.push(`${fid(fobj, 'f')} = h5py.File(${pyStr(fn)}, 'r')`); }
		}
		const uniq = (a) => [...new Set(a)];
		for (const w of uniq(warn)) void w;
		// 변수 하나씩
		const pyAssign = [], mAssign = [];
		for (const u of usedVars.values()) {
			const { v, f: fobj } = u;
			const acc = v.acc || [{ t: 'var', k: v.name }];
			let pe = '', me = '';
			if (fobj.fmt === 'mat' || fobj.fmt === 'mat73') {
				pe = fobj.fmt === 'mat' ? fid(fobj, 'd') : fid(fobj, 'f');
				me = fid(fobj, 'S');
				for (const a of acc) {
					if (a.t === 'var' || a.t === 'field') { pe += `[${pyStr(a.k).replace(/^r/, '')}]`; me += '.' + a.k; }
					else if (a.t === 'cell') { const ns = a.dims.map((d, i) => [d, i]).filter(([d]) => d > 1).map(([, i]) => a.sub[i]); if (ns.length) pe += `[${ns.join(', ')}]`; me += `{${a.lin + 1}}`; }
					else if (a.t === 'elem') { const ns = a.dims.map((d, i) => [d, i]).filter(([d]) => d > 1).map(([, i]) => a.sub[i]); if (ns.length) pe += `[${ns.join(', ')}]`; me += `(${a.lin + 1})`; }
				}
				if (fobj.fmt === 'mat73') pe = `mat73(${pe})`;
			} else if (fobj.fmt === 'npy') { pe = `np.load(${pyStr(fobj.name)})`; me = `readNPY(${mStr(fobj.name)})`; }
			else if (fobj.fmt === 'npz') { pe = `${fid(fobj, 'd')}[${pyStr(v.name).replace(/^r/, '')}]`; me = `readNPY(fullfile(${mStr(fobj.name.replace(/\.npz$/i, '') + '_npz')}, ${mStr(v.name + '.npy')}))`; }
			else if (fobj.fmt === 'csv') {
				const a = acc[0];
				if (a.header) { pe = `${fid(fobj, 'df')}[${pyStr(a.name).replace(/^r/, '')}].to_numpy()`; me = `${fid(fobj, 'T')}.(${mStr(a.name)})`; }
				else { pe = `${fid(fobj, 'M')}[:, ${a.j}]`; me = `${fid(fobj, 'M')}(:, ${a.j + 1})`; }
			} else if (fobj.fmt === 'h5') {
				const path = acc[0].path;
				pe = `${fid(fobj, 'f')}[${pyStr(path).replace(/^r/, '')}][()]`;
				const nd = v.dims.length;
				me = nd === 2 ? `h5read(${mStr(fobj.name)}, ${mStr(path)}).'` : nd > 2 ? `permute(h5read(${mStr(fobj.name)}, ${mStr(path)}), ${nd}:-1:1)` : `h5read(${mStr(fobj.name)}, ${mStr(path)})`;
				if (nd > 1) mAssign.push(`% HDF5 는 MATLAB 에서 차원이 거꾸로 읽혀서 뒤집어요`);
			}
			pyAssign.push(`${u.py} = ${pe}`);
			mAssign.push(`${u.m} = ${me};`);
		}

		// 고른 부분 + 바꾸기 → 식
		const squeezes = (fobj) => fobj.fmt === 'mat' || fobj.fmt === 'mat73';
		const pySel = (u, ref, free) => {
			const { v, f: fobj } = u;
			if (fobj.fmt === 'csv') return u.py;
			const dimsIdx = squeezes(fobj) ? nonSingle(v.dims) : v.dims.map((_, i) => i);
			const parts = dimsIdx.map((i) => (free.includes(i) ? ':' : String((ref.idx && ref.idx[i]) || 0)));
			let e = parts.every((p) => p === ':') ? u.py : `${u.py}[${parts.join(', ')}]`;
			if (free.length === 2 && free[0] > free[1]) e += '.T';
			return e;
		};
		const mSel = (u, ref, free) => {
			const { v, f: fobj } = u;
			if (fobj.fmt === 'csv') return u.m;
			const parts = v.dims.map((d, i) => (free.includes(i) ? ':' : d === 1 ? '1' : String(((ref.idx && ref.idx[i]) || 0) + 1)));
			const allFree = v.dims.every((d, i) => free.includes(i) || d === 1);
			let e = allFree ? u.m : `${u.m}(${parts.join(', ')})`;
			if (free.length === 2 && free[0] > free[1]) e = (allFree ? e : '(' + e + ')') + ".'";
			if (free.length === 2 && v.dims.length > 2 && !allFree) e = `squeeze(${e})`;
			if (free.length === 1 && v.dims.length > 2 && !allFree) e = `squeeze(${e})`;
			return e;
		};
		const pyTf = (e, tf, k) => {
			const w = { none: e, real: `np.real(${e})`, imag: `np.imag(${e})`, abs: `np.abs(${e})`, db20: `20 * np.log10(np.abs(${e}))`, db10: `10 * np.log10(${e})`, angle: `np.angle(${e})`, deg: `np.degrees(np.angle(${e}))`, unwrap: `np.unwrap(np.angle(${e}))` }[tf] || e;
			return k != null && k !== '' && +k !== 1 ? `${num(k)} * ${/^[\w.[\]:, ]+$/.test(w) || /^np\.\w+\(.*\)$/.test(w) ? w : '(' + w + ')'}` : w;
		};
		const mTf = (e, tf, k) => {
			const w = { none: e, real: `real(${e})`, imag: `imag(${e})`, abs: `abs(${e})`, db20: `20*log10(abs(${e}))`, db10: `10*log10(${e})`, angle: `angle(${e})`, deg: `rad2deg(angle(${e}))`, unwrap: `unwrap(angle(${e}))` }[tf] || e;
			return k != null && k !== '' && +k !== 1 ? `${num(k)}*${/^[\w.(),: ']+$/.test(w) && !/[+\-*/]/.test(w) ? w : '(' + w + ')'}` : w;
		};
		const exprs = (ref, image) => {
			const u = useVar(ref);
			if (!u) return null;
			const free = image ? [ref.rd ?? 0, ref.cd ?? 1] : [ref.dim ?? 0];
			return { py: pyTf(pySel(u, ref, free), ref.tf, ref.k), m: mTf(mSel(u, ref, free), ref.tf, ref.k), u };
		};

		// ── 경고 ──
		const allText = [f.out, ...st.axes.flatMap((a) => [a.title, a.xlabel, a.ylabel]), ...live.map((s) => s.label), ...live.map((s) => s.cbarLabel)].filter(Boolean);
		const ko = allText.some(hasKo);
		if (f.tex === 'usetex') {
			const bad = allText.filter((t) => /(^|[^\\])[_%&#]/.test(t.replace(/\$[^$]*\$/g, '')));
			if (bad.length) warn.push(`진짜 LaTeX 모드에선 $ 밖의 _ % & # 앞에 \\ 를 붙여야 해요: "${bad[0]}"`);
			warn.push('진짜 LaTeX 모드는 컴퓨터에 TeX(MacTeX·TeX Live·MiKTeX)가 깔려 있어야 파이썬에서 그려져요. 없으면 "$…$ 사이만 수식" 을 고르세요.');
			if (ko) warn.push('진짜 LaTeX 모드에선 한글이 안 나와요 (kotex 설정이 따로 필요). 한글을 쓰려면 "$…$ 사이만 수식" 을 고르세요.');
		}
		if (ko && (f.font === 'cm' || f.tex === 'usetex')) warn.push('MATLAB 의 LaTeX 해석기는 한글을 못 그려요 — 한글이 들어간 이름은 MATLAB 에서 빈칸이 될 수 있어요.');
		if (ko) warn.push('한글이 있어서 파이썬 코드에 한글 글꼴(맑은 고딕·AppleGothic·나눔고딕)을 같이 넣었어요.');
		for (const s of live) {
			const v = getVar(s.y);
			if (v.im && s.y.tf === 'none') warn.push(`"${v.key}" 는 복소수예요 — 그대로 그리면 실수부만 나와요. 크기나 dB 로 바꿔 보세요.`);
			const d = seriesData(s);
			if (d && d.bad) warn.push(`${SERIES_TYPES[s.type]} "${v.key}": X 와 Y 길이가 달라요 — 미리보기는 짧은 쪽에 맞췄지만 코드는 오류가 나요.`);
			if (s.type === 'image' && !CMAP_PY[s.cmap]) warn.push(`색 지도 ${s.cmap} 는 matplotlib 에 없어서 비슷한 색을 코드에 직접 넣었어요.`);
			if (s.type === 'image' && !CMAP_M[s.cmap]) warn.push(`색 지도 ${s.cmap} 는 MATLAB 에 없어서 비슷한 색을 코드에 직접 넣었어요.`);
		}
		st.axes.forEach((a, k) => {
			for (const w of ['x', 'y']) {
				if (a[w + 'scale'] !== 'log') continue;
				const neg = st.series.filter((s) => s.ax === k && getVar(s.y)).some((s) => { const d = seriesData(s); const arr = d && (w === 'x' ? d.x : d.y); return arr && arr.some((q) => q <= 0); });
				if (neg) warn.push(`${axName(k)}: 로그 ${w.toUpperCase()} 축인데 0 이하 값이 있어 그 점은 빠져요.`);
			}
		});

		// ── 파이썬 ──
		const fontRc = [];
		const koList = ko ? ', *KO' : '';
		if (f.tex === 'usetex') {
			fontRc.push(`'text.usetex': True,`);
			const pre = { times: '\\usepackage{mathptmx}', helvetica: '\\usepackage{helvet}\\renewcommand{\\familydefault}{\\sfdefault}', dejavu: '\\usepackage{helvet}\\renewcommand{\\familydefault}{\\sfdefault}', cm: '' }[f.font];
			fontRc.push(`'font.family': '${f.font === 'helvetica' || f.font === 'dejavu' ? 'sans-serif' : 'serif'}',`);
			fontRc.push(`'text.latex.preamble': r'\\usepackage{amsmath}${pre}',`);
		} else if (f.font === 'cm') {
			fontRc.push(`'font.family': ['serif'${koList}],`, `'font.serif': ['cmr10', 'Computer Modern Roman', 'CMU Serif'],`, `'mathtext.fontset': 'cm',`, `'axes.formatter.use_mathtext': True,`, `'axes.unicode_minus': False,  # cmr10 에는 − 글자가 없어서`);
		} else if (f.font === 'times') {
			fontRc.push(`'font.family': ['serif'${koList}],`, `'font.serif': ['Times New Roman', 'Times', 'STIXGeneral', 'DejaVu Serif'],`, `'mathtext.fontset': 'stix',`);
		} else if (f.font === 'helvetica') {
			fontRc.push(`'font.family': ['sans-serif'${koList}],`, `'font.sans-serif': ['Helvetica', 'Arial', 'DejaVu Sans'],`, `'mathtext.fontset': 'stixsans',`);
		} else {
			fontRc.push(`'font.family': ['DejaVu Sans'${koList}],`, `'mathtext.fontset': 'dejavusans',`);
		}
		if (ko && f.font !== 'cm') fontRc.push(`'axes.unicode_minus': False,  # 한글 글꼴엔 − 가 없을 때가 있어서`);
		if (f.tex === 'none') fontRc.push(`'text.parse_math': False,  # $ 를 수식으로 안 읽음`);
		const rc = [
			...fontRc,
			`'font.size': ${num(f.fs)},`,
			`'axes.titlesize': ${num(f.fsTitle)}, 'axes.titleweight': '${f.titleBold ? 'bold' : 'normal'}',`,
			`'axes.labelsize': ${num(f.fs)},`,
			`'xtick.labelsize': ${num(f.fsTick)}, 'ytick.labelsize': ${num(f.fsTick)},`,
			`'legend.fontsize': ${num(f.fsLegend)}, 'legend.frameon': ${f.legendFrame ? 'True' : 'False'},`,
			`'lines.linewidth': ${num(f.lw)},`,
			`'axes.linewidth': ${num(f.axLw)},`,
			`'xtick.major.width': ${num(f.axLw)}, 'ytick.major.width': ${num(f.axLw)},`,
			`'xtick.minor.width': ${num(f.axLw * 0.75)}, 'ytick.minor.width': ${num(f.axLw * 0.75)},`,
			`'xtick.direction': '${f.tickDir}', 'ytick.direction': '${f.tickDir}',`,
		];
		if (f.mirror) rc.push(`'xtick.top': True, 'ytick.right': True,  # 위·오른쪽에도 눈금`);
		if (f.limits === 'ticks') rc.push(`'axes.autolimit_mode': 'round_numbers',  # 범위를 눈금에 맞춰 반올림`, `'axes.xmargin': 0, 'axes.ymargin': 0,`);
		if (f.limits === 'tight') rc.push(`'axes.xmargin': 0, 'axes.ymargin': 0,  # 데이터에 딱 맞춤`);
		rc.push(`'savefig.dpi': ${num(f.dpi)},`);

		py.push('# 그래프 스튜디오에서 만든 코드 — https://smjgallery.kr/tools/plot/');
		py.push(...[...pyImp].sort((a, b) => (a.startsWith('import') === b.startsWith('import') ? 0 : a.startsWith('import') ? -1 : 1)));
		if (ko) pyImp.add('from matplotlib import font_manager');
		py.push('');
		if (ko) py.push('', '# 한글 글꼴: 이 컴퓨터에 있는 것 하나 (Windows 맑은 고딕 · macOS AppleGothic · 리눅스 나눔고딕)', "_have = {f.name for f in font_manager.fontManager.ttflist}", "KO = [f for f in ['Malgun Gothic', 'AppleGothic', 'Apple SD Gothic Neo', 'NanumGothic', 'Noto Sans CJK KR'] if f in _have][:1]", '');
		if (needMat73) py.push('', 'def mat73(ds):', '    """MATLAB v7.3 변수 → numpy (차원 순서를 MATLAB 과 같게, 길이 1 인 차원은 뺌)"""', '    a = ds[()]', "    if a.dtype.names and 'real' in a.dtype.names:", "        a = a['real'] + 1j * a['imag']", '    return np.squeeze(a.T)', '');
		if (pyLoad.length || pyAssign.length) py.push('# ── 1. 데이터 읽기 ──', ...pyLoad, ...pyAssign, '');
		py.push('# ── 2. 글꼴 · 선 모양 ──', 'plt.rcParams.update({', ...rc.map((l) => '    ' + l), '})', '');
		py.push('# ── 3. 그리기 ──');
		const single = f.rows * f.cols === 1;
		const shareArg = (f.sharex ? ', sharex=True' : '') + (f.sharey ? ', sharey=True' : '');
		py.push(single ? `fig, ax = plt.subplots(figsize=(${num(f.w)}, ${num(f.h)}), layout='constrained')` : `fig, axs = plt.subplots(${f.rows}, ${f.cols}, figsize=(${num(f.w)}, ${num(f.h)})${shareArg}, layout='constrained', squeeze=False)`);

		// ── MATLAB ──
		m.push('% 그래프 스튜디오에서 만든 코드 — https://smjgallery.kr/tools/plot/');
		if (mLoad.length || mAssign.length) m.push('%% 1. 데이터 읽기', ...mLoad, ...mAssign, '');
		m.push('%% 2. 그리기');
		m.push(`fig = figure('Units', 'inches', 'Position', [1 1 ${num(f.w)} ${num(f.h)}], 'Color', 'w');`);
		m.push(`tl = tiledlayout(fig, ${f.rows}, ${f.cols}, 'TileSpacing', 'compact', 'Padding', 'compact');`);
		const mFont = { times: 'Times New Roman', helvetica: 'Helvetica', dejavu: 'DejaVu Sans', cm: 'CMU Serif' }[f.font];
		const mAllLatex = f.font === 'cm' || f.tex === 'usetex';
		const mInterp = (s) => (f.tex === 'none' ? 'none' : mAllLatex || /\$/.test(s) ? 'latex' : /\\/.test(s) ? 'tex' : 'none');
		// LaTeX 해석기로 그릴 땐 $ 밖의 _ % & # 를 글자로 (안 그러면 MATLAB 이 오류 글자를 그대로 보여 줌)
		const mText = (s, interp) => {
			if ((interp || mInterp(s)) !== 'latex') return s;
			return String(s).split(/(?<!\\)(\$[^$]*\$)/).map((part) => (part.startsWith('$') ? part : part.replace(/(^|[^\\])([_%&#])/g, '$1\\$2'))).join('');
		};
		const mMarker = (mk) => (mk === 'D' ? 'd' : mk);
		const axHandles = [];
		const lsName = (ls) => (ls === 'none' ? "'none'" : `'${ls}'`);
		const cmapPy = (s) => (CMAP_PY[s.cmap] ? `'${s.cmap}'` : `LinearSegmentedColormap.from_list('${s.cmap}', [${CMAPS[s.cmap].match(/.{6}/g).map((h) => "'#" + h + "'").join(', ')}])`);
		const cmapM = (s) => (CMAP_M[s.cmap] ? `${s.cmap}(256)` : `interp1(linspace(0, 1, 11), [${cmapRGB[s.cmap].map((c) => c.map((v) => +(v / 255).toFixed(3)).join(' ')).join('; ')}], linspace(0, 1, 256))`);
		let sn = 0;

		st.axes.forEach((a, k) => {
			const r = Math.floor(k / f.cols), c = k % f.cols;
			const sers = live.filter((s) => s.ax === k);
			const A = single ? 'ax' : 'ax';
			py.push('');
			if (!single) py.push(`ax = axs[${r}, ${c}]`);
			const mh = `ax${st.axes.length > 1 ? k + 1 : ''}`;
			axHandles.push(mh);
			m.push('');
			m.push(`${mh} = nexttile(tl); hold(${mh}, 'on');`);
			let hasLabel = false;
			const legLabs = sers.filter((s) => s.label && s.type !== 'image').map((s) => s.label);
			const legLi = f.tex === 'none' ? 'none' : mAllLatex || legLabs.some((x) => x.includes('$')) ? 'latex' : legLabs.some((x) => x.includes('\\')) ? 'tex' : 'none';
			for (const s of sers) {
				sn++;
				const color = seriesColor(s), lw = seriesLw(s), ls = seriesLs(s);
				const alpha = isFinite(+s.alpha) && +s.alpha < 1 ? +s.alpha : null;
				const lab = s.label && s.type !== 'image' ? s.label : '';
				if (lab) hasLabel = true;
				if (s.type === 'image') {
					const Z = exprs(s.y, true);
					const xv = s.xv ? exprs(s.xv) : null, yv = s.yv ? exprs(s.yv) : null;
					const zp = `Z${sn}`, zm = `Z${sn}`;
					py.push(`${zp} = ${Z.py}`);
					m.push(`${zm} = ${Z.m};`);
					if (!CMAP_PY[s.cmap]) pyImp.add('from matplotlib.colors import LinearSegmentedColormap');
					const vlim = (s.clo !== '' ? `, vmin=${num(s.clo)}` : '') + (s.chi !== '' ? `, vmax=${num(s.chi)}` : '');
					if (xv || yv) {
						py.push(`pc = ${A}.pcolormesh(${xv ? xv.py : `np.arange(${zp}.shape[1])`}, ${yv ? yv.py : `np.arange(${zp}.shape[0])`}, ${zp}, shading='nearest', cmap=${cmapPy(s)}${vlim}, rasterized=True)`);
						m.push(`imagesc(${mh}, ${xv ? xv.m : `1:size(${zm}, 2)`}, ${yv ? yv.m : `1:size(${zm}, 1)`}, ${zm});`);
					} else {
						py.push(`pc = ${A}.imshow(${zp}, origin='lower', aspect='auto', interpolation='nearest', cmap=${cmapPy(s)}${vlim})`);
						m.push(`imagesc(${mh}, ${zm});`);
					}
					m.push(`set(${mh}, 'YDir', 'normal'); colormap(${mh}, ${cmapM(s)});`);
					if (s.clo !== '' || s.chi !== '') m.push(`${mh}.CLim = [${s.clo !== '' ? num(s.clo) : `min(${zm}(:))`} ${s.chi !== '' ? num(s.chi) : `max(${zm}(:))`}];`);
					if (s.cbar) {
						py.push(`cb = fig.colorbar(pc, ax=${A}${s.cbarLabel ? ', label=' + pyStr(s.cbarLabel) : ''})`);
						m.push(`cb = colorbar(${mh});` + (s.cbarLabel ? ` cb.Label.String = ${mStr(mText(s.cbarLabel))}; cb.Label.Interpreter = '${mInterp(s.cbarLabel)}';` : ''));
						if (s.cbarLabel && mInterp(s.cbarLabel) !== 'latex' && mFont) m.push(`cb.Label.FontName = '${mFont}';`);
					}
					continue;
				}
				const Y = exprs(s.y);
				const X = s.x && s.type !== 'hist' ? exprs(s.x) : null;
				const simple = (e) => /^[A-Za-z_]\w*$/.test(e);
				let yP = Y.py, yM = Y.m, xP = X ? X.py : null, xM = X ? X.m : null;
				if (!simple(yP)) { py.push(`y${sn} = ${yP}`); yP = `y${sn}`; }
				if (xP && !simple(xP)) { py.push(`x${sn} = ${xP}`); xP = `x${sn}`; }
				if (!simple(yM)) { m.push(`y${sn} = ${yM};`); yM = `y${sn}`; }
				if (xM && !simple(xM)) { m.push(`x${sn} = ${xM};`); xM = `x${sn}`; }
				const mk = s.type === 'scatter' ? (s.marker || 'o') : s.marker;
				const ms = +s.ms || 6;
				const mfc = s.filled ? null : 'none';
				const pyLab = lab ? `, label=${pyStr(lab)}` : '';
				const mLab = lab ? `, 'DisplayName', ${mStr(mText(lab, legLi))}` : '';
				const pyA = alpha != null ? `, alpha=${num(alpha)}` : '';
				const xIdxPy = `np.arange(len(${yP}))`, xIdxM = `1:numel(${yM})`;
				if (s.type === 'line' || s.type === 'step') {
					const mkPy = mk ? `, marker='${mk}', ms=${num(ms)}${mfc ? ", mfc='none'" : ''}` : '';
					const fn = s.type === 'step' ? 'step' : 'plot';
					py.push(`${A}.${fn}(${xP ? xP + ', ' : s.type === 'step' ? xIdxPy + ', ' : ''}${yP}, color='${color}', lw=${num(lw)}, ls=${lsName(ls)}${mkPy}${s.type === 'step' ? ", where='post'" : ''}${pyA}${pyLab})`);
					const mkM = mk ? `, 'Marker', '${mMarker(mk)}', 'MarkerSize', ${num(ms)}, 'MarkerFaceColor', ${s.filled ? rgbM(color) : "'none'"}` : '';
					const h = `${s.type === 'step' ? 'stairs' : 'plot'}(${mh}, ${xM ? xM + ', ' : ''}${yM}, 'Color', ${rgbM(color)}, 'LineWidth', ${num(lw)}, 'LineStyle', ${lsName(ls)}${mkM}${mLab});`;
					m.push(alpha != null ? `p = ${h} p.Color(4) = ${num(alpha)};  % 투명도 (숨은 기능)` : h);
				} else if (s.type === 'scatter') {
					py.push(`${A}.scatter(${xP || xIdxPy}, ${yP}, s=${num(ms * ms)}, marker='${mk}', ${s.filled ? `color='${color}'` : `facecolors='none', edgecolors='${color}'`}, linewidths=${num(Math.max(0.5, lw / 2))}${pyA}${pyLab})`);
					m.push(`scatter(${mh}, ${xM || xIdxM}, ${yM}, ${num(ms * ms)}, ${rgbM(color)}, '${mMarker(mk)}'${s.filled ? ", 'filled'" : ''}${alpha != null ? `, 'MarkerFaceAlpha', ${num(alpha)}, 'MarkerEdgeAlpha', ${num(alpha)}` : ''}${mLab});`);
				} else if (s.type === 'stem') {
					py.push(`ml, sl, bl = ${A}.stem(${xP ? xP + ', ' : ''}${yP}, basefmt='k-'${pyLab})`);
					py.push(`plt.setp(sl, color='${color}', lw=${num(lw)}, ls=${lsName(ls === 'none' ? '-' : ls)}); plt.setp(ml, color='${color}', marker='${mk || 'None'}', ms=${num(ms)}${mfc ? ", mfc='none'" : ''}); plt.setp(bl, lw=0.8)`);
					m.push(`stem(${mh}, ${xM ? xM + ', ' : ''}${yM}, 'Color', ${rgbM(color)}, 'LineWidth', ${num(lw)}, 'LineStyle', ${lsName(ls === 'none' ? '-' : ls)}, 'Marker', '${mk ? mMarker(mk) : 'none'}', 'MarkerSize', ${num(ms)}, 'MarkerFaceColor', ${s.filled ? rgbM(color) : "'none'"}${mLab});`);
				} else if (s.type === 'bar') {
					py.push(`${A}.bar(${xP || xIdxPy}, ${yP}, width=${num(s.width)}${xP ? ` * np.min(np.diff(np.unique(${xP})), initial=1)` : ''}, color='${color}'${pyA}${pyLab})`);
					m.push(`bar(${mh}, ${xM ? xM + ', ' : ''}${yM}, ${num(s.width)}, 'FaceColor', ${rgbM(color)}, 'EdgeColor', 'none'${alpha != null ? `, 'FaceAlpha', ${num(alpha)}` : ''}${mLab});`);
				} else if (s.type === 'hist') {
					py.push(`${A}.hist(${yP}[np.isfinite(${yP})], bins=${Math.round(s.bins) || 30}, color='${color}', edgecolor='white', linewidth=0.5${pyA}${pyLab})`);
					m.push(`histogram(${mh}, ${yM}, linspace(min(${yM}), max(${yM}), ${(Math.round(s.bins) || 30) + 1}), 'FaceColor', ${rgbM(color)}, 'EdgeColor', 'w', 'FaceAlpha', ${num(alpha != null ? alpha : 1)}${mLab});`);
				}
			}
			// 축 꾸미기 — 파이썬
			const setArgs = [];
			if (a.title) setArgs.push(`title=${pyStr(a.title)}`);
			if (a.xlabel) setArgs.push(`xlabel=${pyStr(a.xlabel)}`);
			if (a.ylabel) setArgs.push(`ylabel=${pyStr(a.ylabel)}`);
			if (a.xscale === 'log') setArgs.push(`xscale='log'`);
			if (a.yscale === 'log') setArgs.push(`yscale='log'`);
			if (setArgs.length) py.push(`${A}.set(${setArgs.join(', ')})`);
			const lim = (l) => [l[0] !== '' && l[0] != null ? num(l[0]) : 'None', l[1] !== '' && l[1] != null ? num(l[1]) : 'None'];
			const xl = lim(a.xlim), yl = lim(a.ylim);
			if (a.tightx && xl[0] === 'None' && xl[1] === 'None') py.push(`${A}.autoscale(axis='x', tight=True)`);
			if (xl[0] !== 'None' || xl[1] !== 'None') py.push(`${A}.set_xlim(${xl[0]}, ${xl[1]})`);
			if (yl[0] !== 'None' || yl[1] !== 'None') py.push(`${A}.set_ylim(${yl[0]}, ${yl[1]})`);
			if (a.equal) py.push(`${A}.set_aspect('equal', adjustable='box')`);
			if (f.minor || a.grid === 'both') py.push(`${A}.minorticks_on()`);
			if (a.grid !== 'none') {
				py.push(`${A}.grid(True, which='major', ls='${f.gridStyle}', lw=0.6, color='0.78')`);
				if (a.grid === 'both') py.push(`${A}.grid(True, which='minor', ls='${f.gridStyle}', lw=0.4, color='0.89')`);
				py.push(`${A}.set_axisbelow(True)`);
			}
			if (!a.box) py.push(`${A}.spines[['top', 'right']].set_visible(False)`);
			if (!a.box && f.mirror) py.push(`${A}.tick_params(top=False, right=False)`);
			if (hasLabel && a.legend !== 'none') {
				const loc = a.legend === 'outside right' ? `loc='upper left', bbox_to_anchor=(1.02, 1)` : a.legend === 'outside top' ? `loc='lower center', bbox_to_anchor=(0.5, 1.02), ncol=${sers.filter((s) => s.label && s.type !== 'image').length}` : `loc='${a.legend}'`;
				py.push(`${A}.legend(${loc})`);
			}
			// 축 꾸미기 — MATLAB
			const props = [];
			if (mFont) props.push(`'FontName', '${mFont}'`);
			props.push(`'FontSize', ${num(f.fsTick)}`, `'LabelFontSizeMultiplier', ${num(f.fs / f.fsTick)}`, `'TitleFontSizeMultiplier', ${num(f.fsTitle / f.fsTick)}`, `'TitleFontWeight', '${f.titleBold ? 'bold' : 'normal'}'`);
			props.push(`'LineWidth', ${num(f.axLw)}`, `'TickDir', '${f.tickDir}'`, `'Box', '${a.box ? 'on' : 'off'}'`);
			if (mAllLatex) props.push(`'TickLabelInterpreter', 'latex'`);
			if (a.xscale === 'log') props.push(`'XScale', 'log'`);
			if (a.yscale === 'log') props.push(`'YScale', 'log'`);
			if (f.minor || a.grid === 'both') props.push(`'XMinorTick', 'on'`, `'YMinorTick', 'on'`);
			if (a.grid !== 'none') props.push(`'XGrid', 'on'`, `'YGrid', 'on'`, `'GridLineStyle', '${f.gridStyle}'`, `'GridColor', [0.78 0.78 0.78]`, `'GridAlpha', 1`);
			if (a.grid === 'both') props.push(`'XMinorGrid', 'on'`, `'YMinorGrid', 'on'`, `'MinorGridLineStyle', '${f.gridStyle}'`, `'MinorGridColor', [0.89 0.89 0.89]`, `'MinorGridAlpha', 1`);
			const lm = { pad: 'padded', ticks: 'tickaligned', tight: 'tight' }[f.limits];
			props.push(`'XLimitMethod', '${a.tightx ? 'tight' : lm}'`, `'YLimitMethod', '${lm}'`);
			m.push(`set(${mh}, ${props.join(', ...\n    ')});`);
			if (a.title) m.push(`title(${mh}, ${mStr(mText(a.title))}, 'Interpreter', '${mInterp(a.title)}');`);
			if (a.xlabel) m.push(`xlabel(${mh}, ${mStr(mText(a.xlabel))}, 'Interpreter', '${mInterp(a.xlabel)}');`);
			if (a.ylabel) m.push(`ylabel(${mh}, ${mStr(mText(a.ylabel))}, 'Interpreter', '${mInterp(a.ylabel)}');`);
			const ml = (l, n) => `${n}(${mh}, [${l[0] === 'None' ? '-inf' : l[0]} ${l[1] === 'None' ? 'inf' : l[1]}]);`;
			if (xl[0] !== 'None' || xl[1] !== 'None') m.push(ml(xl, 'xlim'));
			if (yl[0] !== 'None' || yl[1] !== 'None') m.push(ml(yl, 'ylim'));
			if (a.equal) m.push(`axis(${mh}, 'equal');`);
			if (hasLabel && a.legend !== 'none') {
				const li = legLi;
				const loc = { best: 'best', 'upper right': 'northeast', 'upper left': 'northwest', 'lower right': 'southeast', 'lower left': 'southwest', 'center right': 'east', 'outside right': 'northeastoutside', 'outside top': 'northoutside' }[a.legend];
				m.push(`legend(${mh}, 'Location', '${loc}', 'Interpreter', '${li}', 'Box', '${f.legendFrame ? 'on' : 'off'}', 'FontSize', ${num(f.fsLegend)}${a.legend === 'outside top' ? ", 'Orientation', 'horizontal'" : ''}${li !== 'latex' && mFont ? `, 'FontName', '${mFont}'` : ''});`);
			}
			m.push(`hold(${mh}, 'off');`);
		});
		if (f.sharex && st.axes.length > 1) m.push('', `linkaxes([${axHandles.join(' ')}], 'x');`);
		if (f.sharey && st.axes.length > 1) m.push(f.sharex ? `linkaxes([${axHandles.join(' ')}], 'xy');` : `linkaxes([${axHandles.join(' ')}], 'y');`);

		// 저장
		const out = (f.out || 'figure').replace(/[\\/:*?"<>|]/g, '_');
		py.push('', '# ── 4. 저장 ──');
		m.push('', '%% 3. 저장');
		const tp = f.transparent ? ', transparent=True' : '';
		if (f.fmtPdf) { py.push(`fig.savefig('${out}.pdf', bbox_inches='tight'${tp})`); m.push(`exportgraphics(fig, '${out}.pdf', 'ContentType', 'vector'${f.transparent ? ", 'BackgroundColor', 'none'" : ''});`); }
		if (f.fmtSvg) { py.push(`fig.savefig('${out}.svg', bbox_inches='tight'${tp})`); m.push(`print(fig, '${out}', '-dsvg');`); }
		if (f.fmtPng) { py.push(`fig.savefig('${out}.png', dpi=${num(f.dpi)}, bbox_inches='tight'${tp})`); m.push(`exportgraphics(fig, '${out}.png', 'Resolution', ${num(f.dpi)}${f.transparent ? ", 'BackgroundColor', 'none'" : ''});`); }
		py.push('plt.show()');

		// import 를 다시 (색 지도 등으로 늘었을 수 있음)
		const impLines = [...pyImp].sort((a, b) => (a.startsWith('import') === b.startsWith('import') ? 0 : a.startsWith('import') ? -1 : 1));
		const firstBlank = py.indexOf('');
		py.splice(1, firstBlank - 1, ...impLines);
		return { py: py.join('\n') + '\n', m: m.join('\n') + '\n', warn: uniq(warn) };
	}

	function exprPreview(s, which) {
		const ref = s[which];
		const v = getVar(ref);
		if (!v) return '';
		const lang = st.fig.lang;
		const image = s.type === 'image' && which === 'y';
		const free = image ? [ref.rd ?? 0, ref.cd ?? 1] : [ref.dim ?? 0];
		const fobj = fileOf(v);
		const name = v.key;
		if (fobj && fobj.fmt === 'csv') return name;
		if (lang === 'm') {
			const parts = v.dims.map((d, i) => (free.includes(i) ? ':' : d === 1 ? '1' : String(((ref.idx && ref.idx[i]) || 0) + 1)));
			return v.dims.every((d, i) => free.includes(i) || d === 1) ? name : `${name}(${parts.join(',')})`;
		}
		const dimsIdx = fobj && (fobj.fmt === 'mat' || fobj.fmt === 'mat73') ? nonSingle(v.dims) : v.dims.map((_, i) => i);
		const parts = dimsIdx.map((i) => (free.includes(i) ? ':' : String((ref.idx && ref.idx[i]) || 0)));
		return parts.every((p) => p === ':') ? name : `${name}[${parts.join(', ')}]`;
	}

	// ───────────────────────── 코드 칸 ─────────────────────────
	let lastCode = null;
	function showCode() {
		const c = codegen();
		lastCode = c;
		const lang = st.fig.lang;
		const pre = $('ps-code');
		pre.textContent = lang === 'm' ? c.m : c.py;
		pre.className = 'ps-code ' + (lang === 'm' ? 'language-matlab' : 'language-python');
		if (window.hljs) { try { delete pre.dataset.highlighted; window.hljs.highlightElement(pre); } catch (e) { /* 색칠 실패는 무시 */ } }
		$('ps-warn').innerHTML = c.warn.map((w) => `<li>⚠️ ${esc(w)}</li>`).join('');
		document.querySelectorAll('#ps-lang button').forEach((b) => b.classList.toggle('is-on', b.dataset.v === lang));
	}

	let raf = 0;
	function update() {
		save();
		clearTimeout(raf);
		raf = setTimeout(() => {
			const has = st.series.some((s) => getVar(s.y));
			$('ps-empty-stage').classList.toggle('hidden', has);
			try { draw(); } catch (e) { console.error(e); $('ps-msg').textContent = '⚠️ 그리다 멈췄어요: ' + e.message; }
			showCode();
		}, 16);
	}

	// ───────────────────────── 예시 데이터 ─────────────────────────
	function demoFile() {
		const N = 2000, fs = 100e3;
		const t = Float64Array.from({ length: N }, (_, i) => i / fs);
		let seed = 7;
		const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
		const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd());
		const y = new Float64Array(N * 3);
		for (let i = 0; i < N; i++) {
			y[i] = Math.sin(2 * Math.PI * 1e3 * t[i]);
			y[i + N] = 0.6 * Math.sin(2 * Math.PI * 2.5e3 * t[i] + 0.7) * Math.exp(-t[i] * 80);
			y[i + 2 * N] = 0.3 * Math.sign(Math.sin(2 * Math.PI * 500 * t[i])) + 0.05 * gauss();
		}
		const snr = Float64Array.from({ length: 13 }, (_, i) => i);
		const erfc = (x) => { const z = Math.abs(x), tt = 1 / (1 + 0.5 * z); const r = tt * Math.exp(-z * z - 1.26551223 + tt * (1.00002368 + tt * (0.37409196 + tt * (0.09678418 + tt * (-0.18628806 + tt * (0.27886807 + tt * (-1.13520398 + tt * (1.48851587 + tt * (-0.82215223 + tt * 0.17087277))))))))); return x >= 0 ? r : 2 - r; };
		const ber = new Float64Array(13 * 2);
		for (let i = 0; i < 13; i++) { const g = Math.pow(10, snr[i] / 10); ber[i] = 0.5 * erfc(Math.sqrt(g)); ber[i + 13] = 0.5 * erfc(Math.sqrt(g / 2)) * 1.0 + 1e-7; }
		const M = 64, K = 96;
		const S = new Float64Array(M * K);
		for (let r = 0; r < M; r++) for (let c = 0; c < K; c++) { const f0 = 20 + 18 * Math.sin(c / 15); S[r + c * M] = -60 + 50 * Math.exp(-Math.pow((r - f0) / 3, 2)) + 3 * gauss(); }
		const fax = Float64Array.from({ length: M }, (_, i) => i * 0.5);
		const tax = Float64Array.from({ length: K }, (_, i) => i * 0.01);
		const iq = { re: new Float64Array(800), im: new Float64Array(800) };
		const pts = [[1, 1], [-1, 1], [-1, -1], [1, -1]];
		for (let i = 0; i < 800; i++) { const p = pts[Math.floor(rnd() * 4)]; iq.re[i] = p[0] / Math.SQRT2 + 0.12 * gauss(); iq.im[i] = p[1] / Math.SQRT2 + 0.12 * gauss(); }
		const blob = window.PlotData.writeMat5([
			{ name: 't', dims: [1, N], re: t },
			{ name: 'y', dims: [N, 3], re: y },
			{ name: 'snr_db', dims: [1, 13], re: snr },
			{ name: 'ber', dims: [13, 2], re: ber },
			{ name: 'S', dims: [M, K], re: S },
			{ name: 'f_khz', dims: [M, 1], re: fax },
			{ name: 't_s', dims: [1, K], re: tax },
			{ name: 'iq', dims: [800, 1], re: iq.re, im: iq.im },
		]);
		return new File([blob], 'demo.mat', { type: 'application/octet-stream' });
	}

	// ───────────────────────── 설정 저장 · 불러오기 ─────────────────────────
	function download(name, data, type) {
		const a = document.createElement('a');
		a.href = URL.createObjectURL(data instanceof Blob ? data : new Blob([data], { type: type || 'text/plain' }));
		a.download = name;
		document.body.appendChild(a); a.click(); a.remove();
		setTimeout(() => URL.revokeObjectURL(a.href), 2000);
	}

	// ───────────────────────── 시작 ─────────────────────────
	function init() {
		load();
		syncAxes();
		const drop = $('ps-drop'), inp = $('ps-file');
		drop.addEventListener('click', (e) => { if (!e.target.closest('button')) inp.click(); });
		inp.addEventListener('change', () => { if (inp.files.length) addFiles([...inp.files]); inp.value = ''; });
		drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('is-over'); });
		drop.addEventListener('dragleave', () => drop.classList.remove('is-over'));
		drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('is-over'); if (e.dataTransfer.files.length) addFiles([...e.dataTransfer.files]); });
		$('ps-demo').addEventListener('click', () => { st.series = []; st.axes = [defAx(st.fig)]; st.fig.rows = st.fig.cols = 1; curAx = 0; addFiles([demoFile()]).then(() => { renderFig(); renderAxes(); }); });
		$('ps-demo-dl').addEventListener('click', () => download('demo.mat', demoFile()));
		const side = $('ps-side');
		side.addEventListener('input', onInput);
		side.addEventListener('change', onInput);
		side.addEventListener('click', onClick);
		$('ps-vars').addEventListener('click', onClick);
		$('ps-add').addEventListener('click', () => {
			const v = files.length ? flatVars(files[files.length - 1]).find((u) => u.kind === 'num') : null;
			const s = newSeries('line', v ? defaultRef(v) : null);
			openSeries.add(s.id);
			renderSeries(); update();
		});
		$('ps-zoom').addEventListener('change', update);
		$('ps-lang').addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; st.fig.lang = b.dataset.v; renderSeries(); update(); });
		$('ps-copy').addEventListener('click', async () => {
			const txt = $('ps-code').textContent;
			try { await navigator.clipboard.writeText(txt); $('ps-copy').textContent = '✅ 복사됨'; } catch (e) { $('ps-copy').textContent = '복사 실패'; }
			setTimeout(() => { $('ps-copy').textContent = '📋 복사'; }, 1500);
		});
		$('ps-dl').addEventListener('click', () => { const lang = st.fig.lang; const name = (st.fig.out || 'figure').replace(/[^\w.-]+/g, '_') || 'figure'; download(lang === 'm' ? `plot_${name}.m` : `plot_${name}.py`, lang === 'm' ? lastCode.m : lastCode.py); });
		$('ps-save').addEventListener('click', () => download('plot-settings.json', JSON.stringify(st, null, 1), 'application/json'));
		$('ps-load').addEventListener('change', async (e) => {
			const fl = e.target.files[0];
			e.target.value = '';
			if (!fl) return;
			try {
				const s = JSON.parse(await fl.text());
				if (!s.fig || !Array.isArray(s.series)) throw new Error('그래프 스튜디오 설정 파일이 아니에요');
				st = { fig: Object.assign(defFig(), s.fig), axes: (s.axes || []).map((a) => Object.assign(defAx(s.fig), a)), series: s.series, nextId: s.nextId || 100 };
				syncAxes(); renderFig(); renderAxes(); renderSeries(); update();
			} catch (err) { $('ps-msg').textContent = '⚠️ ' + err.message; }
		});
		$('ps-reset').addEventListener('click', () => {
			if (!confirm('모양 설정을 처음으로 되돌릴까요? (넣은 파일은 그대로)')) return;
			st = { fig: defFig(), axes: [], series: [], nextId: 1 };
			syncAxes(); curAx = 0;
			for (const f of files) { autoStart(f); break; }
			renderFig(); renderAxes(); renderSeries(); update();
		});
		hookStage();
		renderVars(); renderSeries(); renderAxes(); renderFig();
		update();
		let rt = 0;
		window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(update, 150); });
		// KaTeX 가 늦게 오면 한 번 더
		if (typeof katex === 'undefined') { let n = 0; const iv = setInterval(() => { if (typeof katex !== 'undefined' || ++n > 40) { clearInterval(iv); update(); } }, 250); }
		if (document.fonts && document.fonts.ready) document.fonts.ready.then(update);
	}

	window.__plot = { get st() { return st; }, files, varIndex, codegen, recipe, draw, addFiles, demoFile, setLang: (l) => { st.fig.lang = l; update(); } };
	if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
