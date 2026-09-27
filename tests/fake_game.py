"""Simulador mínimo do Hay Day usado nos testes (substitui o ADBController).

Gera templates sintéticos (padrões aleatórios), desenha as telas com eles e
reage a toques e arrastos como o jogo real: menu de semente/foice, banca,
janela de venda, anúncios e caixotes vendidos.
"""

import os
import threading
import time

import cv2
import numpy as np

from image_detector import imwrite_unicode

W, H = 1280, 720
PATCH = (44, 32)  # w, h

CATEGORIES = ["farm", "wheat_empty", "wheat_ready", "wheat_growing", "seed_wheat", "sickle",
              "shop", "shop_screen", "shop_empty_slot", "collect", "shop_on_sale",
              "sell_item_wheat", "sell", "qty_plus", "price_max", "advertise", "back", "confirm"]


def make_patches(seed=7):
    rng = np.random.default_rng(seed)
    patches = {}
    for cat in CATEGORIES:
        small = rng.integers(0, 256, (4, 5, 3), dtype=np.uint8)
        patches[cat] = cv2.resize(small, PATCH, interpolation=cv2.INTER_NEAREST)
    return patches


def write_templates(root, patches):
    for cat, img in patches.items():
        imwrite_unicode(os.path.join(root, cat, f"{cat}.png"), img)


class FakeGame:
    def __init__(self, patches, n_fields=6, grow_s=1.0, sell_s=1.0):
        self.p = patches
        self.grow_s = grow_s
        self.sell_s = sell_s
        self.lock = threading.RLock()
        self.screen = "farm"
        self.running = True
        self.fields = []
        for i in range(n_fields):
            r, c = divmod(i, 3)
            self.fields.append({"pos": (300 + c * 90, 250 + r * 90), "st": "empty", "t": 0})
        self.menu = None  # (tool, (x,y))
        self.crates = [{"st": "empty", "t": 0, "ad": False} for _ in range(4)]
        self.dialog_crate = None
        self.dialog = {}
        self.wheat = 30
        self.coins = 0
        self.ads = 0
        self.popup = False
        self.rects = []
        self.taps = 0
        self.bg = cv2.GaussianBlur(np.random.default_rng(1).integers(60, 200, (H, W, 3), dtype=np.uint8),
                                   (31, 31), 0)

    # --------------------------------------------------------------- render
    def _tick(self):
        now = time.time()
        for f in self.fields:
            if f["st"] == "growing" and now - f["t"] >= self.grow_s:
                f["st"] = "ready"
        for c in self.crates:
            if c["st"] == "on_sale" and now - c["t"] >= self.sell_s:
                c["st"] = "sold"

    def _put(self, img, cat, x, y, tag):
        ph, pw = self.p[cat].shape[:2]
        img[y:y + ph, x:x + pw] = self.p[cat]
        self.rects.append((x, y, pw, ph, tag))

    def render(self):
        with self.lock:
            self._tick()
            img = self.bg.copy()
            self.rects = []
            if self.screen == "farm":
                self._put(img, "farm", 20, 650, ("farm",))
                self._put(img, "shop", 1100, 300, ("shop",))
                for i, f in enumerate(self.fields):
                    cat = {"empty": "wheat_empty", "growing": "wheat_growing", "ready": "wheat_ready"}[f["st"]]
                    self._put(img, cat, f["pos"][0], f["pos"][1], ("field", i))
                if self.menu:
                    tool, (x, y) = self.menu
                    self._put(img, tool, x, y, ("tool", tool))
            elif self.screen == "shop":
                self._put(img, "shop_screen", 600, 30, ("marker",))
                self._put(img, "back", 1200, 30, ("back",))
                for i, c in enumerate(self.crates):
                    cat = {"empty": "shop_empty_slot", "on_sale": "shop_on_sale", "sold": "collect"}[c["st"]]
                    self._put(img, cat, 200 + i * 200, 300, ("crate", i))
            elif self.screen == "sell":
                self._put(img, "back", 1200, 30, ("back",))
                self._put(img, "sell_item_wheat", 200, 300, ("item",))
                self._put(img, "qty_plus", 700, 300, ("qty_plus",))
                self._put(img, "price_max", 700, 400, ("price_max",))
                if not self.dialog.get("ad"):
                    self._put(img, "advertise", 700, 500, ("advertise",))
                self._put(img, "sell", 900, 600, ("sell",))
            elif self.screen == "crate_dialog":
                self._put(img, "back", 1200, 30, ("back",))
                self._put(img, "advertise", 640, 360, ("create_ad",))
            elif self.screen == "confirm":
                self._put(img, "confirm", 640, 400, ("confirm",))
            if self.popup:
                self._put(img, "back", 1000, 100, ("popup_close",))
            return img

    def hit(self, x, y):
        for rx, ry, rw, rh, tag in reversed(self.rects):
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return tag
        return None

    # ---------------------------------------------------------------- input
    def tap(self, x, y):
        with self.lock:
            self.taps += 1
            self.render()
            tag = self.hit(x, y)
            if tag is None:
                self.menu = None
                return
            kind = tag[0]
            if kind == "popup_close":
                self.popup = False
            elif kind == "field":
                f = self.fields[tag[1]]
                if f["st"] == "empty":
                    self.menu = ("seed_wheat", (f["pos"][0] + 60, f["pos"][1] - 60))
                elif f["st"] == "ready":
                    self.menu = ("sickle", (f["pos"][0] + 60, f["pos"][1] - 60))
                else:
                    self.menu = None
            elif kind == "shop":
                self.screen = "shop"
                self.menu = None
            elif kind == "back":
                self.screen = "farm" if self.screen == "shop" else "shop"
            elif kind == "crate":
                c = self.crates[tag[1]]
                if c["st"] == "empty":
                    self.screen, self.dialog_crate, self.dialog = "sell", tag[1], {"qty": 1}
                elif c["st"] == "sold":
                    self.coins += 100
                    c["st"] = "empty"
                elif c["st"] == "on_sale":
                    self.screen, self.dialog_crate = "crate_dialog", tag[1]
            elif kind == "item":
                self.dialog["item"] = True
            elif kind == "qty_plus":
                self.dialog["qty"] = min(10, self.dialog["qty"] + 1)
            elif kind == "price_max":
                self.dialog["max"] = True
            elif kind == "advertise":
                self.dialog["ad"] = True
            elif kind == "sell" and self.dialog.get("item"):
                c = self.crates[self.dialog_crate]
                c.update(st="on_sale", t=time.time(), ad=self.dialog.get("ad", False))
                self.wheat -= self.dialog["qty"]
                self.ads += int(self.dialog.get("ad", False))
                self.screen = "shop"
            elif kind == "create_ad":
                self.screen = "confirm"
            elif kind == "confirm":
                self.ads += 1
                self.screen = "shop"

    def keyevent(self, code):
        with self.lock:
            if code == 4:
                self.popup = False
                if self.screen != "farm":
                    self.screen = "shop" if self.screen in ("sell", "crate_dialog", "confirm") else "farm"

    def drag(self, points):
        with self.lock:
            self.render()
            if not self.menu:
                return
            tool, _ = self.menu
            if self.hit(*points[0]) != ("tool", tool):
                self.menu = None
                return
            for x, y in points[1:]:
                tag = self.hit(x, y)
                if tag and tag[0] == "field":
                    f = self.fields[tag[1]]
                    if tool == "seed_wheat" and f["st"] == "empty" and self.wheat > 0:
                        f.update(st="growing", t=time.time())
                        self.wheat -= 1
                    elif tool == "sickle" and f["st"] == "ready":
                        f["st"] = "empty"
                        self.wheat += 2
            self.menu = None


