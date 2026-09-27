"""Interface gráfica (Tkinter) do HayDayBot."""

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import config as cfgmod
from adb_controller import ADBController, ADBError
from bot import HayDayBot
from image_detector import TEMPLATE_CATEGORIES, ImageDetector, TemplateLibrary
from logger_setup import get_logger, gui_log_queue, set_debug
from screen import Screen

log = get_logger()

STATUS_COLORS = {
    "connected": ("#2ecc71", "Conectado"),
    "running": ("#f1c40f", "Executando"),
    "error": ("#e74c3c", "Erro"),
    "stopped": ("#bdc3c7", "Parado"),
}

# (seção, [(chave, rótulo, tipo)])  tipo: int|float|bool|str|choice|list|json
SETTINGS = [
    ("Cultivo", [
        ("crop", "Cultura", "choice"),
        ("growth_time", "Tempo de crescimento (s) — trigo = 120", "int"),
        ("max_wait_growth", "Espera máxima pelo crescimento (s)", "int"),
        ("yield_per_field", "Trigo colhido por campo", "int"),
        ("initial_wheat_stock", "Estoque inicial de trigo no silo (estimativa)", "int"),
        ("keep_reserve", "Reserva de trigo que nunca é vendida (para replantar)", "int"),
    ]),
    ("Venda", [
        ("sell_enabled", "Vender trigo na banca", "bool"),
        ("min_sell_qty", "Quantidade mínima para vender", "int"),
        ("max_sell_qty", "Quantidade máxima por caixote", "int"),
        ("sell_qty_start", "Quantidade que a janela de venda mostra ao abrir", "int"),
        ("price_mode", "Preço: default | max | plus | minus", "choice"),
        ("price_clicks", "Cliques em +/- preço (modos plus/minus)", "int"),
        ("max_listings_per_cycle", "Máx. de caixotes colocados à venda por ciclo", "int"),
    ]),
    ("Anúncio", [
        ("advertise_enabled", "Criar anúncios no jornal", "bool"),
        ("advertise_interval", "Intervalo entre anúncios (s)", "int"),
    ]),
    ("Coleta de dinheiro", [
        ("collect_money_enabled", "Coletar vendas concluídas", "bool"),
        ("collect_interval", "Intervalo entre verificações da banca (s)", "int"),
        ("coins_per_sale_estimate", "Moedas estimadas por venda (só para estatística)", "int"),
    ]),
    ("Tempo e segurança", [
        ("check_interval", "Intervalo de verificação (s)", "float"),
        ("max_retries", "Tentativas por etapa", "int"),
        ("step_timeout", "Timeout de cada etapa (s)", "int"),
        ("max_recoveries", "Recuperações seguidas antes de parar", "int"),
        ("restart_game_after_failures", "Falhas de recuperação antes de reiniciar o jogo", "int"),
        ("freeze_timeout", "Tela parada = emulador travado após (s) (0 = desliga)", "int"),
        ("max_same_spot_taps", "Máx. de toques no mesmo ponto em 60s", "int"),
        ("screenshot_on_error", "Salvar screenshot quando ocorrer erro", "bool"),
        ("hotkey", "Tecla de emergência (reinicie o programa ao mudar)", "str"),
        ("debug_log", "Log detalhado (debug) no arquivo", "bool"),
    ]),
    ("Reconhecimento de imagem", [
        ("match_threshold", "Limiar padrão de semelhança (0.3–0.99)", "float"),
        ("template_resolution", "Resolução em que os templates foram recortados", "str"),
        ("scales", "Escalas extras (ex.: 1.0, 0.9, 1.1)", "list"),
        ("thresholds", "Limiar por pasta (JSON, ex.: {\"wheat_ready\": 0.75})", "json"),
    ]),
    ("Arrasto (plantar/colher)", [
        ("drag_mode", "Modo: auto | motionevent | swipe", "choice"),
        ("drag_hold", "Segurar antes de arrastar (s)", "float"),
        ("drag_step_px", "Passo do arrasto (px)", "int"),
        ("swipe_duration_ms", "Duração de cada swipe (ms)", "int"),
    ]),
    ("Avançado", [
        ("game_package", "Pacote do jogo", "str"),
        ("open_game_timeout", "Tempo máx. para o jogo abrir (s)", "int"),
        ("emulator_boot_timeout", "Tempo máx. para o emulador iniciar (s)", "int"),
        ("adb_timeout", "Timeout de comandos ADB (s)", "int"),
    ]),
]


