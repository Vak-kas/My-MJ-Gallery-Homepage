"""받은 메일 진단 — 원본 헤더로 "이 메일 믿어도 되나" 를 쉬운 말로 풀어 줌.

- SPF·DKIM·DMARC: 우리 서버(rspamd)가 적은 Authentication-Results·Received-SPF, DKIM-Signature 의 d= 와 From 도메인 일치, ARC.
- DKIM 은 dkimpy 가 있으면 서버에서 직접 다시 검증(DNS 공개키) → "본문이 바뀌지 않았는지" 확인.
- 전달 경로: Received 를 시간순으로 펼쳐 단계별 걸린 시간·TLS 여부. IP 는 마지막 자리를 가림.
- 피싱 단서: From·Reply-To·Return-Path 가 서로 다른 곳, 이름 칸에 다른 주소, 퓨니코드 도메인 등.
"""

import email
import ipaddress
import logging
import re
from email import policy
from email.utils import getaddresses, parsedate_to_datetime

from django.conf import settings
from django.utils import timezone

from .imap import _decode

OK, WARN, BAD, NONE = "ok", "warn", "bad", "none"
_RANK = {OK: 0, NONE: 1, WARN: 2, BAD: 3}
HEADERS_MAX = 64 * 1024
DKIM_MAX_SIGS = 3

# 조직 도메인(relaxed 정렬)용: 두 단계로 끝나는 흔한 공개 접미사
_TWO_LEVEL = {
	"co.kr", "or.kr", "go.kr", "ac.kr", "ne.kr", "re.kr", "pe.kr", "ms.kr", "hs.kr", "es.kr", "sc.kr", "kg.kr",
	"co.uk", "org.uk", "ac.uk", "gov.uk", "co.jp", "ne.jp", "or.jp", "ac.jp", "com.au", "net.au", "org.au",
	"com.cn", "com.tw", "com.hk", "com.sg", "co.nz", "com.br", "co.in",
}
_IP_RE = re.compile(r"\[(?:IPv6:)?([0-9A-Fa-f:.]+)\]")
_TLS_RE = re.compile(r"\b(?:ESMTPS|ESMTPSA|UTF8SMTPS|UTF8SMTPSA|LMTPS|TLSv?1[._]?\d|version=TLS|using TLS)\b", re.I)


# ---------- 작은 도우미 ----------

def domain_of(addr):
	addr = (addr or "").strip().strip("<>").lower()
	return addr.rsplit("@", 1)[1].strip(".") if "@" in addr else ""


def org_domain(domain):
	parts = (domain or "").lower().strip(".").split(".")
	if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_LEVEL:
		return ".".join(parts[-3:])
	return ".".join(parts[-2:])


def aligned(a, b):
	"""DMARC relaxed 정렬: 조직 도메인이 같으면 같은 곳."""
	return bool(a and b) and org_domain(a) == org_domain(b)


def mask_ip(value):
	"""IP 의 마지막 자리를 가림 (IPv4 마지막 옥텟, IPv6 마지막 묶음)."""
	try:
		ip = ipaddress.ip_address((value or "").strip())
	except ValueError:
		return value or ""
	if ip.version == 4:
		return ".".join(str(ip).split(".")[:3] + ["x"])
	return str(ip).rsplit(":", 1)[0] + ":x"


def _first_addr(value):
	got = getaddresses([str(value)]) if value else []
	return (_decode(got[0][0]), got[0][1].strip().lower()) if got and got[0][1] else ("", "")


def _clean(value):
	return re.sub(r"\s+", " ", str(value or "")).strip()


def _our_ids():
	dom = domain_of(settings.WEBMAIL_USER)
	tls = (getattr(settings, "WEBMAIL_IMAP_TLS_NAME", "") or "").lower()
	return {x for x in (dom, tls, f"mail.{dom}" if dom else "") if x}


# ---------- Authentication-Results ----------

def parse_auth_results(value):
	"""'mx.example; spf=pass smtp.mailfrom=a.com; dkim=pass header.d=a.com' → (authserv_id, [ {method, result, props} ])."""
	chunks = [c.strip() for c in _clean(value).split(";")]
	serv = chunks[0].split()[0].lower() if chunks and chunks[0] else ""
	results = []
	for chunk in chunks[1:]:
		policy_note = re.search(r"\(policy=(\w+)", chunk, re.I)  # rspamd: dmarc=pass (policy=reject)
		chunk = re.sub(r"\([^()]*\)", " ", chunk)  # 주석 제거
		m = re.match(r"([a-z\-]+)\s*=\s*([a-z]+)", chunk, re.I)
		if not m:
			continue
		props = {k.lower(): v.strip('"') for k, v in re.findall(r"([a-z]+\.[a-z\-]+)\s*=\s*(\S+)", chunk, re.I)}
		if policy_note and "policy.dmarc" not in props:
			props["policy.dmarc"] = policy_note.group(1).lower()
		results.append({"method": m.group(1).lower(), "result": m.group(2).lower(), "props": props})
	return serv, results


