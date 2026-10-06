"""Acesso ao Kinect v1 (Xbox 360) pela libfreenect_sync, via ctypes.

O Debian não empacota o binding Python do libfreenect, mas a biblioteca
"sync" (libfreenect_sync.so) tem uma API C simples: pega o último quadro
de profundidade, mexe o motor de inclinação e o LED. Só usamos a
profundidade (em milímetros); a câmera RGB não é necessária e economiza
CPU/USB no Pi.
"""

import ctypes
import ctypes.util

import numpy as np

LARGURA, ALTURA = 640, 480

FREENECT_DEPTH_MM = 5

LED_DESLIGADO = 0
LED_VERDE = 1
LED_VERMELHO = 2
LED_AMARELO = 3
LED_VERDE_PISCANDO = 4
LED_VERMELHO_AMARELO_PISCANDO = 6

TILT_MIN, TILT_MAX = -27, 27


class ErroKinect(IOError):
    pass


class Kinect:
    def __init__(self, indice: int = 0):
        nome = ctypes.util.find_library("freenect_sync") or "libfreenect_sync.so.0.5"
        self.lib = ctypes.CDLL(nome)
        self.indice = indice
        L = self.lib
        L.freenect_sync_get_depth.argtypes = [
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_int, ctypes.c_int]
        L.freenect_sync_get_depth.restype = ctypes.c_int
        L.freenect_sync_set_tilt_degs.argtypes = [ctypes.c_int, ctypes.c_int]
        L.freenect_sync_set_tilt_degs.restype = ctypes.c_int
        L.freenect_sync_set_led.argtypes = [ctypes.c_int, ctypes.c_int]
        L.freenect_sync_set_led.restype = ctypes.c_int
        L.freenect_sync_stop.argtypes = []
        self.angulo = 0
        self._led = None

    def profundidade(self) -> np.ndarray:
        """Último quadro de profundidade, 480x640 uint16 em mm (0 = sem leitura)."""
        buf = ctypes.c_void_p()
        ts = ctypes.c_uint32()
        r = self.lib.freenect_sync_get_depth(
            ctypes.byref(buf), ctypes.byref(ts), self.indice, FREENECT_DEPTH_MM)
        if r != 0 or not buf.value:
            raise ErroKinect("sem quadro de profundidade (câmera do Kinect não abriu)")
        ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint16))
        return np.ctypeslib.as_array(ptr, shape=(ALTURA, LARGURA)).copy()

    def inclinar(self, graus: int) -> bool:
        graus = int(max(TILT_MIN, min(TILT_MAX, round(graus))))
        if self.lib.freenect_sync_set_tilt_degs(graus, self.indice) != 0:
            return False
        self.angulo = graus
        return True

    def led(self, modo: int) -> None:
        if modo == self._led:
            return
        if self.lib.freenect_sync_set_led(modo, self.indice) == 0:
            self._led = modo

    def parar(self) -> None:
        try:
            self.led(LED_DESLIGADO)
        finally:
            self.lib.freenect_sync_stop()
