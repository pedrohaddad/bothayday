"""Reconhecimento de elementos do jogo por template matching (OpenCV).

Cada pasta dentro de templates/ é uma CATEGORIA. Todas as imagens da pasta são
variações do mesmo elemento (ex.: dia/noite, com/sem destaque). Basta
adicionar/substituir arquivos .png — a biblioteca recarrega sozinha.
"""

import os
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp")

# nome da pasta -> (obrigatoriedade, descrição do que recortar)
TEMPLATE_CATEGORIES = {
    "farm": ("OBRIGATÓRIO",
             "Marcador da tela da FAZENDA sem nenhuma janela aberta. Recorte um ícone fixo do HUD "
             "que só aparece na fazenda, ex.: o botão de engrenagem (configurações) ou o botão "
             "da loja/caminhão no canto inferior. Não use números (moedas/XP), pois mudam."),
    "wheat_empty": ("OBRIGATÓRIO",
                    "Campo VAZIO (terra arada marrom, sem nada plantado). Recorte só o miolo "
                    "da terra (~60x40 px), sem as bordas de grama, para casar com qualquer campo."),
    "wheat_ready": ("OBRIGATÓRIO",
                    "Campo com TRIGO MADURO (dourado), pronto para colher. Recorte o miolo do trigo."),
    "wheat_growing": ("opcional",
                      "Campo com trigo CRESCENDO (brotos verdes). Usado só para contar campos."),
    "seed_wheat": ("OBRIGATÓRIO",
                   "Ícone do TRIGO no menu circular que aparece ao tocar num campo vazio."),
    "sickle": ("OBRIGATÓRIO",
               "Ícone da FOICE que aparece ao tocar num campo com trigo pronto."),
    "shop": ("obrigatório p/ vender/coletar",
             "A BANCA de beira de estrada (Roadside Shop) vista na fazenda (o telhado/placa)."),
    "shop_screen": ("recomendado",
                    "Marcador da janela da BANCA aberta, ex.: o título/faixa superior da janela."),
    "shop_empty_slot": ("obrigatório p/ vender",
                        "Caixote VAZIO na banca (espaço livre para colocar à venda)."),
    "collect": ("obrigatório p/ coletar",
                "Caixote VENDIDO na banca (aparece com moedas). Tocar nele coleta o dinheiro."),
    "shop_on_sale": ("opcional",
                     "Caixote com produto À VENDA ainda não vendido (para criar anúncio depois)."),
    "sell_item_wheat": ("obrigatório p/ vender",
                        "Ícone do TRIGO na lista de itens da janela de venda (lado esquerdo)."),
    "silo_tab": ("opcional",
                 "Aba do SILO na janela de venda (se o trigo não aparecer direto)."),
    "sell": ("obrigatório p/ vender",
             "Botão 'Colocar à venda' (Put on sale) da janela de venda."),
    "qty_plus": ("opcional", "Botão '+' da QUANTIDADE na janela de venda."),
    "qty_minus": ("opcional", "Botão '-' da QUANTIDADE na janela de venda."),
    "price_max": ("opcional", "Botão de PREÇO MÁXIMO (seta para cima) na janela de venda."),
    "price_plus": ("opcional", "Botão '+' do PREÇO na janela de venda."),
    "price_minus": ("opcional", "Botão '-' do PREÇO na janela de venda."),
    "advertise": ("opcional (anúncios)",
                  "Opção de ANUNCIAR disponível: a caixa 'Anunciar' DESMARCADA na janela de venda "
                  "e/ou o botão 'Criar anúncio' que aparece ao tocar num caixote à venda."),
    "advertise_cooldown": ("opcional",
                           "Opção de anúncio EM ESPERA (com relógio/contagem regressiva)."),
    "confirm": ("opcional",
                "Botões de CONFIRMAÇÃO (OK/Sim) usados após criar um anúncio. NUNCA recorte "
                "botões verdes que gastam diamantes."),
    "back": ("OBRIGATÓRIO",
             "Botão de FECHAR (X vermelho) e de voltar das janelas. Pode ter várias imagens."),
    "continue": ("opcional",
                 "Botões inofensivos de avisos: 'Continuar', 'OK' de subir de nível, etc."),
    "silo_full": ("opcional", "Janela/aviso de SILO CHEIO."),
    "reconnect": ("opcional",
                  "Botão 'Tentar novamente'/'Recarregar' da tela de conexão perdida."),
}


