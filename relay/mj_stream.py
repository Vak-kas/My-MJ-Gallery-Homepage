#!/usr/bin/env python3
"""MJ Gallery 스트림 보내기/받기 도구 (pyzmq 만 필요: pip install pyzmq).

보내기 (방 화면의 "보내는 주소" = IN 포트)
  # HackRF 실시간 캡처를 바로 보내기 (hackrf_transfer 는 sc8 형식)
  hackrf_transfer -r - -s 2e6 -f 433.92e6 | python mj_stream.py send tcp://smjgallery.kr:5550 --stdin
  # 녹음해 둔 IQ 파일을 실제 속도로 재생하며 보내기
  python mj_stream.py send tcp://smjgallery.kr:5550 --input cap.fc32 --sample-rate 2e6 --format fc32
  # 파일 방으로 파일 전송 (받는 쪽을 먼저 실행해 두세요)
  python mj_stream.py send tcp://smjgallery.kr:5552 --input report.pdf --file

받기 (방 화면의 "받는 주소" = OUT 포트)
  python mj_stream.py recv tcp://smjgallery.kr:5551 --output live.iq          # IQ/일반 (SUB)
  python mj_stream.py recv tcp://smjgallery.kr:5553 --output downloads/ --file # 파일 (PULL)
"""

import argparse
import hashlib
import json
import os
import sys
import time

import zmq

FILE_HEADER = b"MJF1"
FILE_END = b"MJF1-END"
BYTES_PER_SAMPLE = {"fc32": 8, "sc16": 4, "sc8": 2}


def human(n):
	for unit in ("B", "KB", "MB", "GB", "TB"):
		if n < 1024 or unit == "TB":
			return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
		n /= 1024
	return f"{n}"


class Meter:
	"""1초마다 처리량을 stderr 로 출력."""

	def __init__(self, label):
		self.label = label
		self.total = 0
		self.start = self.last = time.monotonic()
		self.last_total = 0

	def add(self, n):
		self.total += n
		now = time.monotonic()
		if now - self.last >= 1:
			rate = (self.total - self.last_total) / (now - self.last)
			print(f"\r{self.label} {human(self.total)}  {rate * 8 / 1e6:.2f} Mbps   ", end="", file=sys.stderr, flush=True)
			self.last, self.last_total = now, self.total

	def done(self):
		elapsed = max(1e-6, time.monotonic() - self.start)
		print(f"\r{self.label} 완료: {human(self.total)} / {elapsed:.1f}s ({self.total * 8 / elapsed / 1e6:.2f} Mbps)   ", file=sys.stderr)


def send(args):
	ctx = zmq.Context()
	sock = ctx.socket(zmq.PUSH)
	sock.sndhwm = 64
	sock.connect(args.address)

	if args.stdin:
		source, name, size = sys.stdin.buffer, "stdin", None
	else:
		source = open(args.input, "rb")
		name, size = os.path.basename(args.input), os.path.getsize(args.input)

	# 녹음 파일을 실제 속도로 재생: 샘플레이트 × 샘플당 바이트
	rate = args.rate_bps
	if args.sample_rate:
		rate = args.sample_rate * BYTES_PER_SAMPLE[args.format]

	meter = Meter("보냄")
	digest = hashlib.sha256()
	if args.file:
		sock.send_multipart([FILE_HEADER, json.dumps({"name": name, "size": size}).encode()])
	started = time.monotonic()
	try:
		while True:
			chunk = source.read(args.chunk)
			if not chunk:
				if args.loop and not args.stdin and not args.file:
					source.seek(0)
					continue
				break
			sock.send(chunk)
			digest.update(chunk)
			meter.add(len(chunk))
			if rate:
				ahead = meter.total / rate - (time.monotonic() - started)
				if ahead > 0:
					time.sleep(ahead)
	except KeyboardInterrupt:
		pass
	finally:
		if args.file:
			sock.send_multipart([FILE_END, json.dumps({"size": meter.total, "sha256": digest.hexdigest()}).encode()])
		meter.done()
		print("남은 데이터를 보내는 중… (Ctrl+C 로 강제 종료)", file=sys.stderr)
		sock.close()  # linger 기본값: 큐에 남은 메시지를 다 보낼 때까지 기다림
		ctx.term()


