// 🫥 숨바꼭질 방 화면 — Three.js 로 집 한 채를 그리고, 술래는 1인칭·숨는 사람은 3인칭(물건으로 변신).
// 판정(위치 범위·속도·쏘기·체력·시간)은 mj-relay 의 relay/mj_hideseek.py 가 하고, 여기선 보여 주고 입력만 보냄.
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';

const cfg = document.getElementById('hs-cfg');
const WS_URL = cfg.dataset.ws, ROOM = cfg.dataset.room, DEFAULT_NAME = cfg.dataset.name, TITLE = cfg.dataset.title;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 무시 */ } } };
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const angLerp = (a, b, t) => a + Math.atan2(Math.sin(b - a), Math.cos(b - a)) * t;

let pid = store.get(`mj-hs-pid-${ROOM}`);
if (!pid) { pid = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join(''); store.set(`mj-hs-pid-${ROOM}`, pid); }

// ── 장면 ─────────────────────────────────────────────────
const stage = $('hs-stage');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
stage.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color('#9fc4e8');
scene.fog = new THREE.Fog('#9fc4e8', 40, 90);
const camera = new THREE.PerspectiveCamera(70, 16 / 9, 0.05, 200);
scene.add(new THREE.HemisphereLight('#ffffff', '#8a7a66', 1.6));
const sun = new THREE.DirectionalLight('#fff4e0', 1.6);
sun.position.set(30, 40, 20);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -20, right: 20, top: 20, bottom: -20, near: 1, far: 100 });
scene.add(sun);
scene.add(sun.target);

const MATS = new Map();
const mat = (c) => { if (!MATS.has(c)) MATS.set(c, new THREE.MeshStandardMaterial({ color: c, roughness: 0.75 })); return MATS.get(c); };
function mesh(geo, color, x = 0, y = 0, z = 0) {
	const m = new THREE.Mesh(geo, mat(color));
	m.position.set(x, y, z);
	m.castShadow = true; m.receiveShadow = true;
	return m;
}
const box = (w, h, d, c, x, y, z) => mesh(new THREE.BoxGeometry(w, h, d), c, x, y, z);
const cyl = (rt, rb, h, c, x, y, z, seg = 16) => mesh(new THREE.CylinderGeometry(rt, rb, h, seg), c, x, y, z);

let PROPS = {}, MAP = null, SPEED = { hider: 4.2, seeker: 4.6 };
// 물건 모양: 바닥이 y=0, 크기는 서버의 PROPS(w,h,d)
function buildProp(type) {
	const [, w, h, d] = PROPS[type] || ['', 0.8, 0.8, 0.8];
	const g = new THREE.Group();
	const legs = (y, c, inset = 0.06) => { for (const sx of [-1, 1]) for (const sz of [-1, 1]) g.add(box(0.05, y, 0.05, c, sx * (w / 2 - inset), y / 2, sz * (d / 2 - inset))); };
	switch (type) {
		case 'box': g.add(box(w, h, d, '#b5835a', 0, h / 2, 0)); g.add(box(w + 0.01, 0.08, 0.2, '#d9c08c', 0, h, 0)); break;
		case 'chair': legs(0.45, '#6b4423'); g.add(box(w, 0.08, d, '#8b5a2b', 0, 0.49, 0)); g.add(box(w, 0.5, 0.06, '#8b5a2b', 0, 0.78, -d / 2 + 0.03)); break;
		case 'stool': g.add(cyl(w / 2, w / 2, 0.07, '#a0522d', 0, h - 0.035, 0)); for (let k = 0; k < 3; k++) { const a = (k / 3) * Math.PI * 2; g.add(box(0.04, h - 0.07, 0.04, '#6b4423', Math.cos(a) * w * 0.35, (h - 0.07) / 2, Math.sin(a) * w * 0.35)); } break;
		case 'table': legs(0.74, '#6b4423', 0.1); g.add(box(w, 0.06, d, '#9c6b3c', 0, 0.77, 0)); break;
		case 'sofa': g.add(box(w, 0.45, d, '#4a6fa5', 0, 0.225, 0)); g.add(box(w, 0.45, 0.25, '#3d5d8c', 0, 0.675, -d / 2 + 0.125)); for (const s of [-1, 1]) g.add(box(0.2, 0.3, d, '#3d5d8c', s * (w / 2 - 0.1), 0.6, 0)); break;
		case 'plant': g.add(cyl(0.2, 0.15, 0.4, '#c0623b', 0, 0.2, 0)); g.add(mesh(new THREE.SphereGeometry(0.32, 14, 10), '#3f8f3a', 0, 0.82, 0)); g.add(mesh(new THREE.SphereGeometry(0.22, 12, 8), '#4fa648', 0.1, 1.05, 0.05)); break;
		case 'lamp': g.add(cyl(0.15, 0.17, 0.05, '#333333', 0, 0.025, 0)); g.add(cyl(0.02, 0.02, 1.3, '#555555', 0, 0.7, 0)); g.add(cyl(0.12, 0.2, 0.3, '#f3e7c9', 0, 1.45, 0)); break;
		case 'barrel': g.add(cyl(w / 2, w / 2, h, '#2f6db5', 0, h / 2, 0, 20)); for (const y of [0.2, h - 0.2]) g.add(cyl(w / 2 + 0.01, w / 2 + 0.01, 0.05, '#24558d', 0, y, 0, 20)); break;
		case 'shelf': {
			g.add(box(w, h, 0.04, '#5c3d24', 0, h / 2, -d / 2 + 0.02));
			for (const s of [-1, 1]) g.add(box(0.04, h, d, '#5c3d24', s * (w / 2 - 0.02), h / 2, 0));
			const cols = ['#c0392b', '#2980b9', '#27ae60', '#f39c12', '#8e44ad', '#16a085'];
			for (let r = 0; r < 4; r++) {
				const y = 0.05 + r * (h / 4);
				g.add(box(w, 0.03, d, '#5c3d24', 0, y, 0));
				let x = -w / 2 + 0.08;
				for (let k = 0; x < w / 2 - 0.12; k++) { const bw = 0.06 + ((k * 7 + r * 3) % 4) * 0.02; g.add(box(bw, h / 4 - 0.12, d * 0.7, cols[(k + r) % cols.length], x + bw / 2, y + (h / 4 - 0.12) / 2 + 0.02, 0)); x += bw + 0.01; }
			}
			break;
		}
		case 'tv': g.add(box(w * 0.7, 0.4, d, '#3b3b3b', 0, 0.2, 0)); g.add(box(w, 0.55, 0.06, '#111111', 0, 0.68, -0.05)); g.add(box(w - 0.08, 0.47, 0.01, '#2b4b6b', 0, 0.68, -0.015)); break;
		case 'bed': g.add(box(w, 0.35, d, '#7a5230', 0, 0.175, 0)); g.add(box(w - 0.06, 0.2, d - 0.06, '#f0f0f0', 0, 0.45, 0)); g.add(box(0.5, 0.12, d * 0.6, '#ffffff', -w / 2 + 0.35, 0.6, 0)); g.add(box(w * 0.55, 0.06, d - 0.04, '#7fa7d9', w * 0.18, 0.58, 0)); break;
		case 'fridge': g.add(box(w, h, d, '#e3e6ea', 0, h / 2, 0)); g.add(box(w + 0.005, 0.02, d * 0.98, '#b9bec5', 0, h * 0.62, 0.005)); g.add(box(0.03, 0.4, 0.04, '#9aa0a8', w / 2 - 0.1, h * 0.8, d / 2 + 0.02)); break;
		case 'trash': g.add(cyl(w / 2, w / 2 - 0.04, h, '#7d8590', 0, h / 2, 0)); g.add(cyl(w / 2 + 0.02, w / 2 + 0.02, 0.05, '#5c636c', 0, h, 0)); break;
		case 'ball': g.add(mesh(new THREE.SphereGeometry(w / 2, 20, 14), '#e74c3c', 0, w / 2, 0)); break;
		default: g.add(box(w, h, d, '#999999', 0, h / 2, 0));
	}
	return g;
}
function buildSeeker() {
	const g = new THREE.Group();
	g.add(cyl(0.28, 0.3, 1.1, '#d64545', 0, 0.75, 0));
	g.add(mesh(new THREE.SphereGeometry(0.22, 16, 12), '#f2c9a0', 0, 1.5, 0));
	g.add(box(0.36, 0.08, 0.1, '#222222', 0, 1.55, -0.18));   // 눈가리개 / 고글
	g.add(box(0.08, 0.08, 0.5, '#333333', 0.25, 1.05, -0.3));  // 총
	return g;
}