def _received_spf(value):
	v = _clean(value)
	m = re.match(r"(\w+)", v)
	envelope = re.search(r"envelope-from=\"?<?([^\s\";>]+)", v, re.I)
	return {"result": m.group(1).lower() if m else "", "mailfrom": envelope.group(1) if envelope else ""}


def _dkim_tags(value):
	tags = {}
	for part in re.sub(r"\s+", "", str(value or "")).split(";"):
		if "=" in part:
			k, v = part.split("=", 1)
			tags[k.lower()] = v
	return tags


# ---------- Received 경로 ----------

def parse_received(value):
	v = _clean(value)
	head, _sep, date_part = v.rpartition(";")
	if not _sep:
		head, date_part = v, ""
	try:
		dt = parsedate_to_datetime(date_part.strip()) if date_part.strip() else None
	except (TypeError, ValueError, IndexError):
		dt = None
	if dt and dt.tzinfo is None:
		dt = None
	frm = re.search(r"\bfrom\s+(\S+)", head, re.I)
	by = re.search(r"\bby\s+(\S+)", head, re.I)
	proto = re.search(r"\bwith\s+(\S+)", head, re.I)
	ip = _IP_RE.search(head.split(" by ", 1)[0]) if frm else None
	return {
		"from": (frm.group(1) if frm else "").strip("();"),
		"by": (by.group(1) if by else "").strip("();"),
		"with": (proto.group(1) if proto else "").strip("();"),
		"ip": mask_ip(ip.group(1)) if ip else "",
		"tls": bool(_TLS_RE.search(head)),
		"local": bool(proto and proto.group(1).upper().startswith("LMTP")) or bool(ip and ip.group(1) in ("127.0.0.1", "::1")),
		"dt": dt,
	}


def _duration_text(seconds):
	if seconds is None:
		return ""
	if seconds < 0:
		return "시계 차이"
	if seconds < 1:
		return "1초 안"
	if seconds < 60:
		return f"{int(seconds)}초"
	if seconds < 3600:
		return f"{int(seconds // 60)}분 {int(seconds % 60)}초"
	return f"{int(seconds // 3600)}시간 {int(seconds % 3600 // 60)}분"


def route(msg):
	hops = [parse_received(v) for v in (msg.get_all("Received") or [])][::-1][:30]  # 위가 최신 → 시간순으로
	out, prev = [], None
	for hop in hops:
		delay = (hop["dt"] - prev).total_seconds() if hop["dt"] and prev else None
		out.append({**{k: hop[k] for k in ("from", "by", "with", "ip", "tls", "local")},
		            "time": timezone.localtime(hop["dt"]).strftime("%m.%d %H:%M:%S") if hop["dt"] else "",
		            "delay": _duration_text(delay), "slow": bool(delay and delay > 300)})
		prev = hop["dt"] or prev
	dts = [h["dt"] for h in hops if h["dt"]]
	total = (dts[-1] - dts[0]).total_seconds() if len(dts) >= 2 else None
	return out, _duration_text(total)


# ---------- DKIM 직접 검증 ----------

class _ListLog(logging.Handler):
	def __init__(self):
		super().__init__()
		self.lines = []

	def emit(self, record):
		self.lines.append(record.getMessage())


def verify_dkim(raw, dnsfunc=None):
	"""dkimpy 로 DKIM 서명을 직접 검증. dkimpy 가 없으면 None."""
	try:
		import dkim
	except ImportError:
		return None
	out = []
	count = len(email.message_from_bytes(raw, policy=policy.compat32).get_all("DKIM-Signature") or [])
	for idx in range(min(count, DKIM_MAX_SIGS)):
		log = logging.getLogger(f"webmail.dkim.{idx}")
		log.propagate = False
		handler = _ListLog()
		log.addHandler(handler)
		try:
			d = dkim.DKIM(raw, logger=log)
			kwargs = {"dnsfunc": dnsfunc} if dnsfunc else {}
			ok = bool(d.verify(idx=idx, **kwargs))
			domain = (d.domain or b"").decode("ascii", "replace").lower()
			selector = (d.selector or b"").decode("ascii", "replace")
		except Exception as exc:  # noqa: BLE001 — DNS·형식 오류는 실패로
			ok, domain, selector = False, "", ""
			handler.lines.append(str(exc))
		finally:
			log.removeHandler(handler)
		reason = " / ".join(handler.lines)[-300:]
		out.append({"domain": domain, "selector": selector, "ok": ok, "reason": reason, "body_changed": "body hash mismatch" in reason,
		            "no_key": bool(re.search(r"public key|NXDOMAIN|no answer|dns", reason, re.I)) and "body hash" not in reason})
	return out


