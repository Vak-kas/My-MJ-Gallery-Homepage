// 수식: $x^2$ → 인라인 수식, 빈 줄에서 "$$ " → 블록 수식, 클릭하면 편집 팝오버(실시간 미리보기 + OCR)
import { InputRule } from '@tiptap/core';
import { BlockMath, InlineMath } from '@tiptap/extension-mathematics';
import katex from 'katex';
import { dismissOnOutside, h, placeFloating } from '../dom.js';

const KATEX_OPTIONS = { throwOnError: false };

let closeActive = null;

// pos 위치의 수식 노드를 편집하는 팝오버
export const openMathEditor = (editor, pos, { isNew = false } = {}) => {
    closeActive?.();
    const node = editor.state.doc.nodeAt(pos);
    if (!node || !['inlineMath', 'blockMath'].includes(node.type.name)) return;
    const { api, notify } = editor.storage.inlineMath;

    let type = node.type.name;
    const input = h('textarea', { class: 'mj-math__input', rows: 3, spellcheck: 'false', placeholder: '예: \\frac{a}{b}, x^2 + y^2 = z^2' });
    input.value = node.attrs.latex || '';
    const preview = h('div', { class: 'mj-math__preview' });
    const modeBtn = h('button', { type: 'button', class: 'mj-chip' });
    const ocrInput = h('input', { type: 'file', accept: 'image/*', hidden: true });
    const ocrBtn = h('button', { type: 'button', class: 'mj-chip', text: '📷 수식 이미지 인식' });

    const renderPreview = () => {
        const latex = input.value.trim();
        modeBtn.textContent = type === 'blockMath' ? '블록 수식 ↔ 인라인' : '인라인 수식 ↔ 블록';
        if (!latex) {
            preview.textContent = '미리보기';
            preview.classList.add('is-empty');
            return;
        }
        preview.classList.remove('is-empty');
        try {
            katex.render(latex, preview, { ...KATEX_OPTIONS, displayMode: type === 'blockMath' });
        } catch (err) {
            preview.textContent = err.message;
        }
    };

    const panel = h('div', { class: 'mj-pop mj-math' }, [
        h('div', { class: 'mj-pop__title', text: '수식 (LaTeX)' }),
        input,
        preview,
        h('div', { class: 'mj-math__row' }, [
            modeBtn,
            ocrBtn,
            ocrInput,
            h('span', { class: 'mj-math__hint', text: type === 'blockMath' ? '⌘/Ctrl+Enter 완료' : 'Enter 완료' }),
            h('button', { type: 'button', class: 'mj-btn mj-btn--primary', text: '완료', onclick: () => finish(true) }),
        ]),
    ]);

    const currentPos = () => {
        // 다른 사용자가 없으니 문서 변경은 이 팝오버의 동작뿐 → 처음 위치 그대로 유효
        const current = editor.state.doc.nodeAt(pos);
        return current && ['inlineMath', 'blockMath'].includes(current.type.name) ? pos : null;
    };

    let cleanup = () => {};
    const finish = (commit) => {
        cleanup();
        panel.remove();
        closeActive = null;
        const at = currentPos();
        if (at === null) return;
        const current = editor.state.doc.nodeAt(at);
        const latex = input.value.trim();
        const chain = editor.chain();
        if (commit && latex) {
            if (type !== current.type.name) {
                // 인라인 → 블록이면 문단이 자동으로 나뉘고, 블록 → 인라인이면 새 문단에 담김
                const replacement = type === 'blockMath'
                    ? { type: 'blockMath', attrs: { latex } }
                    : { type: 'paragraph', content: [{ type: 'inlineMath', attrs: { latex } }] };
                chain.insertContentAt({ from: at, to: at + current.nodeSize }, replacement).focus().run();
                return;
            } else if (latex !== current.attrs.latex) {
                chain.command(({ tr }) => {
                    tr.setNodeMarkup(at, undefined, { ...current.attrs, latex });
                    return true;
                });
            }
            chain.focus(at + 1).run();
            return;
        }
        if (commit && !latex) {
            chain.deleteRange({ from: at, to: at + current.nodeSize }).focus().run();
            return;
        }
        // 취소: 새로 만든 빈 수식이면 지움
        if (isNew && !current.attrs.latex) chain.deleteRange({ from: at, to: at + current.nodeSize });
        chain.focus().run();
    };

    input.addEventListener('input', renderPreview);
    input.addEventListener('keydown', (e) => {
        if (e.isComposing) return;
        const submit = type === 'blockMath' ? (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) : (e.key === 'Enter' && !e.shiftKey);
        if (submit) {
            e.preventDefault();
            finish(true);
        }
    });
    modeBtn.addEventListener('click', () => {
        type = type === 'blockMath' ? 'inlineMath' : 'blockMath';
        renderPreview();
    });
    ocrBtn.addEventListener('click', () => ocrInput.click());
    ocrInput.addEventListener('change', async () => {
        const file = ocrInput.files?.[0];
        if (!file) return;
        ocrBtn.disabled = true;
        ocrBtn.textContent = '인식 중…';
        try {
            const latex = await api.mathOcr(file);
            if (latex) {
                input.value = latex;
                renderPreview();
            } else notify?.('수식을 찾지 못했습니다.', 'error');
        } catch (err) {
            notify?.(`수식 인식 실패: ${err.message}`, 'error');
        } finally {
            ocrBtn.disabled = false;
            ocrBtn.textContent = '📷 수식 이미지 인식';
            ocrInput.value = '';
        }
    });

    document.body.append(panel);
    const anchor = editor.view.nodeDOM(pos);
    placeFloating(anchor instanceof Element ? anchor : editor.view.dom, panel, 'bottom-start');
    renderPreview();
    setTimeout(() => {
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
    }, 0);
    cleanup = dismissOnOutside(panel, () => finish(true));
    closeActive = () => finish(true);
};

