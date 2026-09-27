"""Testes da etapa de decisão e ação: lista completa de plantações, NMS que não elimina
vizinhos, cliques confirmados visualmente e passagens de plantio/colheita.

Rodar:  python -m pytest -q tests/test_actions.py
"""

import logging
import os
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bot as botmod  # noqa: E402
import config as cfgmod  # noqa: E402
from bot import HayDayBot  # noqa: E402
from image_detector import ImageDetector, Match, TemplateLibrary, build_detector  # noqa: E402
from scene_game import SceneADB, SceneGame, make_templates  # noqa: E402
from state_machine import State, StepContext  # noqa: E402

CFG = cfgmod.normalize({"template_resolution": "640x480", "resolution": "640x480",
                        "action_delay": 0.05, "check_interval": 1, "confirm_timeout": 1.0,
                        "action_retries": 2, "max_same_spot_taps": 50})
TIGHT = (62, 34)  # campos encostados, como no Hay Day


CROPS = [(40, 22), (60, 30), (118, 60)]  # "miolo" pequeno, médio e o campo inteiro


@pytest.fixture(scope="module")
def tdir():
    return make_templates(tempfile.mkdtemp())


@pytest.fixture(scope="module")
def crop_dirs():
    return {c: make_templates(tempfile.mkdtemp(), crop=c) for c in CROPS}


def make_bot(tdir, game, **cfg):
    b = HayDayBot(dict(CFG, **cfg), tdir, tempfile.mkdtemp())
    b.adb = b.screen.adb = SceneADB(game)
    b.stop_event = threading.Event()

    class M:
        context = StepContext(State.PLANT, 1, 300)
    b.machine = M()
    return b


def centers_match(found, expected, tol=10):
    return all(any(abs(m.center[0] - x) <= tol and abs(m.center[1] - y) <= tol for m in found)
               for x, y in expected)


# ============================================================ 1) trigos prontos
@pytest.mark.parametrize("crop", CROPS)
@pytest.mark.parametrize("rows,cols", [(3, 3), (4, 4)])
def test_many_adjacent_ready_all_detected(crop_dirs, crop, rows, cols):
    game = SceneGame(["ready"] * rows * cols, rows=rows, cols=cols, spacing=TIGHT,
                     origin=(560, 560) if rows == 3 else (600, 520))
    det = build_detector(CFG, TemplateLibrary(crop_dirs[crop]))
    for t in (0.3, 1.9, 4.4, 7.7):  # quadros diferentes da animação
        found = det.find_all(game.render(t=t), "wheat_ready")
        expected = [game.screen_center(i) for i in range(rows * cols)]
        assert len(found) == rows * cols, (t, [str(m) for m in found])
        assert centers_match(found, expected)


@pytest.mark.parametrize("crop", [(60, 30), (118, 60)])
@pytest.mark.parametrize("origin", [(410, 520), (820, 500), (640, 380), (600, 760)])
def test_ready_in_different_screen_positions_including_edges(crop_dirs, crop, origin):
    game = SceneGame(["ready"] * 9, spacing=TIGHT, origin=origin)
    det = build_detector(CFG, TemplateLibrary(crop_dirs[crop]))
    img = game.render(t=1.1)
    visible = [game.screen_center(i) for i in range(9)
               if 12 <= game.screen_center(i)[0] <= 628 and 8 <= game.screen_center(i)[1] <= 472]
    found = det.find_all(img, "wheat_ready")
    assert len(found) == len(visible) and centers_match(found, visible), [str(m) for m in found]
    assert all(0 <= m.center[0] < 640 and 0 <= m.center[1] < 480 for m in found)  # clicável


def test_ready_with_different_animation_phases_per_field(tdir):
    game = SceneGame(["ready"] * 9, spacing=TIGHT, phases=True, seed=11)
    det = build_detector(CFG, TemplateLibrary(tdir))
    counts = [len(det.find_all(game.render(t=t), "wheat_ready")) for t in (0.2, 0.9, 2.6, 5.1, 8.3)]
    assert counts == [9] * 5


