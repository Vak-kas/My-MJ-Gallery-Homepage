// 작은 DOM 헬퍼 + 떠 있는 패널 위치 계산
import { computePosition, flip, offset, shift } from '@floating-ui/dom';

export const h = (tag, props = {}, children = []) => {
    const el = document.createElement(tag);
    Object.entries(props).forEach(([key, value]) => {
        if (value === undefined || value === null || value === false) return;
        if (key === 'class') el.className = value;
        else if (key === 'text') el.textContent = value;
        else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
        else if (key in el && typeof value !== 'string') el[key] = value;
        else el.setAttribute(key, value === true ? '' : value);
    });
    (Array.isArray(children) ? children : [children]).forEach((child) => {
        if (child === null || child === undefined || child === false) return;
        el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    });
    return el;
};

// reference: Element 또는 { getBoundingClientRect } 형태
export const placeFloating = (reference, floating, placement = 'bottom-start') => {
    computePosition(reference, floating, {
        placement,
        strategy: 'fixed',
        middleware: [offset(6), flip({ padding: 8 }), shift({ padding: 8 })],
    }).then(({ x, y }) => {
        Object.assign(floating.style, { left: `${x}px`, top: `${y}px` });
    });
};

// 패널 바깥 클릭 / Esc 로 닫기
export const dismissOnOutside = (panel, onDismiss) => {
    const onDown = (e) => {
        if (!panel.contains(e.target)) onDismiss();
    };
    const onKey = (e) => {
        if (e.key === 'Escape') {
            e.preventDefault();
            onDismiss();
        }
    };
    setTimeout(() => {
        document.addEventListener('mousedown', onDown, true);
        document.addEventListener('keydown', onKey, true);
    }, 0);
    return () => {
        document.removeEventListener('mousedown', onDown, true);
        document.removeEventListener('keydown', onKey, true);
    };
};

export const isHttpUrl = (text) => /^https?:\/\/[^\s]+$/i.test(text || '');
