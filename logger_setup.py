"""Configuração de logs: arquivo diário em logs/ + fila para a interface."""

import datetime
import logging
import os
import queue
import sys

LOGGER_NAME = "haydaybot"

# Fila consumida pela interface (thread principal do Tk).
gui_log_queue = queue.Queue()


class QueueHandler(logging.Handler):
    def emit(self, record):
        try:
            gui_log_queue.put_nowait((record.levelno, self.format(record)))
        except Exception:  # nunca deixar o log derrubar o bot
            pass


def setup_logging(logs_dir, debug=False):
    logger = logging.getLogger(LOGGER_NAME)
    if getattr(logger, "_configured", False):
        set_debug(debug)
        return logger
    os.makedirs(logs_dir, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    short = logging.Formatter("[%(asctime)s] %(message)s", "%H:%M:%S")
    full = logging.Formatter("[%(asctime)s] %(levelname)-7s %(threadName)s: %(message)s",
                             "%Y-%m-%d %H:%M:%S")

    fname = os.path.join(logs_dir, f"haydaybot_{datetime.date.today():%Y%m%d}.log")
    fh = logging.FileHandler(fname, encoding="utf-8")
    fh.setFormatter(full)
    fh.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.addHandler(fh)

    qh = QueueHandler()
    qh.setFormatter(short)
    qh.setLevel(logging.INFO)
    logger.addHandler(qh)

    # Console só quando existe (no .exe --windowed stdout é None).
    if sys.stdout is not None:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(short)
        ch.setLevel(logging.INFO)
        logger.addHandler(ch)

    logger._configured = True
    logger._file_handler = fh
    return logger


def set_debug(debug):
    logger = logging.getLogger(LOGGER_NAME)
    fh = getattr(logger, "_file_handler", None)
    if fh is not None:
        fh.setLevel(logging.DEBUG if debug else logging.INFO)


def get_logger():
    return logging.getLogger(LOGGER_NAME)
