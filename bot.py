"""Lógica do bot de Hay Day: plantar, colher, vender, anunciar e coletar dinheiro."""

import collections
import os
import subprocess
import threading
import time

from adb_controller import ADBController, ADBError, ADBInterrupted, DeviceLost
from config import parse_resolution
from image_detector import DUPLICATE_ISO_DISTANCE, TemplateLibrary, build_detector, grid_dedupe, grid_spacing
from logger_setup import get_logger
from screen import Screen
from state_machine import BotStopped, FatalError, State, StateMachine, StepFailed

log = get_logger()

KEY_BACK = 4


class GameNotRunning(Exception):
    """O Hay Day não está em primeiro plano."""


class EmulatorFrozen(Exception):
    """A tela não muda há muito tempo."""


FIELD_KEYS = {"empty": "wheat_empty", "ready": "wheat_ready", "growing": "wheat_growing"}
FIELD_NAMES = {"empty": "vazia", "ready": "pronta", "growing": "crescendo"}
STUCK_TTL = 180  # s que um trigo que não respondeu fica fora da colheita antes de nova tentativa


class FieldScan:
    """Plantações vistas num screenshot: cada posição com UM estado + o que foi descartado e por quê."""

    def __init__(self):
        self.empty, self.ready, self.growing = [], [], []
        self.discarded = []  # [(Match, motivo)]

    @property
    def total(self):
        return len(self.empty) + len(self.ready) + len(self.growing)

    def state_at(self, target):
        for key in ("empty", "ready", "growing"):
            if any(target.iso_distance(m) < DUPLICATE_ISO_DISTANCE for m in getattr(self, key)):
                return key
        return None

    def nearest(self, key, target, max_iso=1.5):
        best = min(getattr(self, key), key=lambda m: m.iso_distance(target), default=None)
        return best if best is not None and best.iso_distance(target) < max_iso else None


