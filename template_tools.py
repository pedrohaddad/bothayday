"""Janelas auxiliares: recortar templates de um screenshot e testar a detecção."""

import datetime
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from image_detector import TEMPLATE_CATEGORIES, WORLD_CATEGORIES, imread_unicode, imwrite_unicode

# Elementos animados (balançam/piscam): salvar vários quadros como variações.
ANIMATED_DEFAULT = {"wheat_ready", "wheat_growing"}

MAX_VIEW_W = 1100
MAX_VIEW_H = 640


def to_photo(img_bgr, max_w=MAX_VIEW_W, max_h=MAX_VIEW_H):
    """Converte BGR -> PhotoImage redimensionado. Retorna (photo, escala)."""
    h, w = img_bgr.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    if scale < 1.0:
        pil = pil.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return ImageTk.PhotoImage(pil), scale


class TemplateCropper(tk.Toplevel):
    """Mostra um screenshot; arraste o mouse para selecionar e salve na pasta da categoria."""

    def __init__(self, master, image_bgr, templates_dir, screenshots_dir, capture_cb=None,
                 on_saved=None, source=""):
        super().__init__(master)
        self.title("Recortar template")
        self.source = source
        self.templates_dir = templates_dir
        self.screenshots_dir = screenshots_dir
        self.capture_cb = capture_cb
        self.on_saved = on_saved
        self.img = None
        self.scale = 1.0
        self.sel = None
        self._start = None
        self._rect = None

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Categoria:").pack(side="left")
        cats = sorted(set(TEMPLATE_CATEGORIES) | set(self._existing_dirs()))
        self.cat_var = tk.StringVar(value=cats[0] if cats else "farm")
        self.cat_box = ttk.Combobox(top, textvariable=self.cat_var, values=cats, width=20)
        self.cat_box.pack(side="left", padx=4)
        self.cat_box.bind("<<ComboboxSelected>>", lambda e: self._update_hint())
        ttk.Label(top, text="Nome:").pack(side="left", padx=(10, 0))
        self.name_var = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.name_var, width=22).pack(side="left", padx=4)
        ttk.Button(top, text="Salvar recorte", command=self.save).pack(side="left", padx=4)
        ttk.Button(top, text="Abrir imagem...", command=self.open_image).pack(side="left", padx=4)
        if capture_cb:
            ttk.Button(top, text="Capturar nova", command=self.capture_new).pack(side="left", padx=4)
        self.frames_var = tk.IntVar(value=0)
        if capture_cb:
            ttk.Label(top, text="Quadros extras da animação:").pack(side="left", padx=(10, 0))
            ttk.Spinbox(top, from_=0, to=8, textvariable=self.frames_var, width=3).pack(side="left", padx=2)

        self.hint = ttk.Label(self, text="", wraplength=1050, foreground="#555", padding=(6, 0))
        self.hint.pack(fill="x")
        self.info = ttk.Label(self, text="Arraste com o botão esquerdo para selecionar a área.",
                              padding=(6, 2))
        self.info.pack(fill="x")

        self.canvas = tk.Canvas(self, bg="#222", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)

        prev = ttk.Frame(self, padding=6)
        prev.pack(fill="x")
        ttk.Label(prev, text="Prévia do recorte (tamanho real):").pack(side="left")
        self.preview = ttk.Label(prev)
        self.preview.pack(side="left", padx=8)

        self._update_hint()
        if image_bgr is not None:
            self.set_image(image_bgr)
        self.transient(master)

    def _existing_dirs(self):
        if not os.path.isdir(self.templates_dir):
            return []
        return [d for d in os.listdir(self.templates_dir)
                if os.path.isdir(os.path.join(self.templates_dir, d))]

    def _update_hint(self):
        cat = self.cat_var.get()
        req, desc = TEMPLATE_CATEGORIES.get(cat, ("personalizado", "Categoria personalizada."))
        extra = ""
        if cat in ANIMATED_DEFAULT:
            extra = ("  • Elemento ANIMADO: salve com 4 quadros extras (a câmera não pode se mexer "
                     "durante a captura).")
            if self.capture_cb:
                self.frames_var.set(4)
        elif self.capture_cb:
            self.frames_var.set(0)
        self.hint.config(text=f"[{req}] {desc}{extra}")

    def set_image(self, img):
        self.img = img
        self.photo, self.scale = to_photo(img)
        self.canvas.delete("all")
        self.canvas.config(width=self.photo.width(), height=self.photo.height())
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.sel = None
        self._rect = None
        h, w = img.shape[:2]
        src = f" — origem: {self.source}" if self.source else ""
        self.info.config(text=f"Imagem {w}x{h} (exibida a {self.scale:.0%}){src}. "
                              "Arraste para selecionar a área.")

    def open_image(self):
        path = filedialog.askopenfilename(parent=self, initialdir=self.screenshots_dir,
                                          filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            img = imread_unicode(path, cv2.IMREAD_COLOR)
            if img is None:
                messagebox.showerror("Erro", "Não foi possível abrir a imagem.", parent=self)
            else:
                self.source = os.path.basename(path)
                self.set_image(img)

    def capture_new(self):
        try:
            img = self.capture_cb()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erro", f"Falha ao capturar: {exc}", parent=self)
            return
        if img is not None:
            self.source = "nova captura"
            self.set_image(img)

    def _press(self, e):
        self._start = (e.x, e.y)
        if self._rect:
            self.canvas.delete(self._rect)
        self._rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#00ff66", width=2)

    def _drag(self, e):
        if self._start and self._rect:
            self.canvas.coords(self._rect, self._start[0], self._start[1], e.x, e.y)

    def _release(self, e):
        if not self._start or self.img is None:
            return
        x1, y1 = self._start
        x2, y2 = e.x, e.y
        self._start = None
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        h, w = self.img.shape[:2]
        rx1, ry1 = int(x1 / self.scale), int(y1 / self.scale)
        rx2, ry2 = min(w, int(x2 / self.scale)), min(h, int(y2 / self.scale))
        if rx2 - rx1 < 6 or ry2 - ry1 < 6:
            self.sel = None
            self.info.config(text="Seleção muito pequena.")
            return
        self.sel = (rx1, ry1, rx2, ry2)
        crop = self.img[ry1:ry2, rx1:rx2]
        self._prev_photo, _ = to_photo(crop, 300, 200)
        self.preview.config(image=self._prev_photo)
        self.info.config(text=f"Seleção: x={rx1} y={ry1} {rx2 - rx1}x{ry2 - ry1} px")

    def save(self):
        if self.img is None or not self.sel:
            messagebox.showwarning("Recorte", "Selecione uma área primeiro.", parent=self)
            return
        cat = self.cat_var.get().strip()
        if not cat or any(c in cat for c in '\\/:*?"<>|'):
            messagebox.showwarning("Recorte", "Categoria inválida.", parent=self)
            return
        name = self.name_var.get().strip() or f"{cat}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
        if not name.lower().endswith(".png"):
            name += ".png"
        path = os.path.join(self.templates_dir, cat, name)
        if os.path.exists(path) and not messagebox.askyesno(
                "Substituir", f"{name} já existe. Substituir?", parent=self):
            return
        x1, y1, x2, y2 = self.sel
        crop = self.img[y1:y2, x1:x2]
        imwrite_unicode(path, crop)
        saved = [path]
        n_frames = 0
        try:
            n_frames = int(self.frames_var.get())
        except (tk.TclError, ValueError):
            pass
        if n_frames > 0 and self.capture_cb:
            saved += self._save_animation_frames(path, crop, n_frames)
        self.name_var.set("")
        self.info.config(text=self._self_check(cat, crop, saved))
        if self.on_saved:
            for p in saved:
                self.on_saved(cat, p)

    def _save_animation_frames(self, path, crop, n):
        """Captura mais telas e salva o MESMO retângulo como variações (quadros da animação)."""
        x1, y1, x2, y2 = self.sel
        base, ext = os.path.splitext(path)
        g0 = cv2.GaussianBlur(crop, (0, 0), 1.5)
        kept = [g0]
        out = []
        self.config(cursor="watch")
        self.update()
        try:
            for i in range(n):
                self.after(350)
                frame = self.capture_cb()
                if frame is None or frame.shape != self.img.shape:
                    break
                c = frame[y1:y2, x1:x2]
                g = cv2.GaussianBlur(c, (0, 0), 1.5)
                sim0 = float(cv2.matchTemplate(g, g0, cv2.TM_CCOEFF_NORMED).max())
                if sim0 < 0.35:  # outro conteúdo: a câmera mexeu ou abriu uma janela
                    break
                if all(float(cv2.matchTemplate(g, k, cv2.TM_CCOEFF_NORMED).max()) < 0.985 for k in kept):
                    p = f"{base}_q{i + 1}{ext}"
                    imwrite_unicode(p, c)
                    kept.append(g)
                    out.append(p)
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("Quadros da animação", f"Falha ao capturar quadros: {exc}", parent=self)
        finally:
            self.config(cursor="")
        return out

    def _self_check(self, cat, crop, saved):
        """Confere se o template salvo é encontrado na própria imagem (mesmo detector do bot)."""
        msg = f"Salvo: {os.path.basename(saved[0])}"
        if len(saved) > 1:
            msg += f" + {len(saved) - 1} quadro(s) da animação"
        det = getattr(self.master, "_tool_detector", None)
        if det is None:
            return msg
        try:
            detector = det()
            detector.library.invalidate()
            info = detector.diagnose(self.img, cat)
            ok = info["best"] >= info["threshold"]
            msg += f".  Autoteste nesta imagem: {info['best']:.2f} " + ("✔" if ok else "✘ (veja o README)")
            if min(crop.shape[:2]) < 12:
                msg += "  • Recorte muito pequeno: prefira ≥ 20 px."
        except Exception as exc:  # noqa: BLE001
            msg += f" (autoteste falhou: {exc})"
        return msg


class DetectionTester(tk.Toplevel):
    """Roda o reconhecimento de uma categoria no screenshot e desenha os resultados."""

    def __init__(self, master, image_bgr, detector, screenshots_dir, capture_cb=None, source=""):
        super().__init__(master)
        self.title("Testar detecção de templates (mesmo detector do bot)")
        self.source = source
        self.detector = detector
        self.screenshots_dir = screenshots_dir
        self.capture_cb = capture_cb
        self.img = image_bgr

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Categoria:").pack(side="left")
        cats = detector.library.categories()
        self.cat_var = tk.StringVar(value=cats[0] if cats else "")
        self.cat_box = ttk.Combobox(top, textvariable=self.cat_var, values=cats, width=20,
                                    state="readonly")
        self.cat_box.pack(side="left", padx=4)
        self.cat_box.bind("<<ComboboxSelected>>", lambda e: self._sync_threshold())
        ttk.Label(top, text="Limiar:").pack(side="left", padx=(10, 0))
        self.thr_var = tk.DoubleVar(value=detector.threshold)
        ttk.Spinbox(top, from_=0.3, to=0.99, increment=0.01, textvariable=self.thr_var,
                    width=6).pack(side="left", padx=4)
        ttk.Button(top, text="Testar", command=self.run).pack(side="left", padx=4)
        ttk.Button(top, text="Testar todas", command=self.run_all).pack(side="left", padx=4)
        ttk.Button(top, text="Abrir imagem...", command=self.open_image).pack(side="left", padx=4)
        if capture_cb:
            ttk.Button(top, text="Capturar nova", command=self.capture_new).pack(side="left", padx=4)
        ttk.Button(top, text="Calibrar zoom", command=self.calibrate).pack(side="left", padx=4)

        self.src_label = ttk.Label(self, text="", padding=(6, 0), foreground="#555")
        self.src_label.pack(fill="x")
        self.result = ttk.Label(self, text="", padding=6, wraplength=1050, justify="left")
        self.result.pack(fill="x")
        self.view = ttk.Label(self)
        self.view.pack(padx=6, pady=6)
        self._sync_threshold()
        self._show(self.img)
        self.transient(master)

    def _sync_threshold(self):
        cat = self.cat_var.get()
        if cat:
            self.thr_var.set(round(self.detector.threshold_for(cat), 2))

    def _show(self, img):
        if img is None:
            self.result.config(text="Nenhuma imagem. Capture uma tela primeiro.")
            return
        h, w = img.shape[:2]
        zoom = self.detector.world_zoom
        self.src_label.config(text=f"Imagem: {self.source or '-'} — {w}x{h}.  Zoom da câmera calibrado: "
                                   f"{f'{zoom:.2f}x' if zoom else 'não'}")
        self.photo, _ = to_photo(img)
        self.view.config(image=self.photo)

    def open_image(self):
        path = filedialog.askopenfilename(parent=self, initialdir=self.screenshots_dir,
                                          filetypes=[("Imagens", "*.png *.jpg *.jpeg *.bmp")])
        if path:
            self.img = imread_unicode(path, cv2.IMREAD_COLOR)
            self.source = os.path.basename(path)
            self._show(self.img)

    def capture_new(self):
        try:
            self.img = self.capture_cb()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erro", f"Falha ao capturar: {exc}", parent=self)
            return
        self.source = "nova captura"
        self._show(self.img)

    def run(self):
        cat = self.cat_var.get()
        if self.img is None or not cat:
            return
        try:
            thr = float(self.thr_var.get())
        except (tk.TclError, ValueError):
            thr = self.detector.threshold_for(cat)
        self.detector.library.invalidate()
        matches = self.detector.find_all(self.img, cat, thr)
        info = self.detector.diagnose(self.img, cat)
        txt = f"{len(matches)} encontrado(s) com limiar {thr:.2f}.  " + self.detector.describe(cat, info)
        if matches:
            txt += "\n" + ", ".join(str(m) for m in matches[:12])
        elif info["templates"] and info.get("best_zoom_score", 0) >= thr:
            txt += "\n→ O elemento existe com outro zoom de câmera; clique em 'Calibrar zoom'."
        elif info["templates"] and info.get("best_rejected", 0) >= thr:
            txt += "\n→ Forma igual mas cor/brilho diferentes: há uma janela escurecendo a tela?"
        self.result.config(text=txt)
        self._show(self.detector.annotate(self.img, matches))

    def calibrate(self):
        if self.img is None:
            return
        self.detector.reset_calibration()
        zoom = self.detector.calibrate_world(self.img, force=True)
        lines = [f"zoom da câmera: {zoom:.2f}x" if zoom else "zoom da câmera: não determinado"]
        for cat in WORLD_CATEGORIES:
            if self.detector.library.has(cat):
                ms = self.detector.find_all(self.img, cat)
                best = max((m.score for m in ms), default=self.detector.best_score(self.img, cat))
                lines.append(f"{cat}: {len(ms)} ({best:.2f})")
        self.result.config(text="Calibração — " + " | ".join(lines))
        self._show(self.img)

    def run_all(self):
        if self.img is None:
            return
        colors = [(0, 0, 255), (0, 200, 0), (255, 0, 0), (0, 200, 255), (255, 0, 255), (255, 255, 0)]
        out = self.img
        lines = []
        self.detector.library.invalidate()
        for i, cat in enumerate(self.detector.library.categories()):
            if not self.detector.library.has(cat):
                continue
            ms = self.detector.find_all(self.img, cat)
            best = max((m.score for m in ms), default=self.detector.best_score(self.img, cat))
            lines.append(f"{cat}: {len(ms)} ({best:.2f})")
            out = self.detector.annotate(out, ms, colors[i % len(colors)])
        self.result.config(text=" | ".join(lines) or "Nenhum template cadastrado.")
        self._show(out)