def recv(args):
	ctx = zmq.Context()
	sock = ctx.socket(zmq.PULL if args.file else zmq.SUB)
	if not args.file:
		sock.setsockopt(zmq.SUBSCRIBE, b"")
	sock.rcvhwm = 1000
	sock.connect(args.address)
	print(f"{args.address} 에서 기다리는 중… (Ctrl+C 로 종료)", file=sys.stderr)

	meter = Meter("받음")
	out = None
	digest = hashlib.sha256()
	try:
		while True:
			frames = sock.recv_multipart()
			if args.file and frames[0] == FILE_HEADER:
				info = json.loads(frames[1].decode())
				path = args.output
				if os.path.isdir(path):
					path = os.path.join(path, os.path.basename(info.get("name") or "received.bin"))
				out = open(path, "wb")
				print(f"\n파일 받기 시작: {path} ({human(info['size']) if info.get('size') else '크기 모름'})", file=sys.stderr)
				continue
			if args.file and frames[0] == FILE_END:
				info = json.loads(frames[1].decode())
				ok = info.get("sha256") == digest.hexdigest()
				meter.done()
				print("무결성 확인: " + ("일치 ✅" if ok else "불일치 ❌ (일부 손실)"), file=sys.stderr)
				break
			if out is None:
				out = open(args.output if not os.path.isdir(args.output) else os.path.join(args.output, "stream.bin"), "wb")
			# GNU Radio pass_tags 를 켜면 [태그, 샘플] 멀티파트 → 마지막 프레임이 샘플
			data = frames[-1] if args.samples_only else b"".join(frames)
			out.write(data)
			digest.update(data)
			meter.add(len(data))
	except KeyboardInterrupt:
		meter.done()
	finally:
		if out:
			out.close()
		sock.close(0)
		ctx.term()


def main():
	parser = argparse.ArgumentParser(description="MJ Gallery 스트림 보내기/받기")
	sub = parser.add_subparsers(dest="cmd", required=True)

	p_send = sub.add_parser("send", help="데이터 보내기 (방의 IN 주소)")
	p_send.add_argument("address", help="예: tcp://smjgallery.kr:5550")
	src = p_send.add_mutually_exclusive_group(required=True)
	src.add_argument("--input", help="보낼 파일")
	src.add_argument("--stdin", action="store_true", help="표준입력으로 받은 데이터를 보냄 (hackrf_transfer -r - | ...)")
	p_send.add_argument("--file", action="store_true", help="파일 방으로 보냄 (이름·크기·무결성 정보 포함)")
	p_send.add_argument("--chunk", type=int, default=64 * 1024, help="한 메시지 크기 (기본 64KB)")
	p_send.add_argument("--rate-bps", type=float, help="초당 바이트 상한")
	p_send.add_argument("--sample-rate", type=float, help="IQ 파일을 이 샘플레이트로 실시간 재생")
	p_send.add_argument("--format", choices=sorted(BYTES_PER_SAMPLE), default="fc32", help="IQ 형식 (기본 fc32)")
	p_send.add_argument("--loop", action="store_true", help="파일을 끝까지 보내면 처음부터 반복")
	p_send.set_defaults(func=send)

	p_recv = sub.add_parser("recv", help="데이터 받기 (방의 OUT 주소)")
	p_recv.add_argument("address", help="예: tcp://smjgallery.kr:5551")
	p_recv.add_argument("--output", required=True, help="저장할 파일 (파일 방이면 폴더도 가능)")
	p_recv.add_argument("--file", action="store_true", help="파일 방에서 받기")
	p_recv.add_argument("--samples-only", action="store_true", help="멀티파트면 마지막 프레임(샘플)만 저장")
	p_recv.set_defaults(func=recv)

	args = parser.parse_args()
	args.func(args)


if __name__ == "__main__":
	main()
