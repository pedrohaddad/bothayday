"""Controle do emulador Android via ADB (toques, arrastos, screenshots, apps)."""

import os
import re
import shutil
import subprocess
import threading

import cv2
import numpy as np

from logger_setup import get_logger

log = get_logger()

# Evita abrir uma janela de console para cada comando adb no Windows.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Endereços ADB padrão dos emuladores mais comuns.
KNOWN_EMULATOR_ADDRESSES = (
    # MEmu: 21503 para a 1ª instância, +10 para cada instância seguinte
    [f"127.0.0.1:{21503 + 10 * i}" for i in range(6)]
    # MuMu Player 12: 16384 para a 1ª instância, +32 para cada seguinte
    + [f"127.0.0.1:{16384 + 32 * i}" for i in range(4)]
    # MuMu Player 6 / MuMu X
    + ["127.0.0.1:7555"]
    # Genéricos (BlueStacks/LDPlayer/Nox)
    + ["127.0.0.1:5555", "127.0.0.1:5557", "127.0.0.1:62001"]
)

_DEVICE_LOST_HINTS = ("not found", "offline", "no devices", "unauthorized",
                      "closed", "disconnected", "cannot connect", "no emulators")


class ADBError(Exception):
    """Falha ao executar um comando ADB."""


class DeviceLost(ADBError):
    """Dispositivo desconectado/offline."""


class ADBInterrupted(ADBError):
    """Comando interrompido pelo botão PARAR / tecla de emergência."""


