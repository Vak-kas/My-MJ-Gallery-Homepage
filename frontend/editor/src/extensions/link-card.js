// 링크 카드 블록 (카드 / 페이지 미리보기 / 멘션) + URL 단독 붙여넣기 시 선택 팝업
import { Node, mergeAttributes } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { dismissOnOutside, h, isHttpUrl, placeFloating } from '../dom.js';

const MODES = [
    ['card', '카드'],
    ['preview', '미리보기'],
    ['mention', '멘션'],
];

const fetchInto = async (editor, findPos, url, mode) => {
    const { api, notify } = editor.storage.linkCard;
    try {
        const meta = await api.fetchUrlPreview(url);
        const pos = findPos();
        if (pos === null) return;
        const node = editor.state.doc.nodeAt(pos);
        if (!node || node.type.name !== 'linkCard') return;
        const tr = editor.state.tr.setNodeMarkup(pos, undefined, {
            ...node.attrs,
            url,
            mode: mode || node.attrs.mode,
            title: meta.title || url,
            description: meta.description || '',
            image: meta.image || '',
            favicon: meta.favicon || '',
            siteName: meta.site_name || '',
        });
        editor.view.dispatch(tr.setMeta('addToHistory', false));
    } catch (err) {
        notify?.(`링크 정보를 가져오지 못했습니다: ${err.message}`, 'error');
        const pos = findPos();
        const node = pos === null ? null : editor.state.doc.nodeAt(pos);
        if (node && node.type.name === 'linkCard' && !node.attrs.title) {
            const tr = editor.state.tr.setNodeMarkup(pos, undefined, { ...node.attrs, url, title: url });
            editor.view.dispatch(tr.setMeta('addToHistory', false));
        }
    }
};

// 붙여넣은 URL 처리 방식 선택 팝업
const showUrlPicker = (editor, url, range) => {
    const coords = editor.view.coordsAtPos(range.inner);
    const options = [
        ['link', '🔗', '링크', '텍스트 링크로 삽입'],
        ['card', '📰', '카드', '제목 + 썸네일 카드'],
        ['preview', '🖼️', '페이지 미리보기', '큰 이미지 + 설명'],
    ];
    let cleanup = () => {};
    const close = (mode) => {
        cleanup();
        panel.remove();
        const chain = editor.chain().focus();
        if (mode === 'card' || mode === 'preview') {
            chain.insertContentAt({ from: range.from, to: range.to }, { type: 'linkCard', attrs: { url, mode } }).run();
            const findPos = () => {
                let found = null;
                editor.state.doc.descendants((node, pos) => {
                    if (found !== null) return false;
                    if (node.type.name === 'linkCard' && node.attrs.url === url && !node.attrs.title) found = pos;
                    return found === null;
                });
                return found;
            };
            fetchInto(editor, findPos, url, mode);
        } else {
            chain.insertContentAt(range.inner, { type: 'text', text: url, marks: [{ type: 'link', attrs: { href: url } }] }).run();
        }
    };
    const panel = h('div', { class: 'mj-pop mj-url-picker' }, [
        h('div', { class: 'mj-pop__title', text: '붙여넣은 링크를 어떻게 넣을까요?' }),
        ...options.map(([mode, icon, label, desc]) => h('button', {
            type: 'button',
            class: 'mj-pop__item',
            onmousedown: (e) => e.preventDefault(),
            onclick: () => close(mode),
        }, [h('span', { class: 'mj-pop__icon', text: icon }), h('span', {}, [h('b', { text: label }), h('small', { text: desc })])])),
    ]);
    document.body.append(panel);
    placeFloating({ getBoundingClientRect: () => new DOMRect(coords.left, coords.top, 0, coords.bottom - coords.top) }, panel);
    cleanup = dismissOnOutside(panel, () => close('link'));
};