def test_explained_reports_reason_for_discards(tdir):
    game = SceneGame(["ready"] * 9, spacing=TIGHT)
    det = build_detector(CFG, TemplateLibrary(tdir))
    found, rejected = det.find_all_explained(game.render(t=1.0), "wheat_ready", threshold=0.99)
    assert len(found) < 9
    assert rejected and all(why for _, why in rejected)
    assert any("abaixo do limiar" in why for _, why in rejected)


# ============================================================ 2) espaços de plantio
@pytest.mark.parametrize("crop", CROPS)
def test_all_empty_spaces_listed_exactly_once(crop_dirs, crop):
    game = SceneGame(["empty"] * 9, spacing=TIGHT)
    det = build_detector(CFG, TemplateLibrary(crop_dirs[crop]))
    empty = det.find_all(game.render(), "wheat_empty")
    assert len(empty) == 9, [str(m) for m in empty]  # nem espaços a menos, nem duplicados
    assert centers_match(empty, [game.screen_center(i) for i in range(9)])


def test_some_occupied_some_free(tdir):
    layout = ["empty", "growing", "ready", "growing", "empty", "empty", "ready", "growing", "empty"]
    game = SceneGame(layout, spacing=TIGHT)
    b = make_bot(tdir, game)
    scan = b.scan_fields(game.render(t=0.7), "teste")
    for key in ("empty", "ready", "growing"):
        exp = [game.screen_center(i) for i, s in enumerate(layout) if s == key]
        got = getattr(scan, key)
        assert len(got) == len(exp) and centers_match(got, exp), (key, [str(m) for m in got])


# ======================================================= 3) detecções próximas
@pytest.mark.parametrize("crop", [(40, 22), (60, 30)])
def test_sparse_ready_neighbors_are_not_merged(crop_dirs, crop):
    """Só 4 prontos: um par vizinho e dois isolados. O par NÃO pode virar um só."""
    layout = ["growing"] * 16
    for i in (0, 1, 10, 15):  # 0 e 1 vizinhos; 10 e 15 afastados
        layout[i] = "ready"
    game = SceneGame(layout, rows=4, cols=4, spacing=TIGHT, origin=(600, 520))
    tdir = crop_dirs[crop]
    det = build_detector(CFG, TemplateLibrary(tdir))
    img = game.render(t=0.8)
    found = det.find_all(img, "wheat_ready")
    exp = [game.screen_center(i) for i in (0, 1, 10, 15)]
    assert len(found) == 4 and centers_match(found, exp), [str(m) for m in found]
    b = make_bot(tdir, game)
    scan = b.scan_fields(img)
    assert len(scan.ready) == 4 and centers_match(scan.ready, exp)
    assert len(scan.growing) == 12



