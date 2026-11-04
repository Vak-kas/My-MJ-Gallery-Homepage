#!/usr/bin/env bash
# smjgallery.kr 보내기 전용 메일 서버 (Postfix + OpenDKIM) — 서버에서 직접 실행:
#   sudo bash scripts/mailserver/setup_postfix_dkim.sh smjgallery.kr
#
# 하는 일
#   1) postfix·opendkim 설치, Django 가 localhost:25 로만 보내게 설정 (바깥에서 25번 포트로 받지 않음)
#   2) DKIM 키 생성 (selector: mj) → 화면에 DNS 에 넣을 TXT 값 출력
#   3) 메일 헤더에서 내부 IP·보낸 프로그램 정보 제거
# 여러 번 실행해도 안전 (키가 이미 있으면 새로 만들지 않음)

set -euo pipefail
DOMAIN="${1:-smjgallery.kr}"
SELECTOR="mj"
HOSTNAME_FQDN="mail.${DOMAIN}"

[ "$(id -u)" = 0 ] || { echo "sudo 로 실행하세요"; exit 1; }

echo "▶ 패키지 설치"
export DEBIAN_FRONTEND=noninteractive
debconf-set-selections <<< "postfix postfix/main_mailer_type select Internet Site"
debconf-set-selections <<< "postfix postfix/mailname string ${DOMAIN}"
apt-get update -qq
apt-get install -y -qq postfix opendkim opendkim-tools mailutils >/dev/null

echo "▶ Postfix: 보내기 전용, localhost 에서만 받음"
postconf -e "myhostname = ${HOSTNAME_FQDN}"
postconf -e "mydomain = ${DOMAIN}"
postconf -e "myorigin = ${DOMAIN}"
postconf -e "inet_interfaces = loopback-only"
postconf -e "inet_protocols = ipv4"
postconf -e "mydestination = localhost"
postconf -e "mynetworks = 127.0.0.0/8"
postconf -e "relayhost ="
postconf -e "smtp_tls_security_level = may"
postconf -e "smtp_tls_loglevel = 1"
postconf -e "smtpd_banner = \$myhostname ESMTP"
postconf -e "disable_vrfy_command = yes"
postconf -e "message_size_limit = 10485760"
postconf -e "smtp_helo_name = ${HOSTNAME_FQDN}"
# 로컬 사용자 메일(cron 알림 등)은 버림 — 받는 서버가 아님
postconf -e "local_recipient_maps ="
postconf -e "luser_relay ="
# OpenDKIM 연결
postconf -e "milter_default_action = accept"
postconf -e "milter_protocol = 6"
postconf -e "smtpd_milters = inet:127.0.0.1:8891"
postconf -e "non_smtpd_milters = inet:127.0.0.1:8891"
# 헤더에서 내부 정보 제거 (Received: from localhost ..., User-Agent 등)
cat > /etc/postfix/header_checks <<'HC'
/^Received:.*127\.0\.0\.1/    IGNORE
/^X-Originating-IP:/          IGNORE
/^X-Mailer:/                  IGNORE
/^User-Agent:/                IGNORE
HC
postconf -e "header_checks = regexp:/etc/postfix/header_checks"

echo "▶ OpenDKIM"
mkdir -p "/etc/opendkim/keys/${DOMAIN}"
if [ ! -f "/etc/opendkim/keys/${DOMAIN}/${SELECTOR}.private" ]; then
  opendkim-genkey -b 2048 -d "${DOMAIN}" -D "/etc/opendkim/keys/${DOMAIN}" -s "${SELECTOR}" -v
fi
chown -R opendkim:opendkim /etc/opendkim/keys
chmod 600 "/etc/opendkim/keys/${DOMAIN}/${SELECTOR}.private"
cat > /etc/opendkim.conf <<CONF
Syslog                  yes
SyslogSuccess           yes
LogWhy                  no
UMask                   007
Mode                    s
Canonicalization        relaxed/simple
SubDomains              no
OversignHeaders         From
Domain                  ${DOMAIN}
Selector                ${SELECTOR}
KeyFile                 /etc/opendkim/keys/${DOMAIN}/${SELECTOR}.private
Socket                  inet:8891@127.0.0.1
PidFile                 /run/opendkim/opendkim.pid
UserID                  opendkim:opendkim
TrustAnchorFile         /usr/share/dns/root.key
CONF
mkdir -p /run/opendkim && chown opendkim:opendkim /run/opendkim

systemctl enable --now opendkim >/dev/null
systemctl restart opendkim
systemctl enable --now postfix >/dev/null
systemctl restart postfix

echo
echo "================= DNS 에 넣을 레코드 (leto.kr 관리 화면) ================="
echo "1) SPF   — TXT  @            v=spf1 ip4:$(curl -s https://checkip.amazonaws.com || echo 서버IP) -all"
echo "2) DKIM  — TXT  ${SELECTOR}._domainkey   아래 값 (p= 뒤 큰따옴표 조각을 모두 이어 붙여 한 줄로)"
sed -e 's/^.*( *//' -e 's/ *) *;.*$//' "/etc/opendkim/keys/${DOMAIN}/${SELECTOR}.txt" | tr -d '\n' | sed 's/"[[:space:]]*"//g'; echo
echo "3) DMARC — TXT  _dmarc       v=DMARC1; p=reject; rua=mailto:postmaster@${DOMAIN}; adkim=s; aspf=s"
echo "4) A     — mail             $(curl -s https://checkip.amazonaws.com || echo 서버IP)   (PTR 요청 때 이 이름을 씀)"
echo "=========================================================================="
echo
echo "다음: (a) AWS 에 25번 포트 제한 해제 + 역방향 DNS(PTR → ${HOSTNAME_FQDN}) 요청  (b) 위 DNS 등록"
echo "      (c) 확인: sudo opendkim-testkey -d ${DOMAIN} -s ${SELECTOR} -vvv   /   venv/bin/python manage.py send_test_mail 받는주소"
