// 본문 이미지 블록: 업로드 중 표시, 캡션, 대표이미지(1개) 선택
import { Node, mergeAttributes } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { h } from '../dom.js';

// uploadId → 업로드 완료 URL (undo/redo 로 옛 blob 주소가 되살아나도 저장 시 교체)
const uploadedUrls = new Map();
const pendingUploads = new Map();

const findImageByUploadId = (doc, uploadId) => {
    let found = null;
    doc.descendants((node, pos) => {
        if (found) return false;
        if (node.type.name === 'image' && node.attrs.uploadId === uploadId) found = { node, pos };
        return !found;
    });
    return found;
};

export const insertImageFiles = (editor, files, pos = null) => {
    const images = Array.from(files || []).filter((f) => f && f.type && f.type.startsWith('image/'));
    if (!images.length) return false;
    const { api, notify } = editor.storage.image;

    const nodes = images.map((file) => {
        const uploadId = `u${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
        const blobUrl = URL.createObjectURL(file);
        const job = api.uploadImage(file, file.name || 'image')
            .then((url) => {
                uploadedUrls.set(uploadId, url);
                const hit = findImageByUploadId(editor.state.doc, uploadId);
                if (hit) {
                    // 주소만 바꾸는 작업은 실행취소 기록에 남기지 않음 → Cmd+Z 한 번에 이미지 통째로 사라짐
                    const tr = editor.state.tr.setNodeMarkup(hit.pos, undefined, { ...hit.node.attrs, src: url, uploadId: null });
                    editor.view.dispatch(tr.setMeta('addToHistory', false));
                }
            })
            .catch((err) => {
                const hit = findImageByUploadId(editor.state.doc, uploadId);
                if (hit) {
                    const tr = editor.state.tr.delete(hit.pos, hit.pos + hit.node.nodeSize);
                    editor.view.dispatch(tr.setMeta('addToHistory', false));
                }
                notify?.(`이미지 업로드 실패: ${err.message}`, 'error');
            })
            .finally(() => pendingUploads.delete(uploadId));
        pendingUploads.set(uploadId, job);
        return { type: 'image', attrs: { src: blobUrl, alt: file.name || '', uploadId } };
    });

    const chain = editor.chain().focus();
    if (pos === null) chain.insertContent(nodes);
    else chain.insertContentAt(pos, nodes);
    chain.run();
    return true;
};

export const waitForImageUploads = () => Promise.all(Array.from(pendingUploads.values()));

// 저장용 JSON 정리: 업로드 상태값 제거, 완료된 업로드 주소로 교체
export const finalizeImageAttrs = (attrs) => {
    const next = { ...attrs };
    if (next.uploadId && uploadedUrls.has(next.uploadId)) next.src = uploadedUrls.get(next.uploadId);
    delete next.uploadId;
    return next;
};

export const Image = Node.create({
    name: 'image',
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
        return {
            src: { default: '' },
            alt: { default: '' },
            caption: { default: '' },
            isCover: { default: false },
            uploadId: { default: null, rendered: false },
        };
    },

    parseHTML() {
        return [
            {
                tag: 'figure[data-type="image"]',
                getAttrs: (el) => {
                    const img = el.querySelector('img');
                    return {
                        src: img?.getAttribute('src') || '',
                        alt: img?.getAttribute('alt') || '',
                        caption: el.querySelector('figcaption')?.textContent || '',
                        isCover: el.getAttribute('data-cover') === 'true',
                    };
                },
            },
            {
                tag: 'img[src]',
                getAttrs: (el) => ({ src: el.getAttribute('src') || '', alt: el.getAttribute('alt') || '' }),
            },
        ];
    },

    renderHTML({ node }) {
        const { src, alt, caption, isCover } = node.attrs;
        return [
            'figure',
            mergeAttributes({ 'data-type': 'image', 'data-cover': isCover ? 'true' : null }),
            ['img', { src, alt }],
            ['figcaption', {}, caption || ''],
        ];
    },

    addProseMirrorPlugins() {
        const editor = this.editor;
        return [
            new Plugin({
                key: new PluginKey('mjImagePasteDrop'),
                props: {
                    handlePaste: (view, event) => {
                        const files = Array.from(event.clipboardData?.files || []);
                        if (!files.some((f) => f.type.startsWith('image/'))) return false;
                        event.preventDefault();
                        return insertImageFiles(editor, files);
                    },
                    handleDrop: (view, event, slice, moved) => {
                        if (moved) return false;
                        const files = Array.from(event.dataTransfer?.files || []);
                        if (!files.some((f) => f.type.startsWith('image/'))) return false;
                        event.preventDefault();
                        const coords = view.posAtCoords({ left: event.clientX, top: event.clientY });
                        let pos = coords ? coords.pos : null;
                        if (pos !== null) {
                            const $pos = view.state.doc.resolve(pos);
                            pos = $pos.depth > 0 ? $pos.after(1) : pos;
                        }
                        return insertImageFiles(editor, files, pos);
                    },
                },
            }),
        ];
    },

    addNodeView() {
        return ({ node: initialNode, getPos, editor }) => {
            let node = initialNode;
            const img = h('img', { draggable: 'false' });
            const loading = h('div', { class: 'mj-img__loading', text: '업로드 중…' });
            const coverBtn = h('button', { type: 'button', class: 'mj-img__cover' });
            const caption = h('input', { class: 'mj-img__caption', type: 'text', placeholder: '캡션 입력 (선택)' });
            const dom = h('figure', { class: 'mj-img', 'data-type': 'image' }, [
                h('div', { class: 'mj-img__frame' }, [img, loading, coverBtn]),
                caption,
            ]);

            const setAttrs = (attrs, addToHistory = true) => {
                const pos = getPos();
                if (typeof pos !== 'number') return;
                const tr = editor.state.tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...attrs });
                if (!addToHistory) tr.setMeta('addToHistory', false);
                editor.view.dispatch(tr);
            };

            coverBtn.addEventListener('mousedown', (e) => e.preventDefault());
            coverBtn.addEventListener('click', () => {
                const pos = getPos();
                if (typeof pos !== 'number') return;
                const makeCover = !node.attrs.isCover;
                const { tr } = editor.state;
                editor.state.doc.descendants((child, childPos) => {
                    if (child.type.name !== 'image') return;
                    const want = childPos === pos ? makeCover : false;
                    if (child.attrs.isCover !== want) tr.setNodeMarkup(childPos, undefined, { ...child.attrs, isCover: want });
                });
                editor.view.dispatch(tr);
            });

            caption.addEventListener('input', () => setAttrs({ caption: caption.value }, false));
            caption.addEventListener('change', () => setAttrs({ caption: caption.value }));
            caption.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const pos = getPos();
                    if (typeof pos === 'number') {
                        editor.chain().insertContentAt(pos + node.nodeSize, { type: 'paragraph' }).focus(pos + node.nodeSize + 1).run();
                    }
                }
            });

            const render = () => {
                if (img.getAttribute('src') !== node.attrs.src) img.setAttribute('src', node.attrs.src || '');
                img.alt = node.attrs.alt || node.attrs.caption || '';
                loading.hidden = !node.attrs.uploadId;
                dom.classList.toggle('is-cover', !!node.attrs.isCover);
                coverBtn.textContent = node.attrs.isCover ? '★ 대표이미지' : '☆ 대표로 선택';
                if (document.activeElement !== caption) caption.value = node.attrs.caption || '';
            };
            render();

            return {
                dom,
                update: (updated) => {
                    if (updated.type.name !== 'image') return false;
                    node = updated;
                    render();
                    return true;
                },
                stopEvent: (event) => event.target === caption || event.target === coverBtn,
                ignoreMutation: () => true,
                selectNode: () => dom.classList.add('is-selected'),
                deselectNode: () => dom.classList.remove('is-selected'),
            };
        };
    },
});
