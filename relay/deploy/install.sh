#!/bin/bash
# mj-relay 1회 설치 스크립트 (서버에서 실행: sudo bash relay/deploy/install.sh)
# 하는 일:
#   1) .env 에 RELAY_API_KEY 가 없으면 무작위 값 추가
#   2) 파이썬 의존성 설치 (pyzmq, aiohttp)
#   3) systemd 서비스 등록·시작
#   4) nginx 사이트 설정에 WebSocket 프록시 include 추가 → 설정 검사 후 reload
#   5) deploy.sh 에 mj-relay 재시작 줄 추가 (배포 때 새 코드 반영)
set -euo pipefail

PROJECT=/home/ubuntu/projects/smjgallery
NGINX_SITE=/etc/nginx/sites-available/smjgallery
INCLUDE_LINE="    include $PROJECT/relay/deploy/nginx-relay.conf;"

if [ "$(id -u)" -ne 0 ]; then
	echo "sudo 로 실행해 주세요: sudo bash relay/deploy/install.sh" >&2
	exit 1
fi
cd "$PROJECT"

echo "== 1) RELAY_API_KEY"
if grep -q '^RELAY_API_KEY=' .env; then
	echo "이미 있음"
else
	echo "RELAY_API_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
	echo "추가함"
fi

echo "== 2) 의존성"
sudo -u ubuntu "$PROJECT/venv/bin/pip" install -q -r requirements.txt

echo "== 3) systemd 서비스"
cp relay/deploy/mj-relay.service /etc/systemd/system/mj-relay.service
systemctl daemon-reload
systemctl enable --now mj-relay
systemctl restart mj-relay
sleep 1
systemctl is-active mj-relay

echo "== 4) nginx WebSocket 프록시"
if grep -qF "nginx-relay.conf" "$NGINX_SITE"; then
	echo "이미 있음"
else
	cp "$NGINX_SITE" "$NGINX_SITE.bak.$(date +%Y%m%d%H%M%S)"
	# HTTPS server 블록의 'location / {' 바로 앞에 include 추가
	awk -v line="$INCLUDE_LINE" '
		!done && /^[[:space:]]*location \/ \{/ { print line; print ""; done=1 }
		{ print }
	' "$NGINX_SITE" > "$NGINX_SITE.new"
	mv "$NGINX_SITE.new" "$NGINX_SITE"
	echo "추가함 (백업: $NGINX_SITE.bak.*)"
fi
nginx -t
systemctl reload nginx

echo "== 5) deploy.sh"
if [ -f deploy.sh ] && ! grep -q "mj-relay" deploy.sh; then
	cp deploy.sh "deploy.sh.bak.$(date +%Y%m%d%H%M%S)"
	echo 'sudo systemctl restart mj-relay' >> deploy.sh
	echo "재시작 줄 추가함"
else
	echo "변경 없음"
fi

echo
echo "완료. health: $(curl -s http://127.0.0.1:8090/health)"
echo "※ Lightsail 콘솔 → 네트워킹 → IPv4 방화벽에서 TCP 5550-5599 를 열어야 외부에서 접속됩니다."
