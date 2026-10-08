#!/bin/bash
# 화면 송출용 TURN 서버(coturn) 1회 설치 (서버에서 실행: sudo bash relay/deploy/install_turn.sh)
# 하는 일:
#   1) coturn 설치
#   2) .env 에 TURN_SECRET 이 없으면 무작위 값 추가
#   3) /etc/turnserver.conf 작성 (기존 파일은 백업) → coturn 켜기
#   4) gunicorn 재시작 (사이트가 TURN_SECRET 을 읽도록)
set -euo pipefail

PROJECT=/home/ubuntu/projects/smjgallery
REALM=smjgallery.kr

if [ "$(id -u)" -ne 0 ]; then
	echo "sudo 로 실행해 주세요: sudo bash relay/deploy/install_turn.sh" >&2
	exit 1
fi
cd "$PROJECT"

echo "== 1) coturn 설치"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q coturn >/dev/null
echo "설치됨: $(turnserver --version 2>/dev/null | head -1 || echo coturn)"

echo "== 2) TURN_SECRET"
if grep -q '^TURN_SECRET=' .env; then
	echo "이미 있음"
else
	echo "TURN_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
	echo "추가함"
fi
SECRET=$(grep '^TURN_SECRET=' .env | head -1 | cut -d= -f2- | tr -d '"'"'")

echo "== 3) /etc/turnserver.conf"
PRIVATE_IP=$(hostname -I | awk '{print $1}')
PUBLIC_IP=$(curl -s --max-time 5 https://checkip.amazonaws.com | tr -d '[:space:]')
if [ -z "$PUBLIC_IP" ]; then
	echo "공인 IP 를 알아내지 못했어요. 인터넷 연결을 확인해 주세요." >&2
	exit 1
fi
[ -f /etc/turnserver.conf ] && cp /etc/turnserver.conf "/etc/turnserver.conf.bak.$(date +%Y%m%d%H%M%S)"
sed -e "s|__REALM__|$REALM|" -e "s|__SECRET__|$SECRET|" -e "s|__PUBLIC_IP__|$PUBLIC_IP|" -e "s|__PRIVATE_IP__|$PRIVATE_IP|" \
	relay/deploy/turnserver.conf.template > /etc/turnserver.conf
chmod 640 /etc/turnserver.conf
chown root:turnserver /etc/turnserver.conf 2>/dev/null || true
mkdir -p /var/log/turnserver && chown turnserver:turnserver /var/log/turnserver 2>/dev/null || true
if [ -f /etc/default/coturn ]; then
	sed -i 's/^#\?TURNSERVER_ENABLED=.*/TURNSERVER_ENABLED=1/' /etc/default/coturn
fi
systemctl enable coturn >/dev/null
systemctl restart coturn
sleep 1
systemctl is-active coturn
echo "공인 IP $PUBLIC_IP / 사설 IP $PRIVATE_IP"

echo "== 4) 사이트 재시작 (.env 의 TURN_SECRET 을 다시 읽도록)"
systemctl restart gunicorn

echo
echo "완료."
echo "※ Lightsail 콘솔 → 인스턴스 → 네트워킹 → IPv4 방화벽에 아래 3개 규칙을 추가해야 외부에서 연결됩니다:"
echo "   - 사용자 지정 UDP 3478"
echo "   - 사용자 지정 TCP 3478"
echo "   - 사용자 지정 UDP 49160-49200"