export const LinkCard = Node.create({
    name: 'linkCard',
    group: 'block',
    atom: true,
    draggable: true,
    selectable: true,

    addOptions() {
        return { api: null, notify: null };
    },

    addStorage() {
        return { api: this.options.api, notify: this.options.notify };
    },

    addAttributes() {
        const attr = (name) => ({
            default: '',
            parseHTML: (el) => el.getAttribute(`data-${name}`) || '',
            renderHTML: (attrs) => ({ [`data-${name}`]: attrs[name === 'site-name' ? 'siteName' : name] || null }),
        });
        return {
            url: attr('url'),
            title: attr('title'),
            description: attr('description'),
            image: attr('image'),
            favicon: attr('favicon'),
            siteName: attr('site-name'),
            mode: { ...attr('mode'), default: 'card', parseHTML: (el) => el.getAttribute('data-mode') || 'card' },
        };
    },

    parseHTML() {
        return [{ tag: 'div[data-type="link-card"]' }];
    },

    renderHTML({ HTMLAttributes, node }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-type': 'link-card' }), ['a', { href: node.attrs.url }, node.attrs.title || node.attrs.url]];
    },

    addProseMirrorPlugins() {
        const editor = this.editor;
        return [
            new Plugin({
                key: new PluginKey('mjUrlPastePicker'),
                props: {
                    handlePaste: (view, event) => {
                        const text = (event.clipboardData?.getData('text/plain') || '').trim();
                        if (!isHttpUrl(text) || event.clipboardData?.files?.length) return false;
                        const { selection } = view.state;
                        const { $from } = selection;
                        // 빈 문단에 URL만 붙여넣었을 때만 선택지를 보여줌 (문장 중간은 기본 링크 붙여넣기)
                        if (!selection.empty || $from.parent.type.name !== 'paragraph' || $from.parent.content.size !== 0) return false;
                        if ($from.depth !== 1) return false;
                        event.preventDefault();
                        showUrlPicker(editor, text, { from: $from.before(), to: $from.after(), inner: $from.pos });
                        return true;
                    },
                },
            }),
        ];
    },

    addNodeView() {
        return ({ node: initialNode, getPos, editor }) => {
            let node = initialNode;
            const dom = h('div', { class: 'mj-lc', 'data-type': 'link-card' });
            const body = h('div', { class: 'mj-lc__body' });
            const bar = h('div', { class: 'mj-lc__bar' });
            dom.append(body, bar);

            const findPos = () => {
                const pos = getPos();
                return typeof pos === 'number' ? pos : null;
            };
            const setAttrs = (attrs) => {
                const pos = findPos();
                if (pos === null) return;
                editor.view.dispatch(editor.state.tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...attrs }));
            };

            const renderInput = () => {
                const input = h('input', { type: 'url', class: 'mj-lc__input', placeholder: 'https:// 링크를 붙여넣고 Enter', value: node.attrs.url || '' });
                const go = () => {
                    const url = input.value.trim();
                    if (!isHttpUrl(url)) {
                        editor.storage.linkCard.notify?.('http(s):// 로 시작하는 주소를 넣어주세요.', 'error');
                        return;
                    }
                    setAttrs({ url, title: '' });
                    fetchInto(editor, findPos, url);
                };
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        go();
                    }
                });
                body.replaceChildren(h('div', { class: 'mj-lc__form' }, [
                    h('span', { class: 'mj-lc__icon', text: '🔗' }),
                    input,
                    h('button', { type: 'button', class: 'mj-btn', text: '가져오기', onclick: go }),
                ]));
                bar.hidden = true;
                if (!node.attrs.url) setTimeout(() => input.focus(), 0);
            };

            const renderCard = () => {
                const { url, title, description, image, favicon, siteName, mode } = node.attrs;
                const img = image ? h('img', { src: image, alt: '', loading: 'lazy' }) : null;
                const icon = favicon ? h('img', { class: 'mj-lc__favicon', src: favicon, alt: '' }) : null;
                if (icon) icon.addEventListener('error', () => icon.remove());
                const meta = h('div', { class: 'mj-lc__meta' }, [
                    h('div', { class: 'mj-lc__title', text: title || url }),
                    description && mode !== 'mention' ? h('div', { class: 'mj-lc__desc', text: description }) : null,
                    h('div', { class: 'mj-lc__site' }, [icon, siteName || url]),
                ]);
                if (mode === 'mention') {
                    body.replaceChildren(h('div', { class: 'mj-lc__mention' }, [icon || '🔗', h('span', { text: title || url })]));
                } else if (mode === 'preview') {
                    body.replaceChildren(h('div', { class: 'mj-lc__preview' }, [img ? h('div', { class: 'mj-lc__hero' }, [img]) : null, meta]));
                } else {
                    body.replaceChildren(h('div', { class: 'mj-lc__card' }, [meta, img ? h('div', { class: 'mj-lc__thumb' }, [img]) : null]));
                }
                bar.hidden = false;
                bar.replaceChildren(
                    ...MODES.map(([value, label]) => h('button', {
                        type: 'button',
                        class: `mj-chip${value === mode ? ' is-active' : ''}`,
                        text: label,
                        onclick: () => setAttrs({ mode: value }),
                    })),
                    h('button', { type: 'button', class: 'mj-chip', text: '✎ 주소 수정', onclick: () => renderInput() }),
                );
            };

            const render = () => {
                if (node.attrs.url && !node.attrs.title) {
                    body.replaceChildren(h('div', { class: 'mj-lc__loading', text: `불러오는 중… ${node.attrs.url}` }));
                    bar.hidden = true;
                } else if (!node.attrs.url) renderInput();
                else renderCard();
            };
            render();

            return {
                dom,
                update: (updated) => {
                    if (updated.type.name !== 'linkCard') return false;
                    node = updated;
                    render();
                    return true;
                },
                stopEvent: (event) => !!event.target.closest?.('input, button'),
                ignoreMutation: () => true,
                selectNode: () => dom.classList.add('is-selected'),
                deselectNode: () => dom.classList.remove('is-selected'),
            };
        };
    },
});