// ── 집 ───────────────────────────────────────────────────
const world = new THREE.Group();
scene.add(world);
const solids = [];       // 충돌 상자 {x0,x1,z0,z1}
const wallMeshes = [];
const propGroups = new Map();   // id → group (진짜 물건)
const removed = new Set();      // 이번 판에 숨는 사람이 치운 진짜 물건 id
function applyRemoved(list) {
	removed.clear(); for (const id of list || []) removed.add(id);
	for (const [id, g] of propGroups) g.visible = !removed.has(id);
}
function buildWorld() {
	world.clear(); solids.length = 0; wallMeshes.length = 0; propGroups.clear();
	const floorCol = { 거실: '#c8a77e', 부엌: '#d6d6d2', 침실: '#b7c4d6' };
	const ground = mesh(new THREE.PlaneGeometry(80, 80), '#7fae6a', 0, -0.01, 0);
	ground.rotation.x = -Math.PI / 2; ground.position.set(MAP.w / 2, -0.02, MAP.d / 2);
	world.add(ground);
	for (const r of MAP.rooms) {
		const f = mesh(new THREE.PlaneGeometry(r.w, r.d), floorCol[r.name] || '#cccccc');
		f.rotation.x = -Math.PI / 2; f.position.set(r.x + r.w / 2, 0, r.z + r.d / 2);
		f.castShadow = false;
		world.add(f);
	}
	for (const w of MAP.walls) {
		const m = box(w.w, MAP.wall_h, w.d, '#efe9e1', w.x, MAP.wall_h / 2, w.z);
		world.add(m); wallMeshes.push(m);
		solids.push({ x0: w.x - w.w / 2, x1: w.x + w.w / 2, z0: w.z - w.d / 2, z1: w.z + w.d / 2 });
	}
	for (const p of MAP.props) {
		const g = buildProp(p.type);
		g.position.set(p.x, 0, p.z); g.rotation.y = p.ry;
		g.userData = { kind: 'prop', id: p.id, type: p.type };
		world.add(g); propGroups.set(p.id, g);
		const [, w, , d] = PROPS[p.type];
		const c = Math.abs(Math.cos(p.ry)), s = Math.abs(Math.sin(p.ry));
		const ex = (c * w + s * d) / 2, ez = (s * w + c * d) / 2;
		solids.push({ x0: p.x - ex, x1: p.x + ex, z0: p.z - ez, z1: p.z + ez, prop: p.id });
	}
}

// ── 상태 ─────────────────────────────────────────────────
let ws = null, S = null, ended = false, retry = 0, deadline = 0;
const ents = new Map();    // eid → {group, prop, x, z, ry, tx, tz, tr, name}
let seekerObj = null;      // 다른 사람이 보는 술래 {group, x, z, ry, tx, tz, tr}
const me = { x: 0, z: 0, ry: 0, yaw: 0, pitch: -0.25, lock: false, prop: 'box', group: null, sentAt: 0, sx: 0, sz: 0, sr: 0 };
const keys = new Set();
let lastStatus = '', lastRole = '';

function myRole() { return S && S.me ? S.me.role : null; }
function playing() { return S && (S.status === 'hide' || S.status === 'seek') && S.me && S.me.alive && S.me.role; }

function setEnt(e) {
	let o = ents.get(e.id);
	if (!o) { o = { x: e.x, z: e.z, ry: e.ry, tx: e.x, tz: e.z, tr: e.ry }; ents.set(e.id, o); }
	if (o.prop !== e.prop) { if (o.group) world.remove(o.group); o.prop = e.prop; o.group = buildProp(e.prop); o.group.userData = { kind: 'ent', id: e.id }; world.add(o.group); }
	o.tx = e.x; o.tz = e.z; o.tr = e.ry; o.name = e.name || ''; o.alive = e.alive;
	if (S && S.me && e.id === S.me.eid) o.self = true;
	return o;
}
function syncEnts() {
	const keep = new Set((S.ents || []).map((e) => e.id));
	for (const [id, o] of ents) if (!keep.has(id)) { world.remove(o.group); ents.delete(id); }
	for (const e of S.ents || []) setEnt(e);
	const sk = S.seeker;
	const showSeeker = sk && myRole() !== 'seeker';
	if (showSeeker && !seekerObj) { seekerObj = { group: buildSeeker(), x: sk.x, z: sk.z, ry: sk.ry, tx: sk.x, tz: sk.z, tr: sk.ry }; world.add(seekerObj.group); }
	if (!showSeeker && seekerObj) { world.remove(seekerObj.group); seekerObj = null; }
	if (seekerObj && sk) { seekerObj.tx = sk.x; seekerObj.tz = sk.z; seekerObj.tr = sk.ry; seekerObj.name = sk.name; }
}

