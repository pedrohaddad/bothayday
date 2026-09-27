"""Máquina de estados genérica com tentativas, timeout por etapa e estado seguro."""

import enum
import time

from logger_setup import get_logger

log = get_logger()


class State(enum.Enum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    OPEN_GAME = "OPEN_GAME"
    CHECK_FIELD = "CHECK_FIELD"
    PLANT = "PLANT"
    WAIT_GROWTH = "WAIT_GROWTH"
    HARVEST = "HARVEST"
    SELL = "SELL"
    ADVERTISE = "ADVERTISE"
    COLLECT_MONEY = "COLLECT_MONEY"
    RECOVER = "RECOVER"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class BotStopped(Exception):
    """Parada solicitada (botão PARAR ou tecla de emergência)."""


class StepFailed(Exception):
    """A etapa atual falhou; pode ser tentada novamente."""


class StepTimeout(StepFailed):
    """A etapa excedeu o tempo máximo."""


class FatalError(Exception):
    """Erro que impede continuar (ex.: jogo não instalado)."""


class StepContext:
    def __init__(self, state, attempt, timeout):
        self.state = state
        self.attempt = attempt
        self.started = time.monotonic()
        self.deadline = self.started + timeout
        self.timeout = timeout

    def elapsed(self):
        return time.monotonic() - self.started

    def check_deadline(self):
        if time.monotonic() > self.deadline:
            raise StepTimeout(f"Etapa {self.state.value} excedeu {self.timeout:.0f}s")


class StateMachine:
    """
    handlers: {State: callable(ctx) -> próximo State}
    redirect: callable(exc) -> State|None  (ex.: conexão perdida -> CONNECTING)
    Estados em `fatal_on_exhaust` vão para ERROR quando esgotam as tentativas;
    os demais vão para `safe_state`.
    """

    def __init__(self, handlers, initial, stop_event, safe_state=State.RECOVER,
                 max_retries=3, default_timeout=120, timeouts=None, retry_delay=2.0,
                 redirect=None, on_failure=None, on_transition=None,
                 fatal_on_exhaust=(State.CONNECTING, State.RECOVER),
                 max_consecutive_failures=25):
        self.handlers = handlers
        self.initial = initial
        self.stop_event = stop_event
        self.safe_state = safe_state
        self.max_retries = max(1, int(max_retries))
        self.default_timeout = default_timeout
        self.timeouts = dict(timeouts or {})
        self.retry_delay = retry_delay
        self.redirect = redirect
        self.on_failure = on_failure
        self.on_transition = on_transition
        self.fatal_on_exhaust = set(fatal_on_exhaust)
        self.max_consecutive_failures = max_consecutive_failures
        self.state = initial
        self.context = None

    def _wait(self, seconds):
        if self.stop_event.wait(seconds):
            raise BotStopped()

    def _set_state(self, new):
        if new != self.state:
            old = self.state
            self.state = new
            log.debug("Estado: %s -> %s", old.value, new.value)
            if self.on_transition:
                self.on_transition(old, new)

    def run(self):
        attempts = 0
        consecutive_failures = 0
        self._set_state(self.initial)
        while True:
            if self.stop_event.is_set():
                self._set_state(State.STOPPED)
                break
            state = self.state
            if state in (State.ERROR, State.STOPPED):
                break
            handler = self.handlers.get(state)
            if handler is None:
                log.error("Estado sem tratador: %s", state.value)
                self._set_state(State.ERROR)
                break
            timeout = self.timeouts.get(state, self.default_timeout)
            self.context = StepContext(state, attempts + 1, timeout)
            try:
                nxt = handler(self.context)
                if not isinstance(nxt, State):
                    raise StepFailed(f"Tratador de {state.value} retornou valor inválido: {nxt!r}")
                attempts = 0
                consecutive_failures = 0
                self._set_state(nxt)
            except BotStopped:
                self._set_state(State.STOPPED)
                break
            except FatalError as exc:
                log.error("ERRO FATAL em %s: %s", state.value, exc)
                self._notify_failure(state, exc, fatal=True)
                self._set_state(State.ERROR)
                break
            except Exception as exc:  # noqa: BLE001 - qualquer falha vira nova tentativa
                if self.stop_event.is_set():
                    self._set_state(State.STOPPED)
                    break
                attempts += 1
                consecutive_failures += 1
                log.warning("Falha em %s (tentativa %d/%d): %s",
                            state.value, attempts, self.max_retries, exc)
                self._notify_failure(state, exc)
                if consecutive_failures >= self.max_consecutive_failures:
                    log.error("Muitas falhas seguidas (%d). Parando por segurança.",
                              consecutive_failures)
                    self._set_state(State.ERROR)
                    break
                target = self.redirect(exc) if self.redirect else None
                try:
                    if target is not None and target != state:
                        log.info("Indo para %s por causa do erro.", target.value)
                        attempts = 0
                        self._wait(1.0)
                        self._set_state(target)
                    elif attempts >= self.max_retries:
                        attempts = 0
                        if state in self.fatal_on_exhaust or state == self.safe_state:
                            log.error("Limite de tentativas esgotado em %s.", state.value)
                            self._set_state(State.ERROR)
                            break
                        log.warning("Limite de tentativas em %s. Voltando ao estado seguro (%s).",
                                    state.value, self.safe_state.value)
                        self._set_state(self.safe_state)
                    else:
                        self._wait(self.retry_delay)
                except BotStopped:
                    self._set_state(State.STOPPED)
                    break
        self.context = None
        return self.state

    def _notify_failure(self, state, exc, fatal=False):
        if self.on_failure:
            try:
                self.on_failure(state, exc, fatal)
            except Exception as cb_exc:  # noqa: BLE001
                log.debug("on_failure falhou: %s", cb_exc)
