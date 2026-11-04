#!/usr/bin/env bash
# smjgallery.kr 메일 서버 (받기 + 보내기 + IMAP + 웹메일) — 서버에서 직접 실행:
#   sudo bash scripts/mailserver/setup_mailserver.sh smjgallery.kr mjseo
#
# 구성 (메일함은 딱 하나: mjseo@smjgallery.kr. 사이트 회원과는 무관)
#   Postfix   : 받기(25) · 보내기(25 밖으로) · 폰/웹메일에서 보내기(587, 로그인 필요)
#   Dovecot   : IMAP(993) · 메일함 저장(Maildir) · 587 로그인 확인
#   OpenDKIM  : 나가는 메일 서명 (selector mj)
#   rspamd    : 스팸 점수 (스팸은 "Junk" 폴더로)
#   Roundcube : 웹메일 https://mail.smjgallery.kr (nginx + php-fpm, sqlite)
#   TLS       : Let's Encrypt (mail.smjgallery.kr 인증서를 certbot 으로 새로 받음)
# 별칭: noreply@ postmaster@ abuse@ admin@ hostmaster@ → mjseo
# 여러 번 실행해도 안전. 메일 비밀번호는 실행 중 물어봄 (화면에 안 보임).

set -euo pipefail
DOMAIN="${1:-smjgallery.kr}"
USERNAME="${2:-mjseo}"
MAILHOST="mail.${DOMAIN}"
SELECTOR="mj"
VMAIL_DIR="/var/mail/vhosts"
MAILBOX="${USERNAME}@${DOMAIN}"

[ "$(id -u)" = 0 ] || { echo "sudo 로 실행하세요"; exit 1; }
export DEBIAN_FRONTEND=noninteractive

echo "▶ 1/8 패키지"
debconf-set-selections <<< "postfix postfix/main_mailer_type select Internet Site"
debconf-set-selections <<< "postfix postfix/mailname string ${DOMAIN}"
debconf-set-selections <<< "roundcube-core roundcube/dbconfig-install boolean true"
debconf-set-selections <<< "roundcube-core roundcube/database-type select sqlite3"
apt-get update -qq
apt-get install -y -qq postfix dovecot-core dovecot-imapd dovecot-lmtpd \
  opendkim opendkim-tools rspamd redis-server \
  roundcube roundcube-sqlite3 php-fpm php-intl php-gd php-zip \
  certbot python3-certbot-nginx mailutils >/dev/null

echo "▶ 2/8 메일함 사용자(vmail)와 비밀번호"
getent group vmail >/dev/null || groupadd -g 5000 vmail
id vmail >/dev/null 2>&1 || useradd -g vmail -u 5000 -d "${VMAIL_DIR}" -s /usr/sbin/nologin vmail
mkdir -p "${VMAIL_DIR}/${DOMAIN}/${USERNAME}"
chown -R vmail:vmail "${VMAIL_DIR}"
chmod -R 750 "${VMAIL_DIR}"
usermod -aG vmail ubuntu   # S3 백업이 메일함을 읽을 수 있게
if [ ! -s /etc/dovecot/users ] || ! grep -q "^${MAILBOX}:" /etc/dovecot/users; then
  read -rsp "  ${MAILBOX} 메일 비밀번호 (IMAP·웹메일·587 에 씀): " PW; echo
  read -rsp "  한 번 더: " PW2; echo
  [ "$PW" = "$PW2" ] || { echo "비밀번호가 달라요"; exit 1; }
  HASH=$(doveadm pw -s SHA512-CRYPT -p "$PW")
  unset PW PW2
  touch /etc/dovecot/users
  grep -v "^${MAILBOX}:" /etc/dovecot/users > /etc/dovecot/users.new || true
  echo "${MAILBOX}:${HASH}" >> /etc/dovecot/users.new
  mv /etc/dovecot/users.new /etc/dovecot/users
fi
chown root:dovecot /etc/dovecot/users; chmod 640 /etc/dovecot/users

