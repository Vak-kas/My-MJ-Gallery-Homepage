"""서버 자원 읽기 (Linux /proc). 맥 등에서는 가능한 값만 돌려줌."""

import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

from django.conf import settings

SERVICES = ["gunicorn", "nginx", "mj-relay", "coturn"]


def _read(path):
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def boot_id():
    return _read("/proc/sys/kernel/random/boot_id").strip() or "unknown"


def uptime_seconds():
    raw = _read("/proc/uptime").split()
    return float(raw[0]) if raw else None


def memory():
    info = {}
    for line in _read("/proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        if rest.strip():
            info[key] = int(rest.split()[0]) * 1024
    if not info:
        return None
    total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
    swap_total, swap_free = info.get("SwapTotal", 0), info.get("SwapFree", 0)
    return {"total": total, "used": total - avail, "pct": round((total - avail) / total * 100) if total else 0,
            "swap_total": swap_total, "swap_used": swap_total - swap_free,
            "swap_pct": round((swap_total - swap_free) / swap_total * 100) if swap_total else 0}


def network_counters():
    """기본 인터페이스(lo 제외) 누적 수신·송신 바이트."""
    rx = tx = 0
    for line in _read("/proc/net/dev").splitlines()[2:]:
        name, _, data = line.partition(":")
        name = name.strip()
        if not data or name == "lo" or name.startswith(("docker", "veth", "br-")):
            continue
        fields = data.split()
        rx += int(fields[0])
        tx += int(fields[8])
    return (rx, tx) if (rx or tx) else None


def cpu_percent(sample=0.3):
    def snap():
        parts = _read("/proc/stat").splitlines()[0].split()[1:] if _read("/proc/stat") else []
        nums = [int(x) for x in parts]
        return (nums[3] + nums[4], sum(nums)) if nums else None
    a = snap()
    if not a:
        return None
    time.sleep(sample)
    b = snap()
    idle, total = b[0] - a[0], b[1] - a[1]
    return round((1 - idle / total) * 100) if total else 0


def dir_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def service_states():
    if not shutil.which("systemctl"):
        return []
    states = []
    for name in SERVICES:
        try:
            out = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            out = "unknown"
        states.append({"name": name, "state": out or "unknown"})
    return states


def snapshot():
    disk = shutil.disk_usage("/")
    load = os.getloadavg() if hasattr(os, "getloadavg") else None
    base = Path(settings.BASE_DIR)
    storage = []
    for label, path in (("업로드 (media)", settings.MEDIA_ROOT), ("비공개 파일 (맡겨두기·클립보드)", getattr(settings, "PRIVATE_MEDIA_ROOT", base / "private_media")),
                        ("캐시", base / ".django_cache")):
        if path and os.path.isdir(path):
            storage.append({"label": label, "bytes": dir_size(path)})
    db = settings.DATABASES["default"]
    if db["ENGINE"].endswith("sqlite3") and os.path.exists(db["NAME"]):
        storage.append({"label": "데이터베이스 (SQLite)", "bytes": os.path.getsize(db["NAME"])})
    up = uptime_seconds()
    up_text = ""
    if up:
        days, rest = divmod(int(up), 86400)
        up_text = (f"{days}일 " if days else "") + f"{rest // 3600}시간 {rest % 3600 // 60}분"
    return {
        "uptime_text": up_text,
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cores": os.cpu_count() or 1,
        "uptime": up,
        "load": [round(x, 2) for x in load] if load else None,
        "cpu": cpu_percent(),
        "memory": memory(),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free, "pct": round(disk.used / disk.total * 100)},
        "storage": storage,
        "services": service_states(),
        "net": network_counters(),
        "linux": bool(_read("/proc/meminfo")),
    }
