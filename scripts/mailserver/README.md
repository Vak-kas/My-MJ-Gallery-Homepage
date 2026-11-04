# smjgallery.kr 보내기 전용 메일 서버

사이트가 보내는 메일(가입 인증·아이디 찾기·비밀번호 재설정)을 Gmail 같은 남의 계정이 아니라
**우리 서버(Postfix + DKIM)** 로 직접 보낸다. 받는 메일함은 만들지 않는다 (MX 없음).

## 순서 (서버·DNS·AWS 작업은 직접)

1. **AWS 에 요청 (필수, 하루 정도 걸림)** — Lightsail/EC2 는 기본으로 바깥 25번 포트를 막아 둠.
   AWS 콘솔 → Support → "Request to remove email sending limitations" 양식에
   고정 IP `43.202.189.130`, 역방향 DNS(PTR) `mail.smjgallery.kr`, 용도(회원 인증 메일, 하루 수십 통)를 적어 제출.
   승인되면 25번 포트가 열리고 PTR 이 잡힌다. (PTR 이 `ec2-…amazonaws.com` 그대로면 Gmail 이 스팸으로 보낼 수 있음)
2. **서버에서 설치**
   ```bash
   cd /home/ubuntu/projects/smjgallery && git pull
   sudo bash scripts/mailserver/setup_postfix_dkim.sh smjgallery.kr
   ```
   끝에 DNS 에 넣을 값 4개가 찍힌다.
3. **DNS 등록** (leto.kr 관리 화면, 지금 SPF 는 `v=spf1 -all` 이라 반드시 바꿔야 함)
   | 종류 | 이름 | 값 |
   |---|---|---|
   | TXT | `@` | `v=spf1 ip4:43.202.189.130 -all` |
   | TXT | `mj._domainkey` | 스크립트가 출력한 `v=DKIM1; k=rsa; p=...` |
   | TXT | `_dmarc` | `v=DMARC1; p=reject; rua=mailto:postmaster@smjgallery.kr; adkim=s; aspf=s` |
   | A | `mail` | `43.202.189.130` |
4. **확인**
   ```bash
   sudo opendkim-testkey -d smjgallery.kr -s mj -vvv      # "key OK" 가 나와야 함 (DNS 반영 뒤)
   ```
5. **Django 연결** — 서버 `.env` 에 추가 후 `sudo systemctl restart gunicorn`
   ```
   EMAIL_HOST=localhost
   EMAIL_PORT=25
   EMAIL_USE_TLS=False
   DEFAULT_FROM_EMAIL=MJ Gallery <noreply@smjgallery.kr>
   ```
   ```bash
   venv/bin/python manage.py send_test_mail 내주소@gmail.com
   ```
   Gmail 에서 받은 메일 → "원본 보기" 에 `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS` 가 보이면 끝.

## 운영 메모
- 큐에 쌓인 메일: `mailq`, 로그: `sudo journalctl -u postfix -n 50`, DKIM 로그: `sudo journalctl -u opendkim -n 50`
- 바깥에서 25번으로 들어오는 연결은 받지 않음(`inet_interfaces = loopback-only`) → 열린 포트 늘지 않음
- 25번 포트 해제가 거절되면 대안: Amazon SES SMTP(587)를 relayhost 로 — 같은 DKIM/SPF 로 우리 도메인 그대로 보냄