class FakeADB:
    """Mesma interface usada pelo bot, mas conversando com o FakeGame."""

    def __init__(self, game, motionevent=True, stop_event=None):
        self.game = game
        self.device = "127.0.0.1:21503"
        self._me = motionevent
        self.stop_event = stop_event
        self.offline_once = False

    def _chk(self):
        from adb_controller import ADBInterrupted, DeviceLost
        if self.stop_event is not None and self.stop_event.is_set():
            raise ADBInterrupted("stop")
        if self.offline_once:
            self.offline_once = False
            raise DeviceLost("device offline (simulado)")

    def start_server(self): pass
    def version(self): return "Android Debug Bridge (fake)"
    def online_devices(self): return [self.device]
    def list_devices(self): return [{"serial": self.device, "state": "device", "desc": ""}]
    def connect(self, a): return True, "connected"
    def scan_emulators(self, a=None): return [self.device]
    def boot_completed(self): return True
    def is_online(self): return True
    def kill_all(self): pass
    def touch_up(self, x, y): pass
    def supports_motionevent(self): return self._me
    def is_package_installed(self, p): return True
    def foreground_package(self): return "com.supercell.hayday" if self.game.running else "com.android.launcher"
    def is_app_running(self, p): return self.game.running

    def start_app(self, p):
        self.game.running = True

    def stop_app(self, p):
        self.game.running = False
        self.game.screen = "farm"

    def screencap(self):
        self._chk()
        return self.game.render()

    def tap(self, x, y):
        self._chk()
        self.game.tap(x, y)

    def keyevent(self, c):
        self._chk()
        self.game.keyevent(c)

    def swipe(self, x1, y1, x2, y2, d=300):
        self._chk()
        self.game.drag([(x1, y1), (x2, y2)])

    def drag_path(self, points, hold_s=0.2, step_px=40):
        self._chk()
        from adb_controller import ADBController
        self.game.drag(ADBController.interpolate(points, step_px))
        return points[-1]
