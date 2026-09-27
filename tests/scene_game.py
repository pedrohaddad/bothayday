"""Hay Day simulado com gráficos realistas (cena de farm_scene.py) para testar a LÓGICA do bot:
lista de plantações, menus, cliques confirmados e arrastos.

Reproduz comportamentos do jogo real:
  * tocar numa plantação vazia/pronta abre o menu (semente/foice) ao lado dela;
  * com um menu aberto, o próximo toque apenas FECHA o menu (o toque é "consumido");
  * arrastar a ferramenta sobre as plantações planta/colhe as que o dedo cruza;
  * cada trigo balança numa fase diferente (animação).
Falhas simuláveis: toques ignorados (`drop_taps`) e plantações que o arrasto não registra
(`drag_miss`).
"""

import os
import time

import cv2
import numpy as np

from farm_scene import FarmWorld, H, W, screenshot, world_to_screen
from image_detector import imwrite_unicode

FIELD_HALF = (62, 34)  # meia largura/altura do losango de uma plantação no mundo


def draw_tool(img, tool, x, y):
    x, y = int(x), int(y)
    cv2.circle(img, (x, y), 17, (235, 235, 235), -1)
    cv2.circle(img, (x, y), 17, (60, 60, 60), 2)
    if tool == "seed_wheat":
        cv2.ellipse(img, (x, y), (8, 12), 20, 0, 360, (60, 190, 235), -1)
        for k in (-4, 0, 4):
            cv2.line(img, (x - 5, y + k), (x + 5, y + k - 3), (30, 110, 160), 1)
    else:  # foice
        cv2.ellipse(img, (x + 2, y - 2), (10, 10), 0, 180, 360, (110, 110, 110), 4)
        cv2.line(img, (x - 8, y - 2), (x - 3, y + 11), (40, 80, 140), 3)
    return img


class SceneGame:
    def __init__(self, layout, rows=3, cols=3, spacing=(62, 34), origin=(560, 560), zoom=1.0,
                 phases=True, seed=5):
        self.world = FarmWorld(fields=list(layout), rows=rows, cols=cols, spacing=spacing, origin=origin)
        rng = np.random.default_rng(seed)
        for f in self.world.fields:
            f["phase"] = float(rng.uniform(0, 6.28)) if phases else 0.0
        self.zoom = zoom
        self.t0 = time.time()
        self.menu = None          # (tool, (sx, sy)) em coordenadas de tela
        self.drop_taps = 0        # quantos próximos toques o "jogo" ignora
        self.drag_miss = set()    # índices de plantações que o arrasto não registra (1 vez cada)
        self.taps = []            # histórico de toques recebidos
        self.drags = 0
        self.wheat = 99

    # ----------------------------------------------------------- geometria
    def screen_center(self, i):
        return world_to_screen(self.world.fields[i]["pos"], self.zoom)

    def field_at(self, sx, sy):
        wx = (sx - W / 2) / self.zoom + 700.0
        wy = (sy - H / 2) / self.zoom + 600.0
        for i, f in enumerate(self.world.fields):
            dx, dy = abs(wx - f["pos"][0]), abs(wy - f["pos"][1])
            if dx / FIELD_HALF[0] + dy / FIELD_HALF[1] <= 1.0:
                return i
        return None

    def states(self):
        return [f["st"] for f in self.world.fields]

    # -------------------------------------------------------------- render
    def render(self, t=None):
        t = (time.time() - self.t0) if t is None else t
        img = screenshot(self.world, self.zoom, t=t)
        if self.menu:
            tool, (x, y) = self.menu
            draw_tool(img, tool, x, y)
        return img

    # --------------------------------------------------------------- input
    def tap(self, x, y):
        self.taps.append((int(x), int(y)))
        if self.drop_taps > 0:
            self.drop_taps -= 1
            return
        if self.menu is not None:  # toque com menu aberto só fecha o menu
            self.menu = None
            return
        i = self.field_at(x, y)
        if i is None:
            return
        st = self.world.fields[i]["st"]
        sx, sy = self.screen_center(i)
        if st == "empty":
            self.menu = ("seed_wheat", (sx + 55, sy - 45))
        elif st == "ready":
            self.menu = ("sickle", (sx + 55, sy - 45))

    def drag(self, points):
        self.drags += 1
        if not self.menu:
            return
        tool, (mx, my) = self.menu
        x0, y0 = points[0]
        self.menu = None
        if abs(x0 - mx) > 17 or abs(y0 - my) > 17:
            return  # não pegou a ferramenta
        missed = set(self.drag_miss)
        for x, y in points[1:]:
            i = self.field_at(x, y)
            if i is None or i in missed:
                continue
            f = self.world.fields[i]
            if tool == "seed_wheat" and f["st"] == "empty" and self.wheat > 0:
                f["st"] = "growing"
                self.wheat -= 1
            elif tool == "sickle" and f["st"] == "ready":
                f["st"] = "empty"
        self.drag_miss -= missed  # cada falha simulada acontece uma vez


class SceneADB:
    def __init__(self, game):
        self.game = game
        self.device = "127.0.0.1:21503"

    def screencap(self):
        return self.game.render()

    def tap(self, x, y, hold_ms=0):
        self.game.tap(x, y)

    def swipe(self, x1, y1, x2, y2, d=300):
        if (x1, y1) == (x2, y2):
            self.game.tap(x1, y1)
        else:
            self.game.drag([(x1, y1), (x2, y2)])

    def drag_path(self, points, hold_s=0.2, step_px=40):
        from adb_controller import ADBController
        self.game.drag(ADBController.interpolate(points, step_px))
        return points[-1]

    def supports_motionevent(self): return True
    def keyevent(self, code): self.game.menu = None
    def is_package_installed(self, p): return True
    def foreground_package(self): return "com.supercell.hayday"
    def is_app_running(self, p): return True
    def start_app(self, p): pass
    def stop_app(self, p): pass
    def kill_all(self): pass
    def touch_up(self, x, y): pass
    def is_online(self): return True


def make_templates(root, crop=(60, 30)):
    """Recorta os templates de screenshots da cena, como o usuário faz no emulador."""
    def save(cat, img, cx, cy, w, h, name=None):
        x, y = int(round(cx - w / 2)), int(round(cy - h / 2))
        imwrite_unicode(os.path.join(root, cat, (name or cat) + ".png"), img[y:y + h, x:x + w])

    g = SceneGame(["empty", "ready", "growing"] + ["growing"] * 6, spacing=(70, 38), phases=False)
    a = g.render(t=0.0)
    save("farm", a, 605, 445, 44, 44)
    cw, ch = crop
    save("wheat_empty", a, *g.screen_center(0), cw, ch)
    save("wheat_growing", a, *g.screen_center(2), cw, ch)
    for k, t in enumerate(np.linspace(0, 2.4, 5)):
        save("wheat_ready", g.render(t=float(t)), *g.screen_center(1), cw, ch, f"q{k}")
    for tool, idx in (("seed_wheat", 0), ("sickle", 1)):
        g.menu = None
        g.tap(*g.screen_center(idx))
        img = g.render(t=0.0)
        _, (x, y) = g.menu
        save(tool, img, x, y, 36, 36)
    g.menu = None
    return root
