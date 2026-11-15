/* 그래프 스튜디오 — 데이터 파일 읽기 (브라우저 안에서만)
 *
 * MATLAB .mat (v4 · v5/v6/v7 · v7.3=HDF5), NumPy .npy · .npz, CSV/TXT, HDF5 .h5 를 읽어
 * 변수 목록으로 바꾼다. 서버로 보내지 않는다.
 *
 * 변수(Var) 모양:
 *   { file, key, name, kind: 'num'|'char'|'struct'|'cell'|'skip', cls, dims, strides,
 *     re: Float64Array, im: Float64Array|null, text, children: [Var], note }
 *   dims/strides 는 '코드에서 보이는 차원 순서' 그대로 (MATLAB 파일은 MATLAB 순서, npy·h5 는 numpy 순서).
 *   key 는 파일 안에서 변수를 찾는 길 — 'y', 's.snr', 'c{2}', 's(3).f', 'sig/raw' — 설정 저장·복원에 씀.
 *   acc 는 코드 생성용 접근 단계 [{t:'var'|'field'|'cell'|'elem'|'col'|'h5', ...}].
 */
(function () {
	'use strict';

	const pad8 = (n) => (n + 7) & ~7;
	const prod = (a) => a.reduce((p, v) => p * v, 1);
	const colStrides = (d) => { const s = []; let k = 1; for (const v of d) { s.push(k); k *= v; } return s; };
	const rowStrides = (d) => { const s = new Array(d.length); let k = 1; for (let i = d.length - 1; i >= 0; i--) { s[i] = k; k *= d[i]; } return s; };
	const MAX_ELEMS = 50e6; // 숫자 5천만 개 (400 MB) 넘는 변수는 건너뜀

	async function inflate(bytes, raw) {
		if (typeof DecompressionStream === 'undefined') throw new Error('이 브라우저는 압축 풀기를 못 해요 (최신 Chrome·Edge·Safari·Firefox 로 열어 주세요)');
		const ds = new DecompressionStream(raw ? 'deflate-raw' : 'deflate');
		const stream = new Blob([bytes]).stream().pipeThrough(ds);
		const chunks = [];
		const reader = stream.getReader();
		let total = 0;
		try {
			for (;;) {
				const { done, value } = await reader.read();
				if (done) break;
				chunks.push(value); total += value.length;
			}
		} catch (e) {
			// MATLAB 이 쓴 압축 덩어리는 끝에 쓰레기 바이트가 붙는 경우가 있음 — 여기까지 푼 걸로 씀
			if (!total) throw e;
		}
		const out = new Uint8Array(total);
		let o = 0;
		for (const c of chunks) { out.set(c, o); o += c.length; }
		return out;
	}

	function mkNum(base, dims, strides, re, im, cls) {
		return Object.assign(base, { kind: 'num', cls, dims, strides, re, im: im || null });
	}

	// ───────────────────────── MAT v5 (v6·v7 포함) ─────────────────────────
	const MI = { INT8: 1, UINT8: 2, INT16: 3, UINT16: 4, INT32: 5, UINT32: 6, SINGLE: 7, DOUBLE: 9, INT64: 12, UINT64: 13, MATRIX: 14, COMPRESSED: 15, UTF8: 16, UTF16: 17, UTF32: 18 };
	const CLS = { 1: 'cell', 2: 'struct', 3: 'object', 4: 'char', 5: 'sparse', 6: 'double', 7: 'single', 8: 'int8', 9: 'uint8', 10: 'int16', 11: 'uint16', 12: 'int32', 13: 'uint32', 14: 'int64', 15: 'uint64', 16: 'function_handle', 17: 'opaque' };

	function tagAt(dv, off, le) {
		const w = dv.getUint32(off, le);
		if (w >>> 16) return { type: w & 0xffff, n: w >>> 16, data: off + 4, next: off + 8 };
		const n = dv.getUint32(off + 4, le);
		return { type: w, n, data: off + 8, next: off + 8 + pad8(n) };
	}

	function readTyped(dv, t, le) {
		const { type, n, data } = t;
		const size = { 1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 4, 9: 8, 12: 8, 13: 8, 16: 1, 17: 2, 18: 4 }[type];
		if (!size) throw new Error('알 수 없는 숫자 형식 ' + type);
		const cnt = Math.floor(n / size);
		const out = new Float64Array(cnt);
		for (let i = 0, o = data; i < cnt; i++, o += size) {
			switch (type) {
				case 1: out[i] = dv.getInt8(o); break;
				case 2: case 16: out[i] = dv.getUint8(o); break;
				case 3: out[i] = dv.getInt16(o, le); break;
				case 4: case 17: out[i] = dv.getUint16(o, le); break;
				case 5: out[i] = dv.getInt32(o, le); break;
				case 6: case 18: out[i] = dv.getUint32(o, le); break;
				case 7: out[i] = dv.getFloat32(o, le); break;
				case 9: out[i] = dv.getFloat64(o, le); break;
				case 12: out[i] = Number(dv.getBigInt64(o, le)); break;
				case 13: out[i] = Number(dv.getBigUint64(o, le)); break;
			}
		}
		return out;
	}

	function readStr(dv, t) {
		let s = '';
		for (let i = 0; i < t.n; i++) { const c = dv.getUint8(t.data + i); if (!c) break; s += String.fromCharCode(c); }
		return s;
	}

	function charText(codes, dims, type) {
		if (type === MI.UTF8) {
			const s = new TextDecoder().decode(new Uint8Array(Array.from(codes)));
			return s;
		}
		const r = dims[0] || 0, c = prod(dims.slice(1));
		const rows = [];
		for (let i = 0; i < r; i++) {
			let s = '';
			for (let j = 0; j < c; j++) s += String.fromCodePoint(codes[i + j * r] || 32);
			rows.push(s);
		}
		return rows.join('\n');
	}

	// miMATRIX 하나 (태그 다음 내용 [start, end)) → Var
	function parseMatrix(dv, start, end, le, base) {
		if (end <= start) return Object.assign(base, { kind: 'num', cls: 'double', dims: [0, 0], strides: [1, 0], re: new Float64Array(0), im: null });
		let t = tagAt(dv, start, le);
		const flags = dv.getUint32(t.data, le);
		const cls = CLS[flags & 0xff] || '?';
		const complex = !!(flags & 0x800), logical = !!(flags & 0x200);
		t = tagAt(dv, t.next, le);
		const dims = Array.from(readTyped(dv, t, le));
		t = tagAt(dv, t.next, le);
		const nm = readStr(dv, t);
		if (!base.name) base.name = nm;
		let off = t.next;
		const n = prod(dims);
		base.dims = dims;
		if (['double', 'single', 'int8', 'uint8', 'int16', 'uint16', 'int32', 'uint32', 'int64', 'uint64'].includes(cls)) {
			if (n > MAX_ELEMS) return Object.assign(base, { kind: 'skip', cls, note: '너무 커서 건너뜀' });
			t = tagAt(dv, off, le);
			const re = readTyped(dv, t, le);
			let im = null;
			if (complex) im = readTyped(dv, tagAt(dv, t.next, le), le);
			return mkNum(base, dims, colStrides(dims), re, im, logical ? 'logical' : cls);
		}
		if (cls === 'char') {
			t = n ? tagAt(dv, off, le) : null;
			const codes = t ? readTyped(dv, t, le) : [];
			return Object.assign(base, { kind: 'char', cls, text: charText(codes, dims, t && t.type) });
		}
		if (cls === 'cell') {
			const kids = [];
			for (let k = 0; k < n; k++) {
				t = tagAt(dv, off, le);
				const sub = sub2ind(k, dims);
				const kid = { file: base.file, name: '', key: base.key + '{' + (dims.filter((d) => d > 1).length <= 1 ? (k + 1) : sub.map((v) => v + 1).join(',')) + '}', acc: base.acc.concat([{ t: 'cell', lin: k, sub, dims }]) };
				kids.push(parseMatrix(dv, t.data, t.data + t.n, le, kid));
				off = t.next;
			}
			return Object.assign(base, { kind: 'cell', cls, children: kids });
		}
		if (cls === 'struct' || cls === 'object') {
			let className = '';
			t = tagAt(dv, off, le);
			if (cls === 'object') { className = readStr(dv, t); off = t.next; t = tagAt(dv, off, le); }
			const fl = readTyped(dv, t, le)[0];
			t = tagAt(dv, t.next, le);
			const names = [];
			for (let i = 0; i < t.n / fl; i++) {
				let s = '';
				for (let j = 0; j < fl; j++) { const c = dv.getUint8(t.data + i * fl + j); if (!c) break; s += String.fromCharCode(c); }
				names.push(s);
			}
			off = t.next;
			const kids = [];
			for (let k = 0; k < n; k++) {
				const sub = sub2ind(k, dims);
				const elemKey = n === 1 ? base.key : base.key + '(' + (k + 1) + ')';
				const elemAcc = n === 1 ? base.acc : base.acc.concat([{ t: 'elem', lin: k, sub, dims }]);
				const fields = [];
				for (const f of names) {
					t = tagAt(dv, off, le);
					const kid = { file: base.file, name: f, key: elemKey + '.' + f, acc: elemAcc.concat([{ t: 'field', k: f }]) };
					fields.push(parseMatrix(dv, t.data, t.data + t.n, le, kid));
					off = t.next;
				}
				if (n === 1) kids.push(...fields);
				else kids.push({ file: base.file, name: '(' + (k + 1) + ')', key: elemKey, acc: elemAcc, kind: 'struct', cls: 'struct', dims: [1, 1], children: fields });
				if (kids.length > 400) break;
			}
			return Object.assign(base, { kind: 'struct', cls: cls === 'object' ? className || 'object' : 'struct', children: kids });
		}
		if (cls === 'sparse') {
			if (n > 4e6) return Object.assign(base, { kind: 'skip', cls, note: '큰 희소 행렬은 건너뜀' });
			t = tagAt(dv, off, le); const ir = readTyped(dv, t, le);
			t = tagAt(dv, t.next, le); const jc = readTyped(dv, t, le);
			t = tagAt(dv, t.next, le); const pr = readTyped(dv, t, le);
			const pi = complex ? readTyped(dv, tagAt(dv, t.next, le), le) : null;
			const re = new Float64Array(n), im = complex ? new Float64Array(n) : null;
			for (let c = 0; c < dims[1]; c++) for (let p = jc[c]; p < jc[c + 1]; p++) { re[ir[p] + c * dims[0]] = pr[p]; if (im) im[ir[p] + c * dims[0]] = pi[p]; }
			return mkNum(base, dims, colStrides(dims), re, im, 'sparse');
		}
		return Object.assign(base, { kind: 'skip', cls, note: cls === 'opaque' ? 'string·table·datetime 같은 새 형식은 못 읽어요 (double·char 로 바꿔 저장해 주세요)' : '그릴 수 없는 형식' });
	}

	function sub2ind(k, dims) {
		const s = [];
		for (const d of dims) { s.push(k % d); k = Math.floor(k / d); }
		return s;
	}

	async function parseMat5(buf, file) {
		const u8 = new Uint8Array(buf);
		const le = u8[126] === 0x49 && u8[127] === 0x4d; // 'IM'
		const vars = [];
		let off = 128;
		const dv0 = new DataView(buf);
		while (off + 8 <= buf.byteLength) {
			const t = tagAt(dv0, off, le);
			let dv = dv0, s = t.data, e = t.data + t.n;
			if (t.type === MI.COMPRESSED) {
				const inner = await inflate(u8.subarray(t.data, t.data + t.n));
				dv = new DataView(inner.buffer, inner.byteOffset, inner.byteLength);
				const it = tagAt(dv, 0, le);
				if (it.type !== MI.MATRIX) { off = t.data + t.n; continue; }
				s = it.data; e = it.data + it.n;
				off = t.data + t.n;
			} else {
				off = t.next;
				if (t.type !== MI.MATRIX) continue;
			}
			// 변수 이름을 먼저 알아야 key·acc 를 만들 수 있음
			const peek = peekName(dv, s, le);
			if (!peek || peek.startsWith('__')) continue;
			const v = parseMatrix(dv, s, e, le, { file, name: peek, key: peek, acc: [{ t: 'var', k: peek }] });
			vars.push(v);
		}
		return vars;
	}

	function peekName(dv, s, le) {
		try {
			let t = tagAt(dv, s, le);
			t = tagAt(dv, t.next, le);
			t = tagAt(dv, t.next, le);
			return readStr(dv, t);
		} catch (e) { return ''; }
	}

	// ───────────────────────── MAT v4 ─────────────────────────
	function parseMat4(buf, file) {
		const dv = new DataView(buf);
		const vars = [];
		let off = 0;
		while (off + 20 <= buf.byteLength) {
			let le = true;
			let type = dv.getInt32(off, true);
			if (type < 0 || type > 4052) { le = false; type = dv.getInt32(off, false); }
			const mrows = dv.getInt32(off + 4, le), ncols = dv.getInt32(off + 8, le), imagf = dv.getInt32(off + 12, le), namlen = dv.getInt32(off + 16, le);
			if (mrows < 0 || ncols < 0 || namlen <= 0 || namlen > 256) break;
			let name = '';
			for (let i = 0; i < namlen - 1; i++) name += String.fromCharCode(dv.getUint8(off + 20 + i));
			off += 20 + namlen;
			const P = Math.floor(type / 10) % 10, T = type % 10;
			const size = [8, 4, 4, 2, 2, 1][P];
			const n = mrows * ncols;
			const rd = () => {
				const a = new Float64Array(n);
				for (let i = 0; i < n; i++, off += size) {
					a[i] = [() => dv.getFloat64(off, le), () => dv.getFloat32(off, le), () => dv.getInt32(off, le), () => dv.getInt16(off, le), () => dv.getUint16(off, le), () => dv.getUint8(off)][P]();
				}
				return a;
			};
			const re = rd();
			const im = imagf ? rd() : null;
			const dims = [mrows, ncols];
			const base = { file, name, key: name, acc: [{ t: 'var', k: name }] };
			if (T === 1) vars.push(Object.assign(base, { kind: 'char', cls: 'char', dims, text: charText(re, dims) }));
			else if (T === 0) vars.push(mkNum(base, dims, colStrides(dims), re, im, 'double'));
			else vars.push(Object.assign(base, { kind: 'skip', cls: 'sparse', dims, note: 'v4 희소 행렬은 못 읽어요' }));
		}
		return vars;
	}

	// ───────────────────────── NumPy .npy ─────────────────────────
	function parseNpy(buf, file, name, acc) {
		const u8 = new Uint8Array(buf);
		if (!(u8[0] === 0x93 && String.fromCharCode(...u8.subarray(1, 6)) === 'NUMPY')) throw new Error('npy 파일이 아니에요');
		const dv = new DataView(buf);
		const major = u8[6];
		const hlen = major === 1 ? dv.getUint16(8, true) : dv.getUint32(8, true);
		const hstart = major === 1 ? 10 : 12;
		const header = new TextDecoder('latin1').decode(u8.subarray(hstart, hstart + hlen));
		const descr = (header.match(/'descr'\s*:\s*'([^']+)'/) || [])[1];
		const fortran = /'fortran_order'\s*:\s*True/.test(header);
		const shapeTxt = (header.match(/'shape'\s*:\s*\(([^)]*)\)/) || [])[1] || '';
		const dims = shapeTxt.split(',').map((s) => s.trim()).filter(Boolean).map(Number);
		const base = { file, name, key: name, acc };
		const m = /^([<>|=])([a-zA-Z])(\d+)$/.exec(descr || '');
		if (!m) return Object.assign(base, { kind: 'skip', cls: descr || '?', dims, note: '이 자료형은 못 읽어요 (' + (descr || '?') + ')' });
		const le = m[1] !== '>';
		const kind = m[2], size = +m[3];
		const n = prod(dims);
		if (n > MAX_ELEMS) return Object.assign(base, { kind: 'skip', cls: descr, dims, note: '너무 커서 건너뜀' });
		let off = hstart + hlen;
		const one = (o, sz) => {
			if (kind === 'f') return sz === 8 ? dv.getFloat64(o, le) : sz === 4 ? dv.getFloat32(o, le) : f16(dv.getUint16(o, le));
			if (kind === 'i') return sz === 1 ? dv.getInt8(o) : sz === 2 ? dv.getInt16(o, le) : sz === 4 ? dv.getInt32(o, le) : Number(dv.getBigInt64(o, le));
			if (kind === 'u' || kind === 'b') return sz === 1 ? dv.getUint8(o) : sz === 2 ? dv.getUint16(o, le) : sz === 4 ? dv.getUint32(o, le) : Number(dv.getBigUint64(o, le));
			return NaN;
		};
		if (!'fiubc'.includes(kind)) return Object.assign(base, { kind: 'skip', cls: descr, dims, note: '숫자가 아닌 배열은 못 읽어요' });
		const re = new Float64Array(n);
		let im = null;
		if (kind === 'c') {
			im = new Float64Array(n);
			const h = size / 2;
			for (let i = 0; i < n; i++, off += size) {
				re[i] = h === 8 ? dv.getFloat64(off, le) : dv.getFloat32(off, le);
				im[i] = h === 8 ? dv.getFloat64(off + h, le) : dv.getFloat32(off + h, le);
			}
		} else {
			for (let i = 0; i < n; i++, off += size) re[i] = one(off, size);
		}
		const cls = { f: 'float', i: 'int', u: 'uint', b: 'bool', c: 'complex' }[kind] + (kind === 'b' ? '' : size * 8 * (kind === 'c' ? 1 : 1));
		return mkNum(base, dims, fortran ? colStrides(dims) : rowStrides(dims), re, im, cls);
	}

	function f16(h) {
		const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 0x1f, f = h & 0x3ff;
		if (e === 0) return s * Math.pow(2, -14) * (f / 1024);
		if (e === 31) return f ? NaN : s * Infinity;
		return s * Math.pow(2, e - 15) * (1 + f / 1024);
	}

	// ───────────────────────── .npz (zip) ─────────────────────────
	async function unzip(buf) {
		const dv = new DataView(buf);
		const u8 = new Uint8Array(buf);
		let eocd = -1;
		for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 70000); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
		if (eocd < 0) throw new Error('zip 끝 표시를 못 찾았어요');
		const count = dv.getUint16(eocd + 10, true);
		let p = dv.getUint32(eocd + 16, true);
		const out = [];
		for (let k = 0; k < count; k++) {
			if (dv.getUint32(p, true) !== 0x02014b50) break;
			const method = dv.getUint16(p + 10, true);
			let csize = dv.getUint32(p + 20, true);
			const nlen = dv.getUint16(p + 28, true), xlen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true);
			let lho = dv.getUint32(p + 42, true);
			const name = new TextDecoder().decode(u8.subarray(p + 46, p + 46 + nlen));
			// ZIP64 (4GB 넘는 npz): 추가 필드에서 크기·위치
			if (csize === 0xffffffff || lho === 0xffffffff) {
				let x = p + 46 + nlen;
				const xe = x + xlen;
				while (x < xe) {
					const id = dv.getUint16(x, true), sz = dv.getUint16(x + 2, true);
					if (id === 1) {
						let q = x + 4;
						if (dv.getUint32(p + 24, true) === 0xffffffff) q += 8;
						if (csize === 0xffffffff) { csize = Number(dv.getBigUint64(q, true)); q += 8; }
						if (lho === 0xffffffff) lho = Number(dv.getBigUint64(q, true));
					}
					x += 4 + sz;
				}
			}
			p += 46 + nlen + xlen + clen;
			const ln = dv.getUint16(lho + 26, true), lx = dv.getUint16(lho + 28, true);
			const ds = lho + 30 + ln + lx;
			const raw = u8.subarray(ds, ds + csize);
			out.push({ name, get: async () => (method === 0 ? raw.slice() : method === 8 ? await inflate(raw, true) : null) });
		}
		return out;
	}

	async function parseNpz(buf, file) {
		const vars = [];
		for (const ent of await unzip(buf)) {
			if (!ent.name.endsWith('.npy')) continue;
			const name = ent.name.replace(/\.npy$/, '');
			const data = await ent.get();
			if (!data) { vars.push({ file, name, key: name, kind: 'skip', cls: '?', dims: [], note: '이 압축 방식은 못 풀어요' }); continue; }
			vars.push(parseNpy(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength), file, name, [{ t: 'var', k: name }]));
		}
		return vars;
	}

	// ───────────────────────── CSV · TXT ─────────────────────────
	function parseText(buf, file) {
		let txt = new TextDecoder().decode(new Uint8Array(buf));
		if (txt.charCodeAt(0) === 0xfeff) txt = txt.slice(1);
		const lines = txt.split(/\r?\n/).filter((l) => l.trim() && !/^\s*[#%]/.test(l));
		if (!lines.length) throw new Error('빈 파일이에요');
		const first = lines[0];
		const cands = [['\t', /\t/], [',', /,/], [';', /;/]];
		let delim = 'ws';
		for (const [d, re] of cands) if (re.test(first)) { delim = d; break; }
		const split = (l) => (delim === 'ws' ? l.trim().split(/\s+/) : l.split(delim).map((s) => s.trim().replace(/^"(.*)"$/, '$1')));
		const head = split(first);
		const isNum = (s) => s !== '' && !isNaN(Number(s)) || /^(nan|inf|-inf)$/i.test(s);
		const hasHeader = head.some((s) => !isNum(s));
		const rows = (hasHeader ? lines.slice(1) : lines).map(split);
		const nc = Math.max(head.length, ...rows.slice(0, 50).map((r) => r.length));
		const nr = rows.length;
		const cols = Array.from({ length: nc }, () => new Float64Array(nr));
		const num = (s) => { if (s === undefined || s === '') return NaN; const l = s.toLowerCase(); if (l === 'nan') return NaN; if (l === 'inf') return Infinity; if (l === '-inf') return -Infinity; return Number(s); };
		for (let i = 0; i < nr; i++) for (let j = 0; j < nc; j++) cols[j][i] = num(rows[i][j]);
		const used = new Set();
		const vars = cols.map((re, j) => {
			let name = hasHeader ? (head[j] || 'col' + (j + 1)) : 'col' + (j + 1);
			while (used.has(name)) name += '_';
			used.add(name);
			return mkNum({ file, name, key: name, acc: [{ t: 'col', j, name, header: hasHeader }] }, [nr], [1], re, null, 'double');
		});
		return { vars, meta: { delim, header: hasHeader, ncols: nc } };
	}

	// ───────────────────────── HDF5 (MAT v7.3 · .h5) ─────────────────────────
	const H5WASM_URL = 'https://cdn.jsdelivr.net/npm/h5wasm@0.10.3/dist/esm/hdf5_hl.js';
	let h5mod = null;
	async function h5() {
		if (!h5mod) {
			const m = await import(H5WASM_URL);
			const mod = await (m.ready || (m.default && m.default.ready));
			h5mod = { File: m.File || m.default.File, Group: m.Group || m.default.Group, Dataset: m.Dataset || m.default.Dataset, FS: m.FS || (mod && mod.FS) };
		}
		return h5mod;
	}

	function attrStr(obj, name) {
		try {
			const a = obj.attrs && obj.attrs[name];
			if (!a) return '';
			let v = a.value;
			if (Array.isArray(v)) v = v[0];
			if (v instanceof Uint8Array) v = new TextDecoder().decode(v);
			return String(v || '');
		} catch (e) { return ''; }
	}

	async function parseH5(buf, file, isMat) {
		const h = await h5();
		const fname = 'mj_' + Date.now() + '_' + Math.random().toString(36).slice(2) + '.h5';
		h.FS.writeFile(fname, new Uint8Array(buf));
		const f = new h.File(fname, 'r');
		const notes = [];
		try {
			const walk = (grp, path, keyPrefix, acc) => {
				const out = [];
				for (const k of grp.keys()) {
					if (isMat && (k === '#refs#' || k === '#subsystem#')) continue;
					const obj = grp.get(k);
					const p = path ? path + '/' + k : k;
					const key = isMat ? (keyPrefix ? keyPrefix + '.' + k : k) : p;
					const a = acc.concat([isMat ? { t: keyPrefix ? 'field' : 'var', k } : { t: 'h5', path: '/' + p }]);
					const base = { file, name: k, key, acc: isMat ? a : [{ t: 'h5', path: '/' + p }] };
					if (obj instanceof h.Group) {
						const mc = attrStr(obj, 'MATLAB_class');
						if (isMat && mc && mc !== 'struct') { out.push(Object.assign(base, { kind: 'skip', cls: mc, dims: [], note: '이 MATLAB 형식은 v7.3 에서 못 읽어요' })); continue; }
						out.push(Object.assign(base, { kind: 'struct', cls: isMat ? 'struct' : 'group', dims: [1, 1], children: walk(obj, p, key, isMat ? a : []) }));
						continue;
					}
					if (!(obj instanceof h.Dataset)) continue;
					out.push(readDataset(obj, base, isMat));
				}
				return out;
			};
			const readDataset = (ds, base, matl) => {
				const shape = (ds.shape || []).map(Number);
				const mc = matl ? attrStr(ds, 'MATLAB_class') : '';
				const n = prod(shape);
				// MATLAB v7.3 은 차원을 거꾸로 저장 (HDF5 C 순서 = MATLAB 열 우선)
				const dims = matl ? (shape.length ? shape.slice().reverse() : [1, 1]) : shape;
				const strides = matl ? colStrides(dims) : rowStrides(shape);
				if (matl && attrStr(ds, 'MATLAB_empty') ) return mkNum(base, [0, 0], [1, 0], new Float64Array(0), null, mc || 'double');
				if (n > MAX_ELEMS) return Object.assign(base, { kind: 'skip', cls: mc || String(ds.dtype), dims, note: '너무 커서 건너뜀' });
				if (matl && mc === 'cell') return Object.assign(base, { kind: 'skip', cls: 'cell', dims, note: 'v7.3 셀 배열은 못 읽어요 (숫자 배열로 저장해 주세요)' });
				let v;
				try { v = ds.value; } catch (e) { return Object.assign(base, { kind: 'skip', cls: String(ds.dtype), dims, note: '읽기 실패' }); }
				if (v == null) return Object.assign(base, { kind: 'skip', cls: '?', dims, note: '읽기 실패' });
				if (typeof v === 'number' || typeof v === 'bigint') v = [v];
				if (typeof v === 'string') return Object.assign(base, { kind: 'char', cls: 'string', dims, text: v });
				let re, im = null;
				if (Array.isArray(v) && Array.isArray(v[0])) {
					// compound {real, imag}
					re = new Float64Array(v.length); im = new Float64Array(v.length);
					for (let i = 0; i < v.length; i++) { re[i] = Number(v[i][0]); im[i] = Number(v[i][1]); }
				} else if (Array.isArray(v) && typeof v[0] === 'string') {
					return Object.assign(base, { kind: 'char', cls: 'string', dims, text: v.slice(0, 50).join('\n') });
				} else {
					re = Float64Array.from(v, Number);
				}
				if (mc === 'char') return Object.assign(base, { kind: 'char', cls: 'char', dims, text: charText(re, dims) });
				return mkNum(base, dims, strides, re, im, mc || dtypeName(ds.dtype));
			};
			return { vars: walk(f, '', '', []), notes };
		} finally {
			try { f.close(); } catch (e) { /* 무시 */ }
			try { h.FS.unlink(fname); } catch (e) { /* 무시 */ }
		}
	}

	function dtypeName(d) {
		if (typeof d !== 'string') return 'compound';
		const m = /^[<>|=]?([a-zA-Z])(\d*)$/.exec(d);
		if (!m) return d;
		const k = { d: 'float64', f: 'float32', b: 'int8', B: 'uint8', h: 'int16', H: 'uint16', i: 'int32', I: 'uint32', q: 'int64', Q: 'uint64' }[m[1]];
		return k || d;
	}

	// ───────────────────────── 입구 ─────────────────────────
	async function readFile(file) {
		const name = file.name;
		const lower = name.toLowerCase();
		const buf = await file.arrayBuffer();
		const u8 = new Uint8Array(buf, 0, Math.min(buf.byteLength, 128));
		const headTxt = new TextDecoder('latin1').decode(u8);
		const isHdf = (o) => buf.byteLength > o + 8 && new Uint8Array(buf, o, 8).every((b, i) => b === [0x89, 0x48, 0x44, 0x46, 0x0d, 0x0a, 0x1a, 0x0a][i]);
		if (lower.endsWith('.npy')) return { name, fmt: 'npy', vars: [parseNpy(buf, name, name.replace(/\.npy$/i, '').replace(/^.*[\\/]/, ''), [{ t: 'npy' }])], notes: [] };
		if (lower.endsWith('.npz')) return { name, fmt: 'npz', vars: await parseNpz(buf, name), notes: [] };
		if (/\.(csv|tsv|txt|dat|asc)$/.test(lower) && !isHdf(0)) {
			const r = parseText(buf, name);
			return { name, fmt: 'csv', vars: r.vars, notes: [], meta: r.meta };
		}
		if (lower.endsWith('.mat') || headTxt.startsWith('MATLAB')) {
			if (headTxt.startsWith('MATLAB 7.3') || isHdf(512)) {
				const r = await parseH5(buf, name, true);
				return { name, fmt: 'mat73', vars: r.vars, notes: r.notes };
			}
			if (headTxt.startsWith('MATLAB 5.0') || (buf.byteLength > 128 && ((u8[126] === 0x49 && u8[127] === 0x4d) || (u8[126] === 0x4d && u8[127] === 0x49)))) {
				return { name, fmt: 'mat', vars: await parseMat5(buf, name), notes: [] };
			}
			return { name, fmt: 'mat', vars: parseMat4(buf, name), notes: ['MAT v4 (옛 형식) 으로 읽었어요'] };
		}
		if (isHdf(0) || /\.(h5|hdf5|he5|nc)$/.test(lower)) {
			const r = await parseH5(buf, name, false);
			return { name, fmt: 'h5', vars: r.vars, notes: r.notes };
		}
		throw new Error('모르는 파일 형식이에요 — .mat · .npy · .npz · .csv · .txt · .h5 를 넣어 주세요');
	}

	// ───────────────────────── 예시 .mat 쓰기 (v5, 압축 없음) ─────────────────────────
	// 받은 코드를 바로 돌려 볼 수 있게 예시 데이터를 진짜 .mat 파일로 만든다
	function writeMat5(vars) {
		const parts = [];
		const header = new Uint8Array(128);
		const txt = 'MATLAB 5.0 MAT-file, Platform: smjgallery.kr plot studio, Created on: ' + new Date().toUTCString();
		for (let i = 0; i < 116; i++) header[i] = i < txt.length ? txt.charCodeAt(i) : 32;
		header[124] = 0x00; header[125] = 0x01; header[126] = 0x49; header[127] = 0x4d;
		parts.push(header);
		const el = (type, bytes) => {
			const out = new Uint8Array(8 + pad8(bytes.length));
			const dv = new DataView(out.buffer);
			dv.setUint32(0, type, true); dv.setUint32(4, bytes.length, true);
			out.set(bytes, 8);
			return out;
		};
		const cat = (arr) => { const n = arr.reduce((s, a) => s + a.length, 0); const o = new Uint8Array(n); let p = 0; for (const a of arr) { o.set(a, p); p += a.length; } return o; };
		const matrix = (name, dims, re, im) => {
			const flags = new Uint8Array(8); const fdv = new DataView(flags.buffer);
			fdv.setUint32(0, 6 | (im ? 0x800 : 0), true);
			const d = new Uint8Array(dims.length * 4); const ddv = new DataView(d.buffer); dims.forEach((v, i) => ddv.setInt32(i * 4, v, true));
			const nm = new TextEncoder().encode(name);
			const body = [el(MI.UINT32, flags), el(MI.INT32, d), el(MI.INT8, nm), el(MI.DOUBLE, new Uint8Array(Float64Array.from(re).buffer))];
			if (im) body.push(el(MI.DOUBLE, new Uint8Array(Float64Array.from(im).buffer)));
			return el(MI.MATRIX, cat(body));
		};
		for (const v of vars) parts.push(matrix(v.name, v.dims, v.re, v.im));
		return new Blob(parts, { type: 'application/octet-stream' });
	}

	window.PlotData = { readFile, writeMat5, parseMat5, parseNpy, parseText, colStrides, rowStrides, H5WASM_URL };
})();