def open_path(path):
    os.makedirs(path, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - abre o Explorer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HayDayBot — automação de Hay Day (MEmu / MuMu)")
        self.geometry("1060x760")
        self.minsize(900, 640)
        self.cfg = cfgmod.load_config()
        self.bot = None
        self.connected = False
        self.conn_error = False
        self.last_screenshot = None
        self.ui_queue = queue.Queue()
        self.vars = {}
        self._busy = False
        self._hotkey_handle = None

        self.library = TemplateLibrary(cfgmod.TEMPLATES_DIR)
        self.library.ensure_structure()

        self._build()
        self._load_vars()
        self._register_hotkey()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(200, self._poll)
        log.info("HayDayBot pronto. Configure o ADB e clique em CONECTAR.")

    # =============================================================== layout
    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass
        style.configure("Big.TButton", padding=(10, 6), font=("Segoe UI", 10, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 14, "bold"))

        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")
        self.status_canvas = tk.Canvas(header, width=26, height=26, highlightthickness=0)
        self.status_canvas.pack(side="left")
        self.status_dot = self.status_canvas.create_oval(3, 3, 23, 23, fill="#bdc3c7", outline="#777")
        self.status_label = ttk.Label(header, text="Parado", style="Status.TLabel")
        self.status_label.pack(side="left", padx=8)
        self.state_label = ttk.Label(header, text="", foreground="#555")
        self.state_label.pack(side="left", padx=8)
        self.hotkey_label = ttk.Label(header, text="", foreground="#c0392b")
        self.hotkey_label.pack(side="right")

        buttons = ttk.Frame(self, padding=(10, 0))
        buttons.pack(fill="x")
        self.btn_connect = ttk.Button(buttons, text="CONECTAR", style="Big.TButton", command=self.on_connect)
        self.btn_start = ttk.Button(buttons, text="INICIAR BOT", style="Big.TButton", command=self.on_start)
        self.btn_stop = ttk.Button(buttons, text="PARAR BOT", style="Big.TButton", command=self.on_stop)
        self.btn_test = ttk.Button(buttons, text="TESTAR ADB", style="Big.TButton", command=self.on_test_adb)
        self.btn_shot = ttk.Button(buttons, text="CAPTURAR TELA", style="Big.TButton", command=self.on_capture)
        self.btn_tpl = ttk.Button(buttons, text="ABRIR TEMPLATES", style="Big.TButton",
                                  command=lambda: open_path(cfgmod.TEMPLATES_DIR))
        for b in (self.btn_connect, self.btn_start, self.btn_stop, self.btn_test, self.btn_shot, self.btn_tpl):
            b.pack(side="left", padx=3, pady=6)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tab_panel = ttk.Frame(nb, padding=8)
        self.tab_conn = ttk.Frame(nb, padding=8)
        self.tab_settings = ttk.Frame(nb, padding=0)
        self.tab_templates = ttk.Frame(nb, padding=8)
        nb.add(self.tab_panel, text="Painel")
        nb.add(self.tab_conn, text="Conexão")
        nb.add(self.tab_settings, text="Configurações")
        nb.add(self.tab_templates, text="Templates")
        self._build_panel()
        self._build_connection()
        self._build_settings()
        self._build_templates()

    def _build_panel(self):
        stats = ttk.LabelFrame(self.tab_panel, text="Informações", padding=8)
        stats.pack(fill="x")
        self.stat_labels = {}
        items = [
            ("fields_found", "Campos encontrados"), ("fields_planted", "Campos plantados"),
            ("fields_harvested", "Campos colhidos"), ("sold_qty", "Quantidade vendida"),
            ("ads", "Anúncios realizados"), ("money", "Dinheiro coletado"),
            ("runtime", "Tempo de execução"), ("wheat_stock", "Trigo estimado no silo"),
            ("state", "Estado atual"), ("cycles", "Ciclos completos"),
        ]
        for i, (key, text) in enumerate(items):
            r, c = divmod(i, 2)
            ttk.Label(stats, text=text + ":").grid(row=r, column=c * 2, sticky="w", padx=(0, 6), pady=2)
            initial = {"runtime": "00:00:00", "state": "IDLE", "money": "0 vendas coletadas"}.get(key, "0")
            lbl = ttk.Label(stats, text=initial, font=("Segoe UI", 10, "bold"))
            lbl.grid(row=r, column=c * 2 + 1, sticky="w", padx=(0, 40), pady=2)
            self.stat_labels[key] = lbl
        row = (len(items) + 1) // 2
        for key, text in (("last_action", "Última ação"), ("last_error", "Último erro")):
            ttk.Label(stats, text=text + ":").grid(row=row, column=0, sticky="nw", pady=2)
            lbl = ttk.Label(stats, text="-", wraplength=800, justify="left")
            lbl.grid(row=row, column=1, columnspan=3, sticky="w", pady=2)
            self.stat_labels[key] = lbl
            row += 1

        logf = ttk.LabelFrame(self.tab_panel, text="Log", padding=4)
        logf.pack(fill="both", expand=True, pady=(8, 0))
        self.log_text = scrolledtext.ScrolledText(logf, height=16, state="disabled",
                                                  font=("Consolas", 9), wrap="word")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("warn", foreground="#b9770e")
        self.log_text.tag_config("err", foreground="#c0392b")
        bar = ttk.Frame(logf)
        bar.pack(fill="x")
        ttk.Button(bar, text="Limpar", command=self._clear_log).pack(side="left", pady=2)
        ttk.Button(bar, text="Abrir pasta de logs",
                   command=lambda: open_path(cfgmod.LOGS_DIR)).pack(side="left", padx=4, pady=2)
        ttk.Button(bar, text="Abrir screenshots",
                   command=lambda: open_path(cfgmod.SCREENSHOTS_DIR)).pack(side="left", pady=2)

    def _path_row(self, parent, row, key, label, filetypes):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        var = tk.StringVar()
        self.vars[key] = (var, "str")
        ttk.Entry(parent, textvariable=var, width=70).grid(row=row, column=1, sticky="we", padx=4)

        def browse():
            p = filedialog.askopenfilename(parent=self, filetypes=filetypes,
                                           initialdir=os.path.dirname(var.get()) or None)
            if p:
                var.set(os.path.normpath(p))
        ttk.Button(parent, text="Procurar...", command=browse).grid(row=row, column=2, padx=2)

    def _build_connection(self):
        f = ttk.Frame(self.tab_conn)
        f.pack(fill="x")
        f.columnconfigure(1, weight=1)
        exe = [("Executável", "*.exe"), ("Todos", "*.*")]
        self._path_row(f, 0, "adb_path", "Caminho do adb.exe:", exe)
        self._path_row(f, 1, "emulator_path", "Executável do emulador (MEmu/MuMu):", exe)

        ttk.Label(f, text="Argumentos do emulador (opcional):").grid(row=2, column=0, sticky="w", pady=4)
        v = tk.StringVar()
        self.vars["emulator_args"] = (v, "str")
        ttk.Entry(f, textvariable=v, width=30).grid(row=2, column=1, sticky="w", padx=4)

        ttk.Label(f, text="Dispositivo ADB:").grid(row=3, column=0, sticky="w", pady=4)
        dv = tk.StringVar()
        self.vars["device"] = (dv, "str")
        dframe = ttk.Frame(f)
        dframe.grid(row=3, column=1, columnspan=2, sticky="w")
        self.device_box = ttk.Combobox(dframe, textvariable=dv, width=28)
        self.device_box.pack(side="left", padx=4)
        ttk.Button(dframe, text="Listar dispositivos", command=self.on_list_devices).pack(side="left", padx=2)
        ttk.Button(dframe, text="Procurar emuladores", command=self.on_scan).pack(side="left", padx=2)
        ttk.Button(dframe, text="adb connect", command=self.on_connect_address).pack(side="left", padx=2)

        ttk.Label(f, text="Resolução do emulador:").grid(row=4, column=0, sticky="w", pady=4)
        rv = tk.StringVar()
        self.vars["resolution"] = (rv, "str")
        ttk.Entry(f, textvariable=rv, width=14).grid(row=4, column=1, sticky="w", padx=4)

        ttk.Label(f, text="Tempo entre ações (s):").grid(row=5, column=0, sticky="w", pady=4)
        av = tk.StringVar()
        self.vars["action_delay"] = (av, "float")
        ttk.Entry(f, textvariable=av, width=8).grid(row=5, column=1, sticky="w", padx=4)

        bar = ttk.Frame(self.tab_conn)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="Salvar configurações", command=self.on_save).pack(side="left")
        self.conn_info = ttk.Label(self.tab_conn, text="Conexão: não verificada", font=("Segoe UI", 10, "bold"))
        self.conn_info.pack(anchor="w", pady=4)
        ttk.Label(self.tab_conn, justify="left", foreground="#555", text=(
            "Endereços comuns:  MEmu 127.0.0.1:21503 (2ª instância 21513...)   •   "
            "MuMu 12 127.0.0.1:16384 (2ª 16416...)   •   MuMu 6/X 127.0.0.1:7555\n"
            "adb do MEmu: C:\\Program Files\\Microvirt\\MEmu\\adb.exe   •   "
            "adb do MuMu 12: ...\\MuMuPlayer-12.0\\shell\\adb.exe (ou nx_main\\adb.exe)\n"
            "Use SEMPRE o adb.exe do próprio emulador para evitar conflito de versões do servidor ADB."
        )).pack(anchor="w", pady=4)

    def _build_settings(self):
        canvas = tk.Canvas(self.tab_settings, highlightthickness=0)
        sb = ttk.Scrollbar(self.tab_settings, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=8)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
                        if str(e.widget).startswith(str(canvas)) else None)

        for section, fields in SETTINGS:
            lf = ttk.LabelFrame(inner, text=section, padding=6)
            lf.pack(fill="x", pady=4)
            for r, (key, label, typ) in enumerate(fields):
                ttk.Label(lf, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 10))
                if typ == "bool":
                    var = tk.BooleanVar()
                    ttk.Checkbutton(lf, variable=var).grid(row=r, column=1, sticky="w")
                elif typ == "choice":
                    var = tk.StringVar()
                    ttk.Combobox(lf, textvariable=var, values=cfgmod.CHOICES[key], state="readonly",
                                 width=16).grid(row=r, column=1, sticky="w")
                else:
                    var = tk.StringVar()
                    width = 50 if typ in ("json", "list") else 16
                    ttk.Entry(lf, textvariable=var, width=width).grid(row=r, column=1, sticky="w")
                self.vars[key] = (var, typ)
        bar = ttk.Frame(inner)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="Salvar configurações", command=self.on_save).pack(side="left")
        ttk.Button(bar, text="Restaurar padrões", command=self.on_defaults).pack(side="left", padx=6)
        ttk.Button(bar, text="Recarregar config.json", command=self.on_reload).pack(side="left")

    def _build_templates(self):
        ttk.Label(self.tab_templates, wraplength=980, justify="left", text=(
            "Cada pasta em templates/ é um elemento do jogo. Use CAPTURAR TELA com o jogo na tela "
            "certa e depois 'Recortar template' para salvar o recorte na pasta. Use 'Testar detecção' "
            "para ver se o elemento é encontrado e qual limiar usar. Pastas OBRIGATÓRIAS vazias "
            "impedem o ciclo; opcionais só desativam o recurso correspondente."
        )).pack(anchor="w", pady=(0, 6))
        cols = ("status", "qtd", "desc")
        self.tpl_tree = ttk.Treeview(self.tab_templates, columns=cols, show="tree headings", height=16)
        self.tpl_tree.heading("#0", text="Pasta")
        self.tpl_tree.heading("status", text="Tipo")
        self.tpl_tree.heading("qtd", text="Imagens")
        self.tpl_tree.heading("desc", text="O que recortar")
        self.tpl_tree.column("#0", width=150, stretch=False)
        self.tpl_tree.column("status", width=170, stretch=False)
        self.tpl_tree.column("qtd", width=60, anchor="center", stretch=False)
        self.tpl_tree.column("desc", width=600)
        self.tpl_tree.tag_configure("missing", foreground="#c0392b")
        self.tpl_tree.tag_configure("ok", foreground="#1e8449")
        self.tpl_tree.pack(fill="both", expand=True)
        self.tpl_tree.bind("<Double-1>", lambda e: self.on_open_tpl_folder())
        bar = ttk.Frame(self.tab_templates)
        bar.pack(fill="x", pady=6)
        ttk.Button(bar, text="Abrir pasta selecionada", command=self.on_open_tpl_folder).pack(side="left")
        ttk.Button(bar, text="Recortar template...", command=self.on_cropper).pack(side="left", padx=4)
        ttk.Button(bar, text="Testar detecção...", command=self.on_tester).pack(side="left")
        ttk.Button(bar, text="Atualizar lista", command=self.refresh_templates).pack(side="left", padx=4)
        self.refresh_templates()

    def refresh_templates(self):
        self.library.invalidate()
        self.tpl_tree.delete(*self.tpl_tree.get_children())
        cats = list(TEMPLATE_CATEGORIES) + [c for c in self.library.categories()
                                            if c not in TEMPLATE_CATEGORIES]
        for cat in cats:
            req, desc = TEMPLATE_CATEGORIES.get(cat, ("personalizado", ""))
            n = self.library.count(cat)
            tag = "ok" if n else ("missing" if req == "OBRIGATÓRIO" else "")
            self.tpl_tree.insert("", "end", iid=cat, text=cat, values=(req, n, desc), tags=(tag,))

    # =========================================================== config vars
    def _load_vars(self):
        for key, (var, typ) in self.vars.items():
            val = self.cfg.get(key, cfgmod.DEFAULT_CONFIG.get(key))
            if typ == "bool":
                var.set(bool(val))
            elif typ == "json":
                var.set(json.dumps(val, ensure_ascii=False))
            elif typ == "list":
                var.set(", ".join(str(v) for v in val))
            else:
                var.set("" if val is None else str(val))
        self.hotkey_label.config(text=f"Parada de emergência: {self.cfg['hotkey']}")

    def _collect_vars(self):
        data = dict(self.cfg)
        errors = []
        for key, (var, typ) in self.vars.items():
            try:
                raw = var.get()
                if typ == "int":
                    data[key] = int(float(str(raw).replace(",", ".")))
                elif typ == "float":
                    data[key] = float(str(raw).replace(",", "."))
                elif typ == "bool":
                    data[key] = bool(raw)
                elif typ == "json":
                    data[key] = json.loads(raw or "{}")
                elif typ == "list":
                    data[key] = [float(x) for x in str(raw).replace(";", ",").split(",") if x.strip()]
                else:
                    data[key] = str(raw).strip()
            except (ValueError, tk.TclError, json.JSONDecodeError):
                errors.append(key)
        if errors:
            raise ValueError("Valores inválidos em: " + ", ".join(errors))
        return cfgmod.normalize(data)

    def on_save(self, quiet=False):
        try:
            self.cfg = cfgmod.save_config(self._collect_vars())
        except (ValueError, OSError) as exc:
            messagebox.showerror("Configurações", str(exc), parent=self)
            return False
        self._load_vars()
        set_debug(self.cfg["debug_log"])
        if not quiet:
            log.info("Configurações salvas em config.json")
        return True

    def on_defaults(self):
        if messagebox.askyesno("Restaurar padrões", "Restaurar todas as configurações (exceto conexão)?",
                               parent=self):
            keep = {k: self.cfg[k] for k in ("adb_path", "emulator_path", "emulator_args", "device",
                                             "resolution")}
            self.cfg = cfgmod.normalize({**cfgmod.DEFAULT_CONFIG, **keep})
            self._load_vars()

    def on_reload(self):
        self.cfg = cfgmod.load_config()
        self._load_vars()
        log.info("config.json recarregado.")

    # ============================================================ utilidades
    def run_bg(self, fn, done=None, busy=True):
        """Executa fn() numa thread; done(result, error) roda depois na thread da interface."""
        if busy and self._busy:
            log.info("Aguarde a operação anterior terminar.")
            return
        if busy:
            self._busy = True

        def worker():
            result, error = None, None
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001
                error = exc
            finally:
                def finish():
                    if busy:
                        self._busy = False
                    if done:
                        done(result, error)
                self.ui_queue.put(finish)
        threading.Thread(target=worker, daemon=True).start()

    def _make_adb(self):
        return ADBController(self.cfg["adb_path"], self.cfg["device"], self.cfg["adb_timeout"])

    def _bot_running(self):
        return self.bot is not None and self.bot.is_running()

    # ================================================================ ações
    def on_list_devices(self):
        if not self.on_save(quiet=True):
            return
        adb = self._make_adb()

        def work():
            adb.start_server()
            return adb.list_devices()

        def done(devs, err):
            if err:
                log.error("Falha ao listar dispositivos: %s", err)
                return
            self.device_box["values"] = [d["serial"] for d in devs]
            if not devs:
                log.info("Nenhum dispositivo. Clique em 'Procurar emuladores' ou use 'adb connect'.")
            for d in devs:
                log.info("Dispositivo: %s [%s] %s", d["serial"], d["state"], d["desc"])
        self.run_bg(work, done)

    def on_scan(self):
        if not self.on_save(quiet=True):
            return
        adb = self._make_adb()
        log.info("Procurando emuladores nas portas conhecidas (MEmu/MuMu)...")

        def work():
            adb.start_server()
            adb.scan_emulators()
            return adb.list_devices()

        def done(devs, err):
            if err:
                log.error("Falha na busca: %s", err)
                return
            online = [d["serial"] for d in devs if d["state"] == "device"]
            self.device_box["values"] = [d["serial"] for d in devs]
            log.info("Dispositivos online: %s", ", ".join(online) or "nenhum")
            if online and self.vars["device"][0].get() not in online:
                self.vars["device"][0].set(online[0])
        self.run_bg(work, done)

    def on_connect_address(self):
        addr = self.vars["device"][0].get().strip()
        if ":" not in addr:
            messagebox.showinfo("adb connect", "Digite um endereço host:porta no campo Dispositivo, "
                                "ex.: 127.0.0.1:21503", parent=self)
            return
        if not self.on_save(quiet=True):
            return
        adb = self._make_adb()
        self.run_bg(lambda: adb.connect(addr),
                    lambda res, err: log.info("adb connect %s: %s", addr, err or res[1]))

    def on_connect(self):
        if not self.on_save(quiet=True):
            return
        adb = self._make_adb()
        wanted = self.cfg["device"]

        def work():
            adb.start_server()
            ver = adb.version()
            online = adb.online_devices()
            if wanted and wanted not in online and ":" in wanted:
                adb.connect(wanted)
                online = adb.online_devices()
            if not online:
                adb.scan_emulators()
                online = adb.online_devices()
            if not online:
                raise ADBError("Nenhum dispositivo online. Abra o emulador e tente de novo.")
            device = wanted if wanted in online else online[0]
            adb.device = device
            img = adb.screencap()
            return ver, device, online, img

        def done(res, err):
            if err:
                self.connected, self.conn_error = False, True
                self.conn_info.config(text=f"Conexão: FALHOU — {err}", foreground="#c0392b")
                log.error("Conexão falhou: %s", err)
                return
            ver, device, online, img = res
            self.connected, self.conn_error = True, False
            self.device_box["values"] = online
            self.vars["device"][0].set(device)
            self.on_save(quiet=True)
            self.last_screenshot = img
            h, w = img.shape[:2]
            self.conn_info.config(text=f"Conexão: OK — {device} ({w}x{h})", foreground="#1e8449")
            log.info("ADB conectado: %s (%s) tela %dx%d", device, ver, w, h)
            if f"{w}x{h}" != self.cfg["resolution"].replace(" ", ""):
                log.warning("A resolução real (%dx%d) difere da configurada (%s).", w, h, self.cfg["resolution"])
        self.run_bg(work, done)

    def on_test_adb(self):
        if not self.on_save(quiet=True):
            return
        adb = self._make_adb()
        pkg = self.cfg["game_package"]
        tap = self.cfg["test_tap_point"]

        def work():
            report = []
            ver = adb.version()
            report.append(f"✔ ADB funcionando: {ver}")
            devs = adb.list_devices()
            report.append("✔ Dispositivos: " + (", ".join(f"{d['serial']}[{d['state']}]" for d in devs)
                                               or "nenhum"))
            if not adb.device:
                online = [d["serial"] for d in devs if d["state"] == "device"]
                if not online:
                    raise ADBError("\n".join(report + ["✘ Nenhum dispositivo online selecionado."]))
                adb.device = online[0]
            if not adb.is_online():
                raise ADBError("\n".join(report + [f"✘ Dispositivo {adb.device} não está online."]))
            report.append(f"✔ Dispositivo {adb.device} online")
            size = adb.screen_size()
            report.append(f"✔ Resolução (wm size): {size[0]}x{size[1]}")
            adb.tap(*tap)
            report.append(f"✔ Toque de teste enviado em ({tap[0]},{tap[1]})")
            img = adb.screencap()
            report.append(f"✔ Screenshot OK ({img.shape[1]}x{img.shape[0]})")
            fg = adb.foreground_package()
            report.append(("✔ Hay Day em primeiro plano" if fg == pkg
                           else f"• App em primeiro plano: {fg or 'desconhecido'}"))
            report.append("✔ input motionevent suportado (arrasto contínuo)" if adb.supports_motionevent()
                          else "• input motionevent NÃO suportado — será usado swipe campo a campo")
            return "\n".join(report), img

        def done(res, err):
            if err:
                self.conn_error, self.connected = True, False
                self.conn_info.config(text="Conexão: FALHOU", foreground="#c0392b")
                log.error("Teste ADB falhou:\n%s", err)
                messagebox.showerror("Teste ADB", str(err), parent=self)
                return
            text, img = res
            self.last_screenshot = img
            self.connected, self.conn_error = True, False
            self.conn_info.config(text=f"Conexão: OK — {adb.device}", foreground="#1e8449")
            log.info("Teste ADB:\n%s", text)
            messagebox.showinfo("Teste ADB", text, parent=self)
        self.run_bg(work, done)

    def capture_now(self):
        """Captura síncrona usada pelas janelas de templates."""
        adb = self._make_adb()
        if not adb.device:
            online = adb.online_devices()
            if not online:
                raise ADBError("Nenhum dispositivo conectado.")
            adb.device = online[0]
        img = adb.screencap()
        self.last_screenshot = img
        return img

    def on_capture(self):
        if not self.on_save(quiet=True):
            return

        def work():
            img = self.capture_now()
            path = Screen(None, cfgmod.SCREENSHOTS_DIR).save(img, prefix="tela")
            return path

        def done(path, err):
            if err:
                log.error("Falha ao capturar tela: %s", err)
                messagebox.showerror("Capturar tela", str(err), parent=self)
            else:
                log.info("Screenshot salvo: %s", path)
        self.run_bg(work, done)

    def _missing_required(self):
        missing = []
        for cat, (req, _) in TEMPLATE_CATEGORIES.items():
            if req == "OBRIGATÓRIO" and not self.library.has(cat):
                missing.append(cat)
        return missing

    def on_start(self):
        if self._bot_running():
            log.info("O bot já está em execução.")
            return
        if not self.on_save(quiet=True):
            return
        self.library.invalidate()
        missing = self._missing_required()
        if missing and not messagebox.askyesno(
                "Templates faltando",
                "As pastas obrigatórias abaixo estão vazias:\n\n  " + "\n  ".join(missing) +
                "\n\nSem elas o bot não conseguirá reconhecer a tela. Iniciar mesmo assim?", parent=self):
            return
        self.bot = HayDayBot(self.cfg, cfgmod.TEMPLATES_DIR, cfgmod.SCREENSHOTS_DIR)
        self.bot.start()

    def on_stop(self):
        if self.bot is not None:
            self.bot.stop("botão PARAR")

    def emergency_stop(self):
        """Chamado pela tecla de emergência (thread do teclado)."""
        bot = self.bot
        if bot is not None and bot.is_running():
            bot.stop(f"tecla {self.cfg['hotkey']}")

    def _register_hotkey(self):
        hk = self.cfg["hotkey"]
        try:
            self.bind_all(f"<{hk}>", lambda e: self.emergency_stop())
        except tk.TclError:
            pass
        try:
            import keyboard  # captura global: funciona mesmo com o emulador em foco
            self._hotkey_handle = keyboard.add_hotkey(hk.lower(), self.emergency_stop, suppress=False)
            log.info("Tecla de emergência global: %s", hk)
        except Exception as exc:  # noqa: BLE001
            log.warning("Tecla global %s indisponível (%r). Ela só funciona com esta janela em foco.", hk, exc)

    def on_open_tpl_folder(self):
        sel = self.tpl_tree.selection()
        path = os.path.join(cfgmod.TEMPLATES_DIR, sel[0]) if sel else cfgmod.TEMPLATES_DIR
        open_path(path)

    def _tool_detector(self):
        from config import parse_resolution
        tw, _ = parse_resolution(self.cfg["template_resolution"])
        return ImageDetector(self.library, self.cfg["match_threshold"], self.cfg["thresholds"],
                             tw, self.cfg["scales"])

    def on_cropper(self):
        from template_tools import TemplateCropper
        self.on_save(quiet=True)
        TemplateCropper(self, self.last_screenshot, cfgmod.TEMPLATES_DIR, cfgmod.SCREENSHOTS_DIR,
                        capture_cb=self.capture_now,
                        on_saved=lambda cat, p: (log.info("Template salvo: %s", p), self.refresh_templates()))

    def on_tester(self):
        from template_tools import DetectionTester
        self.on_save(quiet=True)
        self.library.invalidate()
        DetectionTester(self, self.last_screenshot, self._tool_detector(), cfgmod.SCREENSHOTS_DIR,
                        capture_cb=self.capture_now)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ============================================================ atualização
    def _poll(self):
        try:
            while True:
                self.ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self._drain_logs()
        self._update_status()
        self.after(250, self._poll)

    def _drain_logs(self):
        lines = []
        try:
            for _ in range(300):
                lines.append(gui_log_queue.get_nowait())
        except queue.Empty:
            pass
        if not lines:
            return
        self.log_text.config(state="normal")
        for level, text in lines:
            tag = "err" if level >= 40 else ("warn" if level >= 30 else "")
            self.log_text.insert("end", text + "\n", tag)
        excess = int(self.log_text.index("end-1c").split(".")[0]) - 3000
        if excess > 0:
            self.log_text.delete("1.0", f"{excess}.0")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _update_status(self):
        running = self._bot_running()
        if running:
            status = "running"
        elif self.bot is not None and self.bot.status == HayDayBot.STATUS_ERROR:
            status = "error"
        elif self.conn_error:
            status = "error"
        elif self.connected:
            status = "connected"
        else:
            status = "stopped"
        color, text = STATUS_COLORS[status]
        self.status_canvas.itemconfig(self.status_dot, fill=color)
        self.status_label.config(text=text)
        self.btn_start.state(["disabled"] if running else ["!disabled"])
        self.btn_stop.state(["!disabled"] if running else ["disabled"])

        if self.bot is None:
            self.state_label.config(text="")
            return
        s = self.bot.stats.snapshot()
        self.state_label.config(text=f"Estado: {s['state']}")
        for key in ("fields_found", "fields_planted", "fields_harvested", "sold_qty", "ads",
                    "wheat_stock", "state", "cycles", "last_action", "last_error"):
            self.stat_labels[key].config(text=str(s[key]))
        money = f"{s['collections']} vendas coletadas"
        if s["coins_estimate"]:
            money += f" (~{s['coins_estimate']} moedas)"
        self.stat_labels["money"].config(text=money)
        rt = int(s["runtime"])
        self.stat_labels["runtime"].config(text=f"{rt // 3600:02d}:{rt % 3600 // 60:02d}:{rt % 60:02d}")

    def on_close(self):
        if self._bot_running():
            if not messagebox.askyesno("Sair", "O bot está rodando. Parar e sair?", parent=self):
                return
            self.bot.stop("fechando o programa")
            self.bot.join(3)
        try:
            import keyboard
            keyboard.unhook_all_hotkeys()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()
