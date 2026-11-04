// 표 도구: 커서가 표 안에 있으면 표 위에 도구 모음(행·열 추가/삭제, 헤더, 병합/분할, 표 삭제)이 뜨고,
// 표에 마우스를 올리면 오른쪽·아래 테두리에 [+] 가 떠서 열/행을 바로 더할 수 있음
import { Extension } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { h, placeFloating } from '../dom.js';

const KEY = new PluginKey('mjTableTools');

// 선택 위치에서 감싸고 있는 표 노드 찾기
const tableAround = (state) => {
    const { $from } = state.selection;
    for (let d = $from.depth; d > 0; d -= 1) {
        if ($from.node(d).type.name === 'table') return { node: $from.node(d), pos: $from.before(d) };
    }
    return null;
};

// wrapper DOM → 표 노드 위치
const tableAtDom = (view, wrapper) => {
    let pos;
    try {
        pos = view.posAtDOM(wrapper, 0);
    } catch {
        return null;
    }
    const direct = view.state.doc.nodeAt(pos);
    if (direct && direct.type.name === 'table') return { node: direct, pos };
    const $pos = view.state.doc.resolve(pos);
    for (let d = $pos.depth; d > 0; d -= 1) {
        if ($pos.node(d).type.name === 'table') return { node: $pos.node(d), pos: $pos.before(d) };
    }
    return null;
};

// 표의 (행 index, 셀 index) 셀 안 텍스트 위치
const cellTextPos = (table, tablePos, rowIndex, cellIndex) => {
    let pos = tablePos + 1;
    for (let r = 0; r < rowIndex; r += 1) pos += table.child(r).nodeSize;
    const row = table.child(rowIndex);
    pos += 1;
    for (let c = 0; c < cellIndex; c += 1) pos += row.child(c).nodeSize;
    return pos + 2; // 셀 열기 + 첫 문단 열기
};

export const TABLE_ACTIONS = [
    { id: 'rowBefore', icon: '↑', title: '위에 행 추가', run: (c) => c.addRowBefore() },
    { id: 'rowAfter', icon: '↓', title: '아래에 행 추가', run: (c) => c.addRowAfter() },
    { id: 'deleteRow', icon: '⊟', title: '행 삭제', run: (c) => c.deleteRow() },
    { id: 'colBefore', icon: '←', title: '왼쪽에 열 추가', run: (c) => c.addColumnBefore() },
    { id: 'colAfter', icon: '→', title: '오른쪽에 열 추가', run: (c) => c.addColumnAfter() },
    { id: 'deleteCol', icon: '⊠', title: '열 삭제', run: (c) => c.deleteColumn() },
    { id: 'headerRow', icon: '⊤', title: '첫 행을 머리글로 / 해제', run: (c) => c.toggleHeaderRow() },
    { id: 'headerCol', icon: '⊢', title: '첫 열을 머리글로 / 해제', run: (c) => c.toggleHeaderColumn() },
    { id: 'merge', icon: '⊞', title: '셀 병합 (여러 셀을 끌어서 선택한 뒤)', run: (c) => c.mergeCells(), can: (e) => e.can().mergeCells() },
    { id: 'split', icon: '⊟', title: '셀 분할 (병합한 셀을)', run: (c) => c.splitCell(), can: (e) => e.can().splitCell() },
    { id: 'deleteTable', icon: '🗑', title: '표 삭제', run: (c) => c.deleteTable() },
];