class ADBController:
    def __init__(self, adb_path="", device="", timeout=20.0, stop_event=None):
        self.adb_path = adb_path
        self.device = device
        self.timeout = float(timeout)
        self.stop_event = stop_event
        self._procs = set()
        self._lock = threading.Lock()
        self._motionevent = None

    # ------------------------------------------------------------------ base
    def resolve_adb(self):
        p = (self.adb_path or "").strip().strip('"')
        if p:
            if os.path.isdir(p):
                p = os.path.join(p, "adb.exe" if os.name == "nt" else "adb")
            if os.path.isfile(p):
                return p
            raise ADBError(f"adb não encontrado em: {p}")
        found = shutil.which("adb")
        if found:
            return found
        raise ADBError("Caminho do adb.exe não configurado (aba Conexão).")

    def _stopped(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def _run(self, args, timeout=None, use_device=True, binary=False, check=True,
             ignore_stop=False):
        if not ignore_stop and self._stopped():
            raise ADBInterrupted("Parada solicitada")
        cmd = [self.resolve_adb()]
        if use_device:
            if not self.device:
                raise DeviceLost("Nenhum dispositivo ADB selecionado.")
            cmd += ["-s", self.device]
        cmd += [str(a) for a in args]
        timeout = float(timeout or self.timeout)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            raise ADBError(f"Não foi possível executar o adb: {exc}") from exc
        with self._lock:
            self._procs.add(proc)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            raise ADBError(f"Tempo esgotado ({timeout:.0f}s) em: adb {' '.join(map(str, args))[:80]}")
        finally:
            with self._lock:
                self._procs.discard(proc)
        if not ignore_stop and self._stopped():
            raise ADBInterrupted("Parada solicitada")
        err_text = err.decode("utf-8", errors="replace").strip()
        low = err_text.lower()
        if use_device and err_text.startswith("error:") and any(h in low for h in _DEVICE_LOST_HINTS):
            raise DeviceLost(f"Dispositivo {self.device} indisponível: {err_text}")
        if check and proc.returncode != 0:
            msg = err_text or out.decode("utf-8", errors="replace").strip()
            if any(h in msg.lower() for h in _DEVICE_LOST_HINTS) and use_device:
                raise DeviceLost(f"Dispositivo {self.device} indisponível: {msg}")
            raise ADBError(f"adb {' '.join(map(str, args))[:60]} falhou: {msg or proc.returncode}")
        return out if binary else out.decode("utf-8", errors="replace")

    def kill_all(self):
        """Mata imediatamente qualquer comando adb em andamento (parada de emergência)."""
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass

    # ------------------------------------------------------------- servidor
    def version(self):
        out = self._run(["version"], use_device=False, timeout=15)
        return out.strip().splitlines()[0] if out.strip() else "desconhecida"

    def start_server(self):
        self._run(["start-server"], use_device=False, timeout=30, check=False)

    def list_devices(self):
        """Retorna [{'serial', 'state', 'desc'}] de `adb devices -l`."""
        out = self._run(["devices", "-l"], use_device=False, timeout=15)
        devices = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append({"serial": parts[0], "state": parts[1],
                                "desc": " ".join(parts[2:])})
        return devices

    def online_devices(self):
        return [d["serial"] for d in self.list_devices() if d["state"] == "device"]

    def connect(self, address):
        out = self._run(["connect", address], use_device=False, timeout=12, check=False)
        low = out.lower()
        ok = ("connected to" in low) and not any(w in low for w in ("cannot", "failed", "unable"))
        return ok, out.strip()

    def scan_emulators(self, addresses=None):
        """Tenta `adb connect` nos endereços conhecidos; retorna os que conectaram."""
        found = []
        for addr in addresses or KNOWN_EMULATOR_ADDRESSES:
            if self._stopped():
                break
            try:
                ok, _ = self.connect(addr)
            except ADBError:
                ok = False
            if ok:
                found.append(addr)
        return found

    # ------------------------------------------------------------ dispositivo
    def get_state(self):
        return self._run(["get-state"], timeout=10, check=False).strip()

    def is_online(self):
        try:
            return self.get_state() == "device"
        except ADBInterrupted:
            raise
        except ADBError:
            return False

    def shell(self, command, timeout=None, check=True, ignore_stop=False):
        return self._run(["shell", command], timeout=timeout, check=check, ignore_stop=ignore_stop)

    def boot_completed(self):
        return self.shell("getprop sys.boot_completed", timeout=10, check=False).strip() == "1"

    def screen_size(self):
        out = self.shell("wm size", timeout=10, check=False)
        m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise ADBError(f"Não foi possível ler a resolução: {out.strip()}")
        return int(m.group(1)), int(m.group(2))

    # --------------------------------------------------------------- entrada
    def tap(self, x, y, hold_ms=0):
        """Toque. Com hold_ms > 0 o dedo fica pressionado esse tempo (swipe parado no lugar):
        alguns jogos ignoram o `input tap` instantâneo quando o emulador está com FPS baixo."""
        if hold_ms and hold_ms > 0:
            self.shell(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(hold_ms)}")
        else:
            self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
                   timeout=self.timeout + duration_ms / 1000.0)

    def keyevent(self, code):
        self.shell(f"input keyevent {int(code)}")

    def supports_motionevent(self):
        """`input motionevent` permite arrastar por vários pontos sem soltar o dedo."""
        if self._motionevent is None:
            try:
                out = self.shell("input", check=False, timeout=10)
                self._motionevent = "motionevent" in out.lower()
            except ADBInterrupted:
                raise
            except ADBError:
                self._motionevent = False
            log.debug("Suporte a 'input motionevent': %s", self._motionevent)
        return self._motionevent

    @staticmethod
    def interpolate(points, step_px=40):
        path = [tuple(map(int, points[0]))]
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            dist = max(abs(x2 - x1), abs(y2 - y1))
            n = max(1, int(dist // max(1, step_px)))
            for i in range(1, n + 1):
                path.append((int(x1 + (x2 - x1) * i / n), int(y1 + (y2 - y1) * i / n)))
        return path

    def drag_path(self, points, hold_s=0.25, step_px=40):
        """Pressiona no 1º ponto, arrasta passando por todos e solta no último."""
        if len(points) < 2:
            raise ValueError("drag_path precisa de pelo menos 2 pontos")
        path = self.interpolate(points, step_px)
        x0, y0 = path[0]
        cmds = [f"input motionevent DOWN {x0} {y0}", f"sleep {hold_s:.2f}"]
        for x, y in path[1:]:
            cmds.append(f"input motionevent MOVE {x} {y}")
        xe, ye = path[-1]
        cmds += ["sleep 0.15", f"input motionevent UP {xe} {ye}"]
        timeout = self.timeout + len(path) * 0.6 + hold_s
        self.shell(" ; ".join(cmds), timeout=timeout)
        return path[-1]

    def touch_up(self, x, y):
        """Solta um toque pendente (usado se o bot for parado no meio de um arrasto)."""
        try:
            self.shell(f"input motionevent UP {int(x)} {int(y)}", check=False,
                       timeout=8, ignore_stop=True)
        except Exception:
            pass

    # ------------------------------------------------------------ screenshot
    def screencap(self):
        """Captura a tela e retorna uma imagem BGR (numpy)."""
        data = self._run(["exec-out", "screencap", "-p"], binary=True, timeout=self.timeout)
        img = _decode_png(data)
        if img is None:
            # adb antigo: exec-out indisponível ou quebras de linha convertidas.
            data = self._run(["shell", "screencap", "-p"], binary=True, timeout=self.timeout)
            img = _decode_png(data)
            if img is None:
                img = _decode_png(data.replace(b"\r\r\n", b"\n").replace(b"\r\n", b"\n"))
        if img is None:
            if not data:
                raise DeviceLost("Screenshot vazio: o emulador pode ter desconectado.")
            raise ADBError("Falha ao decodificar o screenshot do emulador.")
        return img

    # ------------------------------------------------------------------ apps
    def foreground_package(self):
        out = self.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'",
                         check=False, timeout=15)
        for line in out.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                m = re.search(r"\s([A-Za-z0-9_.]+)/", line)
                if m:
                    return m.group(1)
        return ""

    def is_package_installed(self, package):
        out = self.shell(f"pm list packages {package}", check=False, timeout=20)
        return f"package:{package}" in out.split()

    def is_app_running(self, package):
        out = self.shell(f"pidof {package}", check=False, timeout=10).strip()
        if out and out.split()[0].isdigit():
            return True
        out = self.shell(f"ps -A | grep {package} || ps | grep {package}", check=False, timeout=10)
        return package in out

    def start_app(self, package):
        self.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1",
                   check=False, timeout=30)

    def stop_app(self, package):
        self.shell(f"am force-stop {package}", check=False, timeout=15)


def _decode_png(data):
    if not data or len(data) < 100:
        return None
    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img
