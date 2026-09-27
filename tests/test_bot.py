"""Testes: detector de imagem, máquina de estados e o ciclo completo com o jogo simulado.

Rodar:  python -m pytest -q tests
"""

import os
import sys
import threading
import time

import cv2
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfgmod  # noqa: E402
from bot import HayDayBot  # noqa: E402
from fake_game import FakeADB, FakeGame, make_patches, write_templates  # noqa: E402
from image_detector import ImageDetector, TemplateLibrary  # noqa: E402
from state_machine import State, StateMachine, StepFailed  # noqa: E402


@pytest.fixture()
def env(tmp_path):
    patches = make_patches()
    tdir = tmp_path / "templates"
    write_templates(str(tdir), patches)
    sdir = tmp_path / "screenshots"
    sdir.mkdir()
    return patches, str(tdir), str(sdir)


def fast_cfg(**over):
    cfg = cfgmod.normalize({
        "action_delay": 0.05, "check_interval": 1, "growth_time": 1, "max_wait_growth": 20,
        "freeze_timeout": 0, "collect_interval": 1, "advertise_interval": 1,
        "initial_wheat_stock": 30, "keep_reserve": 6, "min_sell_qty": 5, "max_sell_qty": 5,
        "max_same_spot_taps": 50, "coins_per_sale_estimate": 100, "device": "127.0.0.1:21503",
    })
    cfg.update(over)
    return cfg


def make_bot(tdir, sdir, game, cfg, motionevent=True):
    bot = HayDayBot(cfg, tdir, sdir)
    fake = FakeADB(game, motionevent, bot.stop_event)
    bot.adb = fake
    bot.screen.adb = fake
    return bot, fake


def run_until(bot, cond, timeout=40):
    bot.start()
    end = time.time() + timeout
    while time.time() < end and bot.is_running() and not cond():
        time.sleep(0.2)
    bot.stop("fim do teste")
    bot.join(5)
    assert not bot.is_running()


# ------------------------------------------------------------------ detector
def test_detector_finds_all_fields(env):
    patches, tdir, _ = env
    game = FakeGame(patches, n_fields=6)
    img = game.render()
    det = ImageDetector(TemplateLibrary(tdir), 0.8, {}, 1280)
    assert len(det.find_all(img, "wheat_empty")) == 6
    assert det.find(img, "farm") is not None
    assert det.find(img, "sell") is None
    assert det.find_all(img, "categoria_inexistente") == []


def test_detector_scales_templates_to_other_resolution(env):
    patches, tdir, _ = env
    img = FakeGame(patches).render()
    small = cv2.resize(img, (960, 540), interpolation=cv2.INTER_AREA)
    det = ImageDetector(TemplateLibrary(tdir), 0.7, {}, 1280)
    assert len(det.find_all(small, "wheat_empty")) == 6


def test_detector_hot_reload(env, tmp_path):
    patches, tdir, _ = env
    lib = TemplateLibrary(tdir)
    assert lib.count("farm") == 1
    cv2.imwrite(os.path.join(tdir, "farm", "farm2.png"), patches["farm"])
    lib.RECHECK_SECONDS = 0
    assert lib.count("farm") == 2


# -------------------------------------------------------------- state machine
def test_state_machine_retries_then_safe_state():
    stop = threading.Event()
    calls = {"plant": 0, "recover": 0}

    def plant(ctx):
        calls["plant"] += 1
        raise StepFailed("botão não encontrado")

    def recover(ctx):
        calls["recover"] += 1
        stop.set()
        return State.CHECK_FIELD

    sm = StateMachine({State.PLANT: plant, State.RECOVER: recover}, State.PLANT, stop,
                      max_retries=3, retry_delay=0.01)
    final = sm.run()
    assert calls == {"plant": 3, "recover": 1}
    assert final == State.STOPPED


def test_state_machine_timeout():
    stop = threading.Event()

    def slow(ctx):
        while True:
            ctx.check_deadline()
            time.sleep(0.01)

    sm = StateMachine({State.PLANT: slow}, State.PLANT, stop, max_retries=1,
                      default_timeout=0.1, retry_delay=0.01, safe_state=State.PLANT)
    assert sm.run() == State.ERROR