// ── 화면 (HUD · 목록) ────────────────────────────────────
const ROLE_TXT = { seeker: '👁 술래', hider: '🫥 숨는 사람' };
function render() {
	if (!S) return;
	const role = myRole();
	if (S.status !== lastStatus || role !== lastRole) onPhase(lastStatus, S.status);
	lastStatus = S.status; lastRole = role;
	deadline = performance.now() + (S.left || 0) * 1000;
	applyRemoved(S.removed);
	syncEnts();
	$('hs-role').textContent = S.me ? (role ? ROLE_TXT[role] + (S.me.alive ? '' : ' (잡힘)') : '대기') : '👀 구경';
	$('hs-phase').textContent = { lobby: '기다리는 중', hide: `${S.round}판 · 숨는 시간`, seek: `${S.round}판 · 찾는 시간`, over: `${S.round}판 끝` }[S.status] || '';
	const hp = playing() || (S.me && S.me.role && S.status === 'seek');
	$('hs-hp').classList.toggle('hidden', !hp);
	if (S.me && S.me.role) {
		const max = role === 'seeker' ? 100 : 100;
		$('hs-hp-text').textContent = role === 'seeker' ? `❤ 술래 체력 ${S.me.hp} (엉뚱한 물건을 쏘면 −${S.rules.miss})` : `❤ 체력 ${S.me.hp} (한 번 맞으면 −${S.rules.hit})`;
		$('hs-hp-bar').style.width = `${clamp((S.me.hp / max) * 100, 0, 100)}%`;
		$('hs-hp-bar').style.background = S.me.hp > 50 ? '#22c55e' : S.me.hp > 20 ? '#f59e0b' : '#ef4444';
	}
	// 사람 목록
	$('hs-count').textContent = `${S.players.length}/8`;
	$('hs-players').innerHTML = S.players.map((p) => `<li class="flex items-center gap-2"><span>${p.role === 'seeker' ? '👁' : p.role === 'hider' ? (p.alive ? '🫥' : '🎯') : '·'}</span><span class="${p.me ? 'font-semibold' : ''} ${p.role === 'hider' && !p.alive ? 'line-through opacity-60' : ''}">${esc(p.name)}</span>${p.host ? '<span class="text-[11px] text-[#8e8e93]">방장</span>' : ''}${p.me ? '<span class="text-[11px] text-[#0f9f6e]">나</span>' : ''}</li>`).join('');
	const canStart = S.host && (S.status === 'lobby' || S.status === 'over');
	$('hs-host').classList.toggle('hidden', !canStart);
	if (canStart) {
		$('hs-set-hide').innerHTML = S.hide_choices.map((n) => `<option value="${n}" ${n === S.hide_time ? 'selected' : ''}>${n}초</option>`).join('');
		$('hs-set-seek').innerHTML = S.seek_choices.map((n) => `<option value="${n}" ${n === S.seek_time ? 'selected' : ''}>${n / 60}분</option>`).join('');
		$('hs-start').textContent = S.status === 'over' ? '▶ 다음 판 (술래 바꿔서)' : '▶ 시작';
	}
	$('hs-rules').innerHTML = `숨는 ${S.hide_time}초 → 찾는 ${S.seek_time / 60}분. 숨은 사람은 ${100 / S.rules.hit}번 맞으면 잡혀요. 술래가 진짜 물건을 쏘면 체력 −${S.rules.miss}. ${S.rules.taunt}초마다 숨은 사람 자리에서 '삐빅' 소리가 나요. <b>M</b> 지도는 집의 원래 배치도 — 지도에 없는 물건이 수상해요(술래는 ${S.rules.map_show}초 보고 ${S.rules.map_cool}초 쉼). 숨는 사람은 <b>F</b> 로 진짜 물건을 치우고 그 자리에 들어갈 수 있어요(판마다 ${S.rules.swaps}번).`;
	// 덮개
	const over = $('hs-over');
	if (S.status === 'lobby') {
		over.classList.remove('hidden');
		over.innerHTML = `<p class="text-[22px] font-bold">🫥 숨바꼭질</p><p class="max-w-[520px] text-[14px] leading-6 opacity-85">술래는 1인칭으로 집 안을 돌아다니며 수상한 물건을 쏘고, 숨는 사람은 3인칭으로 물건을 보고 <span class="hs-key">E</span> 를 눌러 그 물건으로 변신해 숨어요. 술래는 <span class="hs-key">M</span> 지도(원래 배치도)와 실제를 견줘 보고, 숨는 사람은 <span class="hs-key">F</span> 로 진짜 물건과 자리를 바꿔 지도까지 속일 수 있어요.</p><p class="text-[14px] opacity-80">${S.players.length < 2 ? '친구를 초대해 주세요 (2명부터).' : S.host ? '오른쪽 ▶ 시작을 누르세요.' : `방장(${esc(S.host_name)}) 이 시작하기를 기다리는 중…`}</p>`;
	} else if (S.status === 'over' && S.result) {
		const r = S.result, won = (r.winner === 'seeker' && role === 'seeker') || (r.winner === 'hiders' && role === 'hider');
		over.classList.remove('hidden');
		over.innerHTML = `<p class="text-[28px] font-extrabold">${r.winner === 'seeker' ? '👁 술래 승리!' : '🫥 숨는 쪽 승리!'}</p><p class="text-[15px]">${esc(r.reason)}</p>${role ? `<p class="text-[18px] font-bold" style="color:${won ? '#4ade80' : '#f87171'}">${won ? '이겼어요 🎉' : '졌어요'}</p>` : ''}<p class="text-[13px] opacity-80">잡힘: ${r.caught.map(esc).join(', ') || '없음'} · 살아남음: ${r.alive.map(esc).join(', ') || '없음'}</p><p class="text-[13px] opacity-70">${S.host ? '오른쪽 ▶ 다음 판을 누르면 술래가 바뀌어요.' : '방장이 다음 판을 시작하기를 기다리는 중…'}</p>`;
	} else if (!S.me) {
		over.classList.remove('hidden');
		over.innerHTML = '<p class="text-[16px]">👀 자리가 다 찼어요 (8명). 구경 중이에요.</p>';
		setTimeout(() => over.classList.add('hidden'), 2500);
	} else over.classList.add('hidden');
}
function onPhase(prev, now) {
	if ((now === 'hide' || (!prev && now === 'seek')) && S.me && S.me.role) {
		// 새 판(또는 하던 중에 새로 고침): 내 위치를 서버가 아는 곳으로
		me.x = S.me.x; me.z = S.me.z; me.ry = S.me.ry; me.yaw = S.me.role === 'seeker' ? 0 : Math.PI; me.pitch = S.me.role === 'seeker' ? 0 : -0.3;
		me.lock = false; me.prop = S.me.prop;
		mapSt.open = false; mapSt.coolUntil = 0;
		if (now === 'hide') toast(S.me.role === 'seeker' ? '👁 내가 술래! 눈 감는 중…' : '🫥 숨으세요! 물건을 보고 E', 2200);
	}
	if (now === 'seek') { toast(myRole() === 'seeker' ? '👀 찾기 시작!' : '👀 술래가 눈을 떴어요!', 1800); beep([660, 880], 0.18); }
	if (now === 'over' && document.pointerLockElement) document.exitPointerLock();
}
let toastT = 0;
function toast(text, ms = 1200, color = '') {
	const t = $('hs-toast'); t.textContent = text; t.style.color = color; t.classList.add('on');
	clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove('on'), ms);
}