def test_iso_nms_keeps_isometric_neighbors_and_merges_echoes():
    w, h = 60, 30
    a = Match("wheat_ready", 100, 100, w, h, 0.95)
    diag = Match("wheat_ready", 100 + w // 2, 100 + h // 2, w, h, 0.90)    # vizinho diagonal
    side = Match("wheat_ready", 100 + w, 100, w, h, 0.90)                  # vizinho na mesma linha
    echo = Match("wheat_ready", 100 + 20, 100 + 2, w, h, 0.84)             # eco dentro do mesmo campo
    kept = ImageDetector._nms([a, diag, side, echo], 40)
    assert a in kept and diag in kept and side in kept and echo not in kept


def test_large_crop_does_not_suppress_neighbors():
    """Recorte do tamanho do campo inteiro: vizinhos a meia largura/altura não podem sumir."""
    root = tempfile.mkdtemp()
    make_templates(root, crop=(118, 60))
    game = SceneGame(["ready"] * 9, spacing=TIGHT)
    det = build_detector(CFG, TemplateLibrary(root))
    assert len(det.find_all(game.render(t=0.4), "wheat_ready")) == 9


# ========================================================= 4) cliques confirmados
def test_click_with_visual_change_is_confirmed(tdir, caplog):
    game = SceneGame(["empty"] * 9, spacing=TIGHT)
    b = make_bot(tdir, game)
    caplog.set_level(logging.INFO, logger="haydaybot")
    x, y = game.screen_center(4)
    res = b.tap_confirmed((x, y), "abrir menu", lambda im: b.detector.find(im, "seed_wheat"))
    assert res is not None and len(game.taps) == 1
    assert "Ação confirmada" in caplog.text and "NÃO confirmada" not in caplog.text


def test_click_without_visual_change_is_not_confirmed(tdir, caplog):
    game = SceneGame(["empty"] * 9, spacing=TIGHT)
    game.drop_taps = 99  # o jogo ignora todos os toques
    b = make_bot(tdir, game)
    caplog.set_level(logging.INFO, logger="haydaybot")
    res = b.tap_confirmed(game.screen_center(4), "abrir menu",
                          lambda im: b.detector.find(im, "seed_wheat"), attempts=2)
    assert res is None
    assert len(game.taps) == 2  # tentou de novo, mas não ficou clicando sem parar
    assert caplog.text.count("NÃO confirmada") == 2


def test_dropped_click_is_retried_with_recalculated_position(tdir, caplog):
    game = SceneGame(["empty"] * 9, spacing=TIGHT)
    game.drop_taps = 1
    b = make_bot(tdir, game)
    caplog.set_level(logging.INFO, logger="haydaybot")
    scan = b.scan_fields(game.render())
    tool = b.open_tool_menu(b.order_path(scan.empty), "seed_wheat", "plantar", "empty")
    assert tool is not None and len(game.taps) == 2
    assert "NÃO confirmada" in caplog.text and "Ação confirmada" in caplog.text


def test_menu_already_open_absorbs_first_tap(tdir, caplog):
    game = SceneGame(["empty"] * 4 + ["ready"] * 5, spacing=TIGHT)
    game.tap(*game.screen_center(6))  # menu da foice aberto
    assert game.menu[0] == "sickle"
    b = make_bot(tdir, game)
    caplog.set_level(logging.INFO, logger="haydaybot")
    scan = b.scan_fields(game.render())
    tool = b.open_tool_menu(b.order_path(scan.empty), "seed_wheat", "plantar", "empty")
    assert tool is not None and game.menu[0] == "seed_wheat"
    assert "Outro menu" in caplog.text


# ============================================== 5) plantio/colheita com confirmação
def test_plant_confirms_every_field_and_retries_missed(tdir, caplog):
    game = SceneGame(["empty"] * 9, spacing=TIGHT)
    game.drag_miss = {2, 7}  # o arrasto "passa" por 2 campos sem o jogo registrar
    b = make_bot(tdir, game)
    caplog.set_level(logging.INFO, logger="haydaybot")
    assert b.st_plant(b.machine.context) == State.WAIT_GROWTH
    assert game.states() == ["growing"] * 9
    assert b.stats.fields_planted == 9
    assert "Passagem 1/3: 9 alvos -> 7 confirmados" in caplog.text
    assert "Passagem 2/3: 2 alvos -> 2 confirmados" in caplog.text


def test_plant_only_counts_what_really_changed(tdir):
    game = SceneGame(["empty"] * 9, spacing=TIGHT)
    game.wheat = 5  # só há semente para 5 campos
    b = make_bot(tdir, game)
    b.st_plant(b.machine.context)
    assert b.stats.fields_planted == 5 == game.states().count("growing")


def test_harvest_all_adjacent_ready(tdir):
    game = SceneGame(["ready"] * 9, spacing=TIGHT)
    b = make_bot(tdir, game)
    assert b.st_harvest(b.machine.context) == State.SELL
    assert game.states() == ["empty"] * 9 and b.stats.fields_harvested == 9


def test_stuck_ready_is_not_ignored_forever_and_planting_continues(tdir, monkeypatch):
    layout = ["ready"] + ["empty"] * 8
    game = SceneGame(layout, spacing=TIGHT)
    game.drag_miss = {0}
    b = make_bot(tdir, game, action_retries=0)
    # 1ª colheita: o único trigo não responde -> fica em espera, não trava o ciclo
    with pytest.raises(Exception):
        b.st_harvest(b.machine.context)
    assert b.st_check_field(b.machine.context) == State.PLANT  # planta os vazios mesmo assim
    # passado o tempo de espera, ele volta a ser colhido
    monkeypatch.setattr(botmod, "STUCK_TTL", 0)
    assert b.st_check_field(b.machine.context) == State.HARVEST
    b.st_harvest(b.machine.context)
    assert game.states()[0] == "empty"
