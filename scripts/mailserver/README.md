# smjgallery.kr 메일 서버

메일함은 하나 — **mjseo@smjgallery.kr** (사이트 회원과 무관). 사이트가 보내는 메일(가입 인증·비밀번호 재설정)도 이 서버로 나간다.
받기(25) · 보내기(25/587) · IMAP(993) · 웹메일(https://mail.smjgallery.kr) · DKIM · 스팸 점수(rspamd) · S3 백업.

## 순서 (서버·DNS·AWS 작업은 직접)

1. **AWS 에 25번 포트 제한 해제 + PTR 요청** (양식: [Request to Remove Email Sending Limitations](https://aws-portal.amazon.com/gp/aws/html-forms-controller/contactus/ec2-email-limit-rdns-request), 루트 계정) — Elastic IP `43.202.189.130`, Reverse DNS `mail.smjgallery.kr`. 받기만은 이것 없이도 되지만, 보내기는 승인돼야 함.
2. **DNS 에 `mail` A 레코드** (`43.202.189.130`) — 완료.
3. **Lightsail 네트워킹(방화벽)**: TCP 25, 587, 993 추가. (80·443 은 이미 열려 있음)
4. **서버에서 설치** (중간에 메일 비밀번호를 물어봄 — 사이트 비밀번호와 다른 걸로)
   ```bash
   cd /home/ubuntu/projects/smjgallery && git pull
   sudo bash scripts/mailserver/setup_mailserver.sh smjgallery.kr mjseo
   ```
   mail.smjgallery.kr 인증서를 certbot 이 새로 받고(80 포트로 확인), 끝에 DNS 값이 찍힌다.
5. **DNS 등록** (LETO 관리 화면)
   | 종류 | 이름 | 값 |
   |---|---|---|
   | MX | `@` | `10 mail.smjgallery.kr.` |
   | TXT | `@` | `v=spf1 ip4:43.202.189.130 -all` (지금 있는 `v=spf1 -all` 을 바꿈) |
   | TXT | `mj._domainkey` | 스크립트가 출력한 `v=DKIM1; k=rsa; p=...` |
   | TXT | `_dmarc` | `v=DMARC1; p=reject; rua=mailto:postmaster@smjgallery.kr; adkim=s; aspf=s` |
   MX 를 넣는 순간부터 메일이 서버로 오므로 4번 뒤에 넣는다.
6. **확인**
   ```bash
   sudo opendkim-testkey -d smjgallery.kr -s mj -vvv   # key OK
   ```
   폰·맥 메일 앱에 계정 추가: IMAP `mail.smjgallery.kr` 993 SSL / SMTP `mail.smjgallery.kr` 587 STARTTLS / 아이디 `mjseo@smjgallery.kr`.
   웹메일 https://mail.smjgallery.kr 로그인. Gmail 로 한 통 보내 "원본 보기"에서 SPF/DKIM/DMARC PASS 확인.
7. **사이트 연결 + 백업** — 서버 `.env` 에 추가 후 `sudo systemctl restart gunicorn`
   ```
   EMAIL_HOST=localhost
   EMAIL_PORT=25
   EMAIL_USE_TLS=False
   DEFAULT_FROM_EMAIL=MJ Gallery <noreply@smjgallery.kr>
   MAIL_BACKUP_DIR=/var/mail/vhosts
   ```
   ```bash
   venv/bin/python manage.py send_test_mail mjseo@smjgallery.kr
   ```

## 운영 메모
- 웹메일·메일 앱 로그인이 2초쯤 느리면 Dovecot 이 PAM(리눅스 계정)을 먼저 시도하는 것: `sudo sed -i 's/^!include auth-system.conf.ext/#!include auth-system.conf.ext/' /etc/dovecot/conf.d/10-auth.conf && sudo doveconf -n >/dev/null && sudo systemctl reload dovecot`
- 큐: `mailq` · 로그: `sudo journalctl -u postfix -n 50`, `-u dovecot`, `-u rspamd`
- 스팸 점수 6 이상은 `X-Spam: Yes` 헤더가 붙고 Junk 폴더로, 15 이상은 거절
- 메일함 경로 `/var/mail/vhosts/smjgallery.kr/mjseo` (Maildir) — S3 백업에 포함(`MAIL_BACKUP_DIR`)
- 비밀번호 바꾸기: `sudo doveadm pw -s SHA512-CRYPT` 로 해시 만들어 `/etc/dovecot/users` 의 값 교체 후 `sudo systemctl reload dovecot`
- 별칭(noreply·postmaster·abuse·admin·hostmaster)은 `/etc/postfix/valias` → `sudo postmap /etc/postfix/valias`
- 25번 해제가 거절되면 보내기만 Amazon SES relayhost(587)로: `postconf -e relayhost=[email-smtp.ap-northeast-2.amazonaws.com]:587` + SASL 자격
- `setup_postfix_dkim.sh` 는 보내기 전용(받는 메일함 없음) 버전
