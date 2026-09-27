"""Carregamento, validação e gravação do config.json."""

import copy
import json
import os
import sys


def app_dir():
    """Pasta do programa (ao lado do .exe quando empacotado com PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
SCREENSHOTS_DIR = os.path.join(APP_DIR, "screenshots")
LOGS_DIR = os.path.join(APP_DIR, "logs")

DEFAULT_CONFIG = {
    # --- Conexão ---
    "adb_path": r"C:\Program Files\Microvirt\MEmu\adb.exe",
    "emulator_path": r"C:\Program Files\Microvirt\MEmu\MEmu.exe",
    "emulator_args": "",
    "device": "",
    "resolution": "1280x720",
    "template_resolution": "1280x720",
    "adb_timeout": 20,
    "emulator_boot_timeout": 180,
    "game_package": "com.supercell.hayday",
    "open_game_timeout": 120,
    # --- Cultivo ---
    "crop": "wheat",
    "growth_time": 120,
    "max_wait_growth": 900,
    "yield_per_field": 2,
    "initial_wheat_stock": 20,
    "keep_reserve": 20,
    # --- Venda ---
    "sell_enabled": True,
    "min_sell_qty": 10,
    "max_sell_qty": 10,
    "sell_qty_start": 1,
    "price_mode": "max",
    "price_clicks": 0,
    "max_listings_per_cycle": 2,
    # --- Anúncio ---
    "advertise_enabled": True,
    "advertise_interval": 300,
    # --- Coleta de dinheiro ---
    "collect_money_enabled": True,
    "collect_interval": 120,
    "coins_per_sale_estimate": 0,
    # --- Tempo / segurança ---
    "check_interval": 5,
    "action_delay": 0.5,
    "max_retries": 3,
    "step_timeout": 120,
    "max_recoveries": 6,
    "restart_game_after_failures": 3,
    "freeze_timeout": 180,
    "max_same_spot_taps": 6,
    "screenshot_on_error": True,
    "hotkey": "F8",
    # --- Reconhecimento de imagem ---
    "match_threshold": 0.80,
    "thresholds": {},
    "scales": [1.0],
    # --- Arrasto (plantar/colher) ---
    "drag_mode": "auto",
    "drag_hold": 0.25,
    "drag_step_px": 40,
    "swipe_duration_ms": 400,
    "test_tap_point": [5, 5],
    "debug_log": False,
}

# Tipos esperados, usados para validar valores vindos da interface/arquivo.
_NUMERIC_KEYS_INT = {
    "adb_timeout", "emulator_boot_timeout", "open_game_timeout", "growth_time",
    "max_wait_growth", "yield_per_field", "initial_wheat_stock", "keep_reserve",
    "min_sell_qty", "max_sell_qty", "sell_qty_start", "price_clicks",
    "max_listings_per_cycle", "advertise_interval", "collect_interval",
    "coins_per_sale_estimate", "max_retries", "step_timeout", "max_recoveries",
    "restart_game_after_failures", "freeze_timeout", "max_same_spot_taps",
    "drag_step_px", "swipe_duration_ms",
}
_NUMERIC_KEYS_FLOAT = {"check_interval", "action_delay", "match_threshold", "drag_hold"}
_BOOL_KEYS = {
    "sell_enabled", "advertise_enabled", "collect_money_enabled",
    "screenshot_on_error", "debug_log",
}
CHOICES = {
    "price_mode": ["default", "max", "plus", "minus"],
    "drag_mode": ["auto", "motionevent", "swipe"],
    "crop": ["wheat"],
}


def parse_resolution(text, fallback=(1280, 720)):
    try:
        w, h = str(text).lower().replace(" ", "").split("x")
        w, h = int(w), int(h)
        if w > 0 and h > 0:
            return w, h
    except (ValueError, AttributeError):
        pass
    return fallback


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "sim", "yes", "on")
    return bool(value)


def normalize(cfg):
    """Converte tipos e corrige valores fora de faixa. Retorna um novo dict."""
    out = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in (cfg or {}).items():
        out[key] = value
    for key in _NUMERIC_KEYS_INT:
        try:
            out[key] = int(float(out[key]))
        except (TypeError, ValueError):
            out[key] = DEFAULT_CONFIG[key]
    for key in _NUMERIC_KEYS_FLOAT:
        try:
            out[key] = float(out[key])
        except (TypeError, ValueError):
            out[key] = DEFAULT_CONFIG[key]
    for key in _BOOL_KEYS:
        out[key] = _to_bool(out[key])
    for key, options in CHOICES.items():
        if out.get(key) not in options:
            out[key] = DEFAULT_CONFIG[key]
    for key in ("adb_path", "emulator_path", "emulator_args", "device", "game_package", "hotkey"):
        out[key] = str(out.get(key) or "").strip().strip('"')
    if not out["game_package"]:
        out["game_package"] = DEFAULT_CONFIG["game_package"]
    if not out["hotkey"]:
        out["hotkey"] = "F8"

    # Limites de segurança
    out["max_retries"] = max(1, out["max_retries"])
    out["action_delay"] = max(0.05, out["action_delay"])
    out["check_interval"] = max(1.0, out["check_interval"])
    out["match_threshold"] = min(0.99, max(0.3, out["match_threshold"]))
    out["max_sell_qty"] = max(1, out["max_sell_qty"])
    out["min_sell_qty"] = max(1, min(out["min_sell_qty"], out["max_sell_qty"]))
    out["sell_qty_start"] = max(0, out["sell_qty_start"])
    out["max_same_spot_taps"] = max(3, out["max_same_spot_taps"])
    out["step_timeout"] = max(20, out["step_timeout"])
    out["max_wait_growth"] = max(out["growth_time"], out["max_wait_growth"])
    out["drag_step_px"] = max(5, out["drag_step_px"])

    if not isinstance(out.get("thresholds"), dict):
        out["thresholds"] = {}
    else:
        clean = {}
        for k, v in out["thresholds"].items():
            try:
                clean[str(k)] = min(0.99, max(0.3, float(v)))
            except (TypeError, ValueError):
                pass
        out["thresholds"] = clean
    scales = out.get("scales")
    try:
        scales = [float(s) for s in scales if 0.3 <= float(s) <= 3.0]
    except (TypeError, ValueError):
        scales = []
    out["scales"] = scales or [1.0]
    tp = out.get("test_tap_point")
    try:
        out["test_tap_point"] = [int(tp[0]), int(tp[1])]
    except (TypeError, ValueError, IndexError):
        out["test_tap_point"] = list(DEFAULT_CONFIG["test_tap_point"])
    return out


def load_config(path=CONFIG_PATH):
    """Lê o config.json (criando-o com os padrões se não existir)."""
    data = {}
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            # Mantém uma cópia do arquivo corrompido para o usuário analisar.
            try:
                os.replace(path, path + ".corrompido")
            except OSError:
                pass
            print(f"config.json inválido ({exc}); usando padrões.")
            data = {}
    cfg = normalize(data)
    if not os.path.isfile(path):
        save_config(cfg, path)
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    cfg = normalize(cfg)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return cfg


def ensure_dirs():
    for d in (TEMPLATES_DIR, SCREENSHOTS_DIR, LOGS_DIR, os.path.join(SCREENSHOTS_DIR, "errors")):
        os.makedirs(d, exist_ok=True)
