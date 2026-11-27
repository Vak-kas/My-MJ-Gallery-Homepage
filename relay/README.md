# mj-relay — 데이터 전송 중계 (파일 · 실시간 스트리밍 · GNU Radio ZMQ)

HackRF 등으로 캡처한 IQ 데이터(GNU Radio ZMQ)나 파일을 서버의 "방"을 거쳐 실시간으로 전달합니다.
웹 화면: `https://smjgallery.kr/tools/stream/` (방 만들기는 관리자만, 방 화면은 토큰 링크로 공유)

```
[A] HackRF → GNU Radio ─ ZMQ PUSH Sink (Bind: No) ──▶ tcp://smjgallery.kr:IN
                                                       mj-relay (방마다 PULL → PUB/PUSH)
[B] GNU Radio ─ ZMQ SUB Source (Bind: No) ◀────────── tcp://smjgallery.kr:OUT
[웹] 방 화면 ◀── wss://smjgallery.kr/relay/ws/<방>?token=…  (처리량·스펙트럼 미리보기)
```

## 브라우저 파일 전송
- 파일 방에서 보내는 쪽 링크 페이지에 파일을 끌어놓으면, 받는 쪽 링크 페이지로 **서버 저장 없이** 바로 전달
  (`/relay/ws/<방>/send` → `/relay/ws/<방>/recv`, 1MB 조각, 조각마다 ack 로 받는 쪽 속도에 맞춤)
- 같은 방의 CLI·GNU Radio 수신자에게도 함께 전달되고, CLI 로 보낸 파일도 브라우저에서 받을 수 있음
- 받는 쪽은 Chrome·Edge 에서 저장 폴더를 고르면 디스크에 바로 저장, 아니면 다 받은 뒤 저장
- 받는 사람이 없으면 **맡겨두기**(`/tools/share/`, Django): 서버에 잠시 올려두고 링크로 다운로드, 유효시간 뒤 자동 삭제

## 방 종류
| 종류 | OUT 소켓 | 받는 쪽 | 특징 |
|---|---|---|---|
| IQ Data (GNU Radio) | PUB | ZMQ **SUB** Source | 여러 명 수신, 느리면 버림, 웹 스펙트럼·워터폴 |
| 일반 바이트 | PUB | ZMQ **SUB** Source | 아무 데이터 실시간 |
| Wireless Lab | 포트 없음 | 받는 주소(`wss://…/iq/recv`) | 주소 한 줄(WebSocket)로만 보내고 받음, 5곳까지 수신, 웹 스펙트럼·워터폴 |
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

## WebSocket 으로 I/Q 보내고 받기 (`iq-relay/1` · Wireless Lab)
Wireless Lab 끼리는 ZMQ 포트 없이 **WebSocket 한 줄**로 보내고 받는다. 방 만들기에서 **🛰 Wireless Lab** 을 고르면 포트를 열지 않는 IQ 방이 생긴다(제어 API 로는 `{"kind":"iq","zmq":false}`). 규격 전문은 Wireless Lab 저장소의 `docs/relay-protocol.md`.

```
보내는 쪽  wss://<사이트>/relay/ws/<방>/iq/send?token=<보내는 토큰>
받는 쪽    wss://<사이트>/relay/ws/<방>/iq/recv?token=<받는 토큰>
```

| | ZMQ 포트(IN/OUT) | WebSocket |
|---|---|---|
| 암호화 | 없음 | TLS(wss) |
| 접속 허용 | 링크를 열어 IP 등록 | 주소의 토큰 (IP 등록 필요 없음) |
| 방화벽 | 방마다 포트 2개 | 443 하나 (nginx 의 `/relay/ws/` 프록시 그대로) |
| 신호 정보 | 방을 만들 때 적은 값 | 보내는 쪽이 `hello`·`meta` 로 실어 보냄 → 방 설정(형식·샘플레이트·주파수)과 화면 눈금이 따라감 |
| 빠진 구간 | 알 수 없음 | `gap` 으로 알림 |

