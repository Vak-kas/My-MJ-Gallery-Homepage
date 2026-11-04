// 콜아웃(알림 상자): 아이콘 + 제목 + 본문. 종류(kind)에 따라 색이 다르고 아이콘은 바꿀 수 있음
// 저장 구조: callout(kind, icon) > calloutTitle(inline*) + calloutBody(block+)
import { Node, mergeAttributes } from '@tiptap/core';
import { Plugin, PluginKey, TextSelection } from '@tiptap/pm/state';

export const CALLOUT_KINDS = [
    { id: 'info', icon: 'ℹ️', title: '안내', desc: '파란 상자 · 참고 사항' },
    { id: 'tip', icon: '💡', title: '팁', desc: '초록 상자 · 도움말' },
    { id: 'warn', icon: '⚠️', title: '주의', desc: '노란 상자 · 조심할 점' },
    { id: 'danger', icon: '🚫', title: '경고', desc: '빨간 상자 · 하면 안 되는 것' },
    { id: 'note', icon: '📝', title: '메모', desc: '회색 상자 · 가벼운 메모' },
];
export const CALLOUT_IDS = CALLOUT_KINDS.map((k) => k.id);
export const calloutIcon = (kind, icon) => icon || (CALLOUT_KINDS.find((k) => k.id === kind) || CALLOUT_KINDS[0]).icon;

const cleanIcon = (value) => String(value || '').trim().slice(0, 4);

export const CalloutTitle = Node.create({
    name: 'calloutTitle',
    content: 'inline*',
    defining: true,
    selectable: false,
    parseHTML: () => [{ tag: 'div[data-type="calloutTitle"]' }],
    renderHTML: ({ HTMLAttributes }) => ['div', mergeAttributes(HTMLAttributes, { 'data-type': 'calloutTitle', class: 'mj-callout__title' }), 0],
});

export const CalloutBody = Node.create({
    name: 'calloutBody',
    content: 'block+',
    defining: true,
    selectable: false,
    parseHTML: () => [{ tag: 'div[data-type="calloutBody"]' }],
    renderHTML: ({ HTMLAttributes }) => ['div', mergeAttributes(HTMLAttributes, { 'data-type': 'calloutBody', class: 'mj-callout__body' }), 0],
});

