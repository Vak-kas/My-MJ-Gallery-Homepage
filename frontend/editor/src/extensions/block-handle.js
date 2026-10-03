// 블록 왼쪽 핸들: [+] 아래에 블록 추가, [⋮⋮] 끌어서 이동 / 클릭하면 블록 메뉴(삭제·복제·전환)
import { Extension } from '@tiptap/core';
import { DOMSerializer } from '@tiptap/pm/model';
import { NodeSelection, Plugin, PluginKey, Selection, TextSelection } from '@tiptap/pm/state';
import { dismissOnOutside, h, placeFloating } from '../dom.js';
import { BLOCK_ITEMS, runBlockItem } from './slash-menu.js';

const TURN_INTO = ['paragraph', 'h1', 'h2', 'h3', 'bullet', 'ordered', 'todo', 'quote', 'code'];

// 마우스 y 좌표에 있는 최상위 블록 찾기
const blockAtY = (view, y) => {
    let hit = null;
    view.state.doc.forEach((node, offset) => {
        if (hit) return;
        const dom = view.nodeDOM(offset);
        if (!(dom instanceof HTMLElement)) return;
        const rect = dom.getBoundingClientRect();
        if (y >= rect.top - 4 && y <= rect.bottom + 4) hit = { node, pos: offset, dom };
    });
    return hit;
};

const openBlockMenu = (editor, anchor, pos) => {
    const node = editor.state.doc.nodeAt(pos);
    if (!node) return;
    let cleanup = () => {};
    const close = () => {
        cleanup();
        panel.remove();
    };
    const act = (fn) => () => {
        close();
        fn();
    };
    const canTurn = node.isTextblock || ['bulletList', 'orderedList', 'taskList', 'blockquote'].includes(node.type.name);

    const turnInto = (item) => {
        // 블록 내용을 선택한 뒤 전환 명령 실행
        const $start = editor.state.doc.resolve(pos + 1);
        const sel = TextSelection.between($start, editor.state.doc.resolve(pos + node.nodeSize - 1));
        editor.view.dispatch(editor.state.tr.setSelection(sel));
        const current = editor.state.doc.nodeAt(pos);
        // 목록/인용에서 다른 형태로 바꿀 땐 먼저 감싼 구조를 풂
        if (current && ['bulletList', 'orderedList', 'taskList'].includes(current.type.name)) {
            editor.chain().focus().liftListItem(current.type.name === 'taskList' ? 'taskItem' : 'listItem').run();
        } else if (current && current.type.name === 'blockquote' && item.id !== 'quote') {
            editor.chain().focus().lift('blockquote').run();
        }
        runBlockItem(editor, item);
    };

    const panel = h('div', { class: 'mj-pop mj-blockmenu' }, [
        h('button', { type: 'button', class: 'mj-pop__item', onclick: act(() => {
            editor.chain().command(({ tr }) => {
                tr.delete(pos, pos + node.nodeSize);
                tr.setSelection(Selection.near(tr.doc.resolve(Math.min(pos, tr.doc.content.size))));
                return true;
            }).focus(undefined, { scrollIntoView: false }).run();
        }) }, [h('span', { class: 'mj-pop__icon', text: '🗑' }), h('b', { text: '삭제' })]),
        h('button', { type: 'button', class: 'mj-pop__item', onclick: act(() => {
            editor.chain().command(({ tr }) => {
                const at = pos + node.nodeSize;
                tr.insert(at, node.copy(node.content));
                tr.setSelection(Selection.near(tr.doc.resolve(at + 1)));
                return true;
            }).focus(undefined, { scrollIntoView: false }).run();
        }) }, [h('span', { class: 'mj-pop__icon', text: '⧉' }), h('b', { text: '복제' })]),
        canTurn ? h('div', { class: 'mj-pop__group', text: '전환' }) : null,
        ...(canTurn ? BLOCK_ITEMS.filter((item) => TURN_INTO.includes(item.id)).map((item) => h('button', {
            type: 'button',
            class: 'mj-pop__item',
            onclick: act(() => turnInto(item)),
        }, [h('span', { class: 'mj-pop__icon', text: item.icon }), h('b', { text: item.title })])) : []),
    ]);
    panel.querySelectorAll('button').forEach((b) => b.addEventListener('mousedown', (e) => e.preventDefault()));
    document.body.append(panel);
    placeFloating(anchor, panel, 'bottom-start');
    cleanup = dismissOnOutside(panel, close);
};

