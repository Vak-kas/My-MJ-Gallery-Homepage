// MjGallery 노션형 에디터 진입점 → window.MjEditor.create(...)
import './editor.css';
import { Editor, Extension, textInputRule } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { Placeholder } from '@tiptap/extensions';
import { TaskItem, TaskList } from '@tiptap/extension-list';
import { TableKit } from '@tiptap/extension-table';
import { Details, DetailsContent, DetailsSummary } from '@tiptap/extension-details';
import { TextStyleKit } from '@tiptap/extension-text-style';

import { createApi } from './api.js';
import { parseStoredContent } from './legacy.js';
import { Image, finalizeImageAttrs, waitForImageUploads } from './extensions/image.js';
import { LinkCard } from './extensions/link-card.js';
import { createMathExtensions } from './extensions/math.js';
import { SlashMenu } from './extensions/slash-menu.js';
import { BlockHandle } from './extensions/block-handle.js';
import { createBubbleToolbar } from './extensions/bubble-toolbar.js';

const CONTENT_FORMAT = 'tiptap';
const CONTENT_VERSION = 1;

// -> 입력 시 → 로 바꿈 (코드 블록 안에서는 동작하지 않음)
const Arrows = Extension.create({
    name: 'mjArrows',
    addInputRules() {
        return [
            textInputRule({ find: /->$/, replace: '→' }),
            textInputRule({ find: /<-$/, replace: '←' }),
        ];
    },
});

const mapDoc = (node, fn) => {
    const next = fn({ ...node });
    if (Array.isArray(next.content)) next.content = next.content.map((child) => mapDoc(child, fn));
    return next;
};

const create = ({ element, content = '', api: apiConfig = {}, notify = () => {}, onChange = () => {}, placeholder } = {}) => {
    const api = createApi(apiConfig);

    const editor = new Editor({
        element,
        content: parseStoredContent(content),
        autofocus: false,
        extensions: [
            StarterKit.configure({
                heading: { levels: [1, 2, 3] },
                link: { openOnClick: false, autolink: true, defaultProtocol: 'https' },
                dropcursor: { color: '#2383e2', width: 3 },
            }),
            Placeholder.configure({
                includeChildren: true,
                placeholder: ({ node }) => {
                    if (node.type.name === 'heading') return `제목 ${node.attrs.level}`;
                    if (node.type.name === 'detailsSummary') return '토글 제목';
                    return placeholder || "글을 쓰거나 '/' 를 눌러 블록을 추가하세요";
                },
            }),
            TaskList,
            TaskItem.configure({ nested: true }),
            TableKit.configure({ table: { resizable: false } }),
            Details.configure({ persist: true, HTMLAttributes: { class: 'mj-details' } }),
            DetailsSummary,
            DetailsContent,
            TextStyleKit.configure({ fontSize: false, lineHeight: false }),
            Image.configure({ api, notify }),
            LinkCard.configure({ api, notify }),
            ...createMathExtensions({ api, notify }),
            Arrows,
            SlashMenu,
            BlockHandle,
            createBubbleToolbar(),
        ],
        editorProps: {
            attributes: { class: 'mj-prose', spellcheck: 'false' },
        },
        onUpdate: () => onChange(),
    });

    const getContent = () => {
        const doc = mapDoc(editor.getJSON(), (node) => {
            if (node.type === 'image' && node.attrs) node.attrs = finalizeImageAttrs(node.attrs);
            return node;
        });
        return { format: CONTENT_FORMAT, version: CONTENT_VERSION, doc };
    };

    // 저장 직전: 업로드 중인 이미지 기다리기 + 예전 글에 남은 base64 이미지를 파일로 올리기
    const prepareForSave = async () => {
        await waitForImageUploads();
        const dataImages = [];
        editor.state.doc.descendants((node, pos) => {
            if (node.type.name === 'image' && String(node.attrs.src || '').startsWith('data:image/')) dataImages.push({ node, pos });
        });
        for (const { node } of dataImages) {
            const url = await api.uploadDataUrl(node.attrs.src);
            let target = null;
            editor.state.doc.descendants((child, pos) => {
                if (target === null && child.type.name === 'image' && child.attrs.src === node.attrs.src) target = pos;
                return target === null;
            });
            if (target !== null) {
                const tr = editor.state.tr.setNodeMarkup(target, undefined, { ...node.attrs, src: url });
                editor.view.dispatch(tr.setMeta('addToHistory', false));
            }
        }
        return getContent();
    };

    const setContent = (raw) => {
        editor.commands.setContent(parseStoredContent(raw), { emitUpdate: false });
    };

    const setFontFamily = (fontFamily) => {
        editor.view.dom.style.fontFamily = fontFamily || '';
    };

    // 문서 끝에 빈 줄을 만들고 "/" 메뉴 열기 (외부 "+ 블록 추가" 버튼용)
    const openBlockMenu = () => {
        const { doc } = editor.state;
        const last = doc.lastChild;
        if (last && last.type.name === 'paragraph' && last.content.size === 0) {
            editor.chain().focus(doc.content.size - 1).insertContent('/').run();
        } else {
            editor.chain().insertContentAt(doc.content.size, { type: 'paragraph' }).focus('end').insertContent('/').run();
        }
    };

    return { editor, getContent, prepareForSave, setContent, setFontFamily, openBlockMenu };
};

window.MjEditor = { create, parseStoredContent };
