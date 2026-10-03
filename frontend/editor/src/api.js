// 서버 API 호출 모음 (이미지 업로드 / URL 미리보기 / 수식 OCR)

// 업로드 전에 브라우저에서 먼저 줄여서 요청 크기를 작게 유지 (서버 앞단 용량 제한 대비)
const shrinkImage = async (blob, maxSide = 2000) => {
    if (!blob || blob.type === 'image/gif') return blob;
    try {
        const bitmap = await createImageBitmap(blob);
        const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(bitmap.width * scale);
        canvas.height = Math.round(bitmap.height * scale);
        canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close?.();
        const out = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', 0.9));
        return out && out.size < blob.size ? out : blob;
    } catch (_) {
        return blob;
    }
};

const readJson = async (resp) => {
    try {
        return await resp.json();
    } catch (_) {
        return {};
    }
};

export const createApi = ({ uploadUrl, urlPreviewUrl, mathOcrUrl, csrfToken }) => {
    const headers = csrfToken ? { 'X-CSRFToken': csrfToken } : {};

    const uploadImage = async (blob, filename = 'image') => {
        const body = new FormData();
        body.append('image', await shrinkImage(blob), filename);
        const resp = await fetch(uploadUrl, { method: 'POST', body, credentials: 'same-origin', headers });
        const json = await readJson(resp);
        if (!resp.ok || !json.url) {
            throw new Error(json.error || (resp.status === 413 ? '이미지가 너무 큽니다.' : `업로드 실패 (${resp.status})`));
        }
        return json.url;
    };

    const uploadDataUrl = async (dataUrl) => uploadImage(await (await fetch(dataUrl)).blob(), 'inline-image');

    const fetchUrlPreview = async (url) => {
        const resp = await fetch(`${urlPreviewUrl}?url=${encodeURIComponent(url)}`, { credentials: 'same-origin' });
        const json = await readJson(resp);
        if (!resp.ok || json.error) throw new Error(json.error || `미리보기 실패 (${resp.status})`);
        return json;
    };

    const mathOcr = async (file) => {
        const body = new FormData();
        body.append('image', file);
        const resp = await fetch(mathOcrUrl, { method: 'POST', body, credentials: 'same-origin', headers });
        const json = await readJson(resp);
        if (!resp.ok || json.error) throw new Error(json.error || `인식 실패 (${resp.status})`);
        return json.latex || '';
    };

    return { uploadImage, uploadDataUrl, fetchUrlPreview, mathOcr };
};
