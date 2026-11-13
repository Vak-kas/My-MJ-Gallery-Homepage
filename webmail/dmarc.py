"""DMARC 집계 보고서(rua) 읽기 — Google·Yahoo 등이 postmaster@ 로 보내는 .zip / .xml.gz / .xml 첨부를 사람이 읽을 수 있게.

보고서는 "지난 하루 동안 우리 도메인(From)을 달고 온 메일이 어느 IP 에서 몇 통, SPF·DKIM 이 어떻게 됐는지" 를 모은 것.
"""

import gzip
import io
import re
import zipfile
from datetime import datetime, timezone as dt_timezone
from xml.etree import ElementTree

from django.utils import timezone

from .diagnose import mask_ip

XML_MAX = 10 * 1024 * 1024
REPORT_NAME_RE = re.compile(r"\.(zip|xml\.gz|gz|xml)$", re.I)


class ReportError(Exception):
	pass


def looks_like_report(filename, content_type=""):
	name = (filename or "").lower()
	return bool(REPORT_NAME_RE.search(name)) and ("!" in name or "dmarc" in name or "report" in name or content_type in (
		"application/zip", "application/gzip", "application/x-gzip", "application/xml", "text/xml"))


def extract_xml(data):
	"""zip·gzip·그냥 XML 중 무엇이든 XML bytes 로. 압축 폭탄 방지로 10MB 까지만."""
	if data[:4] == b"PK\x03\x04":
		try:
			with zipfile.ZipFile(io.BytesIO(data)) as zf:
				names = [i for i in zf.infolist() if i.filename.lower().endswith(".xml")] or zf.infolist()
				if not names:
					raise ReportError("압축 안에 파일이 없어요")
				if names[0].file_size > XML_MAX:
					raise ReportError("보고서가 너무 커요")
				with zf.open(names[0]) as fh:
					out = fh.read(XML_MAX + 1)
		except zipfile.BadZipFile:
			raise ReportError("zip 파일이 깨졌어요")
	elif data[:2] == b"\x1f\x8b":
		try:
			with gzip.GzipFile(fileobj=io.BytesIO(data)) as fh:
				out = fh.read(XML_MAX + 1)
		except (OSError, EOFError):
			raise ReportError("gz 파일이 깨졌어요")
	else:
		out = data
	if len(out) > XML_MAX:
		raise ReportError("보고서가 너무 커요")
	return out


def _t(node, path, default=""):
	if node is None:
		return default
	found = node.find(path)
	return (found.text or "").strip() if found is not None and found.text else default


def _when(epoch):
	try:
		return timezone.localtime(datetime.fromtimestamp(int(epoch), tz=dt_timezone.utc)).strftime("%Y.%m.%d %H:%M")
	except (TypeError, ValueError, OverflowError, OSError):
		return ""


def parse_report(data):
	xml = extract_xml(data)
	head = xml[:2048].lower()
	if b"<!doctype" in head or b"<!entity" in xml.lower():  # 외부 엔티티·엔티티 폭탄 차단
		raise ReportError("허용하지 않는 XML 이에요")
	try:
		root = ElementTree.fromstring(xml)
	except ElementTree.ParseError:
		raise ReportError("DMARC 보고서(XML)가 아니에요")
	# 네임스페이스(DMARC 2.0 초안) 제거
	for el in root.iter():
		if isinstance(el.tag, str) and "}" in el.tag:
			el.tag = el.tag.split("}", 1)[1]
	if root.tag != "feedback":
		raise ReportError("DMARC 보고서(XML)가 아니에요")

	meta, pol = root.find("report_metadata"), root.find("policy_published")
	policy_p = _t(pol, "p", "none").lower()
	rows, total, passed = [], 0, 0
	for rec in root.findall("record"):
		row = rec.find("row")
		try:
			count = int(_t(row, "count", "0"))
		except ValueError:
			count = 0
		ev = row.find("policy_evaluated") if row is not None else None
		dkim_al, spf_al = _t(ev, "dkim").lower(), _t(ev, "spf").lower()
		ok = dkim_al == "pass" or spf_al == "pass"
		auth = rec.find("auth_results")
		dkim_auth = [{"domain": _t(d, "domain"), "selector": _t(d, "selector"), "result": _t(d, "result").lower()} for d in (auth.findall("dkim") if auth is not None else [])]
		spf_auth = [{"domain": _t(s, "domain"), "result": _t(s, "result").lower()} for s in (auth.findall("spf") if auth is not None else [])]
		reasons = [f"{_t(r, 'type')}{(': ' + _t(r, 'comment')) if _t(r, 'comment') else ''}" for r in (ev.findall("reason") if ev is not None else [])]
		item = {
			"ip": mask_ip(_t(row, "source_ip")), "count": count, "ok": ok,
			"disposition": _t(ev, "disposition", "none").lower(), "dkim_aligned": dkim_al, "spf_aligned": spf_al,
			"header_from": _t(rec, "identifiers/header_from"), "envelope_from": _t(rec, "identifiers/envelope_from"),
			"dkim": dkim_auth, "spf": spf_auth, "reasons": reasons,
		}
		item["advice"] = _advice(item, policy_p)
		rows.append(item)
		total += count
		passed += count if ok else 0
	rows.sort(key=lambda r: (r["ok"], -r["count"]))
	failed = total - passed
	return {
		"org": _t(meta, "org_name"), "email": _t(meta, "email"), "report_id": _t(meta, "report_id"),
		"begin": _when(_t(meta, "date_range/begin")), "end": _when(_t(meta, "date_range/end")),
		"domain": _t(pol, "domain"), "policy": policy_p, "sp": _t(pol, "sp").lower(), "pct": _t(pol, "pct", "100"),
		"adkim": _t(pol, "adkim", "r"), "aspf": _t(pol, "aspf", "r"),
		"total": total, "passed": passed, "failed": failed, "rows": rows[:200],
		"summary": _summary(total, failed, policy_p, rows),
	}


