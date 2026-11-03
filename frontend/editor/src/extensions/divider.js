// 구분선: 기본 StarterKit 의 horizontalRule 에 style 속성을 더함 (data-style 로 저장·표시)
import HorizontalRule from '@tiptap/extension-horizontal-rule';

export const DIVIDER_STYLES = [
    { id: 'line', icon: '—', title: '기본 선', desc: '--- 로도 가능' },
    { id: 'circle', icon: '—●—', title: '가운데 점', desc: '점에서 좌우로 선이 뻗어 나감' },
    { id: 'diamond', icon: '—◆—', title: '가운데 마름모', desc: '마름모 양쪽으로 선' },
    { id: 'star', icon: '—✦—', title: '가운데 별', desc: '별 양쪽으로 선' },
    { id: 'dots', icon: '· · ·', title: '점 세 개', desc: '가운데 점 셋' },
    { id: 'asterism', icon: '⁂', title: '별표 셋', desc: '고전 책의 장 구분' },
    { id: 'fade', icon: '┈━┈', title: '흐려지는 선', desc: '양 끝이 희미해짐' },
    { id: 'double', icon: '═', title: '두 줄', desc: '가는 선 두 줄' },
    { id: 'dashed', icon: '- - -', title: '점선', desc: '짧게 끊어진 선' },
    { id: 'wave', icon: '〰', title: '물결', desc: '물결 모양 선' },
];

export const DIVIDER_IDS = DIVIDER_STYLES.map((s) => s.id);

export const Divider = HorizontalRule.extend({
    addAttributes() {
        return {
            style: {
                default: 'line',
                parseHTML: (el) => (DIVIDER_IDS.includes(el.getAttribute('data-style')) ? el.getAttribute('data-style') : 'line'),
                renderHTML: (attrs) => ({ 'data-style': DIVIDER_IDS.includes(attrs.style) ? attrs.style : 'line' }),
            },
        };
    },

    addCommands() {
        return {
            ...this.parent?.(),
            // 모양 바꾸기 (블록 메뉴에서 씀)
            setDividerStyle: (style) => ({ commands }) => commands.updateAttributes(this.name, { style: DIVIDER_IDS.includes(style) ? style : 'line' }),
        };
    },
});

// 슬래시 메뉴용: 구분선을 넣은 뒤 방금 넣은 구분선의 모양을 바꿈
export const insertDivider = (chain, style) => chain.setHorizontalRule().command(({ tr }) => {
    let found = null;
    tr.doc.nodesBetween(0, tr.selection.from, (node, pos) => {
        if (node.type.name === 'horizontalRule') found = pos;
    });
    if (found !== null) tr.setNodeMarkup(found, undefined, { style });
    return true;
});