// ── 소리 ─────────────────────────────────────────────────
let audio = null;
function ac() { try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); return audio; } catch (e) { return null; } }
function beep(freqs, vol = 0.12, pan = 0, len = 0.12) {
	const a = ac(); if (!a) return;
	freqs.forEach((f, i) => {
		const o = a.createOscillator(), g = a.createGain(), p = a.createStereoPanner ? a.createStereoPanner() : null;
		const t0 = a.currentTime + i * (len + 0.03);
		o.frequency.value = f; g.gain.setValueAtTime(vol, t0); g.gain.exponentialRampToValueAtTime(0.0001, t0 + len);
		if (p) { p.pan.value = clamp(pan, -1, 1); o.connect(g).connect(p).connect(a.destination); } else o.connect(g).connect(a.destination);
		o.start(t0); o.stop(t0 + len + 0.02);
	});
}
function taunt(pts) {
	const cx = camera.position.x, cz = camera.position.z, yaw = myRole() === 'seeker' ? me.yaw : Math.atan2(-(camera.getWorldDirection(new THREE.Vector3()).x), -(camera.getWorldDirection(new THREE.Vector3()).z));
	pts.forEach(([x, z], i) => setTimeout(() => {
		const dx = x - cx, dz = z - cz, d = Math.hypot(dx, dz);
		// 카메라 기준 오른쪽(+) / 왼쪽(−)
		const right = dx * Math.cos(yaw) - dz * Math.sin(yaw);
		beep([1250, 1650], clamp(0.22 / (1 + d / 7), 0.02, 0.22), d > 0.3 ? right / d : 0, 0.09);
	}, i * 260));
	if (myRole() === 'seeker') toast('🔊 삐빅! 소리가 났어요', 1200);
}

// ── 입력 ─────────────────────────────────────────────────
const typing = () => document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
document.addEventListener('keydown', (e) => {
	if (typing()) return;
	const k = e.key.toLowerCase();
	if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'shift'].includes(k)) { keys.add(k); if (document.pointerLockElement) e.preventDefault(); }
	if (k === 'e' && playing() && myRole() === 'hider') copyLooked();
	if (k === 'f' && playing() && myRole() === 'hider') swapLooked();
	if (k === 'm') toggleMap();
	if (k === 'q' && playing() && myRole() === 'hider') { me.lock = !me.lock; toast(me.lock ? '🔒 방향 고정' : '🔓 방향 풀림', 900); }
});
document.addEventListener('keyup', (e) => keys.delete(e.key.toLowerCase()));
window.addEventListener('blur', () => keys.clear());
stage.addEventListener('click', () => {
	ac();
	if (!document.pointerLockElement && playing()) { stage.requestPointerLock?.(); return; }
	if (document.pointerLockElement && myRole() === 'seeker' && S.status === 'seek') shoot();
});
document.addEventListener('mousemove', (e) => {
	if (document.pointerLockElement !== stage) return;
	me.yaw -= e.movementX * 0.0024;
	me.pitch = clamp(me.pitch - e.movementY * 0.0024, myRole() === 'seeker' ? -1.4 : -1.2, myRole() === 'seeker' ? 1.4 : 0.5);
});
$('hs-full').addEventListener('click', () => { if (document.fullscreenElement) document.exitFullscreen(); else stage.requestFullscreen?.(); });

