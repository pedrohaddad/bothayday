"""Reconhecimento em condições reais do jogo (cena de fazenda renderizada por câmera).

Os templates são recortados de UM screenshot e testados em OUTROS screenshots com:
zoom de câmera diferente, deslocamento de subpixel, trigo balançando (animação) e
janela escurecendo a fazenda — exatamente o que derrubava as pontuações para 0,5–0,75.
"""

import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfgmod  # noqa: E402
from bot import HayDayBot  # noqa: E402
from farm_scene import FarmWorld, screenshot, world_to_screen  # noqa: E402
from image_detector import TemplateLibrary, build_detector, imwrite_unicode  # noqa: E402
from state_machine import State, StepContext  # noqa: E402

LAYOUT = ["empty", "ready", "growing", "empty", "growing", "ready", "growing", "empty", "growing"]
CFG = cfgmod.normalize({"template_resolution": "640x480", "resolution": "640x480",
                        "match_threshold": 0.80, "scales": [1.0]})


def _screen_pt(world, i, zoom=1.0):
    return world_to_screen(world.fields[i]["pos"], zoom)


@pytest.fixture(scope="module")
def tdir(tmp_path_factory):
    """Recorta os templates de screenshots com zoom 1.0 — como o usuário faz no emulador."""
    root = str(tmp_path_factory.mktemp("templates"))
    world = FarmWorld(fields=LAYOUT)
    a = screenshot(world, 1.0, t=0.0)

    def save(cat, img, x, y, w, h, name=None):
        imwrite_unicode(os.path.join(root, cat, (name or cat) + ".png"), img[y:y + h, x:x + w])

    save("farm", a, 583, 423, 44, 44)                                     # engrenagem do HUD
    ex, ey = [int(round(v)) for v in _screen_pt(world, 0)]
    save("wheat_empty", a, ex - 30, ey - 15, 60, 30)
    rx, ry = [int(round(v)) for v in _screen_pt(world, 1)]
    for k, t in enumerate((0.0, 0.6, 1.2, 1.8, 2.4)):                      # quadros da animação
        save("wheat_ready", screenshot(world, 1.0, t=t), rx - 30, ry - 22, 60, 36, f"q{k}")
    sx, sy = [int(round(v)) for v in world_to_screen((922, 710))]
    save("shop", a, sx - 45, sy - 32, 90, 62)
    p = screenshot(world, 1.0, popup=True)
    save("back", p, 462, 106, 32, 32)                                     # X da janela
    return root


def _near(matches, pts, tol=12):
    return all(any(abs(m.center[0] - x) < tol and abs(m.center[1] - y) < tol for m in matches)
               for x, y in pts)


CONDITIONS = [
    # zoom, deslocamento da câmera (subpixel), tempo da animação
    (1.0, (0.0, 0.0), 0.0), (1.0, (0.4, -0.3), 0.9), (1.0, (-0.5, 0.2), 7.3),
    (0.9, (0.0, 0.0), 1.1), (1.12, (0.3, 0.1), 3.7), (0.8, (0.0, 0.0), 5.2), (1.25, (0.0, 0.0), 2.2),
]


@pytest.mark.parametrize("zoom,shift,t", CONDITIONS)
def test_recognizes_farm_fields_and_wheat(tdir, zoom, shift, t):
    world = FarmWorld(fields=LAYOUT)
    img = screenshot(world, zoom, cx=700 + shift[0], cy=600 + shift[1], t=t)
    det = build_detector(CFG, TemplateLibrary(tdir))
    farm = det.find(img, "farm")
    assert farm is not None and farm.score >= 0.8
    if not det.find_all(img, "wheat_empty"):  # igual ao CHECK_FIELD: sem campos -> calibra o zoom
        assert det.calibrate_world(img) is not None
    empty = det.find_all(img, "wheat_empty")
    ready = det.find_all(img, "wheat_ready")
    exp_empty = [_screen_pt(world, i, zoom) for i, s in enumerate(LAYOUT) if s == "empty"]
    exp_ready = [_screen_pt(world, i, zoom) for i, s in enumerate(LAYOUT) if s == "ready"]
    assert len(empty) == len(exp_empty) and _near(empty, exp_empty), (empty, det.learned)
    assert len(ready) == len(exp_ready) and _near(ready, exp_ready), (ready, det.learned)
    assert all(m.score >= 0.8 for m in empty + ready)
    sx, _ = world_to_screen((922 + 45, 710), zoom)
    if sx < 640:  # banca inteira na tela
        assert det.find(img, "shop") is not None


