/* 인용 형식 만들기 (BibTeX·APA·IEEE·MLA·Chicago) — 논문 인용 도구와 논문 찾기가 같이 씀.
   항목 모양은 tools/cite.py 가 돌려주는 것과 같음: {type, title, authors:[{family, given, literal}], year, month, container, volume, issue, pages, doi, arxiv, url, …} */
(() => {
    const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const MON = ['', 'Jan.', 'Feb.', 'Mar.', 'Apr.', 'May', 'Jun.', 'Jul.', 'Aug.', 'Sep.', 'Oct.', 'Nov.', 'Dec.'];
    const MON_FULL = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
    const MON_BIB = ['', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

    // ── 이름 ──
    const hangul = (s) => /[가-힣]/.test(s || '');
    const initials = (given) => (given || '').split(/\s+/).filter(Boolean).map((w) => w.split('-').map((p) => p[0] ? p[0].toUpperCase() + '.' : '').join('-')).join(' ');
    const fullName = (a) => a.literal || !a.given ? a.family : hangul(a.family) ? a.family + a.given : `${a.given} ${a.family}`;
    const joinAnd = (arr, and, serial = true) => arr.length <= 1 ? arr.join('') : arr.length === 2 ? `${arr[0]} ${and} ${arr[1]}` : `${arr.slice(0, -1).join(', ')}${serial ? ',' : ''} ${and} ${arr[arr.length - 1]}`;
    function authorsAPA(as) {
        const one = (a) => a.literal || !a.given ? a.family : hangul(a.family) ? a.family + a.given : `${a.family}, ${initials(a.given)}`;
        if (!as.length) return '';
        if (as.length > 20) return as.slice(0, 19).map(one).join(', ') + ', . . . ' + one(as[as.length - 1]);
        return as.length === 1 ? one(as[0]) : as.slice(0, -1).map(one).join(', ') + ', & ' + one(as[as.length - 1]);
    }
    function authorsIEEE(as) {
        const one = (a) => a.literal || !a.given ? a.family : hangul(a.family) ? a.family + a.given : `${initials(a.given)} ${a.family}`;
        if (as.length > 6) return one(as[0]) + ' et al.';
        return joinAnd(as.map(one), 'and', as.length > 2);
    }
    function authorsMLA(as) {
        const first = (a) => a.literal || !a.given ? a.family : hangul(a.family) ? a.family + a.given : `${a.family}, ${a.given}`;
        if (!as.length) return '';
        if (as.length === 1) return first(as[0]);
        if (as.length === 2) return `${first(as[0])}, and ${fullName(as[1])}`;
        return `${first(as[0])}, et al`;
    }
    function authorsChicago(as) {
        const first = (a) => a.literal || !a.given ? a.family : hangul(a.family) ? a.family + a.given : `${a.family}, ${a.given}`;
        if (!as.length) return '';
        const shown = as.length > 10 ? as.slice(0, 7) : as;
        const names = [first(shown[0]), ...shown.slice(1).map(fullName)];
        return as.length > 10 ? names.join(', ') + ', et al' : names.length === 1 ? names[0] : names.slice(0, -1).join(', ') + ', and ' + names[names.length - 1];
    }
    const dot = (s) => (s && !/[.?!]$/.test(s) ? s + '.' : s);
    const pagesDash = (p) => (p || '').replace(/\s*-+\s*/g, '–');
    const doiUrl = (it) => it.doi ? `https://doi.org/${it.doi}` : it.arxiv ? `https://doi.org/10.48550/arXiv.${it.arxiv}` : it.url || '';
    const I = (s) => (s ? `<i>${esc(s)}</i>` : '');
    const E = esc;

    // ── 형식별 (HTML 로 만들고, 복사할 때 글자만도 같이) ──
    const F = {
        apa(it) {
            const au = authorsAPA(it.authors);
            const date = it.type === 'standard' && it.month ? `${it.year}, ${MON_FULL[it.month]}${it.day ? ' ' + it.day : ''}` : it.year || 'n.d.';
            const head = au ? `${E(dot(au))} (${date}). ` : '';
            const link = doiUrl(it) ? ' ' + E(doiUrl(it)) : '';
            if (it.type === 'article') {
                const vol = it.volume ? `, ${I(it.volume)}${it.issue ? `(${E(it.issue)})` : ''}` : '';
                const pg = it.pages ? `, ${E(pagesDash(it.pages))}` : it.article_number ? `, Article ${E(it.article_number)}` : '';
                return `${head}${E(dot(it.title))} ${I(it.container)}${vol}${pg}.${link}`;
            }
            if (it.type === 'inproceedings' || it.type === 'incollection') {
                return `${head}${E(dot(it.title))} In ${I(it.container)}${it.pages ? ` (pp. ${E(pagesDash(it.pages))})` : ''}. ${it.publisher ? E(dot(it.publisher)) : ''}${link}`.replace(/\s+$/, '');
            }
            if (it.type === 'preprint') {
                return `${head}${I(it.title)}${it.arxiv ? ` (arXiv:${E(it.arxiv)})` : ''}. arXiv.${link}`;
            }
            if (it.type === 'standard') {
                return `${head}${I(it.title)} (${E(it.number)}${it.version ? `, Version ${E(it.version)}` : ''}). 3rd Generation Partnership Project. ${E(it.url)}`;
            }
            return `${head}${I(it.title)}.${it.publisher ? ' ' + E(dot(it.publisher)) : ''}${link}`;
        },
        ieee(it) {
            const au = authorsIEEE(it.authors);
            const head = au ? `${E(au)}, ` : '';
            const when = `${it.month ? MON[it.month] + ' ' : ''}${it.year || ''}`;
            const doi = it.doi ? `, doi: ${E(it.doi)}` : '';
            if (it.type === 'article') {
                const parts = [I(it.container), it.volume && `vol. ${E(it.volume)}`, it.issue && `no. ${E(it.issue)}`, it.pages ? `pp. ${E(pagesDash(it.pages))}` : it.article_number && `Art. no. ${E(it.article_number)}`, when].filter(Boolean);
                return `${head}“${E(it.title)},” ${parts.join(', ')}${doi}.`;
            }
            if (it.type === 'inproceedings') {
                return `${head}“${E(it.title)},” in ${I(it.container)}, ${it.year || ''}${it.pages ? `, pp. ${E(pagesDash(it.pages))}` : ''}${doi}.`;
            }
            if (it.type === 'incollection') return `${head}“${E(it.title)},” in ${I(it.container)}${it.publisher ? `, ${E(it.publisher)}` : ''}, ${it.year || ''}${it.pages ? `, pp. ${E(pagesDash(it.pages))}` : ''}${doi}.`;
            if (it.type === 'preprint') return `${head}“${E(it.title)},” ${I(it.arxiv ? 'arXiv:' + it.arxiv : 'preprint')}, ${when}${doi}.`;
            if (it.type === 'standard') return `${head}“${E(it.title)},” ${E(it.institution)}, ${E(it.number)}, ${when}${it.version ? `, version ${E(it.version)}` : ''}.`;
            if (it.type === 'book') return `${head}${I(it.title)}. ${it.publisher ? E(it.publisher) + ', ' : ''}${it.year || ''}${doi}.`;
            return `${head}“${E(it.title)},” ${it.publisher ? E(it.publisher) + ', ' : ''}${when}${doi}.`;
        },
        mla(it) {
            const au = authorsMLA(it.authors);
            const head = au ? `${E(dot(au))} ` : '';
            const link = doiUrl(it) ? ' ' + E(doiUrl(it).replace(/^https?:\/\//, '')) + '.' : '';
            if (it.type === 'article') {
                const parts = [I(it.container), it.volume && `vol. ${E(it.volume)}`, it.issue && `no. ${E(it.issue)}`, it.year, it.pages && `pp. ${E(pagesDash(it.pages))}`].filter(Boolean);
                return `${head}“${E(dot(it.title))}” ${parts.join(', ')}.${link}`;
            }
            if (it.type === 'inproceedings' || it.type === 'incollection') {
                const parts = [I(it.container), it.publisher && E(it.publisher), it.year, it.pages && `pp. ${E(pagesDash(it.pages))}`].filter(Boolean);
                return `${head}“${E(dot(it.title))}” ${parts.join(', ')}.${link}`;
            }
            if (it.type === 'preprint') return `${head}“${E(dot(it.title))}” ${I('arXiv')}, ${it.year || ''}${it.arxiv ? `, arXiv:${E(it.arxiv)}` : ''}.${link}`;
            if (it.type === 'standard') return `${head}${I(dot(it.title))} ${E(it.number)}${it.version ? `, version ${E(it.version)}` : ''}, 3rd Generation Partnership Project, ${it.day ? it.day + ' ' : ''}${it.month ? MON[it.month] + ' ' : ''}${it.year || ''}.`;
            return `${head}${I(dot(it.title))} ${it.publisher ? E(it.publisher) + ', ' : ''}${it.year || ''}.${link}`;
        },
        chicago(it) {
            const au = authorsChicago(it.authors);
            const head = au ? `${E(dot(au))} ` : '';
            const link = doiUrl(it) ? ' ' + E(doiUrl(it)) + '.' : '';
            if (it.type === 'article') {
                return `${head}“${E(dot(it.title))}” ${I(it.container)}${it.volume ? ' ' + E(it.volume) : ''}${it.issue ? `, no. ${E(it.issue)}` : ''} (${it.year || 'n.d.'})${it.pages ? `: ${E(pagesDash(it.pages))}` : ''}.${link}`;
            }
            if (it.type === 'inproceedings' || it.type === 'incollection') {
                return `${head}“${E(dot(it.title))}” In ${I(it.container)}${it.pages ? `, ${E(pagesDash(it.pages))}` : ''}. ${it.publisher ? E(it.publisher) + ', ' : ''}${it.year || ''}.${link}`;
            }
            if (it.type === 'preprint') return `${head}“${E(dot(it.title))}” Preprint, arXiv, ${it.month ? MON_FULL[it.month] + ' ' : ''}${it.year || ''}.${link}`;
            if (it.type === 'standard') return `${head}${I(dot(it.title))} ${E(it.number)}${it.version ? `, version ${E(it.version)}` : ''}. 3rd Generation Partnership Project, ${it.year || ''}. ${E(it.url)}.`;
            return `${head}${I(dot(it.title))} ${it.publisher ? E(it.publisher) + ', ' : ''}${it.year || ''}.${link}`;
        },
        bibtex(it) { return E(bibtex(it)); },
    };

    // ── BibTeX ──
    const texEsc = (s) => String(s ?? '').replace(/([&%#_$])/g, '\\$1');
    const ascii = (s) => (s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9]/g, '');
    const STOP = new Set(['a', 'an', 'the', 'on', 'of', 'in', 'for', 'and', 'to', 'with', 'is', 'are', 'via', 'towards', 'toward', 'from', 'by', 'at']);
    function bibKey(it) {
        if (it.type === 'standard') return `3gpp.${it.spec_number || it.number}`;
        const fam = ascii(it.authors[0]?.family).toLowerCase() || 'ref';
        const word = (it.title || '').split(/\s+/).map((w) => ascii(w).toLowerCase()).find((w) => w && !STOP.has(w)) || '';
        return `${fam}${it.year || ''}${word}`;
    }
    const bibAuthors = (as) => as.map((a) => (a.literal || !a.given ? `{${texEsc(a.family)}}` : `${texEsc(a.family)}, ${texEsc(a.given)}`)).join(' and ');
    function bibtex(it) {
        const f = [];
        const add = (k, v, raw) => { if (v !== undefined && v !== null && String(v).trim() !== '') f.push([k, raw ? String(v) : `{${texEsc(v)}}`]); };
        let type = { article: 'article', inproceedings: 'inproceedings', incollection: 'incollection', book: 'book', thesis: 'phdthesis', report: 'techreport', standard: 'techreport', preprint: 'misc' }[it.type] || 'misc';
        if (it.type === 'standard') {
            // martisak/3gpp-citations 와 같은 모양
            f.push(['author', '{3GPP}']);
            f.push(['title', `{{${texEsc(it.title)}}}`]);
            f.push(['institution', `{{${texEsc(it.institution)}}}`]);
            add('type', it.report_type);
            add('number', it.spec_number);
            if (it.version) add('note', `Version ${it.version}`);
            if (it.day) add('day', String(it.day).padStart(2, '0'));
            if (it.month) add('month', String(it.month).padStart(2, '0'));
            add('year', it.year);
            if (it.url) f.push(['url', `{${it.url}}`]);
        } else {
            if (it.authors.length) f.push(['author', `{${bibAuthors(it.authors)}}`]);
            add('title', it.title);
            if (type === 'article') add('journal', it.container);
            if (type === 'inproceedings' || type === 'incollection') add('booktitle', it.container);
            add('year', it.year);
            if (it.month) f.push(['month', MON_BIB[it.month]]);
            add('volume', it.volume);
            add('number', it.issue);
            add('pages', (it.pages || '').replace(/\s*[-–]+\s*/g, '--'));
            if (!it.pages && it.article_number && type === 'article') add('articleno', it.article_number);
            if (type !== 'article' && type !== 'misc') add('publisher', it.publisher);
            if (it.type === 'preprint' && it.arxiv) { add('eprint', it.arxiv); add('archivePrefix', 'arXiv'); add('primaryClass', it.primary_class); }
            add('isbn', it.isbn);
            if (it.doi) f.push(['doi', `{${it.doi}}`]);
            if (it.url && !it.doi) f.push(['url', `{${it.url}}`]);
        }
        const w = Math.max(...f.map(([k]) => k.length));
        return `@${type}{${it.key || bibKey(it)},\n${f.map(([k, v]) => `  ${k.padEnd(w)} = ${v}`).join(',\n')}\n}`;
    }

    // ── BibTeX 읽기 (붙여넣기) ──
    function parseBib(src) {
        const out = [];
        let i = 0;
        while ((i = src.indexOf('@', i)) !== -1) {
            const m = /^@(\w+)\s*\{\s*([^,\s]*)\s*,/.exec(src.slice(i));
            if (!m) { i++; continue; }
            if (/^(comment|string|preamble)$/i.test(m[1])) { i += m[0].length; continue; }
            let j = i + m[0].length, depth = 1;
            const start = j;
            while (j < src.length && depth > 0) { if (src[j] === '{') depth++; else if (src[j] === '}') depth--; j++; }
            const body = src.slice(start, j - 1);
            const fields = {};
            const re = /(\w[\w-]*)\s*=\s*/g;
            let fm;
            while ((fm = re.exec(body))) {
                let k = fm[1].toLowerCase(), p = re.lastIndex, v = '';
                if (body[p] === '{') { let d = 0, q = p; do { if (body[q] === '{') d++; else if (body[q] === '}') d--; q++; } while (q < body.length && d > 0); v = body.slice(p + 1, q - 1); re.lastIndex = q; }
                else if (body[p] === '"') { const q = body.indexOf('"', p + 1); v = body.slice(p + 1, q); re.lastIndex = q + 1; }
                else { const q = body.slice(p).search(/[,\n}]/); v = body.slice(p, q < 0 ? undefined : p + q).trim(); re.lastIndex = p + Math.max(q, 0); }
                fields[k] = v.replace(/[{}]/g, '').replace(/\\([&%#_$])/g, '$1').replace(/\s+/g, ' ').trim();
            }
            out.push(fromBib(m[1].toLowerCase(), m[2], fields));
            i = j;
        }
        return out;
    }
    function fromBib(type, key, f) {
        const authors = (f.author || '').split(/\s+and\s+/i).filter(Boolean).map((n) => {
            if (n.includes(',')) { const [fam, ...g] = n.split(','); return { family: fam.trim(), given: g.join(',').trim() }; }
            const parts = n.trim().split(/\s+/);
            return parts.length === 1 ? { family: parts[0], given: '', literal: true } : { family: parts.pop(), given: parts.join(' ') };
        });
        const mon = f.month ? (MON_BIB.indexOf(f.month.slice(0, 3).toLowerCase()) > 0 ? MON_BIB.indexOf(f.month.slice(0, 3).toLowerCase()) : parseInt(f.month, 10) || null) : null;
        const is3gpp = /3gpp/i.test(f.author || '') && /3rd generation|3gpp/i.test(f.institution || '');
        const kind = is3gpp ? 'standard' : ({ article: 'article', inproceedings: 'inproceedings', conference: 'inproceedings', incollection: 'incollection', inbook: 'incollection', book: 'book', phdthesis: 'thesis', mastersthesis: 'thesis', techreport: 'report' }[type] || (f.eprint || /arxiv/i.test(f.journal || '') ? 'preprint' : 'misc'));
        const version = (f.note || '').match(/(\d+\.\d+\.\d+)/)?.[1] || '';
        const specType = /report/i.test(f.type || '') ? 'TR' : 'TS';
        return {
            key, type: kind, title: f.title || '', authors, editors: [],
            year: parseInt(f.year, 10) || null, month: mon, day: parseInt(f.day, 10) || null,
            container: f.journal || f.booktitle || '', volume: f.volume || '', issue: f.number && kind !== 'standard' && kind !== 'report' ? f.number : '',
            pages: (f.pages || '').replace(/-+/g, '-'), article_number: f.articleno || '', publisher: f.publisher || f.institution || f.school || '',
            institution: f.institution || '3rd Generation Partnership Project (3GPP)', doi: (f.doi || '').replace(/^https?:\/\/(dx\.)?doi\.org\//, '').toLowerCase(),
            url: f.url || '', isbn: f.isbn || '', arxiv: f.eprint || '', primary_class: f.primaryclass || '',
            number: kind === 'standard' ? `${specType} ${f.number || ''}` : f.number || '', spec_number: f.number || '', spec_type: specType,
            report_type: f.type || (specType === 'TR' ? 'Technical Report (TR)' : 'Technical Specification (TS)'), version, source: 'bibtex',
        };
    }

    const plain = (htmlStr) => { const d = document.createElement('div'); d.innerHTML = htmlStr; return d.textContent; };
    const sameItem = (a, b) => (a.doi && a.doi.toLowerCase() === (b.doi || '').toLowerCase()) || (a.arxiv && a.arxiv === b.arxiv) || (a.type === 'standard' ? a.spec_number === b.spec_number && a.version === b.version : !a.doi && !a.arxiv && a.title && a.title.toLowerCase() === (b.title || '').toLowerCase());
    window.MjCite = { F, bibtex, bibKey, parseBib, fromBib, plain, sameItem, fullName, esc, MON, MON_FULL, MON_BIB };
})();