echo "▶ 3/8 TLS 인증서 (mail.${DOMAIN})"
cat > /etc/nginx/sites-available/mail <<NG
server {
    listen 80;
    server_name ${MAILHOST};
    root /var/lib/roundcube/public_html;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
NG
ln -sf /etc/nginx/sites-available/mail /etc/nginx/sites-enabled/mail
nginx -t && systemctl reload nginx
if [ ! -d "/etc/letsencrypt/live/${MAILHOST}" ]; then
  certbot certonly --nginx -d "${MAILHOST}" --non-interactive --agree-tos --register-unsafely-without-email || certbot certonly --nginx -d "${MAILHOST}" --non-interactive --agree-tos -m "${MAILBOX}"
fi
CERT="/etc/letsencrypt/live/${MAILHOST}/fullchain.pem"; KEY="/etc/letsencrypt/live/${MAILHOST}/privkey.pem"
# 인증서가 갱신되면 메일 서비스도 다시 읽게
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/mail.sh <<'H'
#!/bin/sh
systemctl reload postfix dovecot nginx 2>/dev/null || true
H
chmod +x /etc/letsencrypt/renewal-hooks/deploy/mail.sh

echo "▶ 4/8 OpenDKIM"
mkdir -p "/etc/opendkim/keys/${DOMAIN}"
[ -f "/etc/opendkim/keys/${DOMAIN}/${SELECTOR}.private" ] || opendkim-genkey -b 2048 -d "${DOMAIN}" -D "/etc/opendkim/keys/${DOMAIN}" -s "${SELECTOR}"
chown -R opendkim:opendkim /etc/opendkim/keys; chmod 600 "/etc/opendkim/keys/${DOMAIN}/${SELECTOR}.private"
cat > /etc/opendkim.conf <<CONF
Syslog yes
UMask 007
Mode sv
Canonicalization relaxed/simple
OversignHeaders From
Domain ${DOMAIN}
Selector ${SELECTOR}
KeyFile /etc/opendkim/keys/${DOMAIN}/${SELECTOR}.private
Socket inet:8891@127.0.0.1
PidFile /run/opendkim/opendkim.pid
UserID opendkim:opendkim
TrustAnchorFile /usr/share/dns/root.key
CONF
systemctl enable --now opendkim >/dev/null; systemctl restart opendkim

echo "▶ 5/8 rspamd (스팸 점수)"
mkdir -p /etc/rspamd/local.d
cat > /etc/rspamd/local.d/worker-proxy.inc <<'R'
bind_socket = "127.0.0.1:11332";
milter = yes;
timeout = 120s;
upstream "local" { default = yes; self_scan = yes; }
R
cat > /etc/rspamd/local.d/actions.conf <<'R'
reject = 15;
add_header = 6;
greylist = null;
R
cat > /etc/rspamd/local.d/milter_headers.conf <<'R'
use = ["x-spamd-result", "x-spam-status"];
R
systemctl enable --now redis-server rspamd >/dev/null; systemctl restart rspamd

echo "▶ 6/8 Dovecot (IMAP 993 · LMTP · 587 로그인)"
cat > /etc/dovecot/local.conf <<D
protocols = imap lmtp
listen = *
ssl = required
ssl_cert = <${CERT}
ssl_key = <${KEY}
ssl_min_protocol = TLSv1.2
disable_plaintext_auth = yes
auth_mechanisms = plain login
mail_location = maildir:${VMAIL_DIR}/%d/%n
mail_privileged_group = vmail
first_valid_uid = 5000
last_valid_uid = 5000
passdb { driver = passwd-file; args = scheme=SHA512-CRYPT username_format=%u /etc/dovecot/users }
userdb  { driver = static; args = uid=vmail gid=vmail home=${VMAIL_DIR}/%d/%n }
namespace inbox {
  inbox = yes
  mailbox Drafts { auto = subscribe; special_use = \\Drafts }
  mailbox Junk   { auto = subscribe; special_use = \\Junk }
  mailbox Sent   { auto = subscribe; special_use = \\Sent }
  mailbox Trash  { auto = subscribe; special_use = \\Trash }
}
service imap-login { inet_listener imap { port = 0 } inet_listener imaps { port = 993 } }
service lmtp { unix_listener /var/spool/postfix/private/dovecot-lmtp { mode = 0600; user = postfix; group = postfix } }
service auth { unix_listener /var/spool/postfix/private/auth { mode = 0660; user = postfix; group = postfix } }
protocol lmtp { mail_plugins = \$mail_plugins sieve }
D
# 스팸 점수 높은 건 Junk 폴더로 (sieve)
apt-get install -y -qq dovecot-sieve >/dev/null
mkdir -p /etc/dovecot/sieve
cat > /etc/dovecot/sieve/default.sieve <<'S'
require ["fileinto"];
if header :contains "X-Spam" "Yes" { fileinto "Junk"; }
S
sievec /etc/dovecot/sieve/default.sieve
cat >> /etc/dovecot/local.conf <<'D'
plugin { sieve_default = file:/etc/dovecot/sieve/default.sieve }
D
systemctl enable --now dovecot >/dev/null; systemctl restart dovecot

echo "▶ 7/8 Postfix"
postconf -e "myhostname = ${MAILHOST}"
postconf -e "mydomain = ${DOMAIN}"
postconf -e "myorigin = ${DOMAIN}"
postconf -e "inet_interfaces = all"
postconf -e "inet_protocols = ipv4"
postconf -e "mydestination = localhost"
postconf -e "mynetworks = 127.0.0.0/8"
postconf -e "relayhost ="
postconf -e "message_size_limit = 26214400"
postconf -e "disable_vrfy_command = yes"
postconf -e "smtpd_banner = \$myhostname ESMTP"
postconf -e "smtp_helo_name = ${MAILHOST}"
# 받는 메일함 (가상 도메인, 사용자 1명 + 별칭)
postconf -e "virtual_mailbox_domains = ${DOMAIN}"
postconf -e "virtual_mailbox_maps = hash:/etc/postfix/vmailbox"
postconf -e "virtual_alias_maps = hash:/etc/postfix/valias"
postconf -e "virtual_transport = lmtp:unix:private/dovecot-lmtp"
echo "${MAILBOX}  ok" > /etc/postfix/vmailbox
cat > /etc/postfix/valias <<A
noreply@${DOMAIN}     ${MAILBOX}
postmaster@${DOMAIN}  ${MAILBOX}
abuse@${DOMAIN}       ${MAILBOX}
admin@${DOMAIN}       ${MAILBOX}
hostmaster@${DOMAIN}  ${MAILBOX}
A
postmap /etc/postfix/vmailbox /etc/postfix/valias
# TLS
postconf -e "smtpd_tls_cert_file = ${CERT}"
postconf -e "smtpd_tls_key_file = ${KEY}"
postconf -e "smtpd_tls_security_level = may"
postconf -e "smtpd_tls_protocols = !SSLv2, !SSLv3, !TLSv1, !TLSv1.1"
postconf -e "smtp_tls_security_level = may"
postconf -e "smtp_tls_loglevel = 1"
# 587 로그인은 Dovecot 이 확인
postconf -e "smtpd_sasl_type = dovecot"
postconf -e "smtpd_sasl_path = private/auth"
postconf -e "smtpd_sasl_auth_enable = no"
postconf -e "smtpd_relay_restrictions = permit_mynetworks, permit_sasl_authenticated, reject_unauth_destination"
postconf -e "smtpd_recipient_restrictions = permit_mynetworks, permit_sasl_authenticated, reject_unauth_destination, reject_unknown_recipient_domain, reject_rbl_client zen.spamhaus.org"
postconf -e "smtpd_helo_required = yes"
postconf -e "smtpd_sender_restrictions = reject_unknown_sender_domain"
# 밀터: 받을 때 rspamd, 보낼 때 DKIM + rspamd
postconf -e "milter_default_action = accept"
postconf -e "milter_protocol = 6"
postconf -e "smtpd_milters = inet:127.0.0.1:8891, inet:127.0.0.1:11332"
postconf -e "non_smtpd_milters = inet:127.0.0.1:8891, inet:127.0.0.1:11332"
# 내부 정보 헤더 제거 (폰·웹메일에서 보낼 때 내 IP 안 보이게)
cat > /etc/postfix/header_checks <<'HC'
/^Received:.*with ESMTPSA/        IGNORE
/^X-Originating-IP:/              IGNORE
/^X-Mailer:/                      IGNORE
/^User-Agent:/                    IGNORE
HC
postconf -e "header_checks = regexp:/etc/postfix/header_checks"
# 587 submission 켜기 (master.cf)
if ! grep -q "^submission " /etc/postfix/master.cf; then
cat >> /etc/postfix/master.cf <<'M'
submission inet n       -       y       -       -       smtpd
  -o syslog_name=postfix/submission
  -o smtpd_tls_security_level=encrypt
  -o smtpd_sasl_auth_enable=yes
  -o smtpd_client_restrictions=permit_sasl_authenticated,reject
  -o smtpd_relay_restrictions=permit_sasl_authenticated,reject
  -o cleanup_service_name=header_cleanup
header_cleanup unix n - - - 0 cleanup
  -o header_checks=regexp:/etc/postfix/header_checks
M
fi
systemctl enable --now postfix >/dev/null; systemctl restart postfix

echo "▶ 8/8 Roundcube 웹메일 (https://${MAILHOST})"
PHPSOCK=$(ls /run/php/php*-fpm.sock | head -1)
cat > /etc/nginx/sites-available/mail <<NG
server {
    listen 80;
    server_name ${MAILHOST};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    server_name ${MAILHOST};
    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    root /var/lib/roundcube/public_html;
    index index.php;
    client_max_body_size 30M;
    add_header X-Frame-Options SAMEORIGIN;
    add_header X-Content-Type-Options nosniff;
    location ~ ^/(config|temp|logs|bin|SQL|README|INSTALL|LICENSE|CHANGELOG|UPGRADING)(/|$) { deny all; }
    location ~ \\.php\$ { include snippets/fastcgi-php.conf; fastcgi_pass unix:${PHPSOCK}; }
    location ~ /\\. { deny all; }
}
NG
cat > /etc/roundcube/config.inc.php.mj <<RC
<?php
\$config['imap_host'] = 'ssl://${MAILHOST}:993';
\$config['smtp_host'] = 'tls://${MAILHOST}:587';
\$config['smtp_user'] = '%u';
\$config['smtp_pass'] = '%p';
\$config['product_name'] = 'MJ Mail';
\$config['username_domain'] = '${DOMAIN}';
\$config['skin'] = 'elastic';
\$config['language'] = 'ko_KR';
\$config['plugins'] = ['archive', 'zipdownload', 'managesieve'];
\$config['session_lifetime'] = 60;
\$config['login_rate_limit'] = 5;
RC
grep -q "config.inc.php.mj" /etc/roundcube/config.inc.php || echo "include('/etc/roundcube/config.inc.php.mj');" >> /etc/roundcube/config.inc.php
nginx -t && systemctl reload nginx
systemctl restart "$(basename "$(dirname "$PHPSOCK")")" 2>/dev/null || systemctl restart php*-fpm

echo
echo "================= DNS 에 넣을 레코드 ================="
IP=$(curl -s https://checkip.amazonaws.com || echo "서버IP")
echo "MX    @             10 ${MAILHOST}."
echo "A     mail          ${IP}   (이미 있음)"
echo "TXT   @             v=spf1 ip4:${IP} -all"
printf "TXT   %s._domainkey   " "${SELECTOR}"; sed -e 's/^.*( *//' -e 's/ *) *;.*$//' "/etc/opendkim/keys/${DOMAIN}/${SELECTOR}.txt" | tr -d '\n' | sed 's/"[[:space:]]*"//g'; echo
echo "TXT   _dmarc        v=DMARC1; p=reject; rua=mailto:postmaster@${DOMAIN}; adkim=s; aspf=s"
echo "======================================================"
echo "Lightsail 방화벽(네트워킹)에서 열 포트: 25, 587, 993 (TCP). 80·443 은 이미 열려 있음"
echo
echo "메일 앱 설정:  IMAP ${MAILHOST} 993 SSL  /  SMTP ${MAILHOST} 587 STARTTLS  /  계정 ${MAILBOX}"
echo "웹메일:        https://${MAILHOST}"
echo "확인:          sudo opendkim-testkey -d ${DOMAIN} -s ${SELECTOR} -vvv ;  venv/bin/python manage.py send_test_mail 주소"