export const Callout = Node.create({
    name: 'callout',
    group: 'block',
    content: 'calloutTitle calloutBody',
    defining: true,
    isolating: true,
    draggable: true,

    addAttributes() {
        return {
            kind: {
                default: 'info',
                parseHTML: (el) => (CALLOUT_IDS.includes(el.getAttribute('data-kind')) ? el.getAttribute('data-kind') : 'info'),
                renderHTML: (attrs) => ({ 'data-kind': CALLOUT_IDS.includes(attrs.kind) ? attrs.kind : 'info' }),
            },
            icon: {
                default: '',
                parseHTML: (el) => cleanIcon(el.getAttribute('data-icon')),
                renderHTML: (attrs) => (attrs.icon ? { 'data-icon': cleanIcon(attrs.icon) } : {}),
            },
        };
    },

    parseHTML: () => [{ tag: 'div[data-type="callout"]' }],

    renderHTML({ node, HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes, { 'data-type': 'callout', class: 'mj-callout' }),
            ['span', { class: 'mj-callout__icon', contenteditable: 'false', title: '클릭해서 아이콘 바꾸기' }, calloutIcon(node.attrs.kind, node.attrs.icon)],
            ['div', { class: 'mj-callout__inner' }, 0],
        ];
    },

    addCommands() {
        return {
            // 현재 블록을 콜아웃 본문으로 감쌈 (빈 문단이면 그냥 새 콜아웃)
            setCallout: (attrs = {}) => ({ state, chain }) => {
                const { $from } = state.selection;
                const block = $from.node($from.depth);
                const useBlock = block && block.isTextblock && block.type.name === 'paragraph' && block.content.size > 0 && $from.depth === 1;
                const bodyContent = useBlock ? [block.toJSON()] : [{ type: 'paragraph' }];
                const node = { type: this.name, attrs: { kind: 'info', ...attrs }, content: [{ type: 'calloutTitle' }, { type: 'calloutBody', content: bodyContent }] };
                if (useBlock) {
                    const from = $from.before(1);
                    return chain().insertContentAt({ from, to: from + block.nodeSize }, node).focus(from + 2).run();
                }
                return chain().insertContent(node).command(({ tr }) => {
                    // 제목 칸으로 커서 이동
                    let titlePos = null;
                    tr.doc.nodesBetween(0, tr.selection.from, (n, pos) => {
                        if (n.type.name === 'calloutTitle') titlePos = pos + 1;
                    });
                    if (titlePos !== null) tr.setSelection(TextSelection.create(tr.doc, titlePos));
                    return true;
                }).focus().run();
            },
            setCalloutKind: (kind) => ({ commands }) => commands.updateAttributes(this.name, { kind: CALLOUT_IDS.includes(kind) ? kind : 'info' }),
            setCalloutIcon: (icon) => ({ commands }) => commands.updateAttributes(this.name, { icon: cleanIcon(icon) }),
        };
    },

    addKeyboardShortcuts() {
        const inCallout = (state) => {
            const { $from } = state.selection;
            for (let d = $from.depth; d > 0; d -= 1) {
                if ($from.node(d).type.name === 'callout') return { depth: d, node: $from.node(d), pos: $from.before(d) };
            }
            return null;
        };
        return {
            // 제목에서 Enter → 본문 첫 줄로
            Enter: ({ editor }) => {
                const { state } = editor;
                const { $from, empty } = state.selection;
                if (!empty) return false;
                const parent = $from.parent;
                if (parent.type.name === 'calloutTitle') {
                    return editor.commands.focus($from.after() + 2);
                }
                // 본문 마지막 빈 문단에서 Enter → 콜아웃 밖으로 나감
                const found = inCallout(state);
                if (!found || parent.type.name !== 'paragraph' || parent.content.size !== 0) return false;
                const body = $from.node($from.depth - 1);
                if (body.type.name !== 'calloutBody' || body.childCount < 2 || $from.index($from.depth - 1) !== body.childCount - 1) return false;
                const after = found.pos + found.node.nodeSize;
                return editor.chain().deleteRange({ from: $from.before(), to: $from.after() }).insertContentAt(after - 1, { type: 'paragraph' }).focus(after).run();
            },
            // 비어 있는 제목+본문에서 Backspace → 콜아웃을 지우고 빈 문단으로
            Backspace: ({ editor }) => {
                const { state } = editor;
                const { $from, empty } = state.selection;
                if (!empty || $from.parentOffset !== 0) return false;
                const found = inCallout(state);
                if (!found || found.node.textContent.length > 0) return false;
                if ($from.parent.type.name !== 'calloutTitle') return false;
                return editor.chain().deleteRange({ from: found.pos, to: found.pos + found.node.nodeSize }).insertContentAt(found.pos, { type: 'paragraph' }).focus(found.pos + 1).run();
            },
        };
    },

    addProseMirrorPlugins() {
        const type = this.type;
        return [
            new Plugin({
                key: new PluginKey('mjCalloutIcon'),
                props: {
                    // 아이콘 클릭 → 이모지 입력
                    handleClick: (view, _pos, event) => {
                        const target = event.target;
                        if (!(target instanceof HTMLElement) || !target.classList.contains('mj-callout__icon')) return false;
                        const dom = target.closest('[data-type="callout"]');
                        const pos = dom ? view.posAtDOM(dom, 0) - 1 : -1;
                        const node = pos >= 0 ? view.state.doc.nodeAt(pos) : null;
                        if (!node || node.type !== type) return false;
                        const next = window.prompt('콜아웃 아이콘 (이모지 하나, 비우면 기본 아이콘)', node.attrs.icon || '');
                        if (next === null) return true;
                        view.dispatch(view.state.tr.setNodeMarkup(pos, undefined, { ...node.attrs, icon: cleanIcon(next) }));
                        return true;
                    },
                },
            }),
        ];
    },
});

export const createCalloutExtensions = () => [Callout, CalloutTitle, CalloutBody];