_ACTION = {"reject": "거절됐어요", "quarantine": "스팸함으로 갔어요", "none": "그냥 배달됐어요"}


def _advice(row, policy_p):
	"""한 줄(IP)의 결과를 쉬운 말로: 무엇이 됐고, 고칠 게 있으면 무엇을."""
	spf_raw = next((s["result"] for s in row["spf"]), "")
	dkim_raw = next((d["result"] for d in row["dkim"]), "")
	if row["dkim_aligned"] == "pass" and row["spf_aligned"] == "pass":
		return "SPF·DKIM 모두 통과. 할 일 없어요."
	if row["dkim_aligned"] == "pass":
		return ("DKIM 도장 덕에 통과. SPF 는 " + ("이 IP 가 SPF 명단에 없어서" if spf_raw in ("fail", "softfail") else "반송 주소 도메인이 달라서") +
		        " 안 맞았어요 — 다른 곳을 거쳐 전달된 메일이면 흔한 일이라 보통 괜찮아요.")
	if row["spf_aligned"] == "pass":
		return ("SPF 덕에 통과. DKIM 도장은 " + ("깨졌어요" if dkim_raw == "fail" else "없거나 다른 도메인 것이었어요") +
		        " — 우리 서버에서 보낸 메일이라면 OpenDKIM 이 서명하는지 확인하세요(opendkim-testkey -d 도메인 -s mj).")
	disp = _ACTION.get(row["disposition"], row["disposition"])
	if spf_raw == "pass" or dkim_raw == "pass":
		return (f"SPF/DKIM 자체는 통과했지만 보이는 보낸 사람 도메인과 달라 실패, {disp}. "
		        "우리가 쓰는 발송 서비스(뉴스레터 등)라면 그 서비스에 우리 도메인 DKIM 을 설정해야 해요.")
	return (f"SPF·DKIM 모두 실패, {disp}. 이 IP 가 우리 서버나 우리가 쓰는 발송 서비스가 아니라면 누군가 우리 도메인을 사칭한 것이고, "
	        + ("정책(p=reject) 대로 막혔으니 할 일은 없어요." if policy_p == "reject" else "정책을 p=quarantine 이나 p=reject 로 올리면 막을 수 있어요.")
	        + " 우리 쪽 서버라면 DNS 의 SPF 레코드에 이 IP 를 넣고 DKIM 서명을 켜세요.")


def _summary(total, failed, policy_p, rows):
	if not total:
		return "이 기간에 우리 도메인으로 온 메일이 없었대요."
	if not failed:
		return f"모두 {total}통, 전부 통과했어요. 우리 도메인 메일이 정상적으로 인증되고 있어요 — 할 일 없어요."
	fail_ips = len([r for r in rows if not r["ok"]])
	return (f"모두 {total}통 중 {failed}통이 실패했어요({fail_ips}개 IP). "
	        + ("정책이 reject 라 실패한 메일은 받는 쪽에서 거절됐어요. " if policy_p == "reject" else "")
	        + "아래 빨간 줄을 보고 우리 서버인지, 사칭인지 확인하세요.")
