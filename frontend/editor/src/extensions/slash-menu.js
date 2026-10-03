// "/" 슬래시 메뉴: 입력하면 블록 목록 팝업, 한글/영문 검색, ↑↓ Enter Esc
import { Extension } from '@tiptap/core';
import { PluginKey } from '@tiptap/pm/state';
import Suggestion from '@tiptap/suggestion';
import { h, placeFloating } from '../dom.js';
import { insertImageFiles } from './image.js';
import { insertMath } from './math.js';

const pickImageFiles = (editor) => {
    const input = h('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true });
    input.addEventListener('change', () => {
        insertImageFiles(editor, input.files);
        input.remove();
    });
    document.body.append(input);
    input.click();
};

export const BLOCK_ITEMS = [
    { id: 'paragraph', group: '기본 블록', icon: '¶', title: '텍스트', desc: '일반 문단', keys: 'text paragraph p 텍스트 문단 본문', run: (c) => c.setParagraph() },
    { id: 'h1', group: '기본 블록', icon: 'H1', title: '제목 1', desc: '큰 제목', keys: 'h1 heading title 제목1 제목 큰', run: (c) => c.setHeading({ level: 1 }) },
    { id: 'h2', group: '기본 블록', icon: 'H2', title: '제목 2', desc: '중간 제목', keys: 'h2 heading 제목2 제목 중간', run: (c) => c.setHeading({ level: 2 }) },
    { id: 'h3', group: '기본 블록', icon: 'H3', title: '제목 3', desc: '작은 제목', keys: 'h3 heading 제목3 제목 작은', run: (c) => c.setHeading({ level: 3 }) },
    { id: 'bullet', group: '기본 블록', icon: '•', title: '글머리 기호 목록', desc: '- 로도 시작 가능', keys: 'bullet list ul 목록 리스트 글머리', run: (c) => c.toggleBulletList() },
    { id: 'ordered', group: '기본 블록', icon: '1.', title: '번호 매기기 목록', desc: '1. 로도 시작 가능', keys: 'ordered number list ol 번호 목록 리스트', run: (c) => c.toggleOrderedList() },
    { id: 'todo', group: '기본 블록', icon: '☑', title: '할 일 목록', desc: '[] 로도 시작 가능', keys: 'todo task check checklist 할일 체크 투두', run: (c) => c.toggleTaskList() },
    { id: 'toggle', group: '기본 블록', icon: '▸', title: '토글', desc: '접고 펼치는 블록', keys: 'toggle details 토글 접기', run: (c) => c.setDetails() },
    { id: 'quote', group: '기본 블록', icon: '❝', title: '인용', desc: '> 로도 시작 가능', keys: 'quote blockquote 인용', run: (c) => c.setBlockquote() },
    { id: 'divider', group: '기본 블록', icon: '—', title: '구분선', desc: '--- 로도 가능', keys: 'divider hr line 구분선 선', run: (c) => c.setHorizontalRule() },
    { id: 'code', group: '기본 블록', icon: '</>', title: '코드', desc: '``` 로도 시작 가능', keys: 'code codeblock 코드', run: (c) => c.setCodeBlock() },
    { id: 'table', group: '기본 블록', icon: '▦', title: '표', desc: '3×3 표', keys: 'table 표 테이블', run: (c) => c.insertTable({ rows: 3, cols: 3, withHeaderRow: true }) },
    { id: 'image', group: '미디어', icon: '🖼', title: '이미지', desc: '파일 선택 (붙여넣기·끌어놓기도 가능)', keys: 'image picture photo img 이미지 사진 그림', after: (editor) => pickImageFiles(editor) },
    { id: 'linkcard', group: '미디어', icon: '🔗', title: '링크 카드', desc: '웹페이지 북마크', keys: 'link bookmark card url 링크 카드 북마크', run: (c) => c.insertContent({ type: 'linkCard' }) },
    { id: 'math', group: '수식', icon: '∑', title: '블록 수식', desc: '빈 줄에서 $$ + 스페이스', keys: 'math equation latex block 수식 블록 방정식', after: (editor) => insertMath(editor, 'block') },
    { id: 'inline-math', group: '수식', icon: '𝑥', title: '인라인 수식', desc: '문장 안에서 $x^2$', keys: 'inline math latex 인라인 수식', after: (editor) => insertMath(editor, 'inline') },
];

export const runBlockItem = (editor, item, range = null) => {
    const chain = editor.chain().focus();
    if (range) chain.deleteRange(range);
    if (item.run) item.run(chain);
    chain.run();
    item.after?.(editor);
};

const filterItems = (query) => {
    const q = (query || '').toLowerCase().replace(/\s+/g, '');
    if (!q) return BLOCK_ITEMS;
    return BLOCK_ITEMS.filter((item) => `${item.title} ${item.keys}`.toLowerCase().replace(/\s+/g, '').includes(q)
        || item.keys.split(' ').some((k) => k.startsWith(q)));
};

const createMenuRenderer = () => {
    let panel = null;
    let items = [];
    let active = 0;
    let command = null;
    let clientRect = null;

    const draw = () => {
        if (!panel) return;
        panel.replaceChildren();
        if (!items.length) {
            panel.append(h('div', { class: 'mj-pop__empty', text: '일치하는 블록이 없어요' }));
            return;
        }
        let lastGroup = null;
        items.forEach((item, index) => {
            if (item.group !== lastGroup) {
                panel.append(h('div', { class: 'mj-pop__group', text: item.group }));
                lastGroup = item.group;
            }
            const row = h('button', {
                type: 'button',
                class: `mj-pop__item${index === active ? ' is-active' : ''}`,
                onmousedown: (e) => e.preventDefault(),
                onclick: () => command?.(item),
                onmouseenter: () => {
                    active = index;
                    panel.querySelectorAll('.mj-pop__item').forEach((el, i) => el.classList.toggle('is-active', i === active));
                },
            }, [h('span', { class: 'mj-pop__icon', text: item.icon }), h('span', {}, [h('b', { text: item.title }), h('small', { text: item.desc })])]);
            panel.append(row);
        });
        panel.querySelectorAll('.mj-pop__item')[active]?.scrollIntoView({ block: 'nearest' });
    };

    const place = () => {
        if (panel && clientRect) placeFloating({ getBoundingClientRect: () => clientRect() || new DOMRect() }, panel);
    };

    return {
        onStart: (props) => {
            panel = h('div', { class: 'mj-pop mj-slash', role: 'listbox' });
            document.body.append(panel);
            items = props.items;
            command = props.command;
            clientRect = props.clientRect;
            active = 0;
            draw();
            place();
        },
        onUpdate: (props) => {
            items = props.items;
            command = props.command;
            clientRect = props.clientRect;
            active = Math.min(active, Math.max(0, items.length - 1));
            draw();
            place();
        },
        onKeyDown: ({ event }) => {
            if (!items.length) return false;
            if (event.key === 'ArrowDown') {
                active = (active + 1) % items.length;
                draw();
                return true;
            }
            if (event.key === 'ArrowUp') {
                active = (active - 1 + items.length) % items.length;
                draw();
                return true;
            }
            if (event.key === 'Enter' || event.key === 'Tab') {
                command?.(items[active]);
                return true;
            }
            return false;
        },
        onExit: () => {
            panel?.remove();
            panel = null;
        },
    };
};

export const SlashMenu = Extension.create({
    name: 'slashMenu',

    addProseMirrorPlugins() {
        return [
            Suggestion({
                editor: this.editor,
                pluginKey: new PluginKey('mjSlashMenu'),
                char: '/',
                allowSpaces: false,
                allow: ({ state, range }) => {
                    const $from = state.doc.resolve(range.from);
                    return !$from.parent.type.spec.code;
                },
                items: ({ query }) => filterItems(query),
                command: ({ editor, range, props }) => runBlockItem(editor, props, range),
                render: createMenuRenderer,
            }),
        ];
    },
});