- **Wireless Lab 에서 쓰기**: Wireless Lab 방 화면의 보내는 주소 / 받는 주소를 복사해 Wireless Lab 의 중계 주소 칸에 붙여 넣는다. 방은 지금처럼 데이터 전송 화면에서만 만든다. 화면에 주소가 나오는 것은 Wireless Lab 방뿐이다.
- **보내는 쪽**(방마다 하나, 둘째는 409): 첫 글 메시지 `hello`(`proto:1`, `format`, `sample_rate_hz`, 선택 `center_hz` 등) → 서버가 `ready`(한도·`max_message` 1MB·받는 쪽 수) → 바이너리 = I/Q 샘플(길이는 샘플 크기의 배수). `meta`(바뀐 값만)·`gap`·`bye` 는 받는 쪽에 그대로. 1초마다 `stats`. `hello.probe:true` 면 `ready` 만 답하고 받는 쪽엔 알리지 않음(연결 확인용).
- **오류**(`{"type":"error","error":코드}` 뒤 닫음): `bad-hello`(5초 안에 hello 가 없거나 필드가 틀림) · `proto` · `too-fast`(샘플레이트×샘플 크기 > 방 속도 상한) · `misaligned` · `too-big` · `quota`(총량 한도 → 방도 닫힘). 방 속도 상한을 넘는 메시지는 버리고 `bytes_dropped` 에 더함.
- **받는 쪽**(방마다 5명, 넘으면 429): `ready`(`sending`) → 보내는 쪽이 있으면 지금의 `hello` → 샘플·`meta`·`gap`·`bye`. 받는 쪽마다 줄(샘플 메시지 64개)이 있어, 느린 받는 쪽은 **그 쪽 것만** 버리고 자리가 나면 `{"type":"gap","where":"relay","lost_bytes":…,"lost_samples":…}` 를 먼저 받는다. 보내는 쪽과 다른 받는 쪽은 기다리지 않는다. 방이 닫히면 `closed`.
- **포트가 있는 IQ Data 방에서도 같은 길이 열려 있다**(화면에는 주소를 안 보여 줌): WebSocket 으로 온 샘플은 ZMQ OUT(GNU Radio SUB)·웹 스펙트럼·통계에도 가고, ZMQ IN 으로 온 샘플(프레임의 마지막 조각, 1MB 넘으면 나눠서)은 WebSocket 받는 쪽에도 간다. 이때 `hello` 는 방 설정으로 서버가 지어 주고, ZMQ 보내는 쪽이 다 나가면 `bye`.
- 받은 I/Q 는 저장하지 않고 내용도 풀지 않는다. 유효 시간·속도·총량 한도는 방 그대로.

맞는지 확인 (Wireless Lab 저장소에서, 방의 두 주소를 넣음):
```bash
venv/bin/python tools/relay_probe.py check "<보내는 주소>" "<받는 주소>"
```

## 입장 (고정 IP 불필요)
- 방을 열면 **보내는 쪽 링크**와 **받는 쪽 링크**가 생김. 각자 GNU Radio 를 돌릴 컴퓨터(같은 인터넷 연결)에서 자기 링크를 열면
  그 네트워크의 공인 IP 가 역할별로 등록되고, **등록된 IP 만** 해당 포트에 접속 가능 (ZMQ ZAP)
- 링크 페이지를 열어 두면 30초마다 다시 등록 → 와이파이 이동 등으로 IP 가 바뀌어도 유지. 등록은 15분 유지
- GNU Radio 를 먼저 켜 둬도 됨: 입장 전 연결은 2초마다 끊고 재확인(ZAP 300 + handshake_ivl) → 입장하면 2초 안에 자동 연결
- 보내는 쪽·받는 쪽이 모두 연결되면 방 화면에 "연결 완료" 표시
- 링크 없이 항상 허용할 **고정 IP**(보내는 쪽)를 방 만들 때 적을 수도 있음

## 보안·제한
- GNU Radio ZMQ 블록은 암호화(CURVE)를 지원하지 않으므로 접속은 IP(링크 입장) 기준으로만 제한
- WebSocket I/Q 길(`/relay/ws/<방>/iq/…`)은 역할 토큰으로만 허용하고 TLS 로 감 — 토큰이 주소에 실리므로 링크를 아무 데나 붙이지 않기
- 유효 시간(기본 1시간·최대 6시간), 속도 상한(기본 16MB/s), 총량 상한(기본 20GB), 동시 방 5개
- 제어 API(`/rooms`)는 127.0.0.1 + `RELAY_API_KEY` 로만 접근, nginx 는 `/relay/ws/` 만 프록시
- 데몬을 재시작하면(배포 포함) 열린 방은 모두 닫힘

## 서버 설치 (1회)
1. **Lightsail 콘솔 → 인스턴스 → 네트워킹 → IPv4 방화벽**: 사용자 지정 TCP `5550-5599` 추가
2. 배포 후 서버에서: `cd /home/ubuntu/projects/smjgallery && sudo bash relay/deploy/install.sh`
   - `.env` 에 `RELAY_API_KEY` 생성, 의존성 설치, `mj-relay` systemd 서비스 등록,
     nginx 에 WebSocket 프록시 include(백업 생성 후 `nginx -t` 검사), `deploy.sh` 에 재시작 줄 추가, gunicorn 재시작
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

