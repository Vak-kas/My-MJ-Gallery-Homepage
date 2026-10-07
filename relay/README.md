# mj-relay — 실시간 데이터 스트림 중계

HackRF 등으로 캡처한 IQ 데이터(GNU Radio ZMQ)나 파일을 서버의 "방"을 거쳐 실시간으로 전달합니다.
웹 화면: `https://smjgallery.kr/tools/stream/` (방 만들기는 관리자만, 방 화면은 토큰 링크로 공유)

```
[A] HackRF → GNU Radio ─ ZMQ PUSH Sink (Bind: No) ──▶ tcp://smjgallery.kr:IN
                                                       mj-relay (방마다 PULL → PUB/PUSH)
[B] GNU Radio ─ ZMQ SUB Source (Bind: No) ◀────────── tcp://smjgallery.kr:OUT
[웹] 방 화면 ◀── wss://smjgallery.kr/relay/ws/<방>?token=…  (처리량·스펙트럼 미리보기)
```

## 방 종류
| 종류 | OUT 소켓 | 받는 쪽 | 특징 |
|---|---|---|---|
| IQ 실시간 | PUB | ZMQ **SUB** Source | 여러 명 수신, 느리면 버림, 웹 스펙트럼·워터폴 |
| 일반 바이트 | PUB | ZMQ **SUB** Source | 아무 데이터 실시간 |
| 파일 | PUSH | ZMQ **PULL** Source / CLI | 손실 없음, 받는 쪽을 먼저 실행 |

IQ 형식: `fc32`(GNU Radio complex, 8B/샘플), `sc8`(hackrf_transfer int8, 2B), `sc16`(int16, 4B).

## CLI (`mj_stream.py`, `pip install pyzmq`)
```bash
# 보내기
hackrf_transfer -r - -s 2e6 -f 433.92e6 | python mj_stream.py send tcp://smjgallery.kr:5550 --stdin
python mj_stream.py send tcp://smjgallery.kr:5550 --input cap.fc32 --sample-rate 2e6 --format fc32
python mj_stream.py send tcp://smjgallery.kr:5552 --input report.pdf --file

# 받기
python mj_stream.py recv tcp://smjgallery.kr:5551 --output live.iq
python mj_stream.py recv tcp://smjgallery.kr:5553 --output . --file
```

## 보안·제한
- 방마다 **보내는 쪽 IP 허용 목록**(ZMQ ZAP) — GNU Radio ZMQ 블록은 암호화(CURVE)를 지원하지 않으므로 IP 제한을 권장
- 유효 시간(기본 1시간·최대 6시간), 속도 상한(기본 16MB/s), 총량 상한(기본 20GB), 동시 방 5개
- 제어 API(`/rooms`)는 127.0.0.1 + `RELAY_API_KEY` 로만 접근, nginx 는 `/relay/ws/` 만 프록시
- 데몬을 재시작하면(배포 포함) 열린 방은 모두 닫힘

## 서버 설치 (1회)
1. **Lightsail 콘솔 → 인스턴스 → 네트워킹 → IPv4 방화벽**: 사용자 지정 TCP `5550-5599` 추가
2. 배포 후 서버에서: `cd /home/ubuntu/projects/smjgallery && sudo bash relay/deploy/install.sh`
   - `.env` 에 `RELAY_API_KEY` 생성, 의존성 설치, `mj-relay` systemd 서비스 등록,
     nginx 에 WebSocket 프록시 include(백업 생성 후 `nginx -t` 검사), `deploy.sh` 에 재시작 줄 추가
3. 확인: `systemctl status mj-relay`, `curl -s 127.0.0.1:8090/health`

## 설정 (`.env`)
| 키 | 기본값 | 설명 |
|---|---|---|
| `RELAY_API_KEY` | (필수) | Django ↔ 데몬 공유 비밀키 |
| `RELAY_PORT_MIN` / `RELAY_PORT_MAX` | 5550 / 5599 | 방에 배정할 포트 범위 (방화벽과 같게) |
| `RELAY_MAX_ROOMS` | 5 | 동시 방 개수 |
| `RELAY_PUBLIC_HOST` | smjgallery.kr | 화면에 보여줄 접속 주소 |

## 테스트
```bash
venv/bin/python -m unittest discover -s relay/tests -t .
venv/bin/python manage.py test tools
```
