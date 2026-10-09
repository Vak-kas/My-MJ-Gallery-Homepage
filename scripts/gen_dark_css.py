"""templates/ 에서 쓰는 Tailwind 임의 색 클래스(bg-[#..], text-[#..], border-[#..] 등)를 모아
다크 모드에서 읽기 좋은 색으로 바꾸는 static/css/theme-dark.css 를 만든다.

  venv/bin/python scripts/gen_dark_css.py

- 밝은 배경 → 어두운 면 (무채색) 또는 같은 색조의 어두운 색 (유채색)
- 어두운 배경에서 대비가 4.5 가 안 되는 글자색 → 같은 색조로 밝게
- 밝은 테두리 → 어두운 테두리
base.html 에 직접 적어 둔 규칙(bg-white, #f5f5f7 등)은 그대로 두고, 그 밖의 색만 여기서 처리한다.
새 색을 쓰는 템플릿을 추가했으면 다시 실행하면 된다.
"""

import colorsys
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "css" / "theme-dark.css"
CARD = (0x17, 0x1A, 0x20)  # 다크 모드 카드 배경
HANDLED = {"bg": {"#ffffff", "#f5f5f7", "#fbfbfd", "#fafafc", "#f2f2f7"},
		   "text": {"#1d1d1f", "#6e6e73", "#86868b", "#8e8e93"}}
PATTERN = re.compile(r"(?<![\w-])(bg|text|border|ring|from|to|via)-\[(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)\]")


def rgb(hex_color):
	h = hex_color.lstrip("#")
	if len(h) == 3:
		h = "".join(c * 2 for c in h)
	return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def to_hex(c):
	return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in c)


def lum(c):
	def ch(v):
		v /= 255
		return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
	r, g, b = (ch(v) for v in c)
	return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
	x, y = sorted((lum(a), lum(b)), reverse=True)
	return (x + 0.05) / (y + 0.05)


def hls(c):
	return colorsys.rgb_to_hls(*(v / 255 for v in c))


def from_hls(h, l, s):
	return tuple(v * 255 for v in colorsys.hls_to_rgb(h, l, s))


def is_neutral(c):
	return max(c) - min(c) < 16


def dark_bg(c):
	if is_neutral(c):
		return "#1d2027" if lum(c) > 0.75 else "#3a3f4a"
	h, _, s = hls(c)
	return to_hex(from_hls(h, 0.17, min(0.55, max(0.3, s))))


def light_text(c):
	h, l, s = hls(c)
	if is_neutral(c) or lum(c) < 0.03 or s < 0.3:
		return "#e5e7eb" if lum(c) < 0.06 else "#a1a1aa"
	while contrast(from_hls(h, l, s), CARD) < 4.5 and l < 0.95:
		l += 0.03
	return to_hex(from_hls(h, l, s))


def dark_border(c):
	if is_neutral(c):
		return "rgba(255, 255, 255, 0.14)"
	h, _, s = hls(c)
	return to_hex(from_hls(h, 0.32, min(0.6, max(0.3, s))))


NAMED = {
	"bg-red-50": "background-color: #3b1717 !important;", "bg-red-100": "background-color: #4a1c1c !important;",
	"bg-amber-50": "background-color: #3a2a10 !important;", "bg-green-50": "background-color: #12301d !important;",
	"border-red-200": "border-color: #7f2a2a !important;", "border-red-300": "border-color: #993333 !important;",
	"border-amber-200": "border-color: #7a5a1c !important;", "border-green-200": "border-color: #1f6b3a !important;",
	"text-red-500": "color: #f87171 !important;", "text-red-600": "color: #f87171 !important;", "text-red-700": "color: #fca5a5 !important;",
	"text-amber-700": "color: #fbbf24 !important;", "text-amber-800": "color: #fcd34d !important;", "text-green-700": "color: #4ade80 !important;",
	"bg-red-50/40": "background-color: rgba(127, 29, 29, 0.25) !important;", "text-red-700/80": "color: #fca5a5 !important;",
}

STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
CSS_DECL = re.compile(r"(background-color|background|color|border-color|border|border-top|border-bottom|border-left|border-right)\s*:\s*([^;]+)")
HEX_IN = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")
RGBA_IN = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
LIGHT_IN_GRADIENT = re.compile(r"rgba?\(\s*(?:255\s*,\s*255\s*,\s*255|245\s*,\s*245\s*,\s*247)\s*(?:,\s*([\d.]+)\s*)?\)")
WHITE_HEX = re.compile(r"#(?:fff|ffffff|f5f5f7)\b|\bwhite\b", re.I)
NAMED_CSS = {"white": "#ffffff", "#fff": "#ffffff"}