// ── 움직임 · 충돌 ────────────────────────────────────────
function radius() {
	if (myRole() === 'seeker') return 0.3;
	const p = PROPS[me.prop]; return p ? clamp(Math.max(p[1], p[3]) / 2 * 0.85, 0.2, 0.9) : 0.35;
}
function blocked(x, z, r) {
	for (const s of solids) {
		if (s.prop && removed.has(s.prop)) continue;
		const cx = clamp(x, s.x0, s.x1), cz = clamp(z, s.z0, s.z1);
		if ((x - cx) ** 2 + (z - cz) ** 2 < r * r) return true;
	}
	return x < r || z < r || x > MAP.w - r || z > MAP.d - r;
}
function move(dt) {
	if (!playing() || (myRole() === 'seeker' && S.status === 'hide')) return;
	let f = 0, s = 0;
	if (keys.has('w') || keys.has('arrowup')) f += 1;
	if (keys.has('s') || keys.has('arrowdown')) f -= 1;
	if (keys.has('d') || keys.has('arrowright')) s += 1;
	if (keys.has('a') || keys.has('arrowleft')) s -= 1;
	const role = myRole();
	if (role === 'hider' && !me.lock) me.ry = me.yaw;
	if (role === 'seeker') me.ry = me.yaw;
	if (!f && !s) return;
	const len = Math.hypot(f, s), sp = SPEED[role] * (keys.has('shift') ? 0.55 : 1) * dt / len;
	const fx = -Math.sin(me.yaw), fz = -Math.cos(me.yaw), rx = Math.cos(me.yaw), rz = -Math.sin(me.yaw);
	const dx = (fx * f + rx * s) * sp, dz = (fz * f + rz * s) * sp, r = radius();
	// 끼어 있으면(변신해서 커진 경우 등) 빠져나오는 쪽은 허용
	const stuck = blocked(me.x, me.z, r);
	if (stuck || !blocked(me.x + dx, me.z, r)) me.x += dx;
	if (stuck || !blocked(me.x, me.z + dz, r)) me.z += dz;
	me.x = clamp(me.x, 0.2, MAP.w - 0.2); me.z = clamp(me.z, 0.2, MAP.d - 0.2);
}
function sendPos(now) {
	if (!playing() || (myRole() === 'seeker' && S.status === 'hide')) return;
	const changed = Math.abs(me.x - me.sx) > 0.01 || Math.abs(me.z - me.sz) > 0.01 || Math.abs(me.ry - me.sr) > 0.01;
	if ((changed && now - me.sentAt > 80) || now - me.sentAt > 1000) {
		send({ type: 'pos', x: +me.x.toFixed(3), z: +me.z.toFixed(3), ry: +me.ry.toFixed(3) });
		me.sentAt = now; me.sx = me.x; me.sz = me.z; me.sr = me.ry;
	}
}

// ── 보기 · 쏘기 · 변신 ───────────────────────────────────
const ray = new THREE.Raycaster();
const CENTER = new THREE.Vector2(0, 0);
function pick(maxDist, includeEnts) {
	ray.setFromCamera(CENTER, camera);
	ray.far = maxDist;
	const targets = [...wallMeshes];
	for (const [id, g] of propGroups) if (!removed.has(id)) targets.push(g);
	if (includeEnts) for (const o of ents.values()) if (!o.self && o.group) targets.push(o.group);
	const hits = ray.intersectObjects(targets, true);
	for (const h of hits) {
		let g = h.object;
		while (g && !g.userData.kind && g.parent) g = g.parent;
		if (!g || !g.userData.kind) return null;   // 벽
		if (g.userData.kind === 'ent' && ents.get(g.userData.id)?.self) continue;
		return { ...g.userData, dist: h.distance, point: h.point };
	}
	return null;
}
let looked = null;
function copyLooked() {
	const t = looked;
	if (!t || t.kind !== 'prop') { toast('물건을 보고 E 를 눌러요', 900); return; }
	const p = MAP.props.find((q) => q.id === t.id);
	if (Math.hypot(p.x - me.x, p.z - me.z) > 4) { toast('조금 더 가까이 가서 E', 900); return; }
	me.prop = t.type;
	const o = ents.get(S.me.eid); if (o) setEnt({ id: S.me.eid, prop: t.type, x: me.x, z: me.z, ry: me.ry, alive: true, name: o.name });
	// 비슷한 방향으로 맞춰 두면 덜 티 남
	me.ry = p.ry; me.yaw = p.ry; me.lock = true;
	send({ type: 'disguise', prop: t.type, from: t.id });
	toast(`✨ ${PROPS[t.type][0]}(으)로 변신! (방향 고정 — Q 로 풀기)`, 1400);
	beep([523, 784], 0.1);
}
// 자리 바꾸기: 보고 있는 진짜 물건을 치우고 그 자리·방향 그대로 들어감 (서버가 확인하고 swap 을 돌려줌)
function swapLooked() {
	const t = looked, left = S.me.swaps || 0;
	if (left <= 0) { toast('자리 바꾸기를 다 썼어요', 900); return; }
	if (!t || t.kind !== 'prop') { toast('바꿀 물건을 보고 F 를 눌러요', 900); return; }
	const p = MAP.props.find((q) => q.id === t.id);
	if (Math.hypot(p.x - me.x, p.z - me.z) > S.rules.swap_range) { toast('조금 더 가까이 가서 F', 900); return; }
	send({ type: 'swap', prop: t.id });
}