export const insertMath = (editor, kind) => {
    const type = kind === 'block' ? 'blockMath' : 'inlineMath';
    const { from } = editor.state.selection;
    editor.chain().focus().insertContent({ type, attrs: { latex: '' } }).run();
    // 삽입된 수식 노드 위치 찾기 (커서 바로 앞)
    let found = null;
    editor.state.doc.nodesBetween(Math.max(0, from - 2), Math.min(editor.state.doc.content.size, editor.state.selection.from + 2), (node, pos) => {
        if (node.type.name === type && !node.attrs.latex) found = pos;
    });
    if (found !== null) openMathEditor(editor, found, { isNew: true });
};

export const createMathExtensions = ({ api, notify }) => {
    let editorRef = null;
    const onClick = (node, pos) => editorRef && openMathEditor(editorRef, pos);

    const Inline = InlineMath.extend({
        addStorage() {
            return { api, notify };
        },
        onCreate() {
            this.parent?.();
            editorRef = this.editor;
        },
        addInputRules() {
            // $x$ (앞뒤 공백 없는 내용) → 인라인 수식. "$5 and $10" 같은 금액은 변환되지 않도록 공백 규칙 적용
            return [
                new InputRule({
                    find: /(^|[^$\\\w])\$([^\s$](?:[^$\n]*[^\s$\\])?)\$$/,
                    handler: ({ state, range, match }) => {
                        const from = range.from + match[1].length;
                        state.tr.replaceWith(from, range.to, this.type.create({ latex: match[2] }));
                    },
                }),
            ];
        },
    }).configure({ onClick, katexOptions: KATEX_OPTIONS });

    const Block = BlockMath.extend({
        addInputRules() {
            return [
                new InputRule({
                    find: /^\$\$\s$/,
                    handler: ({ state, range }) => {
                        const $from = state.doc.resolve(range.from);
                        if ($from.parent.type.name !== 'paragraph') return null;
                        const at = $from.before();
                        state.tr.replaceWith(at, $from.after(), this.type.create({ latex: '' }));
                        setTimeout(() => editorRef && openMathEditor(editorRef, at, { isNew: true }), 0);
                    },
                }),
            ];
        },
    }).configure({ onClick, katexOptions: { ...KATEX_OPTIONS, displayMode: true } });

    return [Inline, Block];
};