export const BlockHandle = Extension.create({
    name: 'blockHandle',

    addProseMirrorPlugins() {
        const editor = this.editor;
        return [
            new Plugin({
                key: new PluginKey('mjBlockHandle'),
                view: (view) => {
                    const plusBtn = h('button', { type: 'button', class: 'mj-handle__btn', title: '아래에 블록 추가', text: '+' });
                    const dragBtn = h('button', { type: 'button', class: 'mj-handle__btn mj-handle__drag', title: '끌어서 이동 · 클릭하면 메뉴', draggable: 'true', text: '⋮⋮' });
                    const handle = h('div', { class: 'mj-handle', contenteditable: 'false' }, [plusBtn, dragBtn]);
                    const host = view.dom.parentElement;
                    host.style.position = host.style.position || 'relative';
                    host.append(handle);

                    let current = null;
                    let frame = 0;

                    const hide = () => {
                        handle.classList.remove('is-visible');
                        current = null;
                    };

                    const show = (block) => {
                        current = block;
                        const hostRect = host.getBoundingClientRect();
                        const rect = block.dom.getBoundingClientRect();
                        const style = getComputedStyle(block.dom);
                        const lineHeight = parseFloat(style.lineHeight) || 24;
                        const paddingTop = parseFloat(style.paddingTop) || 0;
                        const firstLine = Math.min(rect.height, lineHeight + paddingTop);
                        handle.style.top = `${rect.top - hostRect.top + firstLine / 2 - 12}px`;
                        handle.style.left = `${Math.max(0, rect.left - hostRect.left - 52)}px`;
                        handle.classList.add('is-visible');
                    };

                    const onMove = (e) => {
                        if (!editor.isEditable) return;
                        cancelAnimationFrame(frame);
                        frame = requestAnimationFrame(() => {
                            if (handle.contains(e.target)) return;
                            const block = blockAtY(view, e.clientY);
                            if (block) show(block);
                            else hide();
                        });
                    };
                    const onLeave = (e) => {
                        if (!host.contains(e.relatedTarget)) hide();
                    };
                    host.addEventListener('mousemove', onMove);
                    host.addEventListener('mouseleave', onLeave);
                    view.dom.addEventListener('keydown', hide);

                    plusBtn.addEventListener('mousedown', (e) => e.preventDefault());
                    plusBtn.addEventListener('click', () => {
                        if (!current) return;
                        const { node, pos } = current;
                        // 빈 문단이면 그 자리에서, 아니면 아래에 새 줄을 만들고 "/" 메뉴를 엶
                        if (node.type.name === 'paragraph' && node.content.size === 0) {
                            editor.chain().focus(pos + 1).insertContent('/').run();
                        } else {
                            const at = pos + node.nodeSize;
                            editor.chain().insertContentAt(at, { type: 'paragraph' }).focus(at + 1).insertContent('/').run();
                        }
                        hide();
                    });

                    dragBtn.addEventListener('click', () => {
                        if (current) openBlockMenu(editor, dragBtn, current.pos);
                    });

                    dragBtn.addEventListener('dragstart', (e) => {
                        if (!current) return;
                        const { pos, dom } = current;
                        const sel = NodeSelection.create(view.state.doc, pos);
                        view.dispatch(view.state.tr.setSelection(sel));
                        const slice = sel.content();
                        const wrap = document.createElement('div');
                        wrap.append(DOMSerializer.fromSchema(view.state.schema).serializeFragment(slice.content));
                        e.dataTransfer.clearData();
                        e.dataTransfer.setData('text/html', wrap.innerHTML);
                        e.dataTransfer.setData('text/plain', slice.content.textBetween(0, slice.content.size, '\n'));
                        e.dataTransfer.effectAllowed = 'copyMove';
                        e.dataTransfer.setDragImage(dom, 0, 0);
                        // ProseMirror 기본 drop 처리가 이 정보를 보고 원래 블록을 옮김
                        view.dragging = { slice, move: true, node: sel };
                        dom.classList.add('mj-dragging');
                        const end = () => {
                            dom.classList.remove('mj-dragging');
                            dragBtn.removeEventListener('dragend', end);
                        };
                        dragBtn.addEventListener('dragend', end);
                    });

                    return {
                        update: () => {
                            if (current && !current.dom.isConnected) hide();
                        },
                        destroy: () => {
                            host.removeEventListener('mousemove', onMove);
                            host.removeEventListener('mouseleave', onLeave);
                            view.dom.removeEventListener('keydown', hide);
                            handle.remove();
                        },
                    };
                },
            }),
        ];
    },
});