@pytest.mark.parametrize("zoom", [1.0, 0.9, 1.12])
def test_no_false_positives(tdir, zoom):
    world = FarmWorld(fields=["growing", "empty", "growing", "growing", "empty", "growing",
                              "growing", "growing", "growing"])
    det = build_detector(CFG, TemplateLibrary(tdir))
    img = screenshot(world, zoom, t=1.3)
    det.calibrate_world(img, force=True)
    assert det.find_all(img, "wheat_ready") == []              # nenhum trigo pronto na tela
    assert len(det.find_all(img, "wheat_empty")) == 2          # só os 2 vazios, não os crescendo
    assert det.find(img, "back") is None                        # nenhuma janela aberta


def test_dimmed_farm_behind_popup_is_not_the_farm(tdir):
    world = FarmWorld(fields=LAYOUT)
    det = build_detector(CFG, TemplateLibrary(tdir))
    img = screenshot(world, 1.0, popup=True)
    assert det.find(img, "farm") is None
    assert det.find_all(img, "wheat_empty") == []
    assert det.find(img, "back") is not None


def test_diagnose_reports_zoom(tdir):
    world = FarmWorld(fields=LAYOUT)
    det = build_detector(CFG, TemplateLibrary(tdir))
    img = screenshot(world, 0.75, t=0.4)
    info = det.diagnose(img, "wheat_empty")
    assert info["best"] < 0.8                      # na escala 1.0 não serve...
    assert abs(info["best_zoom"] - 0.75) <= 0.06 and info["best_zoom_score"] >= 0.9  # ...e o zoom certo é apontado
    assert "zoom 0.7" in det.describe("wheat_empty", info)


# --------------------------------------------------------------- OPEN_GAME
class SceneADB:
    """ADB falso que devolve a cena renderizada; um toque no X fecha a janela."""

    def __init__(self, zoom, popup=False):
        self.world = FarmWorld(fields=LAYOUT)
        self.zoom, self.popup, self.t = zoom, popup, 0.0
        self.device = "127.0.0.1:21503"

    def screencap(self):
        self.t += 0.37
        return screenshot(self.world, self.zoom, cx=700.2, t=self.t, popup=self.popup)

    def tap(self, x, y):
        if self.popup and abs(x - 478) < 18 and abs(y - 122) < 18:
            self.popup = False

    def keyevent(self, code): pass
    def is_package_installed(self, p): return True
    def foreground_package(self): return "com.supercell.hayday"
    def is_app_running(self, p): return True
    def start_app(self, p): pass
    def stop_app(self, p): pass
    def kill_all(self): pass


@pytest.mark.parametrize("zoom,popup", [(1.0, False), (0.85, False), (1.15, True)])
def test_open_game_reaches_farm(tdir, tmp_path, zoom, popup):
    cfg = dict(CFG, action_delay=0.05, check_interval=1, open_game_timeout=30)
    bot = HayDayBot(cfg, tdir, str(tmp_path))
    fake = SceneADB(zoom, popup)
    bot.adb = fake
    bot.screen.adb = fake

    class M:  # contexto mínimo da máquina de estados
        context = StepContext(State.OPEN_GAME, 1, 60)
    bot.machine = M()
    bot.stop_event = threading.Event()
    assert bot.st_open_game(bot.machine.context) == State.CHECK_FIELD
    assert not fake.popup
    if zoom != 1.0:
        assert bot.detector.world_zoom is None or abs(bot.detector.world_zoom - zoom) <= 0.05