## 라이브 방송 (`relay/mj_live.py`)
`/tools/live/` — 방송 만들기는 로그인 회원(한도: 동시 1개·하루 3번·120분·시청자 5명, 관리자 360분·20명), 시청은 링크만 있으면 누구나.
```
[방송 브라우저] ══ WebRTC (영상·소리) ══▶ [시청자 브라우저]      직접 연결
             ╲                          ╱
              ══ TURN(coturn, :3478) ══        직접 연결이 막힌 네트워크(핫스팟 등)만 서버 중계
[양쪽] ── wss://smjgallery.kr/relay/ws/live/<방>?token= ── mj-relay   연결 정보(SDP/ICE)·채팅·시청자 목록
```
- 화면+소리(`getDisplayMedia`), 웹캠, 마이크를 따로 켜고 끔 → 시청자는 화면 위에 웹캠을 작은 창으로 봄
- 방송자가 시청자마다 연결을 하나씩 만듦(offer 는 항상 방송자) → 시청자 5~10명 규모용
- 제어 API: `POST/GET /live`, `GET/DELETE /live/<id>` (127.0.0.1 + `RELAY_API_KEY`)
- TURN 계정은 Django 가 방송마다 시간 제한 임시 계정으로 발급 (`TURN_SECRET`, coturn `use-auth-secret`)

### TURN 서버 설치 (1회)
1. 배포 후 서버에서: `cd /home/ubuntu/projects/smjgallery && sudo bash relay/deploy/install_turn.sh`
   - coturn 설치, `.env` 에 `TURN_SECRET` 생성, `/etc/turnserver.conf` 작성(사설망 중계 차단·속도 제한), gunicorn 재시작
2. **Lightsail 콘솔 → 네트워킹 → IPv4 방화벽**: 사용자 지정 `UDP 3478`, `TCP 3478`, `UDP 49160-49200` 추가
3. 확인: `systemctl status coturn`, 방송 화면의 시청자 목록에서 "서버 중계" 표시

## 실시간 게임 방 (`relay/mj_game.py`)

mj-relay 안에서 함께 도는 게임 방. 판은 서버가 들고 규칙(차례·빈 칸·승패)도 서버가 판단하고, 브라우저는 보여 주기만 한다.

- 제어 API (Django 가 호출): `POST /games` {kind, title, owner_id, owner, public} · `GET /games` · `GET /games/{id}` · `DELETE /games/{id}`
- WebSocket: `/relay/ws/game/{id}?token=<방 토큰>&pid=<브라우저 열쇠>&name=<닉네임>` (nginx 의 `/relay/ws/` 프록시 그대로)
- `pid` 가 같으면 새로고침·잠깐 끊겨도 자리를 돌려받음, 90초 안 돌아오면 자리 비움(대국 중이면 상대 승)
- 아무도 없이 30분 → 방 닫음, 방 최대 6시간·30개, 방마다 30명
- 게임 종류 = 규칙 클래스 하나, `LOGICS` 에 추가
  - `OmokLogic`: 15×15 자유룰, 무르기 부탁·기권·흑백 바꿔 다시
  - `HideSeekLogic`(숨바꼭질, `relay/mj_hideseek.py`): 술래·숨는 사람 위치는 상태 대신 `room.emit` 으로 바로(초당 십여 번), 서버가 집 범위·속도·쏘기(거리·방향·쿨타임)·체력·시간 판정, 자리 바꾸기(`swap` — 진짜 물건을 치우고 그 자리에, 판마다 2번·4 m 안, 치운 물건은 `removed` 로 알림), 맵 고르기(`MAPS` — 집·사무실·창고·학교·마트, 방장이 `settings.map` 으로, 바꾸면 `map` 을 모두에게 다시 보냄)·점수
  - `CatchLogic`(그림 맞추기): 1초 타이머(`tick`)로 고르기·그리기·정답 공개, 사람마다 다른 상태(제시어는 그리는 사람만), 그림 선은 `room.emit` 으로 바로 전달, 채팅 훅(`on_chat`)으로 정답 처리
- 규칙 클래스가 쓸 수 있는 훅: `on_join` · `on_leave(room, pid)` · `on_message` · `on_chat`(선택) · `tick`(선택) · `snapshot(room, pid)` · `seat_of`
