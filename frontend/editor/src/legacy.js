// 예전 Editor.js 글(JSON) → Tiptap 이 읽을 수 있는 HTML 로 변환
// 각 블록을 Tiptap 확장들의 parseHTML 규칙에 맞는 마크업으로 만들어 주면 에디터가 알아서 노드로 바꿈

const esc = (value) => String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

// execCommand 시절의 <font face/color> 를 Tiptap TextStyle 이 이해하는 <span style> 로 바꿈
const normalizeInline = (html) => {
    const tpl = document.createElement('template');
    tpl.innerHTML = String(html ?? '');
    tpl.content.querySelectorAll('font').forEach((font) => {
        const span = document.createElement('span');
        const face = font.getAttribute('face');
        const color = font.getAttribute('color');
        if (face) span.style.fontFamily = face;
        if (color) span.style.color = color;
        span.append(...font.childNodes);
        font.replaceWith(span);
    });
    tpl.content.querySelectorAll('script, style, iframe, object, embed').forEach((el) => el.remove());
    return tpl.innerHTML;
};

const inline = (data) => normalizeInline(data?.html ?? data?.text ?? '');

const listItemsHtml = (items, ordered) => {
    const tag = ordered ? 'ol' : 'ul';
    const lis = (items || []).map((item) => {
        if (typeof item === 'string') return `<li><p>${normalizeInline(item)}</p></li>`;
        const content = normalizeInline(item?.content ?? item?.text ?? '');
        const nested = item?.items?.length ? listItemsHtml(item.items, ordered) : '';
        return `<li><p>${content}</p>${nested}</li>`;
    }).join('');
    return `<${tag}>${lis}</${tag}>`;
};

const blockToHtml = (block) => {
    const type = block?.type;
    const data = block?.data || {};
    switch (type) {
    case 'paragraph':
        return `<p>${inline(data)}</p>`;
    case 'header':
    case 'h1':
    case 'h2':
    case 'h3': {
        const level = type === 'header' ? Math.min(3, Math.max(1, Number(data.level) || 2)) : Number(type[1]);
        return `<h${level}>${inline(data)}</h${level}>`;
    }
    case 'list':
    case 'nestedList':
        return listItemsHtml(data.items, data.style === 'ordered');
    case 'checklist':
        return `<ul data-type="taskList">${(data.items || []).map((item) => `<li data-type="taskItem" data-checked="${item?.checked ? 'true' : 'false'}"><p>${normalizeInline(item?.text ?? '')}</p></li>`).join('')}</ul>`;
    case 'quote':
        return `<blockquote><p>${inline(data)}</p>${data.caption ? `<p>— ${normalizeInline(data.caption)}</p>` : ''}</blockquote>`;
    case 'warning':
        return `<blockquote><p><strong>${normalizeInline(data.title || '알림')}</strong></p><p>${normalizeInline(data.message || '')}</p></blockquote>`;
    case 'code':
        return `<pre><code>${esc(data.code || '')}</code></pre>`;
    case 'delimiter':
        return '<hr>';
    case 'table': {
        const rows = (data.content || []).map((row, rowIndex) => {
            const cellTag = data.withHeadings && rowIndex === 0 ? 'th' : 'td';
            return `<tr>${(row || []).map((cell) => `<${cellTag}><p>${normalizeInline(cell)}</p></${cellTag}>`).join('')}</tr>`;
        }).join('');
        return rows ? `<table><tbody>${rows}</tbody></table>` : '';
    }
    case 'image': {
        const src = data.url || data.file?.url || data.src || '';
        if (!src) return '';
        return `<figure data-type="image"${data.isCover ? ' data-cover="true"' : ''}><img src="${esc(src)}" alt="${esc(data.alt || data.caption || '')}"><figcaption>${esc(data.caption || '')}</figcaption></figure>`;
    }
    case 'toggle': {
        const items = Array.isArray(data.items) ? data.items : String(data.content || '').split('\n');
        const body = items.filter((line) => String(line).trim()).map((line) => `<p>${normalizeInline(line)}</p>`).join('') || '<p></p>';
        return `<details><summary>${normalizeInline(data.title || '')}</summary><div data-type="detailsContent">${body}</div></details>`;
    }
    case 'math': {
        const latex = esc(data.latex ?? data.text ?? '');
        if (!latex) return '';
        return data.displayMode
            ? `<div data-type="block-math" data-latex="${latex}"></div>`
            : `<p><span data-type="inline-math" data-latex="${latex}"></span></p>`;
    }
    case 'linkcard': {
        if (!data.url) return '';
        const attrs = {
            'data-url': data.url,
            'data-title': data.title || data.url,
            'data-description': data.description,
            'data-image': data.image,
            'data-favicon': data.favicon,
            'data-site-name': data.site_name,
            'data-mode': data.mode || 'card',
        };
        const attrText = Object.entries(attrs).filter(([, v]) => v).map(([k, v]) => `${k}="${esc(v)}"`).join(' ');
        return `<div data-type="link-card" ${attrText}></div>`;
    }
    case 'linkembed':
        return data.url ? `<p><a href="${esc(data.url)}">${esc(data.label || data.url)}</a></p>` : '';
    default:
        return '';
    }
};

export const editorJsToHtml = (data) => (data?.blocks || []).map(blockToHtml).join('');

// 저장된 content 문자열 → 에디터 초기 내용 (Tiptap JSON 또는 HTML)
export const parseStoredContent = (raw) => {
    const text = String(raw || '').trim();
    if (!text) return '';
    try {
        const parsed = JSON.parse(text);
        if (parsed?.format === 'tiptap' && parsed.doc) return parsed.doc;
        if (Array.isArray(parsed?.blocks)) return editorJsToHtml(parsed);
    } catch (_) {
        // JSON 이 아니면 아주 옛날 HTML/텍스트 글
    }
    if (/<[a-z][\s\S]*>/i.test(text)) return normalizeInline(text);
    return text.split(/\n{2,}/).map((para) => `<p>${esc(para).replace(/\n/g, '<br>')}</p>`).join('');
};
