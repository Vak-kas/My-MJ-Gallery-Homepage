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
    let lastUnread = null;
    async function refreshUnread() {
        try {
            const { unread } = await api('unread');
            document.querySelectorAll('[data-mail-unread]').forEach((b) => { b.hidden = !unread; b.textContent = unread > 99 ? '99+' : unread; });
            // 새 메일이 늘었으면 떠 있는 메일 버튼의 뻐꾸기가 날아와 앉음 (처음 읽을 때는 안 함)
            const fab = document.getElementById('mail-fab');
            if (fab && lastUnread !== null && unread > lastUnread) {
                fab.classList.remove('is-arrive'); void fab.offsetWidth; fab.classList.add('is-arrive');
                setTimeout(() => fab.classList.remove('is-arrive'), 1500);
            }
            lastUnread = unread;
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
            signature: '', contacts: {}, scheduled: [], appPasswords: [], imapHost: '',
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
        const nameOf = (a) => (a && a.email && state.contacts[a.email.toLowerCase()]?.name) || a?.name || a?.email || '';
        const esc = (t) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

        // ── 폴더·라벨 ──
        function renderFolders() {
            foldersEl.innerHTML = '';
            if (mode === 'full') foldersEl.append(h('button', { class: 'mjm__compose-btn', type: 'button', text: '✏️ 메일 쓰기', onclick: () => openCompose() }),
                h('div', { class: 'mjm__quicklinks' }, [h('button', { type: 'button', class: 'mjm__mini', text: '내게 쓰기', onclick: () => openCompose({ to: user, self: true }) }), h('button', { type: 'button', class: 'mjm__mini', text: '⚙ 설정', onclick: openSettings })]));
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
            try {
                const r = await api('state');
                Object.assign(state, { folders: r.folders, signature: r.signature || '', contacts: r.contacts || {}, scheduled: r.scheduled || [], appPasswords: r.app_passwords || [], imapHost: r.imap_host || '' });
                renderFolders(); if (mode === 'mini') renderList();
            } catch (e) { say(e.message, true); }
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
                mode === 'mini' ? h('button', { type: 'button', class: 'mjm__iconbtn', title: '설정', text: '⚙', onclick: () => openSettings() }) : null,
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
                const who = outgoing ? `받는 사람: ${m.to_text || '(없음)'}` : (nameOf(m.from) || '(보낸 사람 없음)');
                const row = h('li', {
                    class: `mjm__row${m.seen ? '' : ' is-unread'}${state.current?.uid === m.uid && state.current?.folder === m.folder ? ' is-current' : ''}${state.cursor === idx ? ' is-cursor' : ''}`,
                    'data-uid': m.uid, onclick: () => { state.cursor = idx; openMessage(m.uid); },
                }, [
                    h('span', { class: 'mjm__rowctl' }, [cb, star]),
                    outgoing ? null : avatar(nameOf(m.from), m.from.email),
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
                    h('h3', { class: 'mjm__sent-title', text: info.scheduled ? '예약 발송을 등록했어요' : '메일 발송이 완료되었습니다' }),
                    h('p', { class: 'mjm__dim', text: `${info.time} · 받는 사람 ${info.to}${info.cc ? ' · 참조 ' + info.cc : ''}` }),
                    h('p', { class: 'mjm__sent-subject', text: info.subject || '(제목 없음)' }),
                    h('div', { class: 'mjm__sent-actions' }, [
                        info.scheduled ? h('button', { type: 'button', class: 'mjm__send', text: '예약 목록 보기', onclick: () => { state.sentInfo = null; openSettings('scheduled'); } }) : h('button', { type: 'button', class: 'mjm__send', text: '보낸 편지함 보기', onclick: () => { state.sentInfo = null; goFolder('sent'); } }),
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
                h('div', { class: 'mjm__sender' }, [avatar(nameOf(m.from), m.from.email), h('div', { class: 'mjm__meta' }, [
                    h('div', {}, [h('b', { text: nameOf(m.from) || m.from.email }), nameOf(m.from) ? h('span', { class: 'mjm__dim', text: ` <${m.from.email}>` }) : null,
                        h('button', { type: 'button', class: 'mjm__mini mjm__mini--inline', title: '이 주소의 표시 이름 정하기', text: state.contacts[m.from.email?.toLowerCase()] ? '이름 바꾸기' : '이름 정하기', onclick: () => setContact(m.from.email, nameOf(m.from)) })]),
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

        // ── 쓰기 (서식 편집기: HTML 로 보내고 글자 본문도 같이) ──
        function openCompose({ reply, forward, draft, all = false, to = '', self = false } = {}) {
            const sigBlock = state.signature ? `<br><br><div class="mjm-sig">-- <br>${state.signature}</div>` : '';
            const quoteBlock = (m) => `<br><br><div class="mjm-quote-head">${esc(m.date_text)}에 ${esc(m.from_text)} 님이 쓴 글:</div><blockquote style="border-left:3px solid #ddd;margin:8px 0;padding-left:10px;color:#555">${m.body_html || esc(m.text).replace(/\n/g, '<br>')}</blockquote>`;
            const init = { to, cc: '', bcc: '', subject: '', html: sigBlock, in_reply_to: '', references: '', reply_folder: '', reply_uid: '', draft_uid: '' };
            if (self) init.subject = '[메모] ';
            if (reply) {
                const others = all ? [...reply.to, ...reply.cc].map((a) => a.email).filter((e) => e && e !== user && e !== reply.from.email) : [];
                Object.assign(init, { to: reply.reply_to, cc: others.join(', '), subject: /^re:/i.test(reply.subject) ? reply.subject : `Re: ${reply.subject}`, html: sigBlock + quoteBlock(reply), in_reply_to: reply.message_id, references: reply.references, reply_folder: reply.folder, reply_uid: reply.uid });
            }
            if (forward) Object.assign(init, { subject: /^fwd?:/i.test(forward.subject) ? forward.subject : `Fwd: ${forward.subject}`, html: sigBlock + `<br><br><div class="mjm-quote-head">---------- 전달한 메일 ----------<br>보낸 사람: ${esc(forward.from_text)}<br>날짜: ${esc(forward.date_text)}<br>제목: ${esc(forward.subject)}<br>받는 사람: ${esc(forward.to_text)}</div><br>${forward.body_html || esc(forward.text).replace(/\n/g, '<br>')}` });
            if (draft) Object.assign(init, { to: draft.to_text, cc: draft.cc_text, bcc: draft.bcc_text, subject: draft.subject === '(제목 없음)' ? '' : draft.subject, html: draft.is_html ? draft.body_html : esc(draft.text).replace(/\n/g, '<br>'), draft_uid: draft.uid });
            const form = h('form', { class: 'mjm__compose', enctype: 'multipart/form-data' });
            const dl = h('datalist', { id: 'mjm-contacts' }, [...new Set([...Object.keys(state.contacts), ...Object.keys(contacts())])].map((e) => { const n = state.contacts[e]?.name || contacts()[e]; return h('option', { value: n ? `${n} <${e}>` : e }); }));
            const field = (name, label, value = '', hidden = false) => h('label', { class: 'mjm__field', hidden }, [h('span', { text: label }), h('input', { name, type: 'text', value, placeholder: name === 'to' ? '이름 <주소> 또는 주소, 여러 명은 쉼표' : '', list: 'mjm-contacts', autocomplete: 'off' })]);
            const ccField = field('cc', '참조', init.cc, !init.cc), bccField = field('bcc', '숨은 참조', init.bcc, !init.bcc);
            const subjectField = field('subject', '제목', init.subject);
            const editor = h('div', { class: 'mjm__editor', contenteditable: 'true', 'data-placeholder': '내용' });
            editor.innerHTML = init.html;
            const cmd = (name, value = null) => { editor.focus(); document.execCommand(name, false, value); };
            const tb = h('div', { class: 'mjm__fmt' }, [
                ['bold', '<b>B</b>', '굵게 (⌘B)'], ['italic', '<i>I</i>', '기울임 (⌘I)'], ['underline', '<u>U</u>', '밑줄 (⌘U)'], ['strikeThrough', '<s>S</s>', '취소선'],
            ].map(([c, html, title]) => h('button', { type: 'button', html, title, onmousedown: (e) => e.preventDefault(), onclick: () => cmd(c) })));
            tb.append(
                h('span', { class: 'mjm__fmt-sep' }),
                h('button', { type: 'button', text: '• 목록', title: '글머리 목록', onmousedown: (e) => e.preventDefault(), onclick: () => cmd('insertUnorderedList') }),
                h('button', { type: 'button', text: '1. 목록', title: '번호 목록', onmousedown: (e) => e.preventDefault(), onclick: () => cmd('insertOrderedList') }),
                h('button', { type: 'button', text: '🔗', title: '링크', onmousedown: (e) => e.preventDefault(), onclick: () => { const u = prompt('링크 주소 (https://…)'); if (u) cmd('createLink', u); } }),
                h('select', { class: 'mjm__selmenu', title: '글자 크기', onmousedown: (e) => e.stopPropagation(), onchange: (e) => { if (e.target.value) cmd('fontSize', e.target.value); e.target.value = ''; } }, [['', '크기'], ['2', '작게'], ['3', '보통'], ['5', '크게'], ['6', '아주 크게']].map(([v, t]) => h('option', { value: v, text: t }))),
                h('input', { type: 'color', title: '글자색', value: '#1d1d1f', oninput: (e) => cmd('foreColor', e.target.value) }),
                h('button', { type: 'button', text: '서식 지우기', onmousedown: (e) => e.preventDefault(), onclick: () => cmd('removeFormat') }),
                h('span', { class: 'mjm__spacer' }),
            );
            const files = h('input', { type: 'file', name: 'attachments', multiple: true });
            const submit = h('button', { type: 'submit', class: 'mjm__send', text: '보내기' });
            const draftBtn = h('button', { type: 'button', text: '임시 저장', onclick: () => saveDraft(false) });
            const previewBtn = h('button', { type: 'button', text: '미리보기', onclick: () => togglePreview() });
            const scheduleBtn = h('button', { type: 'button', text: '⏰ 예약', onclick: () => toggleSchedule() });
            const status = h('span', { class: 'mjm__dim mjm__draftstatus' });
            const toField = field('to', '받는 사람', init.to);
            const previewBox = h('div', { class: 'mjm__previewbox', hidden: true });
            const scheduleBox = h('div', { class: 'mjm__schedulebox', hidden: true }, [
                h('label', {}, ['보낼 시각 ', h('input', { type: 'datetime-local', name: 'send_at_local', min: localIso(new Date(Date.now() + 5 * 60000)) })]),
                h('button', { type: 'button', class: 'mjm__send', text: '예약하기', onclick: () => doSchedule() }),
                h('span', { class: 'mjm__dim', text: '그 시각에 서버가 대신 보내요 (1분 단위). 설정 › 예약에서 취소할 수 있어요' }),
            ]);
            form.append(
                h('div', { class: 'mjm__toolbar' }, [h('button', { type: 'button', class: 'mjm__back', text: '‹ 닫기', onclick: closeCompose }), h('h3', { class: 'mjm__readsubject mjm__readsubject--tb', text: reply ? (all ? '전체 답장' : '답장') : forward ? '전달' : draft ? '초안 이어 쓰기' : self ? '내게 쓰기' : '새 메일' }), h('span', { class: 'mjm__spacer' }),
                    h('button', { type: 'button', class: 'mjm__mini', text: '참조', title: '참조 칸', onclick: () => { ccField.hidden = !ccField.hidden; } }), h('button', { type: 'button', class: 'mjm__mini', text: '숨은 참조', onclick: () => { bccField.hidden = !bccField.hidden; } }),
                    h('button', { type: 'button', class: 'mjm__mini', text: '서명 편집', onclick: openSettings })]),
                dl, toField, ccField, bccField, subjectField, tb, editor, previewBox, scheduleBox,
                h('label', { class: 'mjm__files' }, ['📎 첨부 (모두 20MB 까지) ', files]),
                h('div', { class: 'mjm__composebar' }, [submit, scheduleBtn, draftBtn, previewBtn, status, h('span', { class: 'mjm__spacer' }), h('span', { class: 'mjm__dim', text: `보내는 사람: ${root.dataset.fromName ? root.dataset.fromName + ' ' : ''}<${user}>` })]),
            );
            for (const [k, v] of Object.entries({ in_reply_to: init.in_reply_to, references: init.references, reply_folder: init.reply_folder, reply_uid: init.reply_uid, draft_uid: init.draft_uid })) form.append(h('input', { type: 'hidden', name: k, value: v }));
            let dirty = false, autosave = 0;
            const markDirty = () => { dirty = true; clearTimeout(autosave); autosave = setTimeout(() => { if (dirty) saveDraft(true); }, 30000); };
            form.addEventListener('input', markDirty);
            editor.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && ['b', 'i', 'u'].includes(e.key.toLowerCase())) { e.preventDefault(); cmd({ b: 'bold', i: 'italic', u: 'underline' }[e.key.toLowerCase()]); } });
            const payload = () => { const fd = new FormData(form); fd.delete('send_at_local'); fd.set('html', editor.innerHTML); fd.set('body', htmlToText(editor.innerHTML)); return fd; };
            async function saveDraft(auto) {
                const fd = payload(); fd.delete('attachments');
                try { const r = await api('draft', { method: 'POST', body: fd }); form.querySelector('[name=draft_uid]').value = r.uid; dirty = false; status.textContent = `${auto ? '자동 ' : ''}임시 저장 ${new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}`; loadFolders(); if (state.folder === 'drafts') loadList(); }
                catch (e) { if (!auto) say(e.message, true); }
            }
            function togglePreview() {
                if (!previewBox.hidden) { previewBox.hidden = true; editor.hidden = false; tb.hidden = false; previewBtn.textContent = '미리보기'; return; }
                previewBox.innerHTML = '';
                const fr = h('iframe', { class: 'mjm__body', sandbox: 'allow-same-origin', title: '미리보기' });
                fr.srcdoc = bodyDoc(`<div style="padding-bottom:8px;margin-bottom:10px;border-bottom:1px solid #eee;color:#555;font-size:12px">받는 사람 ${esc(toField.querySelector('input').value || '(없음)')}<br>제목 <b>${esc(subjectField.querySelector('input').value || '(제목 없음)')}</b></div>${editor.innerHTML}`);
                fr.addEventListener('load', () => { try { fr.style.height = Math.min(4000, fr.contentDocument.body.scrollHeight + 30) + 'px'; } catch { /* sandbox */ } });
                previewBox.append(h('p', { class: 'mjm__dim', text: '받는 사람에게 이렇게 보여요 (메일 앱마다 조금 다를 수 있어요)' }), fr);
                previewBox.hidden = false; editor.hidden = true; tb.hidden = true; previewBtn.textContent = '편집으로';
            }
            function toggleSchedule() { scheduleBox.hidden = !scheduleBox.hidden; if (!scheduleBox.hidden) scheduleBox.querySelector('input').focus(); }
            async function doSchedule() {
                const at = scheduleBox.querySelector('input').value;
                if (!at) { say('보낼 시각을 골라 주세요', true); return; }
                const fd = payload(); fd.set('send_at', at);
                try { const r = await api('schedule', { method: 'POST', body: fd }); state.scheduled = r.scheduled; say(`${r.send_at} 에 보내요`); state.compose = null; dirty = false; state.sentInfo = { to: fd.get('to'), cc: fd.get('cc'), subject: fd.get('subject'), time: r.send_at, scheduled: true }; state.current = null; renderRead(); setPane('read'); loadFolders(); }
                catch (e) { say(e.message, true); }
            }
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                submit.disabled = true; submit.textContent = '보내는 중…'; clearTimeout(autosave);
                try {
                    const fd = payload();
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
            if (reply || forward) { editor.focus(); const sel = window.getSelection(); const r = document.createRange(); r.setStart(editor, 0); r.collapse(true); sel.removeAllRanges(); sel.addRange(r); }
            else if (self) editor.focus(); else toField.querySelector('input').focus();
        }
        const localIso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
        const htmlToText = (html) => { const d = document.createElement('div'); d.innerHTML = html.replace(/<br\s*\/?>/gi, '\n').replace(/<\/(p|div|li|h[1-6]|blockquote|tr)>/gi, '\n'); d.querySelectorAll('style,script').forEach((n) => n.remove()); return (d.textContent || '').replace(/\n{3,}/g, '\n\n').trim(); };

        // ── 설정: 서명 · 템플릿 · 주소록 · 예약 ──
        function openSettings(tab = 'signature') {
            if (state.compose && !confirm('쓰던 메일을 닫을까요?')) return;
            state.compose = null; state.sentInfo = null; state.current = null;
            const wrap = h('div', { class: 'mjm__settings' });
            const tabs = [['signature', '서명'], ['contacts', '주소록'], ['devices', '앱 비밀번호'], ['scheduled', '예약 발송']];
            const body = h('div', { class: 'mjm__settings-body' });
            const draw = (t) => {
                body.innerHTML = '';
                wrap.querySelectorAll('.mjm__chip').forEach((c) => c.classList.toggle('is-active', c.dataset.tab === t));
                if (t === 'signature') {
                    const ed = h('div', { class: 'mjm__editor', contenteditable: 'true' }); ed.innerHTML = state.signature;
                    const cmd = (name, value = null) => { ed.focus(); document.execCommand(name, false, value); };
                    body.append(h('p', { class: 'mjm__dim', text: '새 메일·답장·전달 끝에 자동으로 붙어요. 서식(굵게·기울임·링크)도 돼요. 서버에 저장되니 어느 기기에서나 같아요.' }),
                        h('div', { class: 'mjm__fmt' }, [['bold', '<b>B</b>'], ['italic', '<i>I</i>'], ['underline', '<u>U</u>']].map(([c, html]) => h('button', { type: 'button', html, onmousedown: (e) => e.preventDefault(), onclick: () => cmd(c) })).concat([h('button', { type: 'button', text: '🔗', onmousedown: (e) => e.preventDefault(), onclick: () => { const u = prompt('링크 주소'); if (u) cmd('createLink', u); } }), h('button', { type: 'button', text: '서식 지우기', onmousedown: (e) => e.preventDefault(), onclick: () => cmd('removeFormat') })])),
                        ed,
                        h('div', { class: 'mjm__composebar' }, [h('button', { type: 'button', class: 'mjm__send', text: '서명 저장', onclick: async () => { try { const r = await api('prefs', { method: 'POST', body: { signature: ed.innerHTML } }); state.signature = r.signature; say('서명을 저장했어요'); } catch (e) { say(e.message, true); } } }),
                            h('button', { type: 'button', text: '서명 없음', onclick: () => { ed.innerHTML = ''; } })]));
                } else if (t === 'contacts') {
                    const email = h('input', { type: 'email', placeholder: '주소' }), name = h('input', { type: 'text', placeholder: '표시 이름' }), note = h('input', { type: 'text', placeholder: '메모 (선택)' });
                    body.append(h('p', { class: 'mjm__dim', text: '주소마다 이름을 정해 두면 목록·읽기·자동완성에 그 이름으로 보여요 (예: hey_minj@naver.com → 서민재).' }),
                        h('div', { class: 'mjm__contact-add' }, [email, name, note, h('button', { type: 'button', class: 'mjm__send', text: '저장', onclick: async () => { try { const r = await api('contacts', { method: 'POST', body: { action: 'set', email: email.value, name: name.value, note: note.value } }); state.contacts = r.contacts; say('저장했어요'); draw('contacts'); } catch (e) { say(e.message, true); } } })]));
                    const ul = h('div', { class: 'mjm__contacts' });
                    for (const [e2, c] of Object.entries(state.contacts).sort((a, b) => a[1].name.localeCompare(b[1].name, 'ko'))) ul.append(h('div', { class: 'mjm__contact' }, [avatar(c.name, e2), h('div', { class: 'mjm__contact-main' }, [h('b', { text: c.name }), h('div', { class: 'mjm__dim', text: e2 + (c.note ? ` · ${c.note}` : '') })]),
                        h('button', { type: 'button', text: '✉', title: '메일 쓰기', onclick: () => openCompose({ to: `${c.name} <${e2}>` }) }),
                        h('button', { type: 'button', text: '편집', onclick: () => { email.value = e2; name.value = c.name; note.value = c.note || ''; name.focus(); } }),
                        h('button', { type: 'button', class: 'is-danger', text: '지우기', onclick: async () => { const r = await api('contacts', { method: 'POST', body: { action: 'delete', email: e2 } }); state.contacts = r.contacts; draw('contacts'); } })]));
                    if (!Object.keys(state.contacts).length) ul.append(h('p', { class: 'mjm__empty', text: '아직 없어요. 읽기 화면의 "이름 정하기"로도 넣을 수 있어요.' }));
                    body.append(ul);
                } else if (t === 'devices') {
                    const label = h('input', { type: 'text', placeholder: '기기 이름 (예: 맥북 Mail, 아이폰)', maxlength: 40 });
                    const made = h('div', { class: 'mjm__appmade', hidden: true });
                    body.append(h('p', { class: 'mjm__dim', text: '맥·아이폰 메일 앱에는 본 비밀번호 대신 기기마다 따로 만든 앱 비밀번호를 넣어요. 기기를 잃어버리면 그것만 지우면 돼요. 비밀번호는 만들 때 한 번만 보여요.' }),
                        h('div', { class: 'mjm__contact-add mjm__contact-add--2' }, [label, h('button', { type: 'button', class: 'mjm__send', text: '만들기', onclick: async () => {
                            try {
                                const r = await api('app-passwords', { method: 'POST', body: { action: 'create', label: label.value } });
                                state.appPasswords = r.app_passwords; label.value = '';
                                made.hidden = false; made.innerHTML = '';
                                made.append(h('b', { text: '지금 한 번만 보여요 — 메일 앱에 이렇게 넣으세요' }),
                                    h('table', { class: 'mjm__apptable' }, [
                                        ['받는 메일 서버 (IMAP)', `${state.imapHost} · 993 · SSL`], ['보내는 메일 서버 (SMTP)', `${state.imapHost} · 587 · STARTTLS · 인증 사용`],
                                        ['사용자 이름', r.login], ['비밀번호', r.password],
                                    ].map(([k, v]) => h('tr', {}, [h('th', { text: k }), h('td', {}, [h('code', { text: v })])]))),
                                    h('button', { type: 'button', class: 'mjm__mini', text: '비밀번호 복사', onclick: (e) => { navigator.clipboard?.writeText(r.password); e.target.textContent = '복사했어요'; } }));
                                drawList();
                            } catch (e) { say(e.message, true); }
                        } })]), made);
                    const ul = h('div', { class: 'mjm__contacts' });
                    const drawList = () => {
                        ul.innerHTML = '';
                        for (const a of state.appPasswords) ul.append(h('div', { class: 'mjm__contact' }, [h('span', { class: 'mjm__chip mjm__chip--sent', text: '📱' }), h('div', { class: 'mjm__contact-main' }, [h('b', { text: a.label }), h('div', { class: 'mjm__dim', text: `${a.login} · ${a.created} 만듦` })]),
                            h('button', { type: 'button', class: 'is-danger', text: '지우기', onclick: async () => { if (!confirm(`"${a.label}" 앱 비밀번호를 지울까요? 그 기기는 더 이상 로그인 못 해요.`)) return; try { const r = await api('app-passwords', { method: 'POST', body: { action: 'delete', id: a.id } }); state.appPasswords = r.app_passwords; drawList(); } catch (e) { say(e.message, true); } } })]));
                        if (!state.appPasswords.length) ul.append(h('p', { class: 'mjm__empty', text: '아직 없어요. 위에서 기기 이름을 적고 만들어요.' }));
                    };
                    drawList();
                    body.append(ul);
                } else {
                    const ul = h('div', { class: 'mjm__contacts' });
                    for (const r of state.scheduled) ul.append(h('div', { class: 'mjm__contact' }, [h('span', { class: `mjm__chip mjm__chip--${r.status}`, text: r.status_text }), h('div', { class: 'mjm__contact-main' }, [h('b', { text: r.subject || '(제목 없음)' }), h('div', { class: 'mjm__dim', text: `${r.send_at} · ${r.to}${r.error ? ' · ' + r.error : ''}` })]),
                        r.status === 'pending' ? h('button', { type: 'button', class: 'is-danger', text: '취소', onclick: async () => { try { const x = await api('schedule', { method: 'POST', body: { action: 'cancel', id: r.id } }); state.scheduled = x.scheduled; draw('scheduled'); } catch (e) { say(e.message, true); } } }) : null]));
                    if (!state.scheduled.length) ul.append(h('p', { class: 'mjm__empty', text: '예약한 메일이 없어요. 쓰기 창의 ⏰ 예약으로 등록해요.' }));
                    body.append(h('p', { class: 'mjm__dim', text: '서버가 1분마다 확인해서 때가 된 메일을 보내요. 보낸 뒤엔 보낸 편지함에도 들어가요.' }), ul);
                }
            };
            wrap.append(h('div', { class: 'mjm__toolbar' }, [h('button', { type: 'button', class: 'mjm__back', text: '‹ 닫기', onclick: () => { readEl.innerHTML = ''; renderRead(); if (mode === 'mini') setPane('list'); } }), h('h3', { class: 'mjm__readsubject mjm__readsubject--tb', text: '⚙ 메일 설정' })]),
                h('div', { class: 'mjm__chips' }, tabs.map(([id, label]) => h('button', { type: 'button', class: 'mjm__chip', 'data-tab': id, text: label, onclick: () => draw(id) }))), body);
            readEl.innerHTML = ''; readEl.append(wrap); setPane('read'); draw(tab);
        }
        async function setContact(email, current) {
            if (!email) return;
            const name = prompt(`${email} 를 어떤 이름으로 보여 줄까요?`, current || '');
            if (name === null) return;
            try {
                const r = await api('contacts', { method: 'POST', body: name.trim() ? { action: 'set', email, name: name.trim() } : { action: 'delete', email } });
                state.contacts = r.contacts; say(name.trim() ? '이름을 저장했어요' : '이름을 지웠어요'); renderList(); renderRead();
            } catch (e) { say(e.message, true); }
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
        return { reload: () => { loadList(); loadFolders(); }, compose: openCompose, go: goFolder, settings: openSettings };
    }

    window.MjMail = { create, watchUnread, refreshUnread };
})();