class BotStats:
    FIELDS = ("fields_found", "fields_planted", "fields_harvested", "sold_qty", "listings",
              "ads", "collections", "coins_estimate", "cycles", "wheat_stock")

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with getattr(self, "_lock", threading.Lock()):
            for f in self.FIELDS:
                setattr(self, f, 0)
            self.started_at = None
            self.stopped_at = None
            self.last_action = "-"
            self.last_error = "-"
            self.state = State.IDLE.value

    def inc(self, key, n=1):
        with self._lock:
            setattr(self, key, getattr(self, key) + n)

    def set(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def runtime(self):
        if not self.started_at:
            return 0.0
        return (self.stopped_at or time.time()) - self.started_at

    def snapshot(self):
        with self._lock:
            data = {f: getattr(self, f) for f in self.FIELDS}
            data.update(last_action=self.last_action, last_error=self.last_error,
                        state=self.state, runtime=self.runtime())
        return data


class HayDayBot:
    STATUS_STOPPED = "stopped"
    STATUS_RUNNING = "running"
    STATUS_ERROR = "error"

    def __init__(self, config, templates_dir, screenshots_dir):
        self.cfg = dict(config)
        self.templates_dir = templates_dir
        self.screenshots_dir = screenshots_dir
        self.stop_event = threading.Event()
        self.adb = ADBController(self.cfg["adb_path"], self.cfg["device"],
                                 self.cfg["adb_timeout"], self.stop_event)
        self.library = TemplateLibrary(templates_dir)
        self.detector = build_detector(self.cfg, self.library, abort_check=self.stop_event.is_set)
        self.screen = Screen(self.adb, screenshots_dir)
        self.stats = BotStats()
        self.status = self.STATUS_STOPPED
        self.machine = None
        self._thread = None
        self._warned = set()
        self._tap_history = collections.defaultdict(collections.deque)
        self._pending_touch = None
        self._init_runtime_state()

    def _init_runtime_state(self):
        self.last_ad_time = 0.0
        self.last_collect_time = 0.0
        self.last_planted = 0
        self.last_plant_time = 0.0
        self.no_fields_count = 0
        self.recoveries = 0
        self.recover_failures = 0
        self.force_restart = False
        self.silo_full = False
        self.stuck = []  # [(Match, instante)] trigos que não responderam à colheita
        self.stats.set(wheat_stock=int(self.cfg["initial_wheat_stock"]))

    # ================================================================ ciclo de vida
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.is_running():
            return False
        self.stop_event.clear()
        self.stats.reset()
        self._init_runtime_state()
        self._warned.clear()
        self._tap_history.clear()
        self.status = self.STATUS_RUNNING
        self._thread = threading.Thread(target=self._run, name="HayDayBot", daemon=True)
        self._thread.start()
        return True

    def stop(self, reason="botão PARAR"):
        """Parada imediata: sinaliza a thread e mata comandos adb em andamento."""
        if not self.stop_event.is_set():
            log.info("PARADA solicitada (%s).", reason)
        self.stop_event.set()
        self.adb.kill_all()

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def _run(self):
        self.stats.set(started_at=time.time(), stopped_at=None)
        log.info("Bot iniciado.")
        handlers = {
            State.CONNECTING: self.st_connecting,
            State.OPEN_GAME: self.st_open_game,
            State.CHECK_FIELD: self.st_check_field,
            State.PLANT: self.st_plant,
            State.WAIT_GROWTH: self.st_wait_growth,
            State.HARVEST: self.st_harvest,
            State.SELL: self.st_sell,
            State.ADVERTISE: self.st_advertise,
            State.COLLECT_MONEY: self.st_collect_money,
            State.RECOVER: self.st_recover,
        }
        step = self.cfg["step_timeout"]
        timeouts = {
            State.CONNECTING: self.cfg["emulator_boot_timeout"] + 60,
            State.OPEN_GAME: self.cfg["open_game_timeout"] + 60,
            State.WAIT_GROWTH: self.cfg["max_wait_growth"] + 60,
            State.RECOVER: max(step, self.cfg["open_game_timeout"] + 60),
        }
        self.machine = StateMachine(
            handlers, State.CONNECTING, self.stop_event,
            safe_state=State.RECOVER, max_retries=self.cfg["max_retries"],
            default_timeout=step, timeouts=timeouts,
            retry_delay=max(1.0, self.cfg["check_interval"] / 2),
            redirect=self._redirect, on_failure=self._on_failure,
            on_transition=self._on_transition)
        final = State.ERROR
        try:
            final = self.machine.run()
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro inesperado no bot: %s", exc)
            self.stats.set(last_error=str(exc))
        finally:
            if self._pending_touch:
                self.adb.touch_up(*self._pending_touch)
                self._pending_touch = None
            self.stats.set(stopped_at=time.time(), state=final.value)
            self.status = self.STATUS_ERROR if final == State.ERROR else self.STATUS_STOPPED
            log.info("Bot finalizado (%s).", final.value)

    def _redirect(self, exc):
        if isinstance(exc, ADBInterrupted):
            return None
        if isinstance(exc, (DeviceLost, ADBError)):
            log.warning("Problema de conexão ADB: %s", exc)
            return State.CONNECTING
        if isinstance(exc, GameNotRunning):
            return State.OPEN_GAME
        if isinstance(exc, EmulatorFrozen):
            self.force_restart = True
            return State.RECOVER
        return None

    def _on_failure(self, state, exc, fatal=False):
        self.stats.set(last_error=f"{state.value}: {exc}")
        if isinstance(exc, (ADBInterrupted, BotStopped)):
            return
        if self.cfg["screenshot_on_error"] and not isinstance(exc, (DeviceLost,)):
            img = self.screen.last
            try:
                if not isinstance(exc, ADBError):
                    img = self.screen.capture()
            except Exception:  # noqa: BLE001
                pass
            try:
                path = self.screen.save(img, prefix=f"erro_{state.value}", subdir="errors")
                if path:
                    log.info("Screenshot do erro salvo: %s", path)
            except Exception as save_exc:  # noqa: BLE001
                log.debug("Não salvou screenshot de erro: %s", save_exc)

    def _on_transition(self, old, new):
        self.stats.set(state=new.value)
        log.debug("Estado %s -> %s", old.value, new.value)

    # ================================================================ utilitários
    def _check(self):
        if self.stop_event.is_set():
            raise BotStopped()
        if self.machine is not None and self.machine.context is not None:
            self.machine.context.check_deadline()

    def sleep(self, seconds):
        end = time.monotonic() + max(0.0, seconds)
        while True:
            self._check()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            self.stop_event.wait(min(remaining, 0.2))

    def pause(self, factor=1.0):
        self.sleep(self.cfg["action_delay"] * factor)

    def action(self, text):
        self.stats.set(last_action=text)
        log.info(text)

    def capture(self):
        self._check()
        img = self.screen.capture()
        frozen = self.screen.seconds_unchanged()
        if self.cfg["freeze_timeout"] > 0 and frozen > self.cfg["freeze_timeout"]:
            self.screen.reset_freeze()
            raise EmulatorFrozen(f"A tela não muda há {frozen:.0f}s (emulador travado?)")
        return img

    def has_template(self, category):
        if self.library.has(category):
            return True
        if category not in self._warned:
            self._warned.add(category)
            log.warning("Sem templates em templates/%s/ — recurso ignorado. "
                        "Veja o README para saber o que recortar.", category)
        return False

    def find(self, category, img=None, threshold=None, region=None):
        if not self.has_template(category):
            return None
        img = self.capture() if img is None else img
        return self.detector.find(img, category, threshold, region)

    def find_all(self, category, img=None, threshold=None):
        if not self.has_template(category):
            return []
        img = self.capture() if img is None else img
        return self.detector.find_all(img, category, threshold)

    def wait_for(self, category, timeout=5.0, interval=0.4):
        """Espera um elemento aparecer. Retorna o Match ou None (nunca toca em nada)."""
        if not self.has_template(category):
            return None
        end = time.monotonic() + timeout
        while True:
            m = self.find(category)
            if m or time.monotonic() >= end:
                return m
            self.sleep(interval)

    def wait_gone(self, category, timeout=5.0, interval=0.4):
        end = time.monotonic() + timeout
        while True:
            if self.find(category) is None:
                return True
            if time.monotonic() >= end:
                return False
            self.sleep(interval)

    def _guard_tap(self, x, y, label):
        """Impede tocar repetidamente no mesmo lugar sem resultado."""
        key = (int(x) // 15, int(y) // 15)
        now = time.monotonic()
        dq = self._tap_history[key]
        while dq and now - dq[0] > 60:
            dq.popleft()
        dq.append(now)
        if len(dq) > self.cfg["max_same_spot_taps"]:
            dq.clear()
            raise StepFailed(f"Proteção anti-loop: '{label}' tocado {self.cfg['max_same_spot_taps']}x "
                             f"no mesmo lugar em 60s sem resultado")

    def tap(self, x, y, label="", guard=True, delay_factor=1.0, hold_ms=None):
        self._check()
        if guard:
            self._guard_tap(x, y, label)
        hold = self.cfg["tap_hold_ms"] if hold_ms is None else hold_ms
        log.debug("Toque %s em (%d,%d)%s", label, x, y, f" segurando {hold} ms" if hold else "")
        if hold:
            self.adb.tap(x, y, hold)
        else:
            self.adb.tap(x, y)
        self.pause(delay_factor)

    def tap_confirmed(self, point, label, confirm, refresh=None, attempts=None, timeout=None):
        """Clique -> espera a resposta visual do jogo -> confirma.

        confirm(img) devolve algo verdadeiro quando o jogo respondeu (ex.: o menu apareceu).
        refresh() recalcula a posição do alvo num screenshot novo (ou None se ele sumiu).
        A 2ª tentativa usa a posição recalculada e um toque um pouco mais longo.
        Retorna o resultado de confirm() ou None se a ação não foi confirmada.
        """
        attempts = attempts or (1 + self.cfg["action_retries"])
        timeout = timeout or self.cfg["confirm_timeout"]
        for attempt in range(1, attempts + 1):
            x, y = int(point[0]), int(point[1])
            hold = self.cfg["tap_hold_ms"] if attempt == 1 else max(self.cfg["tap_hold_ms"],
                                                                   self.cfg["retry_tap_hold_ms"])
            log.info("Clique enviado: (%d, %d) — %s%s; aguardando confirmação...", x, y, label,
                     f" [tentativa {attempt}/{attempts}, toque de {hold} ms]" if attempt > 1 else "")
            t0 = time.monotonic()
            self.tap(x, y, label, delay_factor=0.3, hold_ms=hold)
            img = None
            while True:
                img = self.capture()
                result = confirm(img)
                if result:
                    log.info("Ação confirmada: %s (%.1fs)", label, time.monotonic() - t0)
                    return result
                if time.monotonic() - t0 >= timeout:
                    break
                self.sleep(0.3)
            last = attempt == attempts
            log.warning("Ação NÃO confirmada: %s — o jogo não respondeu em %.1fs%s", label, timeout,
                        "" if last else "; recalculando a posição e tentando de novo")
            if last:
                break
            if not self.is_farm(img):
                self.dismiss_popups(img)
            if refresh is not None:
                new = refresh()
                if new is None:
                    log.warning("O alvo de '%s' não está mais na tela; não vou tocar de novo.", label)
                    return None
                if abs(new[0] - x) + abs(new[1] - y) > 2:
                    log.info("Posição recalculada: (%d, %d) -> (%d, %d)", x, y, new[0], new[1])
                point = new
        return None

    def tap_match(self, m, label=None, guard=True, delay_factor=1.0):
        x, y = m.center
        self.tap(x, y, label or m.category, guard, delay_factor)

    # ================================================================ navegação
    def is_farm(self, img):
        if self.library.has("farm"):
            if self.detector.find(img, "farm") is not None:
                return True
            # Plano B: o marcador falhou, mas 2+ elementos que só existem na fazenda aparecem
            # (a verificação de brilho já descarta a fazenda escurecida atrás de uma janela).
            seen = [c for c in ("shop", "wheat_empty", "wheat_ready", "wheat_growing")
                    if self.library.has(c) and self.detector.find(img, c) is not None]
            if len(seen) >= 2:
                if "farm_fallback" not in self._warned:
                    self._warned.add("farm_fallback")
                    log.warning("Template 'farm' não reconhecido, mas a fazenda foi identificada por %s. "
                                "Recorte um ícone fixo do HUD para 'farm' (veja o README).", ", ".join(seen))
                return True
            return False
        self.has_template("farm")  # registra o aviso uma vez
        return any(self.library.has(c) and self.detector.find(img, c) is not None
                   for c in ("shop", "wheat_empty", "wheat_ready", "wheat_growing"))

    def is_shop_open(self, img):
        for cat in ("shop_screen", "shop_empty_slot", "collect", "shop_on_sale"):
            if self.library.has(cat) and self.detector.find(img, cat) is not None:
                return True
        return False

    def dismiss_popups(self, img):
        """Fecha avisos conhecidos. Nunca toca em botões de compra/diamante."""
        for cat in ("reconnect", "continue", "back"):
            if self.library.has(cat):
                m = self.detector.find(img, cat)
                if m:
                    log.info("Fechando janela/aviso (%s).", cat)
                    self.tap_match(m, f"fechar:{cat}", delay_factor=2)
                    return True
        return False

    def check_game_foreground(self):
        pkg = self.cfg["game_package"]
        fg = self.adb.foreground_package()
        if fg and fg != pkg:
            raise GameNotRunning(f"Hay Day não está em primeiro plano (atual: {fg})")
        if not fg and not self.adb.is_app_running(pkg):
            raise GameNotRunning("Hay Day não está em execução")

    def ensure_farm(self, attempts=None, quiet=False):
        """Garante que a fazenda está visível. Retorna o screenshot."""
        attempts = attempts or (self.cfg["max_retries"] + 3)
        for i in range(attempts):
            img = self.capture()
            if self.is_farm(img):
                return img
            if i == 0:
                self.check_game_foreground()
                if not quiet:
                    log.info("Fora da fazenda ou tela inesperada; tentando voltar...")
            if not self.dismiss_popups(img) and i >= 1:
                log.info("Pressionando VOLTAR do Android.")
                self.adb.keyevent(KEY_BACK)
            self.sleep(max(1.0, self.cfg["action_delay"] * 2))
        raise StepFailed("Tela inesperada: não foi possível voltar para a fazenda")

    def open_shop(self):
        img = self.capture()
        if self.is_shop_open(img):
            return img
        if not self.has_template("shop"):
            raise StepFailed("Template 'shop' ausente: não sei onde fica a banca")
        img = self.ensure_farm()
        m = self.detector.find(img, "shop")
        if m is None:
            raise StepFailed("Banca (shop) não encontrada na tela — ajuste a câmera ou o template")
        self.action("Abrindo loja")
        self.tap_match(m, "banca", delay_factor=2)
        for _ in range(12):
            img = self.capture()
            if self.is_shop_open(img):
                return img
            self.sleep(0.5)
        raise StepFailed("A banca não abriu após o toque")

    def close_to_farm(self):
        img = self.capture()
        if self.is_farm(img):
            return img
        log.info("Voltando para a fazenda")
        return self.ensure_farm(quiet=True)

    # --------------------------------------------------------------- arrasto
    @staticmethod
    def order_path(matches):
        """Ordena campos em 'zigue-zague' por linhas para um arrasto contínuo."""
        if not matches:
            return []
        hs = sorted(m.h for m in matches)
        tol = hs[len(hs) // 2] * 0.6
        rows = []
        for m in sorted(matches, key=lambda m: m.center[1]):
            if rows and abs(m.center[1] - rows[-1][0]) <= tol:
                rows[-1][1].append(m)
            else:
                rows.append([m.center[1], [m]])
        out = []
        for i, (_, row) in enumerate(rows):
            row.sort(key=lambda m: m.center[0], reverse=bool(i % 2))
            out.extend(row)
        return out

    def _drag_mode(self):
        mode = self.cfg["drag_mode"]
        if mode == "auto":
            mode = "motionevent" if self.adb.supports_motionevent() else "swipe"
        return mode

    # ------------------------------------------------------------ plantações
    def scan_fields(self, img, purpose=None):
        """captura -> detecção -> validação -> lista única de plantações com estado.

        Uma mesma posição pode casar com mais de um template (ex.: brotos sobre a terra casam
        com 'vazio' e 'crescendo'); fica o estado de maior pontuação e o outro é registrado
        como descartado, com o motivo.
        """
        scan = FieldScan()
        tagged = []
        for key, cat in FIELD_KEYS.items():
            if not self.library.has(cat):
                if key != "growing":
                    self.has_template(cat)
                continue
            found, rejected = self.detector.find_all_explained(img, cat)
            tagged += [(m, key) for m in found]
            scan.discarded += [(m, why) for m, why in rejected]
        tagged.sort(key=lambda t: -t[0].score)
        kept = []
        for m, key in tagged:
            clash = next(((k, kk) for k, kk in kept if m.iso_distance(k) < DUPLICATE_ISO_DISTANCE), None)
            if clash is not None:
                scan.discarded.append((m, f"mesma plantação já classificada como {FIELD_NAMES[clash[1]]} "
                                          f"({clash[0].score:.2f} > {m.score:.2f})"))
                continue
            kept.append((m, key))
        # ecos: usa o espaçamento do grid medido com TODAS as plantações (o grid completo)
        state = {id(m): key for m, key in kept}
        all_fields = [m for m, _ in kept]
        if len(all_fields) >= 4:
            self.detector.field_spacing = grid_spacing(all_fields)
        for m in grid_dedupe(all_fields, scan.discarded, spacing=self.detector.field_spacing):
            getattr(scan, state[id(m)]).append(m)
        if purpose:
            self._log_scan(scan, purpose)
        return scan

    def _log_scan(self, scan, purpose):
        log.info("[%s] Plantações detectadas: %d -> vazias %d, prontas %d, crescendo %d | "
                 "candidatos descartados: %d", purpose, scan.total, len(scan.empty), len(scan.ready),
                 len(scan.growing), len(scan.discarded))
        for m, why in sorted(scan.discarded, key=lambda r: -r[0].score)[:10]:
            log.info("   descartado %s em %s (%.2f): %s", m.category, m.center, m.score, why)
        if len(scan.discarded) > 10:
            log.info("   ... e mais %d descartados (veja o log detalhado)", len(scan.discarded) - 10)
            for m, why in scan.discarded[10:]:
                log.debug("   descartado %s em %s (%.2f): %s", m.category, m.center, m.score, why)

    def _is_stuck(self, m):
        now = time.time()
        self.stuck = [(s, t) for s, t in self.stuck if now - t < STUCK_TTL]
        return any(m.iso_distance(s) < DUPLICATE_ISO_DISTANCE for s, _ in self.stuck)

    def open_tool_menu(self, ordered, tool_cat, label, kind):
        """Toca numa plantação e CONFIRMA que o menu (semente/foice) abriu. Retorna o Match do ícone.

        No máximo 2 plantações x 2 tentativas (a 2ª com a posição recalculada) = 4 toques.
        """
        if not self.has_template(tool_cat):
            raise StepFailed(f"Sem template '{tool_cat}': impossível confirmar o menu, nenhum toque enviado")
        img = self.capture()
        pre = self.detector.find(img, tool_cat)
        if pre is not None:
            log.info("Menu de '%s' já está aberto (ícone em %s); usando-o.", label, pre.center)
            return pre
        other = "sickle" if tool_cat == "seed_wheat" else "seed_wheat"
        if self.library.has(other) and self.detector.find(img, other) is not None:
            log.info("Outro menu (%s) está aberto: o 1º toque pode apenas fechá-lo.", other)
        for target in ordered[:2]:
            box = {"t": target}

            def refresh(box=box):
                scan = self.scan_fields(self.capture())
                near = scan.nearest(kind, box["t"])
                if near is None:
                    return None
                box["t"] = near
                return near.center

            tool = self.tap_confirmed(target.center, f"{label}: abrir menu na plantação {target.center}",
                                      confirm=lambda im: self.detector.find(im, tool_cat), refresh=refresh,
                                      attempts=2)
            if tool:
                return tool
        raise StepFailed(f"O menu '{tool_cat}' não abriu ao tocar nas plantações (confirmação visual falhou)")

    def _drag_over(self, tool, ordered, tool_cat, label, kind):
        mode = self._drag_mode()
        log.info("Arrastando '%s' de %s sobre %d plantações (modo %s): %s", tool_cat, tool.center,
                 len(ordered), mode, " -> ".join(str(t.center) for t in ordered))
        if mode == "motionevent":
            points = [tool.center] + [t.center for t in ordered]
            self._pending_touch = points[-1]
            try:
                self.adb.drag_path(points, self.cfg["drag_hold"], self.cfg["drag_step_px"])
            finally:
                self._pending_touch = None
        else:
            for i, t in enumerate(ordered):
                if i > 0:
                    try:
                        tool = self.open_tool_menu([t], tool_cat, label, kind)
                    except StepFailed as exc:
                        log.warning("Pulando %s nesta passagem: %s", t.center, exc)
                        continue
                tx, ty = tool.center
                cx, cy = t.center
                self.adb.swipe(tx, ty, cx, cy, self.cfg["swipe_duration_ms"])
                self.pause()
        self.pause(2)

    def work_fields(self, kind, targets, tool_cat, label):
        """Planta/colhe em passagens, confirmando visualmente CADA plantação.

        Retorna (confirmadas, restantes, último screenshot, interrompido_por_janela).
        """
        done = []
        remaining = list(targets)
        img = None
        interrupted = None
        passes = 1 + self.cfg["action_retries"]
        zero_progress = 0
        for n in range(1, passes + 1):
            if not remaining:
                break
            ordered = self.order_path(remaining)
            tool = self.open_tool_menu(ordered, tool_cat, label, kind)
            self._drag_over(tool, ordered, tool_cat, label, kind)
            img = self.capture()
            if self.library.has("silo_full") and self.detector.find(img, "silo_full") is not None:
                interrupted = "silo_full"
            elif not self.is_farm(img):
                interrupted = "popup"
            if interrupted:
                log.warning("Uma janela apareceu depois de %s (%s). Fechando.", label,
                            "silo cheio" if interrupted == "silo_full" else "sem trigo suficiente?")
                self.dismiss_popups(img)
                self.sleep(1)
                img = self.ensure_farm()
            after = self.scan_fields(img)
            still, ok = [], []
            for t in remaining:
                (ok if after.state_at(t) != kind else still).append(t)
            done += ok
            log.info("[%s] Passagem %d/%d: %d alvos -> %d confirmados na tela%s", label, n, passes,
                     len(remaining), len(ok),
                     "" if not still else "; sem mudança em " + ", ".join(str(t.center) for t in still))
            # próxima passagem só com os que não mudaram, nas posições RECALCULADAS
            remaining = [after.nearest(kind, t) or t for t in still]
            if interrupted:
                break
            zero_progress = zero_progress + 1 if not ok else 0
            if zero_progress >= 2:
                break
        return done, remaining, img, interrupted

    @staticmethod
    def removed(before, after):
        """Itens de `before` que não existem mais em `after` (mesma posição)."""
        return [b for b in before if not any(b.same_spot(a) for a in after)]

    def _next_after_harvest(self):
        return State.SELL

    # ================================================================ estados
    def st_connecting(self, ctx):
        self.action("Conectando ao ADB...")
        self.adb.start_server()
        version = self.adb.version()
        log.info("ADB OK (%s)", version)

        wanted = self.cfg["device"]
        online = self.adb.online_devices()
        if wanted and wanted not in online and ":" in wanted:
            self.adb.connect(wanted)
            online = self.adb.online_devices()
        if not online and self.cfg["emulator_path"]:
            self._launch_emulator()
            online = self._wait_for_device()
        if not online:
            found = self.adb.scan_emulators([wanted] if wanted and ":" in wanted else None)
            online = self.adb.online_devices() if found else []
        if not online:
            raise DeviceLost("Nenhum dispositivo ADB online. Abra o emulador e clique em CONECTAR.")
        device = wanted if wanted in online else online[0]
        if wanted and device != wanted:
            log.warning("Dispositivo '%s' não encontrado; usando '%s'.", wanted, device)
        self.adb.device = device

        # Aguarda o Android terminar de iniciar.
        end = time.monotonic() + self.cfg["emulator_boot_timeout"]
        while not self.adb.boot_completed():
            if time.monotonic() > end:
                raise StepFailed("O Android do emulador não terminou de iniciar")
            self.sleep(3)

        img = self.capture()
        h, w = img.shape[:2]
        cw, ch = parse_resolution(self.cfg["resolution"])
        if (w, h) != (cw, ch):
            log.warning("Resolução do emulador %dx%d difere da configurada %dx%d. "
                        "Os templates serão escalados, mas o ideal é usar a mesma resolução.",
                        w, h, cw, ch)
        self.action(f"ADB conectado ({device}, {w}x{h})")
        return State.OPEN_GAME

    def _launch_emulator(self):
        path = self.cfg["emulator_path"]
        if not path or not os.path.isfile(path):
            log.warning("Executável do emulador não encontrado: %s", path)
            return
        args = [path] + (self.cfg["emulator_args"].split() if self.cfg["emulator_args"] else [])
        self.action("Iniciando o emulador...")
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(args, cwd=os.path.dirname(path), creationflags=flags,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
        except OSError as exc:
            log.error("Falha ao iniciar o emulador: %s", exc)

    def _wait_for_device(self):
        end = time.monotonic() + self.cfg["emulator_boot_timeout"]
        wanted = self.cfg["device"]
        while time.monotonic() < end:
            self.sleep(5)
            if wanted and ":" in wanted:
                self.adb.connect(wanted)
            else:
                self.adb.scan_emulators()
            online = self.adb.online_devices()
            if online:
                return online
        return []

    def st_open_game(self, ctx):
        pkg = self.cfg["game_package"]
        if not self.adb.is_package_installed(pkg):
            raise FatalError(f"O pacote {pkg} (Hay Day) não está instalado no emulador")
        # Ao (re)abrir, o jogo redefine o zoom da câmera: recalibra.
        self.detector.reset_calibration()
        if self.force_restart:
            self.action("Reiniciando o Hay Day...")
            self.adb.stop_app(pkg)
            self.sleep(3)
            self.force_restart = False
        if self.adb.foreground_package() != pkg:
            self.action("Abrindo o Hay Day...")
            self.adb.start_app(pkg)
            self.sleep(5)
        end = time.monotonic() + self.cfg["open_game_timeout"]
        last_diag = 0.0
        img = None
        while time.monotonic() < end:
            img = self.capture()
            if self.is_farm(img):
                zoom = self.detector.world_zoom
                self.action("Hay Day encontrado" + (f" (zoom da câmera {zoom:.2f}x)" if zoom else ""))
                self.screen.reset_freeze()
                return State.CHECK_FIELD
            if self.adb.foreground_package() not in (pkg, ""):
                self.adb.start_app(pkg)
            if self.dismiss_popups(img):  # telas de conexão/aviso durante o carregamento
                continue
            # Nenhuma janela: pode ser o zoom da câmera diferente do usado nos recortes.
            zoom = self.detector.calibrate_world(img)
            if zoom is not None and self.is_farm(img):
                continue
            if time.monotonic() - last_diag > 20:
                last_diag = time.monotonic()
                self._log_detection("farm", img)
            self.sleep(self.cfg["check_interval"])
        if img is not None:
            self._log_detection("farm", img, level=log.warning)
        raise StepFailed("O Hay Day não chegou à fazenda dentro do tempo limite")

    def _log_detection(self, category, img, level=None):
        """Registra por que um template não foi reconhecido (pontuação, zoom, brilho)."""
        if not self.library.has(category):
            return
        try:
            info = self.detector.diagnose(img, category)
            (level or log.info)("Fazenda ainda não reconhecida — " + self.detector.describe(category, info))
        except Exception as exc:  # noqa: BLE001
            log.debug("Diagnóstico falhou: %s", exc)

    def st_check_field(self, ctx):
        img = self.ensure_farm()
        scan = self.scan_fields(img)
        if scan.total == 0 and self.detector.calibrate_world(img) is not None:
            log.info("Zoom da câmera recalibrado: %.2fx", self.detector.world_zoom)
            scan = self.scan_fields(img)
        self._log_scan(scan, "verificação")
        total = scan.total
        self.stats.set(fields_found=total)
        harvestable = [m for m in scan.ready if not self._is_stuck(m)]
        self.action(f"Campos encontrados: {total} (vazios {len(scan.empty)}, prontos {len(scan.ready)}, "
                    f"crescendo {len(scan.growing)})")
        growing_expected = (self.last_plant_time and
                            time.time() - self.last_plant_time < self.cfg["max_wait_growth"])
        if total == 0 and growing_expected:
            log.info("Nenhum campo vazio/pronto visível; o trigo deve estar crescendo.")
            return State.WAIT_GROWTH
        if total == 0:
            self.no_fields_count += 1
            if self.no_fields_count >= 3:
                self.no_fields_count = 0
                raise StepFailed("Nenhum campo reconhecido. Verifique a câmera (campos visíveis) "
                                 "e os templates wheat_empty / wheat_ready.")
            log.info("Nenhum campo visível; os campos podem estar crescendo. Aguardando.")
            return State.WAIT_GROWTH
        self.no_fields_count = 0
        if harvestable:
            return State.HARVEST
        if len(harvestable) < len(scan.ready):
            log.info("%d trigo(s) pronto(s) em espera após não responderem; serão tentados de novo em "
                     "até %ds.", len(scan.ready) - len(harvestable), STUCK_TTL)
        if scan.empty:
            return State.PLANT
        return State.WAIT_GROWTH

    def st_plant(self, ctx):
        img = self.ensure_farm()
        scan = self.scan_fields(img, "plantio")
        if not scan.empty:
            log.info("Nenhum espaço vazio para plantar.")
            return State.WAIT_GROWTH
        self.action(f"Plantando trigo em {len(scan.empty)} espaço(s) livre(s)")
        done, remaining, img, interrupted = self.work_fields("empty", scan.empty, "seed_wheat", "plantar")
        planted = len(done)
        if planted == 0:
            raise StepFailed("Nenhum campo foi plantado (confirmação visual falhou; verifique o template "
                             "seed_wheat e o estoque de trigo)")
        self.stats.inc("fields_planted", planted)
        self.stats.set(wheat_stock=max(0, self.stats.wheat_stock - planted))
        self.last_planted = planted
        self.last_plant_time = time.time()
        self.recoveries = 0
        self.action(f"{planted} campos plantados")
        if remaining:
            log.warning("%d espaço(s) continuam vazios: %s%s", len(remaining),
                        ", ".join(str(t.center) for t in remaining),
                        " — o jogo abriu uma janela (falta de trigo?)" if interrupted else
                        " — o arrasto passou por eles sem efeito; serão tentados no próximo ciclo")
        return State.WAIT_GROWTH

    def st_wait_growth(self, ctx):
        started = time.time()
        grow = self.cfg["growth_time"]
        since_plant = started - self.last_plant_time if self.last_plant_time else grow
        expected = max(0.0, grow - since_plant)
        self.action(f"Aguardando o trigo crescer (~{expected:.0f}s, verificando a cada "
                    f"{self.cfg['check_interval']:.0f}s)")
        collect_due = False
        while True:
            elapsed = time.time() - started
            img = self.capture()
            if not self.is_farm(img):
                img = self.ensure_farm()
            ready = [m for m in self.find_all("wheat_ready", img) if not self._is_stuck(m)]
            grown_long_enough = since_plant + elapsed >= grow * 0.9
            if ready and (len(ready) >= max(1, self.last_planted) or grown_long_enough):
                self.action(f"Trigo pronto ({len(ready)} campos)")
                return State.HARVEST
            if elapsed >= self.cfg["max_wait_growth"]:
                if ready:
                    return State.HARVEST
                log.info("Tempo máximo de espera atingido; verificando os campos novamente.")
                return State.CHECK_FIELD
            # Aproveita a espera para coletar vendas, se ainda falta bastante tempo.
            remaining = grow - since_plant - elapsed
            if (self.cfg["collect_money_enabled"] and remaining > 40 and
                    self.library.has("collect") and self.library.has("shop") and
                    time.time() - self.last_collect_time >= self.cfg["collect_interval"]):
                collect_due = True
            if collect_due:
                return State.COLLECT_MONEY
            self.sleep(self.cfg["check_interval"])

    def st_harvest(self, ctx):
        img = self.ensure_farm()
        scan = self.scan_fields(img, "colheita")
        targets = [m for m in scan.ready if not self._is_stuck(m)]
        waiting = [m for m in scan.ready if self._is_stuck(m)]
        if waiting:
            log.info("%d trigo(s) em espera (não responderam há pouco): %s", len(waiting),
                     ", ".join(str(m.center) for m in waiting))
        if not targets:
            log.info("Nenhum trigo pronto para colher agora.")
            return State.PLANT if scan.empty else State.SELL

        self.action(f"Colhendo {len(targets)} trigo(s)")
        done, remaining, img, interrupted = self.work_fields("ready", targets, "sickle", "colher")
        if interrupted == "silo_full":
            self.action("Silo cheio! Indo vender.")
            self.silo_full = True
        for m in remaining:
            self.stuck.append((m, time.time()))
        if remaining:
            log.warning("%d trigo(s) não responderam à colheita: %s — nova tentativa em até %ds.",
                        len(remaining), ", ".join(str(m.center) for m in remaining), STUCK_TTL)
        n = len(done)
        if n == 0:
            if self.silo_full:
                return State.SELL
            raise StepFailed("A colheita não foi confirmada na tela (os campos continuam prontos)")
        self.stats.inc("fields_harvested", n)
        self.stats.inc("wheat_stock", n * self.cfg["yield_per_field"])
        self.stats.inc("cycles")
        self.recoveries = 0
        self.action(f"{n} campos colhidos")
        return self._next_after_harvest()

    # ------------------------------------------------------------------ venda
    def _available_to_sell(self):
        available = self.stats.wheat_stock - self.cfg["keep_reserve"]
        if self.silo_full:
            available = max(available, self.cfg["max_sell_qty"])
        return available

    def _ad_due(self):
        return (self.cfg["advertise_enabled"] and
                time.time() - self.last_ad_time >= self.cfg["advertise_interval"])

    def collect_sold(self):
        """Na banca aberta: toca em cada caixote vendido. Nunca toca sem template encontrado."""
        if not self.has_template("collect"):
            return 0
        collected = 0
        failed_spots = []
        for _ in range(12):
            img = self.capture()
            matches = [m for m in self.detector.find_all(img, "collect")
                       if not any(m.same_spot(f) for f in failed_spots)]
            if not matches:
                break
            m = matches[0]
            self.tap_match(m, "coletar venda", delay_factor=1.5)
            img = self.capture()
            still = [a for a in self.detector.find_all(img, "collect") if a.same_spot(m)]
            if still:
                log.warning("Caixote em %s não foi coletado; não vou insistir nele.", m.center)
                failed_spots.append(m)
                if not self.is_shop_open(img):
                    self.dismiss_popups(img)
                continue
            collected += 1
        if collected:
            self.stats.inc("collections", collected)
            self.stats.inc("coins_estimate", collected * self.cfg["coins_per_sale_estimate"])
            self.action(f"Dinheiro coletado ({collected} vendas concluídas)")
            self.recoveries = 0
        self.last_collect_time = time.time()
        return collected

    def _set_quantity(self, qty):
        clicks = qty - self.cfg["sell_qty_start"]
        cat = "qty_plus" if clicks > 0 else "qty_minus"
        if clicks == 0:
            return
        m = self.find(cat)
        if m is None:
            log.warning("Botão %s não encontrado; mantendo a quantidade padrão.", cat)
            return
        for _ in range(abs(clicks)):
            self.tap_match(m, cat, guard=False, delay_factor=0.4)

    def _set_price(self):
        mode = self.cfg["price_mode"]
        if mode == "default":
            return
        if mode == "max":
            m = self.find("price_max")
            if m:
                self.tap_match(m, "preço máximo", guard=False)
                return
            log.warning("Botão price_max não encontrado; usando price_plus x%d.", self.cfg["price_clicks"])
            mode = "plus"
        cat = "price_plus" if mode == "plus" else "price_minus"
        if self.cfg["price_clicks"] <= 0:
            return
        m = self.find(cat)
        if m is None:
            log.warning("Botão %s não encontrado; mantendo o preço sugerido.", cat)
            return
        for _ in range(self.cfg["price_clicks"]):
            self.tap_match(m, cat, guard=False, delay_factor=0.4)

    def _close_dialog(self):
        img = self.capture()
        if not self.dismiss_popups(img):
            self.adb.keyevent(KEY_BACK)
            self.pause(2)

    def st_sell(self, ctx):
        if not self.cfg["sell_enabled"]:
            return State.ADVERTISE
        available = self._available_to_sell()
        if available < self.cfg["min_sell_qty"]:
            log.info("Trigo insuficiente para vender (estoque estimado %d, reserva %d, mínimo %d).",
                     self.stats.wheat_stock, self.cfg["keep_reserve"], self.cfg["min_sell_qty"])
            return State.ADVERTISE
        for cat in ("shop_empty_slot", "sell_item_wheat", "sell"):
            if not self.has_template(cat):
                log.warning("Venda desativada nesta rodada: falta o template '%s'.", cat)
                return State.ADVERTISE

        self.open_shop()
        self.collect_sold()
        listings = 0
        while listings < self.cfg["max_listings_per_cycle"] and available >= self.cfg["min_sell_qty"]:
            img = self.capture()
            slot = self.detector.find(img, "shop_empty_slot")
            if slot is None:
                log.info("Loja cheia — nenhum caixote livre. Venda adiada.")
                break
            self.tap_match(slot, "caixote vazio", delay_factor=2)
            if self.wait_for("sell", timeout=5) is None:
                raise StepFailed("A janela de venda não abriu")

            item = self.find("sell_item_wheat")
            if item is None and self.library.has("silo_tab"):
                tab = self.find("silo_tab")
                if tab:
                    self.tap_match(tab, "aba do silo")
                    item = self.find("sell_item_wheat")
            if item is None:
                log.info("Trigo não encontrado na janela de venda (estoque zerado?).")
                self.stats.set(wheat_stock=min(self.stats.wheat_stock, self.cfg["keep_reserve"]))
                self._close_dialog()
                break
            self.tap_match(item, "trigo", delay_factor=1.5)

            qty = int(min(self.cfg["max_sell_qty"], available))
            self._set_quantity(qty)
            self._set_price()

            advertised = False
            if self._ad_due():
                img = self.capture()
                ad = self.detector.find(img, "advertise") if self.library.has("advertise") else None
                if ad:
                    self.tap_match(ad, "anunciar")
                    advertised = True
                elif self.library.has("advertise_cooldown") and \
                        self.detector.find(img, "advertise_cooldown"):
                    log.info("Anúncio em cooldown; continuando sem anunciar.")

            btn = self.find("sell")
            if btn is None:
                raise StepFailed("Botão de vender sumiu antes de confirmar")
            self.tap_match(btn, "colocar à venda", delay_factor=2)
            if not self.wait_gone("sell", timeout=5):
                self._close_dialog()
                raise StepFailed("A venda não foi confirmada (janela continuou aberta)")

            listings += 1
            available -= qty
            self.stats.inc("listings")
            self.stats.inc("sold_qty", qty)
            self.stats.set(wheat_stock=max(0, self.stats.wheat_stock - qty))
            self.silo_full = False
            self.recoveries = 0
            self.action(f"Produto colocado à venda ({qty}x trigo)")
            if advertised:
                self.last_ad_time = time.time()
                self.stats.inc("ads")
                self.action("Anúncio realizado")
        return State.ADVERTISE

    def st_advertise(self, ctx):
        if not self._ad_due():
            return State.COLLECT_MONEY
        if not (self.library.has("shop_on_sale") and self.library.has("advertise")):
            return State.COLLECT_MONEY
        self.open_shop()
        crate = self.find("shop_on_sale")
        if crate is None:
            log.info("Nenhum produto à venda para anunciar.")
            return State.COLLECT_MONEY
        self.tap_match(crate, "caixote à venda", delay_factor=2)
        img = self.capture()
        ad = self.detector.find(img, "advertise")
        if ad is None:
            if self.library.has("advertise_cooldown") and self.detector.find(img, "advertise_cooldown"):
                log.info("Anúncio em cooldown; tentarei mais tarde.")
                self.last_ad_time = time.time() - self.cfg["advertise_interval"] / 2
            else:
                log.info("Opção de anúncio indisponível agora.")
            self._close_dialog()
            return State.COLLECT_MONEY
        self.tap_match(ad, "criar anúncio", delay_factor=2)
        conf = self.wait_for("confirm", timeout=3) if self.library.has("confirm") else None
        if conf:
            self.tap_match(conf, "confirmar anúncio", delay_factor=2)
        self.last_ad_time = time.time()
        self.stats.inc("ads")
        self.action("Anúncio realizado")
        img = self.capture()
        if not self.is_shop_open(img) and not self.is_farm(img):
            self.dismiss_popups(img)
        return State.COLLECT_MONEY

    def st_collect_money(self, ctx):
        due = time.time() - self.last_collect_time >= self.cfg["collect_interval"]
        if self.cfg["collect_money_enabled"] and due and self.library.has("collect"):
            self.last_collect_time = time.time()  # evita repetir em loop se a banca falhar
            self.open_shop()
            n = self.collect_sold()
            if n == 0:
                log.info("Nenhuma venda concluída ainda.")
        img = self.capture()
        if not self.is_farm(img):
            self.close_to_farm()
        return State.CHECK_FIELD

    # ------------------------------------------------------------ recuperação
    def st_recover(self, ctx):
        self.recoveries += 1
        self.action(f"Recuperando para um estado seguro ({self.recoveries}/{self.cfg['max_recoveries']})")
        if self.recoveries > self.cfg["max_recoveries"]:
            raise FatalError("O bot entrou em recuperação muitas vezes seguidas sem progresso. "
                             "Verifique os templates/câmera e o último screenshot de erro.")
        if not self.adb.is_online():
            raise DeviceLost("Dispositivo offline durante a recuperação")
        if self.force_restart or self.recover_failures >= self.cfg["restart_game_after_failures"]:
            self.recover_failures = 0
            self.force_restart = True
            return State.OPEN_GAME
        try:
            self.check_game_foreground()
            self.ensure_farm()
        except GameNotRunning as exc:
            log.info("%s", exc)
            return State.OPEN_GAME
        except StepFailed:
            self.recover_failures += 1
            log.warning("Recuperação falhou (%d/%d antes de reiniciar o jogo).",
                        self.recover_failures, self.cfg["restart_game_after_failures"])
            return State.RECOVER
        self.recover_failures = 0
        return State.CHECK_FIELD