def imread_unicode(path, flags=cv2.IMREAD_UNCHANGED):
    """cv2.imread não aceita caminhos com acentos no Windows; isto aceita."""
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)


def imwrite_unicode(path, img):
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        raise IOError(f"Falha ao codificar imagem: {path}")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    buf.tofile(path)
    return path


@dataclass
class Match:
    category: str
    x: int
    y: int
    w: int
    h: int
    score: float
    template: str = ""

    @property
    def center(self):
        return self.x + self.w // 2, self.y + self.h // 2

    def distance(self, other):
        (ax, ay), (bx, by) = self.center, other.center
        return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5

    def same_spot(self, other, factor=0.5):
        return self.distance(other) < min(self.w, self.h, other.w, other.h) * factor

    def __str__(self):
        cx, cy = self.center
        return f"{self.category}@({cx},{cy}) {self.score:.2f}"


@dataclass
class Template:
    name: str
    path: str
    image: np.ndarray
    mask: np.ndarray = None


class TemplateLibrary:
    """Carrega templates das pastas e recarrega quando arquivos mudam."""

    RECHECK_SECONDS = 2.0

    def __init__(self, root):
        self.root = root
        self._cache = {}   # category -> (signature, [Template])
        self._checked = {}  # category -> last check time
        self._lock = threading.Lock()

    def folder(self, category):
        return os.path.join(self.root, category)

    def categories(self):
        if not os.path.isdir(self.root):
            return []
        return sorted(d for d in os.listdir(self.root)
                      if os.path.isdir(os.path.join(self.root, d)) and not d.startswith("."))

    def _files(self, category):
        folder = self.folder(category)
        if not os.path.isdir(folder):
            return []
        return sorted(os.path.join(folder, f) for f in os.listdir(folder)
                      if f.lower().endswith(IMG_EXT))

    def _signature(self, files):
        sig = []
        for f in files:
            try:
                st = os.stat(f)
                sig.append((f, st.st_mtime, st.st_size))
            except OSError:
                pass
        return tuple(sig)

    def get(self, category):
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(category)
            if cached and now - self._checked.get(category, 0) < self.RECHECK_SECONDS:
                return cached[1]
            self._checked[category] = now
            files = self._files(category)
            sig = self._signature(files)
            if cached and cached[0] == sig:
                return cached[1]
            templates = []
            for path in files:
                t = self._load(path)
                if t is not None:
                    templates.append(t)
            self._cache[category] = (sig, templates)
            return templates

    @staticmethod
    def _load(path):
        img = imread_unicode(path, cv2.IMREAD_UNCHANGED)
        if img is None or img.size == 0:
            return None
        mask = None
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            alpha = img[:, :, 3]
            img = img[:, :, :3].copy()
            if alpha.min() < 250:  # PNG com transparência -> usa máscara
                m = (alpha > 127).astype(np.uint8) * 255
                mask = cv2.merge([m, m, m])
        if img.shape[0] < 4 or img.shape[1] < 4:
            return None
        return Template(os.path.basename(path), path, img, mask)

    def count(self, category):
        return len(self.get(category))

    def has(self, category):
        return self.count(category) > 0

    def invalidate(self):
        with self._lock:
            self._cache.clear()
            self._checked.clear()

    def ensure_structure(self):
        """Cria as pastas de todas as categorias com um LEIA-ME explicando o conteúdo."""
        os.makedirs(self.root, exist_ok=True)
        for cat, (req, desc) in TEMPLATE_CATEGORIES.items():
            folder = self.folder(cat)
            os.makedirs(folder, exist_ok=True)
            readme = os.path.join(folder, "LEIA-ME.txt")
            if not os.path.exists(readme):
                with open(readme, "w", encoding="utf-8") as fh:
                    fh.write(f"Pasta: {cat}  [{req}]\n\n{desc}\n\n"
                             "Coloque aqui um ou mais recortes .png tirados de screenshots do\n"
                             "emulador NA MESMA RESOLUÇÃO configurada em 'template_resolution'.\n"
                             "Várias imagens = variações aceitas do mesmo elemento.\n"
                             "PNG com transparência: as áreas transparentes são ignoradas.\n")