// ── 지도 (집의 원래 배치도 — 손으로 그린 것처럼 조금씩 어긋남) ──
const mapSt = { open: false, until: 0, coolUntil: 0 };
function closeMap(now) {
	if (!mapSt.open) return;
	mapSt.open = false;
	if (myRole() === 'seeker') mapSt.coolUntil = now + S.rules.map_cool * 1000;
}
function toggleMap() {
	const now = performance.now();
	if (mapSt.open) { closeMap(now); return; }
	if (!playing() || !MAP) return;
	if (myRole() === 'seeker') {
		if (S.status !== 'seek') return;
		if (now < mapSt.coolUntil) { toast(`지도는 ${Math.ceil((mapSt.coolUntil - now) / 1000)}초 뒤에 다시 볼 수 있어요`, 900); return; }
		mapSt.until = now + S.rules.map_show * 1000;
	}
	mapSt.open = true;
}
function rng32(seed) { return () => { seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
function hash(str) { let h = 2166136261; for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619); return h; }
const ROUND_PROPS = new Set(['stool', 'plant', 'lamp', 'barrel', 'trash', 'ball']);
function drawMap(now) {
	const cv = $('hs-map'), cw = cv.clientWidth, ch = cv.clientHeight, dpr = Math.min(2, window.devicePixelRatio || 1);
	if (!cw || !ch) return;
	if (cv.width !== Math.round(cw * dpr) || cv.height !== Math.round(ch * dpr)) { cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr); }
	const g = cv.getContext('2d');
	g.setTransform(dpr, 0, 0, dpr, 0, 0);
	const top = 30, pad = 14, k = Math.min((cw - 2 * pad) / MAP.w, (ch - top - pad) / MAP.d), ox = (cw - MAP.w * k) / 2, oz = top + (ch - top - pad - MAP.d * k) / 2;
	const X = (x) => ox + x * k, Z = (z) => oz + z * k;
	g.fillStyle = '#f4ecd8'; g.fillRect(0, 0, cw, ch);
	g.lineJoin = 'round'; g.lineCap = 'round';
	// 삐뚤빼뚤한 다각형 (판·물건마다 늘 같은 모양)
	const poly = (pts, rnd, amp, fill, stroke, lw) => {
		for (let pass = 0; pass < 2; pass++) {
			g.beginPath();
			pts.forEach(([x, y], i) => { const px = x + (rnd() - 0.5) * amp, py = y + (rnd() - 0.5) * amp; if (i) g.lineTo(px, py); else g.moveTo(px, py); });
			g.closePath();
			if (!pass && fill) { g.fillStyle = fill; g.fill(); }
			g.strokeStyle = stroke; g.lineWidth = lw; g.stroke();
		}
	};
	g.textAlign = 'center'; g.textBaseline = 'middle';
	g.fillStyle = 'rgba(90, 70, 40, 0.22)'; g.font = `700 ${Math.round(k * 1.5)}px sans-serif`;
	for (const r of MAP.rooms) g.fillText(r.name, X(r.x + r.w / 2), Z(r.z + r.d / 2));
	const wr = rng32(hash('w' + S.round));
	for (const w of MAP.walls) poly([[X(w.x - w.w / 2), Z(w.z - w.d / 2)], [X(w.x + w.w / 2), Z(w.z - w.d / 2)], [X(w.x + w.w / 2), Z(w.z + w.d / 2)], [X(w.x - w.w / 2), Z(w.z + w.d / 2)]], wr, 2.2, '#5b4a36', '#3d3122', 1.2);
	g.font = `${Math.max(8, Math.round(k * 0.3))}px sans-serif`;
	for (const p of MAP.props) {
		const rnd = rng32(hash(S.round + p.id)), [name, w, , d] = PROPS[p.type];
		// 자리는 최대 ±0.3 m, 방향은 조금 어긋나게
		const cx = X(p.x + (rnd() - 0.5) * 0.6), cz = Z(p.z + (rnd() - 0.5) * 0.6), a = -p.ry + (rnd() - 0.5) * 0.25;
		let pts;
		if (ROUND_PROPS.has(p.type)) pts = Array.from({ length: 9 }, (_, i) => [cx + Math.cos(i / 9 * 6.283) * w * k / 2, cz + Math.sin(i / 9 * 6.283) * w * k / 2]);
		else pts = [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]].map(([x, z]) => [cx + (x * Math.cos(a) - z * Math.sin(a)) * k, cz + (x * Math.sin(a) + z * Math.cos(a)) * k]);
		poly(pts, rnd, 2.4, 'rgba(255, 255, 255, 0.55)', '#4a3c2a', 1);
		g.fillStyle = '#3d3122'; g.fillText(name, cx, cz);
	}
	// 나
	const mx = X(me.x), mz = Z(me.z), fx = -Math.sin(me.yaw), fz = -Math.cos(me.yaw), r = 7;
	g.beginPath(); g.moveTo(mx + fx * r * 1.7, mz + fz * r * 1.7); g.lineTo(mx - fz * r * 0.8 - fx * r * 0.6, mz + fx * r * 0.8 - fz * r * 0.6); g.lineTo(mx + fz * r * 0.8 - fx * r * 0.6, mz - fx * r * 0.8 - fz * r * 0.6); g.closePath();
	g.fillStyle = '#e11d48'; g.fill(); g.strokeStyle = '#fff'; g.lineWidth = 1.5; g.stroke();
	g.textAlign = 'left'; g.fillStyle = '#3d3122'; g.font = '700 13px sans-serif';
	g.fillText('🗺 원래 배치도', 12, 16);
	g.font = '12px sans-serif'; g.fillStyle = '#7a6a52';
	g.fillText(myRole() === 'seeker' ? '지도에 없는데 놓여 있는 물건이 수상해요 · 손으로 그려 조금 어긋나요' : '술래는 이 지도와 실제를 견줘 봐요 — 지도에 없는 자리에 있으면 티 나요', 118, 16.5);
	if (myRole() === 'seeker') {
		const f = clamp((mapSt.until - now) / (S.rules.map_show * 1000), 0, 1);
		g.fillStyle = 'rgba(0, 0, 0, 0.12)'; g.fillRect(0, ch - 5, cw, 5);
		g.fillStyle = '#e11d48'; g.fillRect(0, ch - 5, cw * f, 5);
	}
}
function updateMap(now) {
	if (mapSt.open && (!playing() || (myRole() === 'seeker' && (now > mapSt.until || S.status !== 'seek')))) closeMap(now);
	$('hs-mapbox').style.display = mapSt.open ? 'block' : 'none';
	if (mapSt.open) drawMap(now);
	const btn = $('hs-mapbtn'), can = playing() && !(myRole() === 'seeker' && S.status !== 'seek');
	btn.style.display = can ? 'block' : 'none';
	if (!can) return;
	const cool = myRole() === 'seeker' && !mapSt.open ? Math.ceil((mapSt.coolUntil - now) / 1000) : 0;
	btn.innerHTML = mapSt.open ? '<span class="hs-key">M</span> 지도 닫기' : cool > 0 ? `🗺 지도 ${cool}초 뒤` : '<span class="hs-key">M</span> 지도';
	btn.style.opacity = cool > 0 ? 0.55 : 1;
}

let lastShot = 0;
const tracers = [];
function shoot() {
	const now = performance.now();
	if (now - lastShot < 380) return;
	lastShot = now;
	beep([180], 0.16, 0, 0.07);
	const t = pick(S.rules.range, true);
	// 총알 선
	const from = camera.position.clone().add(new THREE.Vector3(0.18, -0.15, 0).applyQuaternion(camera.quaternion));
	const to = t ? t.point.clone() : camera.position.clone().add(new THREE.Vector3(0, 0, -S.rules.range).applyQuaternion(camera.quaternion));
	const geo = new THREE.BufferGeometry().setFromPoints([from, to]);
	const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: '#ffd166', transparent: true, opacity: 0.9 }));
	scene.add(line); tracers.push({ line, until: now + 90 });
	if (t) send({ type: 'shoot', target: t.id });
}

