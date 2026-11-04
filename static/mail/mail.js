// MJ Mail — /mail/ 전체 화면과 오른쪽 아래 떠 있는 패널이 같이 쓰는 스크립트
// 서버 API: /mail/api/{state,unread,list,message,action,send}/ (관리자 세션 + CSRF)
(() => {
    const API = '/mail/api/';
    const csrf = () => document.querySelector('meta[name="mj-csrf"]')?.content || (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';

    async function api(path, { method = 'GET', body, query } = {}) {
        const url = API + path + '/' + (query ? '?' + new URLSearchParams(query) : '');
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
        for (const c of [].concat(children)) if (c != null) node.append(c);
        return node;
    };
    const fmtSize = (n) => n < 1024 ? `${n}B` : n < 1048576 ? `${(n / 1024).toFixed(0)}KB` : `${(n / 1048576).toFixed(1)}MB`;
    const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

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
        const state = { folder: 'inbox', page: 1, q: '', list: null, folders: [], current: null, selected: new Set(), pane: 'list', busy: false };
        root.classList.add('mjm', `mjm--${mode}`);
        root.innerHTML = '';
        const foldersEl = h('nav', { class: 'mjm__folders', 'aria-label': '폴더' });
        const listEl = h('section', { class: 'mjm__list' });
        const readEl = h('section', { class: 'mjm__read' });
        const toast = h('div', { class: 'mjm__toast', hidden: true });
        root.append(foldersEl, listEl, readEl, toast);
        const folderMeta = { inbox: ['📥', '받은 편지함'], sent: ['📤', '보낸 편지함'], drafts: ['📝', '임시 보관함'], junk: ['🚫', '스팸'], trash: ['🗑', '휴지통'] };

        const say = (msg, isError) => {
            toast.textContent = msg; toast.hidden = false; toast.classList.toggle('is-error', !!isError);
            clearTimeout(say.t); say.t = setTimeout(() => { toast.hidden = true; }, isError ? 5000 : 2500);
        };
        const setPane = (p) => { state.pane = p; root.dataset.pane = p; };

        // 폴더 목록
        function renderFolders() {
            foldersEl.innerHTML = '';
            if (mode === 'full') foldersEl.append(h('button', { class: 'mjm__compose', type: 'button', text: '✏️ 새 메일', onclick: () => openCompose() }));
            const wrap = h('div', { class: 'mjm__folderlist' });
            for (const f of state.folders.length ? state.folders : Object.keys(folderMeta).map((k) => ({ key: k, total: 0, unseen: 0 }))) {
                const [icon, label] = folderMeta[f.key] || ['📁', f.key];
                wrap.append(h('button', {
                    type: 'button', class: `mjm__folder${f.key === state.folder ? ' is-active' : ''}`, title: `${label} ${f.total}통`,
                    onclick: () => { state.folder = f.key; state.page = 1; state.q = ''; state.selected.clear(); state.current = null; renderFolders(); loadList(); setPane('list'); },
                }, [h('span', { class: 'mjm__folder-icon', text: icon }), h('span', { class: 'mjm__folder-label', text: label }),
                    f.unseen ? h('span', { class: 'mjm__badge', text: f.unseen }) : null]));
            }
            foldersEl.append(wrap);
        }
        async function loadFolders() {
            try { const { folders } = await api('state'); state.folders = folders; renderFolders(); }
            catch (e) { say(e.message, true); }
        }

        // 목록
        function renderList() {
            listEl.innerHTML = '';
            const [icon, label] = folderMeta[state.folder];
            const search = h('input', { class: 'mjm__search', type: 'search', placeholder: '검색 (보낸 사람·제목·본문)', value: state.q });
            search.addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.q = search.value.trim(); state.page = 1; loadList(); } });
            const bar = h('div', { class: 'mjm__bar' }, [
                mode === 'mini' ? h('select', { class: 'mjm__folderselect', onchange: (e) => { state.folder = e.target.value; state.page = 1; state.q = ''; state.selected.clear(); loadList(); } },
                    Object.entries(folderMeta).map(([k, [i, l]]) => { const o = h('option', { value: k, text: `${i} ${l}` }); if (k === state.folder) o.selected = true; return o; }))
                    : h('h2', { class: 'mjm__title', text: `${icon} ${label}` }),
                search,
                h('button', { type: 'button', class: 'mjm__iconbtn', title: '새로고침', text: '⟳', onclick: () => { loadList(); loadFolders(); } }),
                mode === 'mini' ? h('button', { type: 'button', class: 'mjm__iconbtn', title: '새 메일', text: '✏️', onclick: () => openCompose() }) : null,
            ]);
            listEl.append(bar);
            const sel = h('div', { class: 'mjm__selbar', hidden: !state.selected.size }, [
                h('span', { text: `${state.selected.size}통 선택` }),
                h('button', { type: 'button', text: '읽음', onclick: () => act('seen') }),
                h('button', { type: 'button', text: '안 읽음', onclick: () => act('unseen') }),
                state.folder !== 'junk' ? h('button', { type: 'button', text: '스팸', onclick: () => act('move', { to: 'junk' }) }) : h('button', { type: 'button', text: '받은 편지함으로', onclick: () => act('move', { to: 'inbox' }) }),
                h('button', { type: 'button', class: 'is-danger', text: state.folder === 'trash' ? '완전 삭제' : '삭제', onclick: () => act('delete') }),
            ]);
            listEl.append(sel);
            const ul = h('ul', { class: 'mjm__rows' });
            if (!state.list) ul.append(h('li', { class: 'mjm__empty', text: '불러오는 중…' }));
            else if (!state.list.items.length) ul.append(h('li', { class: 'mjm__empty', text: state.q ? '검색 결과가 없어요' : '메일이 없어요' }));
            for (const m of state.list?.items || []) {
                const cb = h('input', { type: 'checkbox', class: 'mjm__cb', 'aria-label': '선택' });
                cb.checked = state.selected.has(m.uid);
                cb.addEventListener('click', (e) => { e.stopPropagation(); cb.checked ? state.selected.add(m.uid) : state.selected.delete(m.uid); sel.hidden = !state.selected.size; sel.firstChild.textContent = `${state.selected.size}통 선택`; });
                const who = state.folder === 'sent' || state.folder === 'drafts' ? `→ ${m.to_text || ''}` : (m.from.name || m.from.email);
                ul.append(h('li', {
                    class: `mjm__row${m.seen ? '' : ' is-unread'}${state.current?.uid === m.uid && state.current?.folder === m.folder ? ' is-current' : ''}`,
                    onclick: () => openMessage(m.uid),
                }, [cb, h('div', { class: 'mjm__rowmain' }, [
                    h('div', { class: 'mjm__rowtop' }, [h('span', { class: 'mjm__who', text: who, title: m.from_text }), h('span', { class: 'mjm__date', text: m.date_text })]),
                    h('div', { class: 'mjm__subject' }, [m.flagged ? h('span', { text: '⭐ ' }) : null, m.answered ? h('span', { class: 'mjm__ans', text: '↩ ' }) : null, h('span', { text: m.subject })]),
                ])]));
            }
            listEl.append(ul);
            if (state.list && state.list.pages > 1) {
                listEl.append(h('div', { class: 'mjm__pager' }, [
                    h('button', { type: 'button', disabled: state.page <= 1, text: '‹ 이전', onclick: () => { state.page -= 1; loadList(); } }),
                    h('span', { text: `${state.page} / ${state.list.pages} · ${state.list.total}통` }),
                    h('button', { type: 'button', disabled: state.page >= state.list.pages, text: '다음 ›', onclick: () => { state.page += 1; loadList(); } }),
                ]));
            }
        }
        async function loadList() {
            state.list = null; renderList();
            try { state.list = await api('list', { query: { folder: state.folder, page: state.page, q: state.q } }); }
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
                say(action === 'delete' ? '지웠어요' : action === 'move' ? '옮겼어요' : '바꿨어요');
                loadList(); loadFolders(); refreshUnread();
            } catch (e) { say(e.message, true); }
        }

        // 읽기
        function renderRead() {
            readEl.innerHTML = '';
            const m = state.current;
            if (!m) { readEl.append(h('div', { class: 'mjm__empty mjm__empty--read', text: mode === 'full' ? '왼쪽에서 메일을 고르세요' : '' })); return; }
            const head = h('div', { class: 'mjm__readhead' }, [
                mode === 'mini' ? h('button', { type: 'button', class: 'mjm__back', text: '‹ 목록', onclick: () => { setPane('list'); } }) : null,
                h('h3', { class: 'mjm__readsubject', text: m.subject }),
                h('div', { class: 'mjm__meta' }, [
                    h('div', {}, [h('b', { text: m.from.name || m.from.email }), m.from.name ? h('span', { class: 'mjm__dim', text: ` <${m.from.email}>` }) : null]),
                    h('div', { class: 'mjm__dim', text: `받는 사람 ${m.to_text}${m.cc_text ? ' · 참조 ' + m.cc_text : ''}` }),
                    h('div', { class: 'mjm__dim', text: m.date_text }),
                ]),
                h('div', { class: 'mjm__actions' }, [
                    h('button', { type: 'button', text: '↩ 답장', onclick: () => openCompose({ reply: m }) }),
                    h('button', { type: 'button', text: '↪ 전달', onclick: () => openCompose({ forward: m }) }),
                    m.folder !== 'junk' ? h('button', { type: 'button', text: '스팸', onclick: () => one('move', { to: 'junk' }) }) : h('button', { type: 'button', text: '스팸 아님', onclick: () => one('move', { to: 'inbox' }) }),
                    h('button', { type: 'button', text: '안 읽음', onclick: () => one('unseen') }),
                    h('button', { type: 'button', class: 'is-danger', text: m.folder === 'trash' ? '완전 삭제' : '삭제', onclick: () => one('delete') }),
                ]),
            ]);
            readEl.append(head);
            if (m.has_remote_images) {
                readEl.append(h('div', { class: 'mjm__notice' }, [h('span', { text: '추적 방지를 위해 외부 그림을 불러오지 않았어요. ' }), h('button', { type: 'button', text: '그림 보기', onclick: () => openMessage(m.uid, { images: true }) })]));
            }
            const frame = h('iframe', { class: 'mjm__body', sandbox: 'allow-same-origin allow-popups allow-popups-to-escape-sandbox', title: '메일 본문' });
            frame.srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline'"><base target="_blank"><style>body{font:14px/1.65 system-ui,-apple-system,sans-serif;color:#1d1d1f;margin:14px;word-break:break-word}img{max-width:100%;height:auto}img[data-src]{display:none}blockquote{border-left:3px solid #ddd;margin:8px 0;padding-left:10px;color:#555}pre{white-space:pre-wrap}a{color:#0066cc}</style></head><body>${m.body_html}</body></html>`;
            frame.addEventListener('load', () => { try { frame.style.height = Math.min(4000, frame.contentDocument.body.scrollHeight + 30) + 'px'; } catch { /* sandbox */ } });
            readEl.append(frame);
            const files = m.attachments.filter((a) => !(a.inline && a.content_type.startsWith('image/') && m.is_html));
            if (files.length) {
                readEl.append(h('div', { class: 'mjm__atts' }, [h('b', { text: `첨부 ${files.length}개` }), ...files.map((a) => h('a', { class: 'mjm__att', href: a.url, download: a.filename, text: `📎 ${a.filename} (${fmtSize(a.size)})` }))]));
            }
            async function one(action, extra = {}) {
                try {
                    await api('action', { method: 'POST', body: { folder: m.folder, uids: [m.uid], action, ...extra } });
                    if (action !== 'unseen') { state.current = null; renderRead(); if (mode === 'mini') setPane('list'); }
                    say(action === 'delete' ? '지웠어요' : action === 'move' ? '옮겼어요' : '안 읽음으로 바꿨어요');
                    loadList(); loadFolders(); refreshUnread();
                } catch (e) { say(e.message, true); }
            }
        }
        async function openMessage(uid, { images = false } = {}) {
            setPane('read');
            readEl.innerHTML = ''; readEl.append(h('div', { class: 'mjm__empty mjm__empty--read', text: '불러오는 중…' }));
            try {
                state.current = await api('message', { query: { folder: state.folder, uid, images: images ? 1 : 0 } });
                renderRead();
                const row = state.list?.items.find((x) => x.uid === uid); if (row && !row.seen) { row.seen = true; renderList(); refreshUnread(); loadFolders(); }
                else renderList();
            } catch (e) { say(e.message, true); state.current = null; renderRead(); }
        }

        // 쓰기
        function openCompose({ reply, forward } = {}) {
            const quote = (m) => `\n\n${m.date_text}에 ${m.from_text} 님이 쓴 글:\n> ` + (m.text || stripHtml(m.body_html)).trim().split('\n').join('\n> ');
            const init = { to: '', cc: '', subject: '', body: '', in_reply_to: '', references: '', reply_folder: '', reply_uid: '' };
            if (reply) Object.assign(init, { to: reply.reply_to, subject: /^re:/i.test(reply.subject) ? reply.subject : `Re: ${reply.subject}`, body: quote(reply), in_reply_to: reply.message_id, references: reply.references, reply_folder: reply.folder, reply_uid: reply.uid });
            if (forward) Object.assign(init, { subject: /^fwd?:/i.test(forward.subject) ? forward.subject : `Fwd: ${forward.subject}`, body: `\n\n---------- 전달한 메일 ----------\n보낸 사람: ${forward.from_text}\n날짜: ${forward.date_text}\n제목: ${forward.subject}\n받는 사람: ${forward.to_text}\n\n${(forward.text || stripHtml(forward.body_html)).trim()}` });
            const form = h('form', { class: 'mjm__compose', enctype: 'multipart/form-data' });
            const field = (name, label, type = 'text', value = '') => { const i = h('input', { name, type, value, placeholder: label, required: name === 'to' }); return h('label', { class: 'mjm__field' }, [h('span', { text: label }), i]); };
            const body = h('textarea', { name: 'body', rows: mode === 'mini' ? 9 : 14, placeholder: '내용' }); body.value = init.body;
            const files = h('input', { type: 'file', name: 'attachments', multiple: true });
            const submit = h('button', { type: 'submit', class: 'mjm__send', text: '보내기' });
            form.append(
                h('div', { class: 'mjm__readhead' }, [h('button', { type: 'button', class: 'mjm__back', text: '‹ 닫기', onclick: () => { state.compose = null; renderRead(); if (mode === 'mini' && !state.current) setPane('list'); } }), h('h3', { class: 'mjm__readsubject', text: reply ? '답장' : forward ? '전달' : '새 메일' })]),
                field('to', '받는 사람', 'text', init.to), field('cc', '참조', 'text', init.cc), field('subject', '제목', 'text', init.subject), body,
                h('label', { class: 'mjm__files' }, ['📎 첨부 (모두 20MB 까지) ', files]),
                h('div', { class: 'mjm__composebar' }, [submit, h('span', { class: 'mjm__dim', text: `보내는 사람: ${root.dataset.user || ''}` })]),
            );
            for (const [k, v] of Object.entries({ in_reply_to: init.in_reply_to, references: init.references, reply_folder: init.reply_folder, reply_uid: init.reply_uid })) form.append(h('input', { type: 'hidden', name: k, value: v }));
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                submit.disabled = true; submit.textContent = '보내는 중…';
                try {
                    await api('send', { method: 'POST', body: new FormData(form) });
                    say('보냈어요'); state.compose = null;
                    if (reply) { const row = state.list?.items.find((x) => x.uid === reply.uid); if (row) row.answered = true; }
                    renderRead(); if (mode === 'mini') setPane('list'); renderList(); loadFolders();
                } catch (err) { say(err.message, true); submit.disabled = false; submit.textContent = '보내기'; }
            });
            state.compose = form;
            readEl.innerHTML = ''; readEl.append(form); setPane('read');
            (reply || forward ? body : form.querySelector('[name=to]')).focus();
            if (reply || forward) body.setSelectionRange(0, 0);
        }
        const stripHtml = (html) => { const d = document.createElement('div'); d.innerHTML = html; d.querySelectorAll('style,script').forEach((n) => n.remove()); return d.innerText || d.textContent || ''; };

        root.addEventListener('keydown', (e) => { if (e.key === 'Escape' && state.compose) { state.compose = null; renderRead(); if (mode === 'mini') setPane('list'); } });

        renderFolders(); renderList(); renderRead(); setPane('list');
        loadFolders(); loadList();
        let lastUnread = null;
        watchUnread((n) => { if (lastUnread !== null && n !== lastUnread && state.folder === 'inbox' && !document.hidden && !state.compose && !state.selected.size) { loadList(); loadFolders(); } lastUnread = n; });
        return { reload: () => { loadList(); loadFolders(); }, compose: openCompose };
    }

    window.MjMail = { create, watchUnread, refreshUnread };
})();
