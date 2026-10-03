// 텍스트를 선택하면 뜨는 서식 툴바 (굵게/기울임/밑줄/취소선/코드/링크/색/글꼴)
import { BubbleMenu } from '@tiptap/extension-bubble-menu';
import { NodeSelection } from '@tiptap/pm/state';
import { dismissOnOutside, h, placeFloating } from '../dom.js';

export const TEXT_COLORS = [
    ['기본', null], ['회색', '#787774'], ['갈색', '#9f6b53'], ['주황', '#d9730d'], ['노랑', '#cb912f'],
    ['초록', '#448361'], ['파랑', '#337ea9'], ['보라', '#9065b0'], ['분홍', '#c14c8a'], ['빨강', '#d44c47'],
];
export const BG_COLORS = [
    ['기본', null], ['회색', '#f1f1ef'], ['갈색', '#f4eeee'], ['주황', '#fbecdd'], ['노랑', '#fbf3db'],
    ['초록', '#edf3ec'], ['파랑', '#e7f3f8'], ['보라', '#f6f3f9'], ['분홍', '#faf1f5'], ['빨강', '#fdebec'],
];
export const FONTS = [
    ['기본 글꼴', null],
    ['Noto Sans KR', "'Noto Sans KR', sans-serif"],
    ['나눔고딕', "'Nanum Gothic', sans-serif"],
    ['IBM Plex Sans KR', "'IBM Plex Sans KR', sans-serif"],
    ['Noto Serif KR', "'Noto Serif KR', serif"],
    ['Serif', 'Georgia, serif'],
    ['Monospace', 'Menlo, monospace'],
];

const createToolbar = (getEditor) => {
    const btn = (label, title, onClick, cls = '') => h('button', {
        type: 'button',
        class: `mj-bubble__btn ${cls}`,
        title,
        text: label,
        onmousedown: (e) => e.preventDefault(),
        onclick: onClick,
    });
    const run = (fn) => () => fn(getEditor().chain().focus()).run();

    const buttons = {
        bold: btn('B', '굵게 (⌘B)', run((c) => c.toggleBold()), 'is-bold'),
        italic: btn('i', '기울임 (⌘I)', run((c) => c.toggleItalic()), 'is-italic'),
        underline: btn('U', '밑줄 (⌘U)', run((c) => c.toggleUnderline()), 'is-underline'),
        strike: btn('S', '취소선', run((c) => c.toggleStrike()), 'is-strike'),
        code: btn('</>', '인라인 코드', run((c) => c.toggleCode())),
    };

    const linkInput = h('input', { type: 'url', class: 'mj-bubble__link', placeholder: '링크 주소 입력 후 Enter' });
    const linkRow = h('div', { class: 'mj-bubble__row', hidden: true }, [linkInput]);

    const linkBtn = btn('🔗', '링크', () => {
        const editor = getEditor();
        if (editor.isActive('link')) {
            editor.chain().focus().extendMarkRange('link').unsetLink().run();
            return;
        }
        mainRow.hidden = true;
        linkRow.hidden = false;
        linkInput.value = '';
        setTimeout(() => linkInput.focus(), 0);
    });
    linkInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            let href = linkInput.value.trim();
            if (href && !/^(https?:|mailto:|\/|#)/i.test(href)) href = `https://${href}`;
            const chain = getEditor().chain().focus().extendMarkRange('link');
            (href ? chain.setLink({ href }) : chain.unsetLink()).run();
            linkRow.hidden = true;
            mainRow.hidden = false;
        } else if (e.key === 'Escape') {
            linkRow.hidden = true;
            mainRow.hidden = false;
            getEditor().commands.focus();
        }
    });

    const colorBtn = btn('A', '글자색 / 배경색', () => {
        const editor = getEditor();
        const swatch = (list, kind) => h('div', { class: 'mj-swatches' }, list.map(([name, color]) => h('button', {
            type: 'button',
            class: 'mj-swatch',
            title: name,
            style: kind === 'text' ? `color:${color || 'inherit'}` : `background:${color || 'transparent'}`,
            text: 'A',
            onmousedown: (e) => e.preventDefault(),
            onclick: () => {
                const chain = editor.chain().focus();
                if (kind === 'text') (color ? chain.setColor(color) : chain.unsetColor()).run();
                else (color ? chain.setBackgroundColor(color) : chain.unsetBackgroundColor()).run();
                close();
            },
        })));
        const panel = h('div', { class: 'mj-pop mj-colors' }, [
            h('div', { class: 'mj-pop__group', text: '글자색' }), swatch(TEXT_COLORS, 'text'),
            h('div', { class: 'mj-pop__group', text: '배경색' }), swatch(BG_COLORS, 'bg'),
        ]);
        let cleanup = () => {};
        const close = () => {
            cleanup();
            panel.remove();
        };
        document.body.append(panel);
        placeFloating(colorBtn, panel, 'bottom-start');
        cleanup = dismissOnOutside(panel, close);
    }, 'is-color');

    const fontSelect = h('select', { class: 'mj-bubble__font', title: '글꼴' }, FONTS.map(([name, value]) => h('option', { value: value || '', text: name })));
    fontSelect.addEventListener('change', () => {
        const chain = getEditor().chain().focus();
        (fontSelect.value ? chain.setFontFamily(fontSelect.value) : chain.unsetFontFamily()).run();
    });

    const clearBtn = btn('⌫', '서식 지우기', run((c) => c.unsetAllMarks()));

    const mainRow = h('div', { class: 'mj-bubble__row' }, [
        buttons.bold, buttons.italic, buttons.underline, buttons.strike, buttons.code,
        h('span', { class: 'mj-bubble__sep' }), linkBtn, colorBtn, fontSelect,
        h('span', { class: 'mj-bubble__sep' }), clearBtn,
    ]);
    const element = h('div', { class: 'mj-bubble' }, [mainRow, linkRow]);

    const refresh = () => {
        const editor = getEditor();
        if (!editor) return;
        Object.entries(buttons).forEach(([name, el]) => el.classList.toggle('is-active', editor.isActive(name)));
        linkBtn.classList.toggle('is-active', editor.isActive('link'));
        fontSelect.value = editor.getAttributes('textStyle').fontFamily || '';
    };
    const reset = () => {
        linkRow.hidden = true;
        mainRow.hidden = false;
    };
    return { element, refresh, reset };
};

export const createBubbleToolbar = () => {
    let editorRef = null;
    const toolbar = createToolbar(() => editorRef);
    return BubbleMenu.extend({
        onCreate() {
            editorRef = this.editor;
            this.parent?.();
        },
        onSelectionUpdate() {
            toolbar.refresh();
            this.parent?.();
        },
        onTransaction() {
            toolbar.refresh();
            this.parent?.();
        },
    }).configure({
        element: toolbar.element,
        pluginKey: 'mjBubbleToolbar',
        appendTo: () => document.body,
        options: { placement: 'top', strategy: 'fixed', offset: 8, flip: true, shift: { padding: 8 }, onShow: toolbar.reset },
        shouldShow: ({ editor, view, state, from, to }) => {
            if (!editor.isEditable || from === to) return false;
            if (!view.hasFocus() && !toolbar.element.contains(document.activeElement)) return false;
            if (state.selection instanceof NodeSelection) return false;
            if (editor.isActive('codeBlock')) return false;
            return state.doc.textBetween(from, to).trim().length > 0;
        },
    });
};