class ImageDetector:
    def __init__(self, library, threshold=0.8, thresholds=None, template_width=1280, scales=(1.0,)):
        self.library = library
        self.threshold = float(threshold)
        self.thresholds = dict(thresholds or {})
        self.template_width = int(template_width) or 1280
        self.scales = list(scales) or [1.0]
        self._scaled_cache = {}

    def threshold_for(self, category):
        return float(self.thresholds.get(category, self.threshold))

    def _scaled(self, tpl, scale):
        if abs(scale - 1.0) < 0.01:
            return tpl.image, tpl.mask
        key = (tpl.path, id(tpl.image), round(scale, 3))
        hit = self._scaled_cache.get(key)
        if hit is None:
            h, w = tpl.image.shape[:2]
            size = (max(4, int(round(w * scale))), max(4, int(round(h * scale))))
            interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            img = cv2.resize(tpl.image, size, interpolation=interp)
            mask = None
            if tpl.mask is not None:
                mask = cv2.resize(tpl.mask, size, interpolation=cv2.INTER_NEAREST)
            if len(self._scaled_cache) > 500:
                self._scaled_cache.clear()
            hit = (img, mask)
            self._scaled_cache[key] = hit
        return hit

    @staticmethod
    def _match(img, tpl, mask):
        if mask is None:
            res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
        else:
            try:
                res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED, mask=mask)
            except cv2.error:
                res = cv2.matchTemplate(img, tpl, cv2.TM_CCORR_NORMED, mask=mask)
        return np.nan_to_num(res, nan=0.0, posinf=0.0, neginf=0.0)

    def _candidates(self, img, category, thr, region, per_template, collect_best=False):
        templates = self.library.get(category)
        if img is None or not templates:
            return [], 0.0
        ox = oy = 0
        search = img
        if region:
            x, y, w, h = [int(v) for v in region]
            x, y = max(0, x), max(0, y)
            search = img[y:y + h, x:x + w]
            ox, oy = x, y
        sh, sw = search.shape[:2]
        base = img.shape[1] / float(self.template_width)
        cands, best = [], 0.0
        for tpl in templates:
            for s in self.scales:
                t_img, t_mask = self._scaled(tpl, base * s)
                th, tw = t_img.shape[:2]
                if th > sh or tw > sw:
                    continue
                res = self._match(search, t_img, t_mask)
                found = 0
                while found < per_template:
                    _, maxv, _, (mx, my) = cv2.minMaxLoc(res)
                    best = max(best, float(maxv))
                    if maxv < thr:
                        break
                    cands.append(Match(category, mx + ox, my + oy, tw, th, float(maxv), tpl.name))
                    found += 1
                    x0, y0 = max(0, mx - tw // 2), max(0, my - th // 2)
                    res[y0:my + th // 2 + 1, x0:mx + tw // 2 + 1] = -1.0
        return cands, best

    @staticmethod
    def _nms(cands, max_results):
        cands.sort(key=lambda m: m.score, reverse=True)
        kept = []
        for c in cands:
            if all(not c.same_spot(k) for k in kept):
                kept.append(c)
                if len(kept) >= max_results:
                    break
        return kept

    def find_all(self, img, category, threshold=None, region=None, max_results=40):
        thr = self.threshold_for(category) if threshold is None else float(threshold)
        cands, _ = self._candidates(img, category, thr, region, max_results)
        return self._nms(cands, max_results)

    def find(self, img, category, threshold=None, region=None):
        found = self.find_all(img, category, threshold, region, max_results=1)
        return found[0] if found else None

    def best_score(self, img, category, region=None):
        """Maior pontuação encontrada (mesmo abaixo do limiar) — útil para calibrar."""
        _, best = self._candidates(img, category, 2.0, region, 1)
        return best

    @staticmethod
    def annotate(img, matches, color=(0, 0, 255)):
        out = img.copy()
        for m in matches:
            cv2.rectangle(out, (m.x, m.y), (m.x + m.w, m.y + m.h), color, 2)
            cv2.putText(out, f"{m.score:.2f}", (m.x, max(12, m.y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        return out
