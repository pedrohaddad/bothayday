"""Gerador de cenas de fazenda parecidas com o Hay Day, para testar o reconhecimento.

Reproduz o que acontece no jogo real entre dois screenshots:
  * o MUNDO (campos, trigo, banca, casa) é desenhado por uma câmera com zoom e
    posição contínuos (float) e reamostrado com interpolação bilinear;
  * o trigo maduro BALANÇA (animação) e a grama tem textura;
  * o HUD (botões) é desenhado por cima, em posição fixa e sem zoom;
  * janelas (popups) escurecem a fazenda inteira por trás.
"""

import cv2
import numpy as np

W, H = 640, 480
WORLD = 1400  # tamanho do "mundo" antes da câmera


def _grass(rng):
    base = np.zeros((WORLD, WORLD, 3), np.float32)
    base[:] = (60, 170, 95)  # BGR verde
    noise = rng.normal(0, 18, (WORLD // 4, WORLD // 4, 1)).astype(np.float32)
    noise = cv2.resize(noise, (WORLD, WORLD), interpolation=cv2.INTER_CUBIC)[..., None]
    fine = rng.normal(0, 8, (WORLD, WORLD, 1)).astype(np.float32)
    return np.clip(base + noise + fine, 0, 255).astype(np.uint8)


def _diamond(cx, cy, w, h):
    return np.array([(cx, cy - h), (cx + w, cy), (cx, cy + h), (cx - w, cy)], np.int32)


class FarmWorld:
    """Mundo fixo: posições dos campos, estados e elementos."""

    def __init__(self, seed=3, fields=None, rows=3, cols=3, spacing=(70, 38), origin=(560, 560)):
        """spacing=(62, 34) = campos encostados, como no Hay Day (vizinho a meia largura/altura)."""
        self.rng = np.random.default_rng(seed)
        self.grass = _grass(self.rng)
        # campos em grade isométrica
        self.fields = []
        for r in range(rows):
            for c in range(cols):
                cx = origin[0] + (c - r) * spacing[0]
                cy = origin[1] + (c + r) * spacing[1]
                self.fields.append({"pos": (cx, cy), "st": "empty"})
        if fields:
            for f, st in zip(self.fields, fields):
                f["st"] = st
        self.stalks = [(self.rng.uniform(-30, 30), self.rng.uniform(-14, 14),
                        self.rng.uniform(0, 6.28)) for _ in range(40)]

    def render_world(self, t=0.0):
        img = self.grass.copy()
        # casa (vermelha) e banca (listrada)
        cv2.rectangle(img, (820, 380), (930, 470), (40, 40, 190), -1)
        cv2.fillPoly(img, [np.array([(810, 385), (875, 330), (940, 385)], np.int32)], (30, 70, 120))
        cv2.rectangle(img, (850, 420), (875, 470), (20, 60, 100), -1)
        for i in range(6):  # banca: toldo listrado
            color = (240, 240, 240) if i % 2 else (60, 60, 220)
            cv2.rectangle(img, (880 + i * 14, 680), (894 + i * 14, 700), color, -1)
        cv2.rectangle(img, (880, 700), (964, 740), (70, 120, 170), -1)
        cv2.putText(img, "SHOP", (892, 728), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (230, 230, 250), 2)
        for f in self.fields:
            cx, cy = f["pos"]
            cv2.fillPoly(img, [_diamond(cx, cy, 62, 34)], (40, 85, 140))       # terra
            cv2.polylines(img, [_diamond(cx, cy, 62, 34)], True, (30, 60, 100), 2)
            for k in range(-3, 4):  # sulcos
                cv2.line(img, (cx - 40 + k * 9, cy - 20 + abs(k) * 2), (cx + 40 + k * 9, cy + 20 - abs(k) * 2),
                         (30, 65, 110), 2)
            if f["st"] == "growing":
                for dx, dy, _ in self.stalks[:25]:
                    cv2.circle(img, (int(cx + dx), int(cy + dy)), 3, (40, 190, 60), -1)
            elif f["st"] == "ready":
                for dx, dy, ph in self.stalks:
                    sway = 3.0 * np.sin(t * 2.0 + ph + f.get("phase", 0.0))  # animação do vento
                    x0, y0 = cx + dx, cy + dy + 8
                    x1, y1 = x0 + sway, y0 - 20
                    cv2.line(img, (int(x0), int(y0)), (int(round(x1)), int(round(y1))), (60, 170, 215), 2)
                    cv2.ellipse(img, (int(round(x1)), int(round(y1))), (3, 6), 0, 0, 360, (70, 200, 240), -1)
        return img

    def field_center_world(self, i):
        return self.fields[i]["pos"]


def camera(world_img, zoom=1.0, cx=700.0, cy=600.0):
    """Projeta o mundo na tela 640x480 com zoom/posição float (bilinear, como a GPU)."""
    m = np.array([[zoom, 0, W / 2 - cx * zoom],
                  [0, zoom, H / 2 - cy * zoom]], np.float32)
    return cv2.warpAffine(world_img, m, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def world_to_screen(pt, zoom=1.0, cx=700.0, cy=600.0):
    return (pt[0] - cx) * zoom + W / 2, (pt[1] - cy) * zoom + H / 2


def draw_hud(img):
    # engrenagem (canto inferior direito) e botão de loja (canto inferior esquerdo)
    cv2.circle(img, (605, 445), 20, (90, 90, 90), -1)
    cv2.circle(img, (605, 445), 20, (30, 30, 30), 2)
    for a in range(0, 360, 45):
        x = int(605 + 17 * np.cos(np.radians(a)))
        y = int(445 + 17 * np.sin(np.radians(a)))
        cv2.circle(img, (x, y), 4, (200, 200, 200), -1)
    cv2.circle(img, (605, 445), 7, (230, 230, 230), -1)
    cv2.rectangle(img, (12, 420), (62, 468), (40, 160, 230), -1)
    cv2.rectangle(img, (12, 420), (62, 468), (20, 80, 120), 2)
    cv2.putText(img, "$", (27, 456), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    # barra de moedas com número (muda)
    cv2.rectangle(img, (440, 8), (630, 36), (40, 40, 40), -1)
    return img


def screenshot(world, zoom=1.0, cx=700.0, cy=600.0, t=0.0, popup=False):
    img = camera(world.render_world(t), zoom, cx, cy)
    img = draw_hud(img)
    if popup:  # janela por cima: escurece tudo e desenha um painel
        img = np.clip(img.astype(np.float32) * 0.45, 0, 255).astype(np.uint8)
        cv2.rectangle(img, (150, 110), (490, 370), (170, 220, 240), -1)
        cv2.circle(img, (478, 122), 16, (40, 40, 220), -1)
    return img