def lookup_dmarc_policy(domain, timeout=3.0):
	"""_dmarc.<도메인> TXT 의 p= (none/quarantine/reject). dnspython 이 없거나 못 찾으면 ''."""
	try:
		import dns.resolver
	except ImportError:
		return ""
	for name in dict.fromkeys([domain, org_domain(domain)]):
		if not name:
			continue
		try:
			answers = dns.resolver.resolve(f"_dmarc.{name}", "TXT", lifetime=timeout)
		except Exception:  # noqa: BLE001
			continue
		for rdata in answers:
			txt = b"".join(rdata.strings).decode("ascii", "replace")
			if txt.lower().startswith("v=dmarc1"):
				m = re.search(r"\bp\s*=\s*(\w+)", txt, re.I)
				return m.group(1).lower() if m else "none"
	return ""


# ---------- 종합 ----------

def _check(key, title, status, summary, detail="", source=""):
	return {"key": key, "title": title, "status": status, "summary": summary, "detail": detail, "source": source}


def analyze(raw, verify=True, dnsfunc=None, dmarc_lookup=None):
	"""원본 메일(bytes) → 진단 dict. verify=False 면 DNS 를 안 씀(헤더만)."""
	msg = email.message_from_bytes(raw, policy=policy.compat32)
	from_name, from_addr = _first_addr(msg.get("From"))
	from_dom = domain_of(from_addr)
	_rn, reply_addr = _first_addr(msg.get("Reply-To"))
	_pn, return_path = _first_addr(msg.get("Return-Path"))
	ours = _our_ids()

	# 1) 우리 서버가 적은 Authentication-Results (두 번째 Received 위에 있거나 authserv-id 가 우리 도메인)
	ordered = list(msg.items())
	received_seen, trusted, foreign = 0, [], []
	for name, value in ordered:
		lname = name.lower()
		if lname == "received":
			received_seen += 1
		elif lname == "authentication-results":
			serv, res = parse_auth_results(value)
			if received_seen <= 1 or serv in ours or any(serv.endswith("." + o) for o in ours):
				trusted.append((serv, res))
			else:
				foreign.append((serv, res))

	def pick(method):
		for serv, res in trusted:
			for r in res:
				if r["method"] == method:
					return r, serv
		return None, ""

	spf_ar, spf_serv = pick("spf")
	dkim_ar, dkim_serv = pick("dkim")
	dmarc_ar, dmarc_serv = pick("dmarc")
	rspf = _received_spf(msg.get("Received-SPF")) if msg.get("Received-SPF") else None
	mailfrom = (spf_ar or {}).get("props", {}).get("smtp.mailfrom") or (rspf or {}).get("mailfrom") or return_path
	mailfrom_dom = domain_of(mailfrom) if "@" in (mailfrom or "") else (mailfrom or "").lower()

	checks = []

	# SPF
	spf_result = (spf_ar or {}).get("result") or (rspf or {}).get("result") or ""
	if spf_result == "pass":
		spf_ok_aligned = aligned(mailfrom_dom, from_dom)
		checks.append(_check("spf", "SPF — 보낸 서버가 허락된 곳인지", OK if spf_ok_aligned else WARN,
		                     f"{mailfrom_dom or '보낸 쪽'} 도메인이 허락한 서버에서 왔어요." + ("" if spf_ok_aligned else f" 다만 보이는 보낸 사람({from_dom})과 다른 도메인 기준이에요."),
		                     "SPF 는 '이 도메인 메일은 이 서버들만 보낼 수 있다' 는 명단이에요. 명단에 있는 서버에서 왔다는 뜻.",
		                     spf_serv or "Received-SPF"))
	elif spf_result in ("fail", "softfail"):
		checks.append(_check("spf", "SPF — 보낸 서버가 허락된 곳인지", BAD if spf_result == "fail" else WARN,
		                     f"{mailfrom_dom or '보낸 쪽'} 도메인이 허락하지 않은 서버에서 왔어요.",
		                     "주소를 흉내 낸 메일일 수 있어요. 다만 다른 곳을 거쳐 '전달' 된 메일은 SPF 가 자주 깨져요 — 그럴 땐 DKIM 결과를 보세요.",
		                     spf_serv or "Received-SPF"))
	elif spf_result:
		checks.append(_check("spf", "SPF — 보낸 서버가 허락된 곳인지", NONE, f"판단할 수 없음 ({spf_result}).",
		                     "보낸 도메인이 SPF 명단을 안 만들었거나 DNS 조회가 안 됐어요.", spf_serv or "Received-SPF"))
	else:
		checks.append(_check("spf", "SPF — 보낸 서버가 허락된 곳인지", NONE, "기록이 없어요.",
		                     "우리 서버가 SPF 결과를 헤더에 남기지 않은 메일이에요(내가 보낸 메일·내부 메일 등)."))

	# DKIM — 헤더 결과 + 직접 검증
	sigs = [_dkim_tags(v) for v in (msg.get_all("DKIM-Signature") or [])]
	sig_domains = [s.get("d", "").lower() for s in sigs if s.get("d")]
	verified = verify_dkim(raw, dnsfunc=dnsfunc) if (verify and sigs) else None
	dkim_detail = "DKIM 은 보내는 서버가 메일에 찍는 전자 도장이에요. 도장이 맞으면 보내는 도중 제목·본문이 바뀌지 않았다는 뜻."
	if verified:
		good = [v for v in verified if v["ok"]]
		good_aligned = [v for v in good if aligned(v["domain"], from_dom)]
		changed = [v for v in verified if v["body_changed"]]
		if good_aligned:
			checks.append(_check("dkim", "DKIM — 보내는 도중 내용이 바뀌지 않았는지", OK,
			                     f"서버에서 직접 검증했어요: {good_aligned[0]['domain']} 의 도장이 맞고, 본문이 바뀌지 않았어요.", dkim_detail, "직접 검증(dkimpy)"))
		elif good:
			checks.append(_check("dkim", "DKIM — 보내는 도중 내용이 바뀌지 않았는지", WARN,
			                     f"도장({good[0]['domain']})은 맞고 본문도 그대로지만, 보이는 보낸 사람({from_dom})과 다른 도메인의 도장이에요.",
			                     dkim_detail + " 발송 대행 서비스(메일침프 등)를 쓰는 곳은 이렇게 나오기도 해요.", "직접 검증(dkimpy)"))
		elif changed:
			checks.append(_check("dkim", "DKIM — 보내는 도중 내용이 바뀌지 않았는지", BAD,
			                     "도장과 본문이 안 맞아요 — 보내는 도중 본문이 바뀌었어요.",
			                     dkim_detail + " 메일링 리스트가 꼬리말을 붙인 경우에도 이렇게 나와요.", "직접 검증(dkimpy)"))
		else:
			reason = verified[0]["reason"] or "이유 모름"
			checks.append(_check("dkim", "DKIM — 보내는 도중 내용이 바뀌지 않았는지", WARN if verified[0]["no_key"] else BAD,
			                     "도장을 확인하지 못했어요." + (" (DNS 에서 공개키를 못 찾음)" if verified[0]["no_key"] else ""),
			                     dkim_detail + f" 세부: {reason}", "직접 검증(dkimpy)"))
	elif dkim_ar:
		d = dkim_ar["props"].get("header.d") or dkim_ar["props"].get("header.i", "").lstrip("@").split("@")[-1]
		res = dkim_ar["result"]
		status = (OK if aligned(d, from_dom) or not d else WARN) if res == "pass" else (BAD if res in ("fail", "permerror") else NONE)
		checks.append(_check("dkim", "DKIM — 보내는 도중 내용이 바뀌지 않았는지", status,
		                     {"pass": f"{d or '보낸 쪽'} 의 도장이 맞아요.", "fail": "도장이 안 맞아요 — 내용이 바뀌었거나 위조예요."}.get(res, f"판단할 수 없음 ({res})."),
		                     dkim_detail + (" (서버에 dkimpy 가 없어 직접 검증은 못 했어요)" if verified is None and verify else ""), dkim_serv))
	elif sigs:
		checks.append(_check("dkim", "DKIM — 보내는 도중 내용이 바뀌지 않았는지", NONE,
		                     f"도장({', '.join(sig_domains)})은 있지만 확인 결과가 없어요.",
		                     dkim_detail + (" 서버에 dkimpy 를 설치하면 여기서 직접 검증해요." if verified is None else "")))
	else:
		checks.append(_check("dkim", "DKIM — 보내는 도중 내용이 바뀌지 않았는지", WARN if from_dom and from_dom not in ours else NONE,
		                     "도장(DKIM 서명)이 없는 메일이에요.", dkim_detail + " 요즘 정상적인 큰 메일 서비스는 거의 다 도장을 찍어요."))

	# DMARC — 우리 서버 결과가 있으면 그대로, 없으면 위 결과로 직접 계산
	dkim_pass_domains = [v["domain"] for v in (verified or []) if v["ok"]] if verified else (
		[dkim_ar["props"].get("header.d", "")] if dkim_ar and dkim_ar["result"] == "pass" else [])
	spf_aligned_pass = spf_result == "pass" and aligned(mailfrom_dom, from_dom)
	dkim_aligned_pass = any(aligned(d, from_dom) for d in dkim_pass_domains)
	if dmarc_lookup is None:
		dmarc_lookup = lookup_dmarc_policy if verify else (lambda _d: "")
	policy_p = (dmarc_ar or {}).get("props", {}).get("policy.dmarc", "") or (dmarc_lookup(from_dom) if from_dom else "")
	policy_text = {"reject": "이 도메인은 위조 메일을 '거절' 하라고 해 뒀어요.", "quarantine": "이 도메인은 위조 메일을 '스팸함으로' 보내라고 해 뒀어요.",
	               "none": "이 도메인은 위조 메일을 '지켜보기만' 하라고 해 뒀어요."}.get(policy_p, "")
	dmarc_detail = "DMARC 는 '보이는 보낸 사람 주소(From)' 가 진짜 그 도메인에서 왔는지 SPF·DKIM 결과를 묶어 최종 판정하는 규칙이에요. " + policy_text
	computed = "pass" if (spf_aligned_pass or dkim_aligned_pass) else ("fail" if (spf_result or sigs) else "")
	dmarc_res = (dmarc_ar or {}).get("result") or computed
	if dmarc_res == "pass":
		why = "도장(DKIM)" if dkim_aligned_pass else "보낸 서버(SPF)" if spf_aligned_pass else "우리 서버 판정"
		checks.append(_check("dmarc", "DMARC — 보낸 사람 주소가 진짜인지", OK, f"보낸 사람 주소({from_dom})가 진짜 그 도메인에서 왔어요. ({why} 로 확인)",
		                     dmarc_detail, dmarc_serv or "직접 계산"))
	elif dmarc_res == "fail":
		checks.append(_check("dmarc", "DMARC — 보낸 사람 주소가 진짜인지", BAD, f"보낸 사람 주소({from_dom})가 그 도메인에서 왔다는 걸 확인하지 못했어요. 사칭일 수 있어요.",
		                     dmarc_detail, dmarc_serv or "직접 계산"))
	else:
		checks.append(_check("dmarc", "DMARC — 보낸 사람 주소가 진짜인지", NONE, "판단할 자료가 없어요." if not dmarc_res else f"판단할 수 없음 ({dmarc_res}).",
		                     dmarc_detail, dmarc_serv))

	# ARC (전달·메일링 리스트를 거친 메일의 이전 인증 기록)
	arc = []
	for v in msg.get_all("ARC-Authentication-Results") or []:
		inst = re.match(r"\s*i\s*=\s*(\d+)\s*;", str(v))
		serv, res = parse_auth_results(re.sub(r"^\s*i\s*=\s*\d+\s*;", "", _clean(v)))
		arc.append({"i": int(inst.group(1)) if inst else 0, "by": serv, "results": [f"{r['method']}={r['result']}" for r in res if r["method"] in ("spf", "dkim", "dmarc")]})
	seals = [re.search(r"\bcv\s*=\s*(\w+)", str(v)) for v in msg.get_all("ARC-Seal") or []]
	arc_cv = [m.group(1).lower() for m in seals if m]
	if arc:
		arc.sort(key=lambda a: a["i"])
		bad_chain = "fail" in arc_cv
		checks.append(_check("arc", "ARC — 중간에 전달한 서버의 기록", WARN if bad_chain else OK,
		                     f"중간 서버 {len(arc)}곳이 받을 때의 인증 결과를 남겼어요." + (" 그런데 기록 사슬이 깨졌어요." if bad_chain else ""),
		                     "메일링 리스트·자동 전달처럼 중간에 거쳐 SPF/DKIM 이 깨질 때, 처음 받았을 때의 결과를 보여 주는 기록이에요. " +
		                     " · ".join(f"{a['i']}번 {a['by']}: {', '.join(a['results']) or '-'}" for a in arc)))

	# 피싱 단서
	clues = []
	if reply_addr and domain_of(reply_addr) and not aligned(domain_of(reply_addr), from_dom):
		clues.append({"status": WARN, "text": f"답장하면 보낸 사람({from_addr})이 아니라 다른 곳({reply_addr})으로 가요.",
		              "detail": "보이는 보낸 사람과 '답장 받을 주소(Reply-To)' 가 달라요. 사칭 메일이 답장을 가로챌 때 흔히 쓰는 수법이에요."})
	if return_path and domain_of(return_path) and from_dom and not aligned(domain_of(return_path), from_dom):
		clues.append({"status": OK if dkim_aligned_pass else WARN, "text": f"반송 주소(Return-Path: {domain_of(return_path)})가 보낸 사람 도메인({from_dom})과 달라요.",
		              "detail": "뉴스레터·발송 대행은 흔히 이래요." + (" DKIM 도장이 보낸 사람 도메인과 맞으니 괜찮아요." if dkim_aligned_pass else " 다른 단서와 같이 보세요.")})
	inner = re.findall(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+", from_name or "")
	if any(a.lower() != from_addr for a in inner):
		clues.append({"status": BAD, "text": f"이름 칸에 다른 주소({inner[0]})를 적어 두었어요. 실제 주소는 {from_addr} 예요.",
		              "detail": "메일 앱이 이름만 보여 줄 때 진짜 주소인 척하려는 흔한 위장이에요."})
	if "xn--" in from_dom:
		clues.append({"status": WARN, "text": f"보낸 사람 도메인({from_dom})이 특수 문자(퓨니코드) 도메인이에요.",
		              "detail": "다른 나라 글자로 유명 도메인과 똑같아 보이게 만든 가짜일 수 있어요."})
	if from_dom and from_dom in ours and not (dkim_aligned_pass or spf_aligned_pass) and len(msg.get_all("Received") or []) > 1:
		clues.append({"status": BAD, "text": f"우리 도메인({from_dom})에서 보낸 척하지만 우리 서버 도장·허락이 확인되지 않아요.",
		              "detail": "내 주소를 사칭한 메일일 수 있어요."})

	hops, total = route(msg)
	no_tls = [h for h in hops if h["from"] and not h["tls"] and not h["local"]]
	if no_tls:
		clues.append({"status": NONE, "text": f"암호화(TLS) 없이 전달된 구간이 {len(no_tls)}곳 있어요.",
		              "detail": "그 구간에선 중간에서 내용을 엿볼 수 있었다는 뜻이에요. 헤더에 표시가 없는 서버도 있어 꼭 위험한 건 아니에요."})

	statuses = [c["status"] for c in checks if c["key"] != "arc"] + [c["status"] for c in clues]
	worst = max(statuses, key=lambda s: _RANK[s]) if statuses else NONE
	if worst == OK or (worst == NONE and dmarc_res == "pass"):
		verdict = (OK, "믿어도 돼요 — 보낸 사람 주소가 진짜고, 오는 길에 바뀌지 않았어요.")
	elif worst == BAD:
		verdict = (BAD, "조심하세요 — 사칭이거나 내용이 바뀐 메일일 수 있어요. 링크·첨부를 열지 마세요.")
	elif worst == WARN:
		verdict = (WARN, "대체로 괜찮지만 확인할 점이 있어요.")
	else:
		verdict = (NONE, "판단할 자료가 부족해요.")

	header_bytes = raw.split(b"\r\n\r\n", 1)[0] if b"\r\n\r\n" in raw else raw.split(b"\n\n", 1)[0]
	return {
		"verdict": verdict[0], "verdict_text": verdict[1],
		"from": from_addr, "from_domain": from_dom, "reply_to": reply_addr, "return_path": return_path,
		"checks": checks, "clues": clues, "route": hops, "route_total": total,
		"foreign_results": [{"by": s, "results": [f"{r['method']}={r['result']}" for r in res]} for s, res in foreign][:5],
		"dkim_verified": verified is not None, "dkimpy_missing": bool(verify and sigs and verified is None), "dmarc_policy": policy_p,
		"headers": header_bytes[:HEADERS_MAX].decode("utf-8", "replace"),
	}