// ── 메시지 ───────────────────────────────────────────────
function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
function flash(group, color = '#ff3b30') {
	if (!group) return;
	group.traverse((m) => { if (m.isMesh) { m.material = m.material.clone(); m.material.emissive = new THREE.Color(color); m.material.emissiveIntensity = 0.8; } });
	setTimeout(() => group.traverse((m) => { if (m.isMesh && m.material.emissive) { m.material.emissiveIntensity = 0; } }), 220);
}
function onMessage(m) {
	if (m.type === 'hello') { retry = 0; $('hs-chat').innerHTML = ''; (m.chat || []).forEach((c) => chatLine(c)); }
	else if (m.type === 'map') { MAP = m.map; PROPS = m.props; SPEED = m.speed || SPEED; buildWorld(); for (const o of ents.values()) world.add(o.group); if (seekerObj) world.add(seekerObj.group); }
	else if (m.type === 'state') { S = m.state; render(); }
	else if (m.type === 'pos') {
		if (m.id === 'seeker') { if (seekerObj) { seekerObj.tx = m.x; seekerObj.tz = m.z; seekerObj.tr = m.ry; } }
		else { const o = ents.get(m.id); if (o) { o.tx = m.x; o.tz = m.z; o.tr = m.ry; } }
	}
	else if (m.type === 'fix') { me.x = m.x; me.z = m.z; }
	else if (m.type === 'disguise') { const o = ents.get(m.id); if (o && !o.self) setEnt({ id: m.id, prop: m.prop, x: o.tx, z: o.tz, ry: o.tr, alive: true, name: o.name }); }
	else if (m.type === 'swap') {
		removed.add(m.prop); const pg = propGroups.get(m.prop); if (pg) pg.visible = false;
		const o = ents.get(m.id), mine = S && S.me && m.id === S.me.eid;
		if (o) { setEnt({ id: m.id, prop: m.kind, x: m.x, z: m.z, ry: m.ry, alive: true, name: o.name }); o.x = m.x; o.z = m.z; o.ry = m.ry; }
		if (mine) {
			me.x = m.x; me.z = m.z; me.ry = m.ry; me.prop = m.kind; me.lock = true; me.sx = m.x; me.sz = m.z; me.sr = m.ry;
			toast(`🔁 ${PROPS[m.kind][0]} 자리에 들어갔어요! 움직이면 빈 자리가 남아요`, 1800); beep([392, 523, 784], 0.1);
		}
	}
	else if (m.type === 'hit') {
		const o = ents.get(m.id); flash(o && o.group);
		if (myRole() === 'seeker') { toast(m.hp > 0 ? '🎯 명중!' : '🎯 잡았다!', 900, '#4ade80'); hitMark(); beep([880, 1320], 0.12); }
		else if (S && S.me && m.id === S.me.eid) { toast(m.hp > 0 ? `💥 맞았어요! 체력 ${m.hp}` : '😵 잡혔어요…', 1400, '#f87171'); beep([300, 200], 0.15); }
	}
	else if (m.type === 'miss') {
		flash(propGroups.get(m.id), '#ffffff');
		if (myRole() === 'seeker') { toast(`❌ 진짜 물건이에요! 체력 ${m.hp}`, 900, '#fbbf24'); beep([220], 0.12); }
	}
	else if (m.type === 'shot') { if (m.why === 'far') toast('너무 멀어요', 700); }
	else if (m.type === 'taunt') taunt(m.pts || []);
	else if (m.type === 'chat') chatLine(m);
	else if (m.type === 'error') chatLine({ system: true, text: `⚠️ ${m.text}` });
	else if (m.type === 'end') { ended = true; const o = $('hs-over'); o.classList.remove('hidden'); o.innerHTML = `<p class="text-[18px] font-bold">🚪 ${esc(m.reason)}</p>`; }
}
function hitMark() { const c = $('hs-cross'); c.classList.add('hit'); setTimeout(() => c.classList.remove('hit'), 200); }
function chatLine(m) {
	const box_ = $('hs-chat'), div = document.createElement('div');
	div.innerHTML = m.system ? `<span class="text-[#8e8e93]">· ${esc(m.text)}</span>` : `<b>${esc(m.name)}</b> ${esc(m.text)}`;
	box_.appendChild(div); box_.scrollTop = box_.scrollHeight;
}
$('hs-chat-form').addEventListener('submit', (e) => { e.preventDefault(); const v = $('hs-chat-in').value.trim(); if (v) { send({ type: 'chat', text: v }); $('hs-chat-in').value = ''; } $('hs-chat-in').blur(); stage.focus(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !typing() && !document.pointerLockElement) { $('hs-chat-in').focus(); e.preventDefault(); } });
$('hs-start').addEventListener('click', () => send({ type: 'start' }));
$('hs-set-hide').addEventListener('change', (e) => send({ type: 'settings', hide: +e.target.value }));
$('hs-set-seek').addEventListener('change', (e) => send({ type: 'settings', seek: +e.target.value }));

function connect(name) {
	ws = new WebSocket(`${WS_URL}&pid=${pid}&name=${encodeURIComponent(name)}`);
	ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
	ws.onclose = () => {
		if (ended) return;
		const o = $('hs-over'); o.classList.remove('hidden'); o.innerHTML = '<p class="text-[15px] opacity-80">연결이 끊겼어요. 다시 연결하는 중…</p>';
		setTimeout(() => connect(name), Math.min(8000, 800 * 2 ** retry++));
	};
}
function begin(name) { store.set('mj-game-name', name); $('hs-name-box').classList.add('hidden'); connect(name); }
const saved = DEFAULT_NAME || store.get('mj-game-name');
if (saved) begin(saved);
else { $('hs-name-box').classList.remove('hidden'); $('hs-name').focus(); }
$('hs-name-form').addEventListener('submit', (e) => { e.preventDefault(); begin($('hs-name').value.trim()); });
$('hs-copy').addEventListener('click', async () => {
	const url = $('hs-copy').dataset.url;
	try { await navigator.clipboard.writeText(url); $('hs-copy').textContent = '✓ 복사됨'; setTimeout(() => { $('hs-copy').textContent = '🔗 초대 링크 복사'; }, 1400); } catch (e) { prompt('링크를 복사하세요', url); }
});
$('hs-kakao').addEventListener('click', () => window.mjShare && window.mjShare({ title: `🫥 숨바꼭질 — ${TITLE}`, text: '링크를 열고 닉네임만 넣으면 바로 같이 할 수 있어요.', url: $('hs-copy').dataset.url, button: '숨바꼭질 하러 가기' }));