# ------------------------------------------------------------- ciclo completo
@pytest.mark.parametrize("motionevent", [True, False])
def test_full_cycle(env, motionevent):
    patches, tdir, sdir = env
    game = FakeGame(patches, n_fields=6)
    bot, _ = make_bot(tdir, sdir, game, fast_cfg(), motionevent)

    def done():
        s = bot.stats
        return s.fields_harvested >= 12 and s.listings >= 2 and s.collections >= 1 and s.ads >= 1

    run_until(bot, done, timeout=60)
    s = bot.stats.snapshot()
    assert s["fields_planted"] >= 6, s
    assert s["fields_harvested"] >= 12, s
    assert s["listings"] >= 2 and s["sold_qty"] >= 10, s
    assert s["collections"] >= 1 and game.coins >= 100, s
    assert s["ads"] >= 1, s
    assert bot.status == HayDayBot.STATUS_STOPPED


def test_recovers_from_popup_and_closed_game(env):
    patches, tdir, sdir = env
    game = FakeGame(patches, n_fields=3)
    game.popup = True            # janela inesperada cobrindo a fazenda
    game.screen = "shop"         # e o jogo aberto na tela errada
    bot, fake = make_bot(tdir, sdir, game, fast_cfg(sell_enabled=False))

    closed = {"done": False}

    def cond():
        if bot.stats.fields_planted >= 3 and not closed["done"]:
            closed["done"] = True
            game.running = False  # jogo fecha no meio do ciclo
            fake.offline_once = True  # e a conexão cai uma vez
        return closed["done"] and bot.stats.fields_harvested >= 6

    run_until(bot, cond, timeout=60)
    assert bot.stats.fields_harvested >= 6
    assert game.running


def test_missing_templates_stop_with_error_not_infinite_clicks(env):
    patches, tdir, sdir = env
    # Remove o template da semente: o bot deve tentar, falhar e parar em ERROR.
    os.remove(os.path.join(tdir, "seed_wheat", "seed_wheat.png"))
    game = FakeGame(patches, n_fields=3)
    bot, _ = make_bot(tdir, sdir, game, fast_cfg(max_retries=2, max_recoveries=2))
    bot.start()
    bot.join(60)
    assert not bot.is_running()
    assert bot.status == HayDayBot.STATUS_ERROR
    assert game.taps < 60  # não ficou clicando indefinidamente
    assert os.listdir(os.path.join(sdir, "errors"))  # screenshots de erro salvos


def test_full_shop_skips_selling(env):
    patches, tdir, sdir = env
    game = FakeGame(patches, n_fields=3, sell_s=999)
    for c in game.crates:
        c["st"] = "on_sale"
        c["t"] = time.time()
    bot, _ = make_bot(tdir, sdir, game, fast_cfg(advertise_enabled=False))
    run_until(bot, lambda: bot.stats.fields_harvested >= 6, timeout=40)
    assert bot.stats.listings == 0
    assert bot.stats.fields_harvested >= 6


def test_stop_is_immediate(env):
    patches, tdir, sdir = env
    game = FakeGame(patches, n_fields=3, grow_s=999)
    bot, _ = make_bot(tdir, sdir, game, fast_cfg(growth_time=999, max_wait_growth=999))
    bot.start()
    end = time.time() + 20
    while time.time() < end and bot.stats.state != "WAIT_GROWTH":
        time.sleep(0.1)
    t0 = time.time()
    bot.stop("F8")
    bot.join(5)
    assert not bot.is_running()
    assert time.time() - t0 < 1.5


def test_config_normalize_bad_values():
    cfg = cfgmod.normalize({"max_retries": "abc", "action_delay": -1, "price_mode": "xyz",
                            "thresholds": {"farm": "0.7", "bad": "x"}, "scales": "nope"})
    assert cfg["max_retries"] == cfgmod.DEFAULT_CONFIG["max_retries"]
    assert cfg["action_delay"] >= 0.05
    assert cfg["price_mode"] == "max"
    assert cfg["thresholds"] == {"farm": 0.7}
    assert cfg["scales"] == [1.0]
