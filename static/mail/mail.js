// MJ Mail — /mail/ 전체 화면과 오른쪽 아래 떠 있는 패널이 같이 쓰는 스크립트
// 서버 API: /mail/api/{state,unread,list,message,action,labels,draft,send}/ (관리자 세션 + CSRF)
(() => {
    const API = '/mail/api/';
    const csrf = () => document.querySelector('meta[name="mj-csrf"]')?.content || (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';

    async function api(path, { method = 'GET', body, query } = {}) {
        const q = query ? Object.fromEntries(Object.entries(query).filter(([, v]) => v !== '' && v != null)) : null;
        const url = API + path + '/' + (q ? '?' + new URLSearchParams(q) : '');
        const headers = { 'X-Requested-With': 'fetch' };
        if (method !== 'GET') headers['X-CSRFToken'] = csrf();
        if (body && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
        const res = await fetch(url, { method, headers, body, credentials: 'same-origin' });
        let data = null;
        try { data = await res.json(); } catch { /* 로그인 페이지 등 */ }
        if (!res.ok || !data || data.ok === false) throw new Error((data && data.error) || `요청 실패 (${res.status})`);
        return data;
    }

    const h = (tag, attrs = {}, children = []) => {
        const node = document.createElement(tag);
        for (const [k, v] of Object.entries(attrs)) {
            if (k === 'class') node.className = v;
            else if (k === 'text') node.textContent = v;
            else if (k === 'html') node.innerHTML = v;
            else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
            else if (v === false || v == null) continue;
            else node.setAttribute(k, v === true ? '' : v);
        }
        for (const c of [].concat(children)) if (c != null && c !== false) node.append(c);
        return node;
    };
    const fmtSize = (n) => n < 1024 ? `${n}B` : n < 1048576 ? `${(n / 1024).toFixed(0)}KB` : `${(n / 1048576).toFixed(1)}MB`;
    const store = {
        get: (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
        set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ } },
    };
    const AVATAR_COLORS = ['#0066cc', '#34c759', '#ff9500', '#af52de', '#ff2d55', '#5ac8fa', '#a2845e', '#1d1d1f'];
    const avatar = (name, email) => {
        const text = (name || email || '?').trim();
        let hash = 0; for (const ch of (email || text)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
        return h('span', { class: 'mjm__avatar', style: `background:${AVATAR_COLORS[hash % AVATAR_COLORS.length]}`, text: text.slice(0, 1).toUpperCase() });
    };
    const FOLDER_META = { inbox: ['📥', '받은 편지함'], sent: ['📤', '보낸 편지함'], drafts: ['📝', '임시 보관함'], junk: ['🚫', '스팸'], trash: ['🗑', '휴지통'] };
    const FILTERS = [['all', '전체'], ['unseen', '안 읽음'], ['flagged', '별표'], ['attach', '첨부']];

    // 받는 사람 자동완성용 주소록: 목록에 보인 주소를 모아 둠
    const contacts = () => store.get('mj:mail:contacts', {});
    const remember = (items) => {
        const book = contacts(); let changed = false;
        for (const a of items) { if (a && a.email && !book[a.email]) { book[a.email] = a.name || ''; changed = true; } }
        if (changed) store.set('mj:mail:contacts', book);
    };

    // ── 안 읽은 메일 수: 화면의 모든 [data-mail-unread] 배지에 반영, 1분마다 ──
    const unreadWatchers = new Set();
    let unreadTimer = 0;
    async function refreshUnread() {
        try {
            const { unread } = await api('unread');
            document.querySelectorAll('[data-mail-unread]').forEach((b) => { b.hidden = !unread; b.textContent = unread > 99 ? '99+' : unread; });
            unreadWatchers.forEach((fn) => fn(unread));
        } catch { /* 연결 안 되면 조용히 */ }
    }
    function watchUnread(fn) {
        if (fn) unreadWatchers.add(fn);
        if (!unreadTimer) {
            refreshUnread();
            unreadTimer = setInterval(() => { if (!document.hidden) refreshUnread(); }, 60000);
            document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshUnread(); });
        }
    }

    // ── 메일 화면 ──
    function create(root, { mode = 'full' } = {}) {
        const state = {
            folder: 'inbox', page: 1, q: '', filter: 'all', sort: 'newest', adv: {}, list: null, folders: [], current: null,
            selected: new Set(), pane: 'list', compose: null, cursor: -1,
        };
        const user = root.dataset.user || '';
        root.classList.add('mjm', `mjm--${mode}`);
        root.innerHTML = '';
        const foldersEl = h('nav', { class: 'mjm__folders', 'aria-label': '폴더' });
        const listEl = h('section', { class: 'mjm__list' });
        const readEl = h('section', { class: 'mjm__read' });
        const toast = h('div', { class: 'mjm__toast', hidden: true });
        root.append(foldersEl, listEl, readEl, toast);

        const say = (msg, isError) => {
            toast.textContent = msg; toast.hidden = false; toast.classList.toggle('is-error', !!isError);
            clearTimeout(say.t); say.t = setTimeout(() => { toast.hidden = true; }, isError ? 5000 : 2500);
        };
        const setPane = (p) => { state.pane = p; root.dataset.pane = p; };
        const folderLabel = (key) => { const f = state.folders.find((x) => x.key === key); if (f) return [f.icon, f.label]; return FOLDER_META[key] || ['🏷', key.replace(/^f:/, '')]; };
        const listQuery = () => ({ folder: state.folder, page: state.page, q: state.q, filter: state.filter, sort: state.sort, ...state.adv });
        const labels = () => state.folders.filter((f) => !f.system);

        // ── 폴더·라벨 ──
        function renderFolders() {
            foldersEl.innerHTML = '';
            if (mode === 'full') foldersEl.append(h('button', { class: 'mjm__compose-btn', type: 'button', text: '✏️ 메일 쓰기', onclick: () => openCompose() }));
            const wrap = h('div', { class: 'mjm__folderlist' });
            const list = state.folders.length ? state.folders : Object.keys(FOLDER_META).map((k) => ({ key: k, total: 0, unseen: 0, system: true }));
            for (const f of list.filter((x) => x.system)) wrap.append(folderButton(f));
            const lbs = list.filter((x) => !x.system);
            const head = h('div', { class: 'mjm__labels-head' }, [h('span', { text: '라벨' }), h('button', { type: 'button', class: 'mjm__mini', title: '라벨 만들기', text: '+', onclick: createLabel })]);
            wrap.append(head);
            for (const f of lbs) wrap.append(folderButton(f, true));
            if (!lbs.length) wrap.append(h('p', { class: 'mjm__labels-empty', text: '라벨을 만들어 메일을 분류해 보세요' }));
            foldersEl.append(wrap);
        }
        function folderButton(f, isLabel = false) {
            const [icon, label] = folderLabel(f.key);
            const btn = h('button', {
                type: 'button', class: `mjm__folder${f.key === state.folder ? ' is-active' : ''}`, title: `${label} ${f.total}통`,
                onclick: () => goFolder(f.key),
            }, [h('span', { class: 'mjm__folder-icon', text: icon }), h('span', { class: 'mjm__folder-label', text: label }),
                f.unseen ? h('span', { class: 'mjm__badge', text: f.unseen }) : (f.total && (f.key === 'drafts') ? h('span', { class: 'mjm__count', text: f.total }) : null)]);
            if (isLabel) {
                btn.append(h('span', { class: 'mjm__folder-tools' }, [
                    h('button', { type: 'button', class: 'mjm__mini', title: '이름 바꾸기', text: '✎', onclick: (e) => { e.stopPropagation(); renameLabel(f); } }),
                    h('button', { type: 'button', class: 'mjm__mini', title: '라벨 지우기', text: '×', onclick: (e) => { e.stopPropagation(); deleteLabel(f); } }),
                ]));
            }
            return btn;
        }
        function goFolder(key) { state.sentInfo = null; state.folder = key; state.page = 1; state.q = ''; state.adv = {}; state.filter = 'all'; state.selected.clear(); state.current = null; state.cursor = -1; renderFolders(); renderRead(); loadList(); setPane('list'); }
        async function loadFolders() {
            try { const { folders } = await api('state'); state.folders = folders; renderFolders(); if (mode === 'mini') renderList(); }
            catch (e) { say(e.message, true); }
        }
        async function createLabel() {
            const name = prompt('새 라벨 이름 (예: 학교, 영수증)'); if (!name) return;
            try { const r = await api('labels', { method: 'POST', body: { action: 'create', name: name.trim() } }); state.folders = r.folders; renderFolders(); say('라벨을 만들었어요'); }
            catch (e) { say(e.message, true); }
        }
        async function renameLabel(f) {
            const name = prompt('라벨 이름', f.label); if (!name || name === f.label) return;
            try { const r = await api('labels', { method: 'POST', body: { action: 'rename', folder: f.key, name: name.trim() } }); state.folders = r.folders; if (state.folder === f.key) state.folder = r.key; renderFolders(); }
            catch (e) { say(e.message, true); }
        }
        async function deleteLabel(f) {
            if (!confirm(`라벨 "${f.label}" 을 지울까요? (안에 메일이 있으면 지워지지 않아요)`)) return;
            try { const r = await api('labels', { method: 'POST', body: { action: 'delete', folder: f.key } }); state.folders = r.folders; if (state.folder === f.key) goFolder('inbox'); else renderFolders(); }
            catch (e) { say(e.message, true); }
        }

        // ── 목록 ──
        let advOpen = false;
        function renderList() {
            listEl.innerHTML = '';
            const [icon, label] = folderLabel(state.folder);
            const search = h('input', { class: 'mjm__search', type: 'search', placeholder: '메일 검색', value: state.q, 'data-search': true });
            search.addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.q = search.value.trim(); state.page = 1; loadList(); } if (e.key === 'Escape') search.blur(); });
            const folderSel = h('select', { class: 'mjm__folderselect', title: '폴더', onchange: (e) => goFolder(e.target.value) },
                (state.folders.length ? state.folders : Object.keys(FOLDER_META).map((k) => ({ key: k }))).map((f) => { const [i, l] = folderLabel(f.key); const o = h('option', { value: f.key, text: `${i} ${l}${f.unseen ? ` (${f.unseen})` : ''}` }); if (f.key === state.folder) o.selected = true; return o; }));
            const bar = h('div', { class: 'mjm__bar' }, [
                mode === 'mini' ? folderSel : h('h2', { class: 'mjm__title' }, [h('span', { text: `${icon} ${label}` }), state.list ? h('span', { class: 'mjm__dim', text: ` ${state.list.total}통` }) : null]),
                h('div', { class: 'mjm__searchwrap' }, [search, h('button', { type: 'button', class: 'mjm__iconbtn mjm__iconbtn--inset', title: '상세 검색', text: '⚙', onclick: () => { advOpen = !advOpen; renderList(); } })]),
                h('button', { type: 'button', class: 'mjm__iconbtn', title: '새로고침', text: '⟳', onclick: () => { loadList(); loadFolders(); } }),
                mode === 'mini' ? h('button', { type: 'button', class: 'mjm__iconbtn', title: '메일 쓰기', text: '✏️', onclick: () => openCompose() }) : null,
            ]);
            listEl.append(bar);
            if (advOpen) listEl.append(advancedPanel());
            // 필터 칩 + 정렬
            const chips = h('div', { class: 'mjm__chips' }, [
                ...FILTERS.map(([id, name]) => h('button', { type: 'button', class: `mjm__chip${state.filter === id ? ' is-active' : ''}`, text: name, onclick: () => { state.filter = id; state.page = 1; loadList(); } })),
                h('span', { class: 'mjm__spacer' }),
                h('button', { type: 'button', class: 'mjm__chip mjm__chip--ghost', title: '정렬', text: state.sort === 'oldest' ? '오래된 순 ↑' : '최신 순 ↓', onclick: () => { state.sort = state.sort === 'oldest' ? 'newest' : 'oldest'; state.page = 1; loadList(); } }),
            ]);
            listEl.append(chips);
            // 선택 바
            const selAll = h('input', { type: 'checkbox', class: 'mjm__cb', title: '전체 선택', 'aria-label': '전체 선택' });
            const items = state.list?.items || [];
            selAll.checked = items.length > 0 && items.every((m) => state.selected.has(m.uid));
            selAll.addEventListener('change', () => { items.forEach((m) => selAll.checked ? state.selected.add(m.uid) : state.selected.delete(m.uid)); renderList(); });
            const selMenu = h('select', { class: 'mjm__selmenu', title: '선택', onchange: (e) => { const v = e.target.value; e.target.value = ''; state.selected.clear(); items.forEach((m) => { if (v === 'all' || (v === 'read' && m.seen) || (v === 'unread' && !m.seen) || (v === 'flagged' && m.flagged)) state.selected.add(m.uid); }); renderList(); } },
                [['', '▾'], ['all', '모두'], ['none', '없음'], ['read', '읽은 메일'], ['unread', '안 읽은 메일'], ['flagged', '별표']].map(([v, t]) => h('option', { value: v, text: t })));
            const emptyBtn = (state.folder === 'junk' || state.folder === 'trash') && items.length ? h('button', { type: 'button', class: 'mjm__chip mjm__chip--danger', text: state.folder === 'junk' ? '스팸함 비우기' : '휴지통 비우기', onclick: emptyFolder }) : null;
            const selbar = h('div', { class: 'mjm__selbar' }, [
                h('span', { class: 'mjm__selall' }, [selAll, selMenu]),
                ...(state.selected.size ? [
                    h('span', { class: 'mjm__dim', text: `${state.selected.size}통` }),
                    h('button', { type: 'button', text: '읽음', onclick: () => act('seen') }),
                    h('button', { type: 'button', text: '안 읽음', onclick: () => act('unseen') }),
                    h('button', { type: 'button', text: '⭐', title: '별표', onclick: () => act('flag') }),
                    moveMenu((to) => act('move', { to })),
                    state.folder !== 'junk' ? h('button', { type: 'button', text: '스팸', onclick: () => act('move', { to: 'junk' }) }) : h('button', { type: 'button', text: '스팸 아님', onclick: () => act('move', { to: 'inbox' }) }),
                    h('button', { type: 'button', class: 'is-danger', text: state.folder === 'trash' ? '완전 삭제' : '삭제', onclick: () => act('delete') }),
                ] : [emptyBtn]),
            ]);
            listEl.append(selbar);
            // 행
            const ul = h('ul', { class: 'mjm__rows', role: 'list' });
            if (!state.list) ul.append(h('li', { class: 'mjm__empty', text: '불러오는 중…' }));
            else if (!items.length) ul.append(h('li', { class: 'mjm__empty' }, [h('span', { class: 'mjm__empty-icon', text: state.q || state.filter !== 'all' ? '🔍' : '🎉' }), h('span', { text: state.q || state.filter !== 'all' || Object.keys(state.adv).length ? '조건에 맞는 메일이 없어요' : '메일이 없어요' })]));
            let lastGroup = null;
            items.forEach((m, idx) => {
                if (m.group !== lastGroup && state.sort !== 'oldest') { ul.append(h('li', { class: 'mjm__group', text: m.group })); lastGroup = m.group; }
                const cb = h('input', { type: 'checkbox', class: 'mjm__cb', 'aria-label': '선택' });
                cb.checked = state.selected.has(m.uid);
                cb.addEventListener('click', (e) => { e.stopPropagation(); cb.checked ? state.selected.add(m.uid) : state.selected.delete(m.uid); renderList(); });
                const star = h('button', { type: 'button', class: `mjm__star${m.flagged ? ' is-on' : ''}`, title: m.flagged ? '별표 지우기' : '별표', text: m.flagged ? '★' : '☆', onclick: (e) => { e.stopPropagation(); toggleStar(m); } });
                const outgoing = state.folder === 'sent' || state.folder === 'drafts';
                const who = outgoing ? `받는 사람: ${m.to_text || '(없음)'}` : (m.from.name || m.from.email || '(보낸 사람 없음)');
                const row = h('li', {
                    class: `mjm__row${m.seen ? '' : ' is-unread'}${state.current?.uid === m.uid && state.current?.folder === m.folder ? ' is-current' : ''}${state.cursor === idx ? ' is-cursor' : ''}`,
                    'data-uid': m.uid, onclick: () => { state.cursor = idx; openMessage(m.uid); },
                }, [
                    h('span', { class: 'mjm__rowctl' }, [cb, star]),
                    outgoing ? null : avatar(m.from.name, m.from.email),
                    h('div', { class: 'mjm__rowmain' }, [
                        h('div', { class: 'mjm__rowtop' }, [h('span', { class: 'mjm__who', text: who, title: m.from_text || m.to_text }), h('span', { class: 'mjm__rowright' }, [m.has_attachment ? h('span', { class: 'mjm__clip', title: '첨부 있음', text: '📎' }) : null, h('span', { class: 'mjm__date', text: m.date_text })])]),
                        h('div', { class: 'mjm__subject' }, [m.draft ? h('span', { class: 'mjm__draft', text: '[초안] ' }) : null, m.answered ? h('span', { class: 'mjm__ans', title: '답장함', text: '↩ ' }) : null, h('span', { text: m.subject }), m.preview ? h('span', { class: 'mjm__preview', text: ` – ${m.preview}` }) : null]),
                    ]),
                    h('span', { class: 'mjm__hoveract' }, [
                        h('button', { type: 'button', title: m.seen ? '안 읽음으로' : '읽음으로', text: m.seen ? '✉' : '📭', onclick: (e) => { e.stopPropagation(); quick(m, m.seen ? 'unseen' : 'seen'); } }),
                        h('button', { type: 'button', title: '삭제', text: '🗑', onclick: (e) => { e.stopPropagation(); quick(m, 'delete'); } }),
                    ]),
                ]);
                ul.append(row);
            });
            listEl.append(ul);
            if (state.list && state.list.pages > 1) {
                listEl.append(h('div', { class: 'mjm__pager' }, [
                    h('button', { type: 'button', disabled: state.page <= 1, text: '‹', onclick: () => { state.page -= 1; loadList(); } }),
                    h('span', { text: `${(state.page - 1) * 30 + 1}–${Math.min(state.page * 30, state.list.total)} / ${state.list.total}` }),
                    h('button', { type: 'button', disabled: state.page >= state.list.pages, text: '›', onclick: () => { state.page += 1; loadList(); } }),
                ]));
            }
        }
        function advancedPanel() {
            const f = (name, label, type = 'text') => h('label', { class: 'mjm__advfield' }, [h('span', { text: label }), h('input', { name, type, value: state.adv[name] || '' })]);
            const form = h('form', { class: 'mjm__adv' }, [
                f('from', '보낸 사람'), f('to', '받는 사람'), f('subject', '제목'), f('text', '본문 낱말'), f('since', '이후', 'date'), f('before', '이전', 'date'),
                h('div', { class: 'mjm__advbar' }, [h('button', { type: 'submit', class: 'mjm__send', text: '검색' }), h('button', { type: 'button', text: '초기화', onclick: () => { state.adv = {}; state.q = ''; state.page = 1; advOpen = false; loadList(); } })]),
            ]);
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                const fd = new FormData(form); state.adv = {};
                for (const [k, v] of fd.entries()) if (String(v).trim()) state.adv[k] = String(v).trim();
                state.page = 1; loadList();
            });
            return form;
        }
        function moveMenu(onPick) {
            const sel = h('select', { class: 'mjm__selmenu', title: '폴더로 이동', onchange: (e) => { const v = e.target.value; e.target.value = ''; if (v) onPick(v); } });
            sel.append(h('option', { value: '', text: '이동 ▾' }));
            for (const f of state.folders.filter((x) => x.key !== state.folder && x.key !== 'drafts' && x.key !== 'sent')) { const [i, l] = folderLabel(f.key); sel.append(h('option', { value: f.key, text: `${i} ${l}` })); }
            return sel;
        }
        async function loadList() {
            state.list = null; renderList();
            try { state.list = await api('list', { query: listQuery() }); remember(state.list.items.map((m) => m.from)); }
            catch (e) { say(e.message, true); state.list = { items: [], total: 0, pages: 1 }; }
            renderList();
        }
        async function act(action, extra = {}) {
            const uids = [...state.selected];
            if (!uids.length) return;
            if (action === 'delete' && state.folder === 'trash' && !confirm(`${uids.length}통을 완전히 지울까요? 되돌릴 수 없어요.`)) return;
            try {
                await api('action', { method: 'POST', body: { folder: state.folder, uids, action, ...extra } });
                state.selected.clear();
                if (state.current && uids.includes(state.current.uid) && ['delete', 'move'].includes(action)) { state.current = null; renderRead(); }
                say({ delete: '지웠어요', move: '옮겼어요', flag: '별표를 붙였어요' }[action] || '바꿨어요');
                loadList(); loadFolders(); refreshUnread();
            } catch (e) { say(e.message, true); }
        }
        async function quick(m, action) {
            try {
                await api('action', { method: 'POST', body: { folder: m.folder, uids: [m.uid], action } });
                if (action === 'delete') { if (state.current?.uid === m.uid) { state.current = null; renderRead(); } loadList(); loadFolders(); }
                else { m.seen = action === 'seen'; renderList(); loadFolders(); }
                refreshUnread();
            } catch (e) { say(e.message, true); }
        }
        async function toggleStar(m) {
            try { await api('action', { method: 'POST', body: { folder: m.folder, uids: [m.uid], action: m.flagged ? 'unflag' : 'flag' } }); m.flagged = !m.flagged; if (state.current?.uid === m.uid) state.current.flagged = m.flagged; renderList(); if (state.current?.uid === m.uid) renderRead(); }
            catch (e) { say(e.message, true); }
        }
        async function emptyFolder() {
            const [, label] = folderLabel(state.folder);
            if (!confirm(`${label}의 메일을 모두 완전히 지울까요? 되돌릴 수 없어요.`)) return;
            try { const r = await api('action', { method: 'POST', body: { folder: state.folder, action: 'empty' } }); say(`${r.count}통을 지웠어요`); state.current = null; renderRead(); loadList(); loadFolders(); }
            catch (e) { say(e.message, true); }
        }

        // ── 읽기 ──
        function renderRead() {
            readEl.innerHTML = '';
            const m = state.current;
            if (state.compose) { readEl.append(state.compose); return; }
            if (state.sentInfo) {  // 방금 보낸 뒤 안내
                const info = state.sentInfo;
                readEl.append(h('div', { class: 'mjm__sent' }, [
                    h('div', { class: 'mjm__sent-icon', text: '✓' }),
                    h('h3', { class: 'mjm__sent-title', text: '메일 발송이 완료되었습니다' }),
                    h('p', { class: 'mjm__dim', text: `${info.time} · 받는 사람 ${info.to}${info.cc ? ' · 참조 ' + info.cc : ''}` }),
                    h('p', { class: 'mjm__sent-subject', text: info.subject || '(제목 없음)' }),
                    h('div', { class: 'mjm__sent-actions' }, [
                        h('button', { type: 'button', class: 'mjm__send', text: '보낸 편지함 보기', onclick: () => { state.sentInfo = null; goFolder('sent'); } }),
                        h('button', { type: 'button', text: '새 메일', onclick: () => { state.sentInfo = null; openCompose(); } }),
                        h('button', { type: 'button', text: '닫기', onclick: () => { state.sentInfo = null; renderRead(); if (mode === 'mini') setPane('list'); } }),
                    ]),
                ]));
                return;
            }
            if (!m) { readEl.append(h('div', { class: 'mjm__empty mjm__empty--read' }, [h('span', { class: 'mjm__empty-icon', text: '✉️' }), h('span', { text: mode === 'full' ? '왼쪽에서 메일을 고르세요' : '' })])); return; }
            const toolbar = h('div', { class: 'mjm__toolbar' }, [
                h('button', { type: 'button', class: 'mjm__back', text: '‹ 목록', onclick: () => { setPane('list'); } }),
                h('span', { class: 'mjm__tb-group' }, [
                    h('button', { type: 'button', title: '이전 메일 (k)', text: '‹', disabled: !m.prev_uid, onclick: () => openMessage(m.prev_uid) }),
                    h('button', { type: 'button', title: '다음 메일 (j)', text: '›', disabled: !m.next_uid, onclick: () => openMessage(m.next_uid) }),
                ]),
                h('span', { class: 'mjm__spacer' }),
                m.folder === 'drafts' ? h('button', { type: 'button', class: 'mjm__primary', text: '✏️ 이어 쓰기', onclick: () => openCompose({ draft: m }) }) : null,
                m.folder !== 'drafts' ? h('button', { type: 'button', title: '답장 (r)', text: '↩ 답장', onclick: () => openCompose({ reply: m }) }) : null,
                m.folder !== 'drafts' && (m.cc.length || m.to.length > 1) ? h('button', { type: 'button', title: '전체 답장 (a)', text: '↩↩ 전체', onclick: () => openCompose({ reply: m, all: true }) }) : null,
                h('button', { type: 'button', title: '전달 (f)', text: '↪ 전달', onclick: () => openCompose({ forward: m }) }),
                h('button', { type: 'button', class: `mjm__star mjm__star--tb${m.flagged ? ' is-on' : ''}`, title: '별표 (s)', text: m.flagged ? '★' : '☆', onclick: () => toggleStar(rowOf(m) || m) }),
                moveMenu((to) => one('move', { to })),
                m.folder !== 'junk' ? h('button', { type: 'button', text: '스팸', onclick: () => one('move', { to: 'junk' }) }) : h('button', { type: 'button', text: '스팸 아님', onclick: () => one('move', { to: 'inbox' }) }),
                h('button', { type: 'button', class: 'is-danger', title: '삭제 (#)', text: '🗑', onclick: () => one('delete') }),
                h('select', { class: 'mjm__selmenu', title: '더보기', onchange: (e) => { const v = e.target.value; e.target.value = ''; if (v === 'unseen') one('unseen'); if (v === 'raw') window.open(m.raw_url, '_blank'); if (v === 'print') printMessage(m); if (v === 'copy') { navigator.clipboard?.writeText(m.from.email); say('주소를 복사했어요'); } } },
                    [['', '⋯'], ['unseen', '안 읽음으로'], ['copy', '보낸 사람 주소 복사'], ['raw', '원본 보기'], ['print', '인쇄']].map(([v, t]) => h('option', { value: v, text: t }))),
            ]);
            readEl.append(toolbar);
            const head = h('div', { class: 'mjm__readhead' }, [
                h('h3', { class: 'mjm__readsubject', text: m.subject }),
                h('div', { class: 'mjm__sender' }, [avatar(m.from.name, m.from.email), h('div', { class: 'mjm__meta' }, [
                    h('div', {}, [h('b', { text: m.from.name || m.from.email }), m.from.name ? h('span', { class: 'mjm__dim', text: ` <${m.from.email}>` }) : null]),
                    h('div', { class: 'mjm__dim', text: `받는 사람 ${m.to_text || '-'}${m.cc_text ? ' · 참조 ' + m.cc_text : ''}${m.bcc_text ? ' · 숨은 참조 ' + m.bcc_text : ''}` }),
                ]), h('div', { class: 'mjm__dim mjm__readdate', text: m.date_text })]),
            ]);
            readEl.append(head);
            if (m.has_remote_images) readEl.append(h('div', { class: 'mjm__notice' }, [h('span', { text: '추적 방지를 위해 외부 그림을 불러오지 않았어요. ' }), h('button', { type: 'button', text: '그림 보기', onclick: () => openMessage(m.uid, { images: true }) })]));
            const frame = h('iframe', { class: 'mjm__body', sandbox: 'allow-same-origin allow-popups allow-popups-to-escape-sandbox', title: '메일 본문' });
            frame.srcdoc = bodyDoc(m.body_html);
            frame.addEventListener('load', () => { try { frame.style.height = Math.min(6000, frame.contentDocument.body.scrollHeight + 30) + 'px'; } catch { /* sandbox */ } });
            readEl.append(frame);
            const files = m.attachments.filter((a) => !(a.inline && a.content_type.startsWith('image/') && m.is_html));
            if (files.length) readEl.append(h('div', { class: 'mjm__atts' }, [h('b', { text: `첨부 ${files.length}개` }), ...files.map((a) => h('a', { class: 'mjm__att', href: a.url, download: a.filename, text: `📎 ${a.filename} (${fmtSize(a.size)})` }))]));
            if (m.folder !== 'drafts') readEl.append(h('div', { class: 'mjm__quickreply' }, [h('button', { type: 'button', text: '↩ 답장', onclick: () => openCompose({ reply: m }) }), h('button', { type: 'button', text: '↪ 전달', onclick: () => openCompose({ forward: m }) })]));
            async function one(action, extra = {}) {
                try {
                    await api('action', { method: 'POST', body: { folder: m.folder, uids: [m.uid], action, ...extra } });
                    if (action !== 'unseen') { const next = m.next_uid || m.prev_uid; state.current = null; renderRead(); if (next && mode === 'full') openMessage(next); else if (mode === 'mini') setPane('list'); }
                    say({ delete: '지웠어요', move: '옮겼어요' }[action] || '안 읽음으로 바꿨어요');
                    loadList(); loadFolders(); refreshUnread();
                } catch (e) { say(e.message, true); }
            }
        }
        const rowOf = (m) => state.list?.items.find((x) => x.uid === m.uid);
        const bodyDoc = (html) => `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline'"><base target="_blank"><style>body{font:14px/1.65 system-ui,-apple-system,sans-serif;color:#1d1d1f;margin:14px;word-break:break-word}img{max-width:100%;height:auto}img[data-src]{display:none}blockquote{border-left:3px solid #ddd;margin:8px 0;padding-left:10px;color:#555}pre{white-space:pre-wrap}a{color:#0066cc}</style></head><body>${html}</body></html>`;
        function printMessage(m) {
            const w = window.open('', '_blank'); if (!w) return;
            w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${m.subject.replace(/</g, '&lt;')}</title><style>body{font:14px/1.6 system-ui;margin:24px;color:#111}h1{font-size:18px}.meta{color:#555;font-size:12px;margin-bottom:16px}img[data-src]{display:none}</style></head><body><h1>${m.subject.replace(/</g, '&lt;')}</h1><div class="meta">${m.from_text.replace(/</g, '&lt;')}<br>받는 사람 ${m.to_text.replace(/</g, '&lt;')}<br>${m.date_text}</div>${m.body_html}</body></html>`);
            w.document.close(); setTimeout(() => w.print(), 300);
        }
        async function openMessage(uid, { images = false } = {}) {
            if (state.compose && !confirm('쓰던 메일을 닫을까요? (임시 저장을 안 했으면 사라져요)')) return;
            state.compose = null; state.sentInfo = null;
            setPane('read');
            readEl.innerHTML = ''; readEl.append(h('div', { class: 'mjm__empty mjm__empty--read', text: '불러오는 중…' }));
            try {
                state.current = await api('message', { query: { ...listQuery(), uid, images: images ? 1 : 0 } });
                const idx = state.list?.items.findIndex((x) => x.uid === uid); if (idx >= 0) state.cursor = idx;
                renderRead();
                const row = rowOf(state.current); if (row && !row.seen) { row.seen = true; refreshUnread(); loadFolders(); }
                renderList();
                remember([state.current.from, ...state.current.to, ...state.current.cc]);
            } catch (e) { say(e.message, true); state.current = null; renderRead(); }
        }

        // ── 쓰기 ──
        function openCompose({ reply, forward, draft, all = false, to = '' } = {}) {
            const sig = store.get('mj:mail:sig', '');
            const quote = (m) => `\n\n${m.date_text}에 ${m.from_text} 님이 쓴 글:\n> ` + (m.text || stripHtml(m.body_html)).trim().split('\n').join('\n> ');
            const init = { to, cc: '', bcc: '', subject: '', body: sig ? `\n\n-- \n${sig}` : '', in_reply_to: '', references: '', reply_folder: '', reply_uid: '', draft_uid: '' };
            if (reply) {
                const others = all ? [...reply.to, ...reply.cc].map((a) => a.email).filter((e) => e && e !== user && e !== reply.from.email) : [];
                Object.assign(init, { to: reply.reply_to, cc: others.join(', '), subject: /^re:/i.test(reply.subject) ? reply.subject : `Re: ${reply.subject}`, body: (sig ? `\n\n-- \n${sig}` : '') + quote(reply), in_reply_to: reply.message_id, references: reply.references, reply_folder: reply.folder, reply_uid: reply.uid });
            }
            if (forward) Object.assign(init, { subject: /^fwd?:/i.test(forward.subject) ? forward.subject : `Fwd: ${forward.subject}`, body: (sig ? `\n\n-- \n${sig}` : '') + `\n\n---------- 전달한 메일 ----------\n보낸 사람: ${forward.from_text}\n날짜: ${forward.date_text}\n제목: ${forward.subject}\n받는 사람: ${forward.to_text}\n\n${(forward.text || stripHtml(forward.body_html)).trim()}` });
            if (draft) Object.assign(init, { to: draft.to_text, cc: draft.cc_text, bcc: draft.bcc_text, subject: draft.subject === '(제목 없음)' ? '' : draft.subject, body: draft.text || stripHtml(draft.body_html), draft_uid: draft.uid });
            const form = h('form', { class: 'mjm__compose', enctype: 'multipart/form-data' });
            const dl = h('datalist', { id: 'mjm-contacts' }, Object.entries(contacts()).map(([e, n]) => h('option', { value: n ? `${n} <${e}>` : e })));
            const field = (name, label, value = '', hidden = false) => h('label', { class: 'mjm__field', hidden }, [h('span', { text: label }), h('input', { name, type: 'text', value, placeholder: name === 'to' ? '이름 <주소> 또는 주소, 여러 명은 쉼표' : '', list: 'mjm-contacts', autocomplete: 'off' })]);
            const ccField = field('cc', '참조', init.cc, !init.cc), bccField = field('bcc', '숨은 참조', init.bcc, !init.bcc);
            const body = h('textarea', { name: 'body', rows: mode === 'mini' ? 9 : 14, placeholder: '내용' }); body.value = init.body;
            const files = h('input', { type: 'file', name: 'attachments', multiple: true });
            const submit = h('button', { type: 'submit', class: 'mjm__send', text: '보내기' });
            const draftBtn = h('button', { type: 'button', text: '임시 저장', onclick: () => saveDraft(false) });
            const status = h('span', { class: 'mjm__dim mjm__draftstatus' });
            const toField = field('to', '받는 사람', init.to);
            form.append(
                h('div', { class: 'mjm__toolbar' }, [h('button', { type: 'button', class: 'mjm__back', text: '‹ 닫기', onclick: closeCompose }), h('h3', { class: 'mjm__readsubject mjm__readsubject--tb', text: reply ? (all ? '전체 답장' : '답장') : forward ? '전달' : draft ? '초안 이어 쓰기' : '새 메일' }), h('span', { class: 'mjm__spacer' }),
                    h('button', { type: 'button', class: 'mjm__mini', text: '참조', title: '참조 칸', onclick: () => { ccField.hidden = !ccField.hidden; } }), h('button', { type: 'button', class: 'mjm__mini', text: '숨은 참조', onclick: () => { bccField.hidden = !bccField.hidden; } }),
                    h('button', { type: 'button', class: 'mjm__mini', text: '서명', title: '서명 설정', onclick: () => { const s = prompt('서명 (메일 끝에 붙어요, 비우면 없음)', store.get('mj:mail:sig', '')); if (s !== null) { store.set('mj:mail:sig', s.trim()); say('서명을 저장했어요'); } } })]),
                dl, toField, ccField, bccField, field('subject', '제목', init.subject), body,
                h('label', { class: 'mjm__files' }, ['📎 첨부 (모두 20MB 까지) ', files]),
                h('div', { class: 'mjm__composebar' }, [submit, draftBtn, status, h('span', { class: 'mjm__spacer' }), h('span', { class: 'mjm__dim', text: `보내는 사람: ${root.dataset.fromName ? root.dataset.fromName + ' ' : ''}<${user}>` })]),
            );
            for (const [k, v] of Object.entries({ in_reply_to: init.in_reply_to, references: init.references, reply_folder: init.reply_folder, reply_uid: init.reply_uid, draft_uid: init.draft_uid })) form.append(h('input', { type: 'hidden', name: k, value: v }));
            let dirty = false, autosave = 0;
            form.addEventListener('input', () => { dirty = true; clearTimeout(autosave); autosave = setTimeout(() => { if (dirty) saveDraft(true); }, 30000); });
            async function saveDraft(auto) {
                const fd = new FormData(form); fd.delete('attachments');
                try { const r = await api('draft', { method: 'POST', body: fd }); form.querySelector('[name=draft_uid]').value = r.uid; dirty = false; status.textContent = `${auto ? '자동 ' : ''}임시 저장 ${new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`; loadFolders(); if (state.folder === 'drafts') loadList(); }
                catch (e) { if (!auto) say(e.message, true); }
            }
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                submit.disabled = true; submit.textContent = '보내는 중…'; clearTimeout(autosave);
                try {
                    const fd = new FormData(form);
                    await api('send', { method: 'POST', body: fd });
                    say('보냈어요'); state.compose = null; dirty = false;
                    state.sentInfo = { to: fd.get('to'), cc: fd.get('cc'), subject: fd.get('subject'), time: new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' }) };
                    if (reply) { const row = rowOf(reply); if (row) row.answered = true; }
                    state.current = null; renderRead(); setPane('read'); renderList(); loadFolders();
                } catch (err) { say(err.message, true); submit.disabled = false; submit.textContent = '보내기'; }
            });
            function closeCompose() {
                if (dirty && !confirm('쓰던 메일을 닫을까요? (임시 저장 안 한 내용은 사라져요)')) return;
                clearTimeout(autosave); state.compose = null; renderRead(); if (mode === 'mini' && !state.current) setPane('list');
            }
            state.compose = form;
            renderRead(); setPane('read');
            (reply || forward ? body : toField.querySelector('input')).focus();
            if (reply || forward) body.setSelectionRange(0, 0);
        }
        const stripHtml = (html) => { const d = document.createElement('div'); d.innerHTML = html; d.querySelectorAll('style,script').forEach((n) => n.remove()); return d.innerText || d.textContent || ''; };

        // ── 단축키 (전체 화면) ──
        if (mode === 'full') {
            document.addEventListener('keydown', (e) => {
                const tag = (e.target.tagName || '').toLowerCase();
                if (['input', 'textarea', 'select'].includes(tag) || e.metaKey || e.ctrlKey || e.altKey) { if (e.key === 'Escape' && tag === 'input') e.target.blur(); return; }
                const items = state.list?.items || [];
                const cur = state.current;
                const keys = {
                    c: () => openCompose(), '/': () => listEl.querySelector('[data-search]')?.focus(),
                    j: () => { if (cur?.next_uid) openMessage(cur.next_uid); else if (!cur && items.length) { state.cursor = Math.min(items.length - 1, state.cursor + 1); renderList(); } },
                    k: () => { if (cur?.prev_uid) openMessage(cur.prev_uid); else if (!cur && items.length) { state.cursor = Math.max(0, state.cursor - 1); renderList(); } },
                    Enter: () => { if (!cur && items[state.cursor]) openMessage(items[state.cursor].uid); },
                    r: () => cur && openCompose({ reply: cur }), a: () => cur && openCompose({ reply: cur, all: true }), f: () => cur && openCompose({ forward: cur }),
                    s: () => { const m = cur ? (rowOf(cur) || cur) : items[state.cursor]; if (m) toggleStar(m); },
                    '#': () => { const m = cur || items[state.cursor]; if (m) quick(m, 'delete'); },
                    u: () => { state.current = null; renderRead(); setPane('list'); },
                    Escape: () => { if (state.compose) { state.compose = null; renderRead(); } },
                };
                if (keys[e.key]) { e.preventDefault(); keys[e.key](); }
            });
        } else {
            root.addEventListener('keydown', (e) => { if (e.key === 'Escape' && state.compose) { state.compose = null; renderRead(); setPane('list'); } });
        }

        renderFolders(); renderList(); renderRead(); setPane('list');
        loadFolders(); loadList();
        let lastUnread = null;
        watchUnread((n) => { if (lastUnread !== null && n !== lastUnread && state.folder === 'inbox' && !document.hidden && !state.compose && !state.selected.size) { loadList(); loadFolders(); } lastUnread = n; });
        return { reload: () => { loadList(); loadFolders(); }, compose: openCompose, go: goFolder };
    }

    window.MjMail = { create, watchUnread, refreshUnread };
})();