// ── 그리기 ───────────────────────────────────────────────
function resize() {
	const w = stage.clientWidth, h = stage.clientHeight;
	renderer.setSize(w, h, false);
	camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(stage);
const tmp = new THREE.Vector3();
function placeCamera() {
	const role = myRole(), alive = S && S.me && S.me.alive;
	if (S && (S.status === 'hide' || S.status === 'seek') && role === 'seeker' && alive) {
		camera.position.set(me.x, 1.6, me.z);
		camera.rotation.set(me.pitch, me.yaw, 0, 'YXZ');
		return;
	}
	if (S && (S.status === 'hide' || S.status === 'seek') && role === 'hider' && alive) {
		const h = PROPS[me.prop] ? PROPS[me.prop][2] : 1;
		const pivot = new THREE.Vector3(me.x, Math.max(0.6, h * 0.8), me.z);
		let dist = 3.2 + h;
		const dir = new THREE.Vector3(Math.sin(me.yaw) * Math.cos(me.pitch), -Math.sin(me.pitch), Math.cos(me.yaw) * Math.cos(me.pitch));
		// 벽에 카메라가 묻히지 않게
		ray.set(pivot, dir); ray.far = dist;
		const hit = ray.intersectObjects(wallMeshes, false)[0];
		if (hit) dist = Math.max(0.6, hit.distance - 0.25);
		camera.position.copy(pivot).addScaledVector(dir, dist);
		camera.lookAt(pivot);
		return;
	}
	// 대기·끝·잡힘·구경: 집을 비스듬히 위에서 (천천히 돎)
	const t = performance.now() / 1000 * 0.05, cx = MAP ? MAP.w / 2 : 12, cz = MAP ? MAP.d / 2 : 8;
	camera.position.set(cx + Math.sin(t) * 22, 20, cz + Math.cos(t) * 22);
	camera.lookAt(cx, 0, cz);
}
function updateTags() {
	const box_ = $('hs-tags'), w = stage.clientWidth, h = stage.clientHeight, out = [];
	const add = (x, y, z, text, color) => {
		tmp.set(x, y, z).project(camera);
		if (tmp.z > 1 || tmp.z < -1) return;
		out.push(`<span class="hs-tag" style="left:${((tmp.x + 1) / 2) * w}px;top:${((1 - tmp.y) / 2) * h}px;color:${color}">${esc(text)}</span>`);
	};
	for (const o of ents.values()) if (o.name && o.group) add(o.group.position.x, (PROPS[o.prop]?.[2] || 1) + 0.35, o.group.position.z, o.self ? '나' : o.name, o.alive === false ? '#9ca3af' : '#86efac');
	if (seekerObj && seekerObj.name) add(seekerObj.group.position.x, 2.1, seekerObj.group.position.z, `👁 ${seekerObj.name}`, '#fca5a5');
	box_.innerHTML = out.join('');
}
let last = performance.now();
function frame(now) {
	const dt = Math.min(0.05, (now - last) / 1000);
	last = now;
	if (MAP) {
		move(dt);
		sendPos(now);
		const k = 1 - Math.exp(-dt * 14);
		for (const o of ents.values()) {
			if (!o.group) continue;
			if (o.self && playing()) { o.x = me.x; o.z = me.z; o.ry = me.ry; }
			else { o.x += (o.tx - o.x) * k; o.z += (o.tz - o.z) * k; o.ry = angLerp(o.ry, o.tr, k); }
			o.group.position.set(o.x, 0, o.z); o.group.rotation.y = o.ry;
		}
		if (seekerObj) {
			seekerObj.x += (seekerObj.tx - seekerObj.x) * k; seekerObj.z += (seekerObj.tz - seekerObj.z) * k; seekerObj.ry = angLerp(seekerObj.ry, seekerObj.tr, k);
			seekerObj.group.position.set(seekerObj.x, 0, seekerObj.z); seekerObj.group.rotation.y = seekerObj.ry;
		}
		placeCamera();
		sun.target.position.set(MAP.w / 2, 0, MAP.d / 2);
		// 보고 있는 것
		const role = myRole();
		looked = playing() && role === 'hider' ? pick(9, false) : null;
		const blind = S && S.status === 'hide' && role === 'seeker';
		$('hs-blind').style.display = blind ? 'flex' : 'none';
		$('hs-cross').style.display = (playing() && !blind) ? 'block' : 'none';
		let hint = '';
		if (S && playing() && !document.pointerLockElement) hint = '화면을 눌러 시작 (마우스로 둘러보기)';
		else if (S && playing() && role === 'hider') {
			const lp = looked && looked.kind === 'prop' ? MAP.props.find((q) => q.id === looked.id) : null, sw = S.me.swaps || 0;
			if (lp) {
				const far = Math.hypot(lp.x - me.x, lp.z - me.z) > 4;
				hint = `<span class="hs-key">E</span> ${esc(PROPS[lp.type][0])}(으)로 변신${sw > 0 ? ` · <span class="hs-key">F</span> 이 물건을 치우고 그 자리에 (${sw}번 남음)` : ''}${far ? ' — 조금 더 가까이' : ''}`;
			} else hint = `지금 모습: ${esc(PROPS[me.prop]?.[0] || '')} ${me.lock ? '🔒' : ''} · 물건을 보고 <span class="hs-key">E</span> 변신${sw > 0 ? ` · <span class="hs-key">F</span> 자리 바꾸기 ${sw}번` : ''}`;
		}
		else if (S && playing() && role === 'seeker' && S.status === 'seek') hint = '수상한 물건을 클릭해서 쏘세요 — 진짜 물건이면 체력이 깎여요 · <span class="hs-key">M</span> 지도와 견줘 보기';
		$('hs-hint').innerHTML = hint;
		if (S && (S.status === 'hide' || S.status === 'seek')) {
			const left = Math.max(0, (deadline - now) / 1000);
			$('hs-timer').textContent = `${Math.floor(left / 60)}:${String(Math.floor(left % 60)).padStart(2, '0')}`;
			$('hs-blind-t').textContent = `${Math.ceil(left)}초 뒤에 눈을 떠요`;
		} else $('hs-timer').textContent = '';
		for (let i = tracers.length - 1; i >= 0; i--) if (now > tracers[i].until) { scene.remove(tracers[i].line); tracers[i].line.geometry.dispose(); tracers.splice(i, 1); }
		updateMap(now);
		updateTags();
	}
	renderer.render(scene, camera);
	requestAnimationFrame(frame);
}
resize();
camera.position.set(12, 20, 30); camera.lookAt(12, 0, 8);
requestAnimationFrame(frame);
window.__hs = { state: () => S, me, send, ents, THREE, removed, mapSt, toggleMap, looked: () => looked };
