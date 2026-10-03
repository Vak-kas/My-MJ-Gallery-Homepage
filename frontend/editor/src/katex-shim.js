// KaTeX 는 페이지에서 CDN 으로 이미 불러오므로 번들에 넣지 않고 window.katex 를 사용
const katex = {
    render: (...args) => window.katex.render(...args),
    renderToString: (...args) => window.katex.renderToString(...args),
};
export default katex;
