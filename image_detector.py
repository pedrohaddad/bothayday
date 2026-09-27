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
    scale: float = 1.0  # fator de zoom em que foi encontrado

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
        if img.dtype != np.uint8:  # PNG de 16 bits (alguns editores salvam assim)
            img = (img / 257.0).round().clip(0, 255).astype(np.uint8)
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


# Elementos do MUNDO do jogo: mudam de tamanho com o zoom da câmera (pinça), que o
# Hay Day redefine ao abrir e que o jogador altera. Botões/menus (UI) só mudam com a
# resolução. Para estas categorias o detector descobre o zoom sozinho (calibração).
WORLD_CATEGORIES = ("farm", "wheat_empty", "wheat_ready", "wheat_growing", "shop")
# Categorias que com certeza fazem parte do mundo e definem o zoom da câmera. "farm" fica de
# fora porque pode ser um ícone do HUD (não muda com o zoom) ou uma construção (muda).
# Ordem = confiabilidade para medir o zoom (estáticos primeiro; o trigo maduro balança).
ZOOM_REFERENCE = ("wheat_empty", "shop", "wheat_growing", "wheat_ready")


class ImageDetector:
    """Template matching robusto a animação, reamostragem da câmera, zoom e telas escurecidas.

    Etapas para cada categoria:
      1. suaviza tela e template (Gaussian) -> tolera trigo balançando e deslocamentos
         de subpixel da câmera (causa das pontuações 0,5–0,75 com TM_CCOEFF_NORMED puro);
      2. TM_CCOEFF_NORMED em cada escala: resolução + zoom calibrado da câmera;
      3. verificação de cor/contraste de cada candidato -> rejeita regiões de outra cor
         e a fazenda escurecida atrás de uma janela (CCOEFF ignora brilho, por isso
         antes a fazenda era "encontrada" mesmo com um popup aberto);
      4. NMS para remover sobreposições.
    """

    def __init__(self, library, threshold=0.8, thresholds=None, template_width=1280, scales=(1.0,),
                 blur_sigma=2.0, color_tolerance=30.0, auto_zoom=True, zoom_range=(0.6, 1.6),
                 calibration_interval=10.0, abort_check=None):
        self.library = library
        self.threshold = float(threshold)
        self.thresholds = dict(thresholds or {})
        self.template_width = int(template_width) or 1280
        self.scales = list(scales) or [1.0]
        self.blur_sigma = float(blur_sigma)
        self.color_tolerance = float(color_tolerance)
        self.auto_zoom = bool(auto_zoom)
        self.zoom_range = (float(zoom_range[0]), float(zoom_range[1]))
        self.calibration_interval = float(calibration_interval)
        # Chamado entre escalas da calibração; se retornar True, a calibração é abandonada
        # (o bot usa isso para o PARAR/F8 ser imediato).
        self.abort_check = abort_check
        self.learned = {}        # categoria -> fator de zoom descoberto
        self.world_zoom = None   # último zoom de câmera descoberto (vale p/ todo o mundo)
        self._last_calibration = {}
        self._scaled_cache = {}
        self._prep = (None, {})  # (imagem original, {sigma: imagem suavizada})

    # ------------------------------------------------------------ utilidades
    def threshold_for(self, category):
        return float(self.thresholds.get(category, self.threshold))

    def reset_calibration(self):
        self.learned.clear()
        self.world_zoom = None
        self._last_calibration.clear()

    def _sigma(self, img_width, tw, th):
        """Suavização proporcional à resolução (match_blur vale para 640 px de largura),
        limitada pelo tamanho do template para não apagar ícones pequenos."""
        if self.blur_sigma <= 0:
            return 0.0
        sigma = self.blur_sigma * img_width / 640.0
        return round(max(0.6, min(sigma, min(tw, th) / 8.0)), 1)

    @staticmethod
    def _smooth(img, sigma):
        if sigma <= 0:
            return img
        return cv2.GaussianBlur(img, (0, 0), sigma)

    def _prepared(self, img, sigma):
        """Tela suavizada (cache da última imagem; guarda a referência p/ o id não ser reutilizado)."""
        src, cache = self._prep
        if src is not img:
            cache = {}
            self._prep = (img, cache)
        if sigma not in cache:
            cache[sigma] = self._smooth(img, sigma)
        return cache[sigma]

    def _scaled(self, tpl, scale, img_width):
        key = (tpl.path, id(tpl.image), round(scale, 3), img_width)
        hit = self._scaled_cache.get(key)
        if hit is None:
            h, w = tpl.image.shape[:2]
            if abs(scale - 1.0) < 0.005:
                img, mask = tpl.image, tpl.mask
            else:
                size = (max(4, int(round(w * scale))), max(4, int(round(h * scale))))
                interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
                img = cv2.resize(tpl.image, size, interpolation=interp)
                mask = None
                if tpl.mask is not None:
                    mask = cv2.resize(tpl.mask, size, interpolation=cv2.INTER_NEAREST)
            m = mask[:, :, 0] > 0 if mask is not None else None
            pix = img[m] if m is not None else img.reshape(-1, 3)
            stats = (pix.mean(axis=0), pix.std(axis=0).mean()) if pix.size else (np.zeros(3), 0.0)
            if len(self._scaled_cache) > 800:
                self._scaled_cache.clear()
            sigma = self._sigma(img_width, img.shape[1], img.shape[0])
            hit = (self._smooth(img, sigma), mask, img, stats, sigma)
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

    def _verify(self, img, x, y, raw_tpl, mask, stats):
        """Confere se a cor média e o contraste do candidato batem com o template."""
        th, tw = raw_tpl.shape[:2]
        patch = img[y:y + th, x:x + tw]
        if patch.shape[:2] != (th, tw):
            return False
        m = mask[:, :, 0] > 0 if mask is not None else None
        pix = patch[m] if m is not None else patch.reshape(-1, 3)
        if not pix.size:
            return False
        t_mean, t_std = stats
        pix = pix.astype(np.float32)
        if float(np.max(np.abs(pix.mean(axis=0) - t_mean))) > self.color_tolerance:
            return False
        p_std = float(pix.std(axis=0).mean())
        if t_std > 4.0 and not (0.55 <= p_std / t_std <= 1.8):
            return False
        return True

    def factors(self, category):
        """Escalas testadas para a categoria (relativas à resolução dos templates).

        UI: só as escalas do config. Mundo: o zoom calibrado da câmera (x escalas do config),
        porque texturas repetitivas (sulcos do solo) também "cabem" em escalas erradas.
        """
        zoom = None
        if category in WORLD_CATEGORIES:
            zoom = self.learned.get(category)
            if zoom is None:
                zoom = self.world_zoom
        out = [zoom * s for s in self.scales] if zoom is not None else list(self.scales)
        if category not in ZOOM_REFERENCE:
            out += list(self.scales)  # "farm": ícone do HUD (escala fixa) OU construção (zoom)
        uniq = []
        for f in out:
            if all(abs(f - u) > 0.004 for u in uniq):
                uniq.append(f)
        return uniq

    def _candidates(self, img, category, thr, region, per_template, factors=None, stats_out=None,
                    max_templates=None):
        templates = self.library.get(category)[:max_templates]
        if img is None or not templates:
            return []
        ox = oy = 0
        raw = img
        region_slice = None
        if region:
            x, y, w, h = [int(v) for v in region]
            x, y = max(0, x), max(0, y)
            region_slice = (slice(y, y + h), slice(x, x + w))
            raw = img[region_slice]
            ox, oy = x, y
        sh, sw = raw.shape[:2]
        base = img.shape[1] / float(self.template_width)
        cands = []
        for tpl in templates:
            for f in (factors or self.factors(category)):
                t_prep, t_mask, t_raw, t_stats, sigma = self._scaled(tpl, base * f, img.shape[1])
                th, tw = t_prep.shape[:2]
                if th > sh or tw > sw:
                    continue
                prep = self._prepared(img, sigma)
                if region_slice is not None:
                    prep = prep[region_slice]
                res = self._match(prep, t_prep, t_mask)
                found = tries = 0
                while found < per_template and tries < per_template * 4 + 8:
                    tries += 1
                    _, maxv, _, (mx, my) = cv2.minMaxLoc(res)
                    if maxv < thr:
                        break
                    x0, y0 = max(0, mx - tw // 2), max(0, my - th // 2)
                    res[y0:my + th // 2 + 1, x0:mx + tw // 2 + 1] = -1.0
                    ok = self._verify(raw, mx, my, t_raw, t_mask, t_stats)
                    if stats_out is not None:
                        stats_out.append((float(maxv), ok, f))
                    if not ok:
                        continue
                    cands.append(Match(category, mx + ox, my + oy, tw, th, float(maxv), tpl.name, f))
                    found += 1
        return cands

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

    # ----------------------------------------------------------- zoom (mundo)
    def _best_at(self, img, category, factor, max_templates=None):
        found = self._candidates(img, category, 0.3, None, 3, factors=[factor], max_templates=max_templates)
        return max((m.score for m in found), default=0.0)

    def calibrate(self, img, category, threshold=None):
        """Procura o zoom da câmera em que a categoria aparece. Retorna (fator, pontuação)."""
        thr = self.threshold_for(category) if threshold is None else float(threshold)
        self._last_calibration[category] = time.monotonic()
        if not self.library.get(category):
            return None, 0.0
        lo, hi = self.zoom_range
        templates = self.library.get(category)
        base = img.shape[1] / float(self.template_width)
        smallest = min(min(t.image.shape[:2]) for t in templates) * base * lo
        # Busca grossa em meia resolução (4x menos pixels) quando os templates são grandes o bastante.
        coarse_img = cv2.pyrDown(img) if smallest >= 24 else img
        best_f, best_s = None, 0.0
        for f in np.arange(lo, hi + 1e-6, 0.05):
            if self.abort_check and self.abort_check():
                return None, 0.0
            s = self._best_at(coarse_img, category, float(f), max_templates=2)
            if s > best_s:
                best_f, best_s = float(f), s
        if best_f is None:
            return None, 0.0
        best_s = 0.0
        for f in np.arange(best_f - 0.04, best_f + 0.0401, 0.02):
            if self.abort_check and self.abort_check():
                return None, 0.0
            if lo - 0.05 <= f <= hi + 0.05:
                s = self._best_at(img, category, float(f))
                if s > best_s:
                    best_f, best_s = float(f), s
        # Só troca de escala se ela for CLARAMENTE melhor que as do config: texturas repetitivas
        # (sulcos, trigo) "cabem" em escalas erradas com pontuação parecida.
        for f in self.scales:
            if self.abort_check and self.abort_check():
                return None, 0.0
            s = self._best_at(img, category, float(f))
            if s >= best_s - 0.05:
                best_f, best_s = float(f), s
                break
        if best_s >= thr:
            self.learned[category] = round(best_f, 3)
            if category in ZOOM_REFERENCE:
                self.world_zoom = round(best_f, 3)
        return round(best_f, 3), best_s

    def calibrate_world(self, img, force=False):
        """Descobre o zoom atual da câmera usando TODOS os elementos do mundo visíveis.

        Para cada escala calcula a média das pontuações de campos, trigo e banca. Texturas
        repetitivas (miolo do solo) pontuam alto em várias escalas; objetos com contorno
        (banca, trigo) têm um pico nítido — a média escolhe a escala certa. Só troca de uma
        escala do config se a nova for claramente melhor. Limitado a 1x a cada
        `calibration_interval` s (salvo force=True). Retorna o zoom ou None.
        """
        if not self.auto_zoom or img is None:
            return None
        now = time.monotonic()
        if not force and now - self._last_calibration.get("__world__", -1e9) < self.calibration_interval:
            return None
        self._last_calibration["__world__"] = now
        cats = [c for c in ZOOM_REFERENCE if self.library.get(c)]
        lo, hi = self.zoom_range
        base = img.shape[1] / float(self.template_width)
        zoom = None
        if cats:
            smallest = min(min(t.image.shape[:2]) for c in cats for t in self.library.get(c)) * base * lo
            coarse_img = cv2.pyrDown(img) if smallest >= 24 else img
            zs = [float(z) for z in np.arange(lo, hi + 1e-6, 0.05)]
            curves = {}
            for c in cats:
                curve = []
                for z in zs:
                    if self.abort_check and self.abort_check():
                        return None
                    curve.append(self._best_at(coarse_img, c, z, max_templates=2))
                curves[c] = curve
            thr = min(self.threshold_for(c) for c in cats)
            present = [c for c in cats if max(curves[c]) >= thr - 0.05]
            if present:
                mean = np.mean([curves[c] for c in present], axis=0)
                z0 = zs[int(np.argmax(mean))]

                def score(z):
                    return float(np.mean([self._best_at(img, c, z) for c in present]))
                best_z, best_s = z0, -1.0
                for z in np.arange(z0 - 0.04, z0 + 0.0401, 0.02):
                    if self.abort_check and self.abort_check():
                        return None
                    sc = score(float(z))
                    if sc > best_s:
                        best_z, best_s = float(z), sc
                for f in self.scales:  # prefere a escala do config se praticamente empata
                    if score(float(f)) >= best_s - 0.03:
                        best_z = float(f)
                        break
                if max(self._best_at(img, c, best_z) for c in present) >= thr:
                    zoom = round(best_z, 3)
                    self.world_zoom = zoom
                    for c in cats:
                        self.learned.pop(c, None)
        # "farm" pode ser HUD ou construção: se não aparece nas escalas atuais, calibra à parte.
        if self.library.get("farm") and not self._nms(self._candidates(img, "farm", self.threshold_for("farm"),
                                                                       None, 1), 1):
            self.calibrate(img, "farm")
        return zoom

    # ---------------------------------------------------------------- busca
    def find_all(self, img, category, threshold=None, region=None, max_results=40):
        thr = self.threshold_for(category) if threshold is None else float(threshold)
        found = self._nms(self._candidates(img, category, thr, region, max_results), max_results)
        if found and self.world_zoom is None and category in ZOOM_REFERENCE:
            # 1º elemento do mundo visto nesta sessão: confirma o zoom pela MELHOR escala,
            # medida no elemento mais estável visível (solo vazio > banca > trigo).
            if self.auto_zoom:
                self.calibrate_world(img, force=True)
            if self.world_zoom is None:
                self.world_zoom = round(found[0].scale, 3)
            found = self._nms(self._candidates(img, category, thr, region, max_results), max_results)
        return found

    def find(self, img, category, threshold=None, region=None):
        found = self.find_all(img, category, threshold, region, max_results=1)
        return found[0] if found else None

    def best_score(self, img, category, region=None):
        """Maior pontuação VERIFICADA nas escalas atuais (mesmo abaixo do limiar)."""
        found = self._candidates(img, category, 0.0, region, 1)
        return max((m.score for m in found), default=0.0)

    def diagnose(self, img, category):
        """Explica por que uma categoria é ou não encontrada (usado no log e no teste)."""
        info = {"templates": self.library.count(category), "threshold": self.threshold_for(category),
                "factors": self.factors(category)}
        stats = []
        self._candidates(img, category, 0.0, None, 1, stats_out=stats)
        info["best"] = max((s for s, ok, _ in stats if ok), default=0.0)
        info["best_rejected"] = max((s for s, ok, _ in stats if not ok), default=0.0)
        if category in WORLD_CATEGORIES:
            saved = (dict(self.learned), self.world_zoom, dict(self._last_calibration))
            f, s = self.calibrate(img, category, 2.0)  # só mede, não aprende
            self.learned, self.world_zoom, self._last_calibration = saved
            info["best_zoom"], info["best_zoom_score"] = f, s
        return info

    @staticmethod
    def describe(category, info):
        txt = (f"{category}: {info['templates']} template(s), melhor {info['best']:.2f} "
               f"(limiar {info['threshold']:.2f}, escalas {', '.join(f'{f:.2f}' for f in info['factors'])})")
        if info.get("best_rejected", 0) > info["best"]:
            txt += f"; {info['best_rejected']:.2f} rejeitado pela cor/brilho (janela por cima?)"
        if info.get("best_zoom") is not None:
            txt += f"; com zoom {info['best_zoom']:.2f}: {info['best_zoom_score']:.2f}"
        return txt

    @staticmethod
    def annotate(img, matches, color=(0, 0, 255)):
        out = img.copy()
        for m in matches:
            cv2.rectangle(out, (m.x, m.y), (m.x + m.w, m.y + m.h), color, 2)
            cv2.putText(out, f"{m.score:.2f}", (m.x, max(12, m.y - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
        return out


def build_detector(cfg, library, abort_check=None):
    """Cria o detector a partir do config — usado pelo bot E pela janela 'Testar detecção'."""
    from config import parse_resolution
    tw, _ = parse_resolution(cfg.get("template_resolution", "1280x720"))
    return ImageDetector(library, cfg.get("match_threshold", 0.8), cfg.get("thresholds", {}), tw,
                         cfg.get("scales", [1.0]), blur_sigma=cfg.get("match_blur", 1.2),
                         color_tolerance=cfg.get("color_tolerance", 30),
                         auto_zoom=cfg.get("auto_zoom", True),
                         zoom_range=cfg.get("zoom_range", (0.6, 1.6)), abort_check=abort_check)