def css_overrides():
	"""템플릿 안 <style> 의 밝은 배경·어두운 글자·밝은 테두리도 다크 모드용으로."""
	out = []
	for path in sorted((ROOT / "templates").rglob("*.html")):
		for block in STYLE_BLOCK.findall(path.read_text(encoding="utf-8")):
			block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)  # 주석 제거
			# 템플릿이 이미 다크 모드 규칙을 직접 적어 둔 클래스는 건드리지 않음
			own_dark = set(re.findall(r"html\.theme-dark\s+([.#][\w-]+)", block))
			for selector, body in CSS_RULE.findall(block):
				selector = " ".join(selector.split())
				if own_dark and set(re.findall(r"[.#][\w-]+", selector)) & own_dark:
					continue
				if not selector or "theme-dark" in selector or selector.startswith("@") or re.fullmatch(r"[\d.%, ]+|from|to", selector):
					continue
				decls = []
				for prop, value in CSS_DECL.findall(body):
					value = value.strip()
					if "gradient" in value and prop in ("background", "background-color") and "url(" not in value:
						dark = LIGHT_IN_GRADIENT.sub(lambda m: f"rgba(17, 19, 24, {m.group(1) or '1'})", value)
						dark = WHITE_HEX.sub("rgba(17, 19, 24, 1)", dark)
						if dark != value:
							decls.append(f"background: {dark.replace('!important', '').strip()} !important")
						continue
					if "gradient" in value or "url(" in value or "var(" in value:
						continue
					value_l = value.lower()
					m = HEX_IN.search(value_l)
					color = m.group(0) if m else NAMED_CSS.get(value_l.replace("!important", "").strip())
					rgba = RGBA_IN.search(value_l)
					if not color and rgba and prop in ("background", "background-color"):
						r, g, b = (int(float(x)) for x in rgba.group(1, 2, 3))
						alpha = rgba.group(4) or "1"
						if (is_neutral((r, g, b)) and lum((r, g, b)) > 0.6) and float(alpha) > 0.4:
							decls.append(f"background-color: rgba(23, 26, 32, {alpha}) !important")
						continue
					if not color:
						continue
					c = rgb(color)
					if prop in ("background", "background-color"):
						if (is_neutral(c) and lum(c) > 0.6) or hls(c)[1] >= 0.88:
							decls.append(f"background-color: {'#171a20' if lum(c) > 0.97 else dark_bg(c)} !important")
					elif prop == "color":
						if contrast(c, CARD) < 4.5:
							decls.append(f"color: {light_text(c)} !important")
					elif (is_neutral(c) and lum(c) > 0.5) or hls(c)[1] >= 0.8:
						decls.append(f"border-color: {dark_border(c)} !important")
				if decls:
					sel = ", ".join(f"html.theme-dark {part.strip()}" for part in selector.split(",") if part.strip() and not part.strip().startswith(("html", ":root", "body")))
					if sel:
						out.append((sel, "; ".join(dict.fromkeys(decls)) + ";"))
	return out



def main():
	found = {}
	for path in sorted((ROOT / "templates").rglob("*.html")):
		for kind, color in PATTERN.findall(path.read_text(encoding="utf-8")):
			found.setdefault(kind, set()).add(color.lower())

	rules = []
	for kind in ("bg", "from", "via", "to"):
		for color in sorted(found.get(kind, ())):
			c = rgb(color)
			light = (is_neutral(c) and lum(c) > 0.6) or hls(c)[1] >= 0.88
			if not light or color in HANDLED.get(kind, ()):
				continue  # 진한 배경·선명한 색 버튼(카카오 노랑 등)은 그대로
			value = dark_bg(c)
			if kind == "bg":
				rules.append((f'[class*="bg-[{color}]" i]', f"background-color: {value} !important;"))
			else:
				rules.append((f'[class*="{kind}-[{color}]" i]', f"--tw-gradient-{kind}: {value} var(--tw-gradient-{kind}-position) !important;"))
	for color in sorted(found.get("text", ())):
		c = rgb(color)
		if color in HANDLED["text"] or contrast(c, CARD) >= 4.5:
			continue
		rules.append((f'[class*="text-[{color}]" i]', f"color: {light_text(c)} !important;"))
	for kind in ("border", "ring"):
		for color in sorted(found.get(kind, ())):
			c = rgb(color)
			if not ((is_neutral(c) and lum(c) > 0.5) or hls(c)[1] >= 0.8):
				continue
			prop = "border-color" if kind == "border" else "--tw-ring-color"
			rules.append((f'[class*="{kind}-[{color}]" i]', f"{prop}: {dark_border(c)} !important;"))

	# 다크 모드에서도 밝게 남는 선명한 배경(카카오 노랑 등) 위 글자는 어둡게 유지
	for color in sorted(found.get("bg", ())):
		c = rgb(color)
		light = (is_neutral(c) and lum(c) > 0.6) or hls(c)[1] >= 0.88
		if not light and lum(c) > 0.55:
			sel = f'[class*="bg-[{color}]" i]'
			rules.append((sel + sel, "color: #1d1d1f !important;"))

	# Tailwind 기본 색 이름 (알림 상자 등)
	for cls, decl in NAMED.items():
		rules.append((f'[class~="{cls}"]', decl))

	css_rules = css_overrides()

	lines = ["/* 자동 생성: scripts/gen_dark_css.py — 직접 고치지 말고 스크립트를 다시 실행하세요 */"]
	lines += [f"html.theme-dark {sel} {{ {decl} }}" for sel, decl in rules]
	lines += ["", "/* 템플릿 <style> 에 직접 적힌 색 */"]
	lines += [f"{sel} {{ {decl} }}" for sel, decl in css_rules]
	OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
	print(f"{OUT.relative_to(ROOT)}: 클래스 {len(rules)}개 + <style> {len(css_rules)}개 규칙")


if __name__ == "__main__":
	main()
