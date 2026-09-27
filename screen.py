"""Captura de tela do emulador, gravação de screenshots e detecção de tela congelada."""

import datetime
import os
import threading
import time

import cv2
import numpy as np

from image_detector import imwrite_unicode


class Screen:
    FREEZE_DIFF = 1.5  # diferença média (0-255) abaixo da qual a tela é considerada igual

    def __init__(self, adb, screenshots_dir):
        self.adb = adb
        self.dir = screenshots_dir
        self.last = None
        self.last_time = 0.0
        self._thumb = None
        self._last_change = time.monotonic()
        self._lock = threading.Lock()

    def capture(self):
        img = self.adb.screencap()
        now = time.monotonic()
        thumb = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (96, 54),
                           interpolation=cv2.INTER_AREA).astype(np.int16)
        with self._lock:
            if self._thumb is None or self._thumb.shape != thumb.shape or \
                    float(np.mean(np.abs(thumb - self._thumb))) > self.FREEZE_DIFF:
                self._last_change = now
            self._thumb = thumb
            self.last = img
            self.last_time = now
        return img

    def seconds_unchanged(self):
        """Há quanto tempo as capturas são idênticas (o Hay Day tem animações contínuas)."""
        with self._lock:
            if self._thumb is None:
                return 0.0
            return time.monotonic() - self._last_change

    def reset_freeze(self):
        with self._lock:
            self._last_change = time.monotonic()

    @property
    def size(self):
        if self.last is None:
            return None
        h, w = self.last.shape[:2]
        return w, h

    def save(self, img=None, prefix="screen", subdir=""):
        img = self.last if img is None else img
        if img is None:
            return None
        folder = os.path.join(self.dir, subdir) if subdir else self.dir
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = os.path.join(folder, f"{prefix}_{stamp}.png")
        return imwrite_unicode(path, img)
