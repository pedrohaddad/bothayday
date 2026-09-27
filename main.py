"""HayDayBot — ponto de entrada. Execute:  python main.py"""

import sys
import traceback

import config
from logger_setup import setup_logging


def main():
    config.ensure_dirs()
    cfg = config.load_config()
    log = setup_logging(config.LOGS_DIR, cfg.get("debug_log", False))
    try:
        from gui import App
    except ImportError as exc:
        msg = (f"Dependência ausente: {exc}\n\n"
               "Execute install.bat (ou: pip install -r requirements.txt).")
        log.error(msg)
        try:
            import tkinter.messagebox as mb
            mb.showerror("HayDayBot", msg)
        except Exception:  # noqa: BLE001
            print(msg, file=sys.stderr)
        return 1
    try:
        app = App()
        app.mainloop()
    except Exception:  # noqa: BLE001
        log.error("Erro fatal na interface:\n%s", traceback.format_exc())
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