export const TableTools = Extension.create({
    name: 'tableTools',

    addProseMirrorPlugins() {
        const editor = this.editor;
        return [
            new Plugin({
                key: KEY,
                view: (view) => {
                    // ── 표 위 도구 모음 ──
                    const groups = [['rowBefore', 'rowAfter', 'deleteRow'], ['colBefore', 'colAfter', 'deleteCol'], ['headerRow', 'headerCol'], ['merge', 'split'], ['deleteTable']];
                    const buttons = {};
                    const bar = h('div', { class: 'mj-tablebar', hidden: true });
                    groups.forEach((ids, gi) => {
                        if (gi) bar.append(h('span', { class: 'mj-bubble__sep' }));
                        ids.forEach((id) => {
                            const action = TABLE_ACTIONS.find((a) => a.id === id);
                            const btn = h('button', {
                                type: 'button', class: 'mj-bubble__btn', title: action.title, text: action.icon,
                                onmousedown: (e) => e.preventDefault(),
                                onclick: () => { action.run(editor.chain().focus()).run(); },
                            });
                            buttons[id] = btn;
                            bar.append(btn);
                        });
                    });
                    document.body.append(bar);

                    const refreshBar = () => {
                        const found = editor.isEditable && (view.hasFocus() || bar.contains(document.activeElement)) ? tableAround(view.state) : null;
                        if (!found) {
                            bar.hidden = true;
                            return;
                        }
                        const dom = view.nodeDOM(found.pos);
                        if (!(dom instanceof HTMLElement)) {
                            bar.hidden = true;
                            return;
                        }
                        TABLE_ACTIONS.forEach((a) => { if (a.can) buttons[a.id].disabled = !a.can(editor); });
                        buttons.headerRow.classList.toggle('is-active', found.node.firstChild?.firstChild?.type.name === 'tableHeader');
                        bar.hidden = false;
                        placeFloating(dom, bar, 'top-start');
                    };

                    // ── 테두리 [+] ──
                    const host = view.dom.parentElement;
                    host.style.position = host.style.position || 'relative';
                    const addCol = h('button', { type: 'button', class: 'mj-table-add mj-table-add--col', title: '오른쪽에 열 추가', text: '+' });
                    const addRow = h('button', { type: 'button', class: 'mj-table-add mj-table-add--row', title: '아래에 행 추가', text: '+' });
                    host.append(addCol, addRow);
                    let hovered = null;

                    const hideAdders = () => {
                        hovered = null;
                        addCol.classList.remove('is-visible');
                        addRow.classList.remove('is-visible');
                    };
                    const showAdders = (wrapper) => {
                        const table = wrapper.querySelector('table');
                        if (!table) return;
                        hovered = wrapper;
                        const hostRect = host.getBoundingClientRect();
                        const rect = table.getBoundingClientRect();
                        const right = Math.min(rect.right, wrapper.getBoundingClientRect().right);
                        addCol.style.left = `${right - hostRect.left - 10}px`;
                        addCol.style.top = `${rect.top - hostRect.top + rect.height / 2 - 11}px`;
                        addRow.style.left = `${rect.left - hostRect.left + Math.min(rect.width, wrapper.clientWidth) / 2 - 11}px`;
                        addRow.style.top = `${rect.bottom - hostRect.top - 10}px`;
                        addCol.classList.add('is-visible');
                        addRow.classList.add('is-visible');
                    };
                    const onMove = (e) => {
                        if (!editor.isEditable) return;
                        const target = e.target;
                        if (!(target instanceof Element)) return;
                        if (target.classList.contains('mj-table-add')) return;
                        const wrapper = target.closest('.tableWrapper');
                        if (wrapper && view.dom.contains(wrapper)) showAdders(wrapper);
                        else if (hovered) hideAdders();
                    };
                    const onLeave = (e) => {
                        if (!host.contains(e.relatedTarget)) hideAdders();
                    };
                    host.addEventListener('mousemove', onMove);
                    host.addEventListener('mouseleave', onLeave);

                    const addAtEdge = (which) => {
                        if (!hovered) return;
                        const found = tableAtDom(view, hovered);
                        if (!found) return;
                        const { node, pos } = found;
                        if (which === 'col') {
                            const sel = cellTextPos(node, pos, 0, node.firstChild.childCount - 1);
                            editor.chain().focus().setTextSelection(sel).addColumnAfter().run();
                        } else {
                            const sel = cellTextPos(node, pos, node.childCount - 1, 0);
                            editor.chain().focus().setTextSelection(sel).addRowAfter().run();
                        }
                        requestAnimationFrame(() => { if (hovered?.isConnected) showAdders(hovered); });
                    };
                    [addCol, addRow].forEach((b) => b.addEventListener('mousedown', (e) => e.preventDefault()));
                    addCol.addEventListener('click', () => addAtEdge('col'));
                    addRow.addEventListener('click', () => addAtEdge('row'));

                    const onBlur = () => setTimeout(refreshBar, 0);
                    view.dom.addEventListener('blur', onBlur);
                    view.dom.addEventListener('focus', refreshBar);
                    window.addEventListener('scroll', refreshBar, true);

                    return {
                        update: () => {
                            refreshBar();
                            if (hovered && !hovered.isConnected) hideAdders();
                        },
                        destroy: () => {
                            bar.remove();
                            addCol.remove();
                            addRow.remove();
                            host.removeEventListener('mousemove', onMove);
                            host.removeEventListener('mouseleave', onLeave);
                            view.dom.removeEventListener('blur', onBlur);
                            view.dom.removeEventListener('focus', refreshBar);
                            window.removeEventListener('scroll', refreshBar, true);
                        },
                    };
                },
            }),
        ];
    },
});
