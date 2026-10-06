"""Gera quadros de profundidade sintéticos (640x480, mm) parecidos com os
do Kinect: parede, chão e uma pessoa com cabeça, tronco, braços e pernas,
opcionalmente com um braço esticado para a frente até a posição `mao`."""

import numpy as np

from visao import FX0, FY0, CX0, CY0

L, A = 640, 480
ALTURA_CAMERA = 1.0
_v, _u = np.mgrid[0:A, 0:L].astype(np.float32)


class Cena:
    def __init__(self, parede_m=3.5, ruido=True, semente=0):
        self.parede = parede_m
        self.ruido = ruido
        self.rng = np.random.default_rng(semente)

    def _fundo(self):
        z = np.full((A, L), self.parede, np.float32)
        abaixo = _v > CY0 + 1
        z_chao = np.where(abaixo, ALTURA_CAMERA * FY0 / np.maximum(_v - CY0, 1e-3), np.inf)
        return np.minimum(z, z_chao)

    @staticmethod
    def _retangulo(zbuf, x0, x1, y0, y1, z):
        u0, u1 = CX0 + x0 * FX0 / z, CX0 + x1 * FX0 / z
        v0, v1 = CY0 - y1 * FY0 / z, CY0 - y0 * FY0 / z
        m = (_u >= u0) & (_u <= u1) & (_v >= v0) & (_v <= v1)
        np.minimum(zbuf, np.where(m, z, np.inf), out=zbuf)

    @staticmethod
    def _elipse(zbuf, xc, yc, rx, ry, z):
        uc, vc = CX0 + xc * FX0 / z, CY0 - yc * FY0 / z
        ru, rv = rx * FX0 / z, ry * FY0 / z
        m = ((_u - uc) / ru) ** 2 + ((_v - vc) / rv) ** 2 <= 1
        np.minimum(zbuf, np.where(m, z, np.inf), out=zbuf)

    def _pessoa(self, zbuf, x, z, altura, mao):
        chao = -ALTURA_CAMERA
        topo = chao + altura
        ombro = topo - 0.26
        quadril = topo - 0.85
        self._elipse(zbuf, x, topo - 0.12, 0.085, 0.12, z)               # cabeça
        self._retangulo(zbuf, x - 0.05, x + 0.05, ombro, topo - 0.2, z)   # pescoço
        self._retangulo(zbuf, x - 0.21, x + 0.21, quadril, ombro, z + 0.02)  # tronco
        self._retangulo(zbuf, x - 0.17, x - 0.02, chao, quadril, z + 0.03)   # pernas
        self._retangulo(zbuf, x + 0.02, x + 0.17, chao, quadril, z + 0.03)
        self._retangulo(zbuf, x - 0.29, x - 0.21, quadril + 0.05, ombro, z + 0.03)  # braço caído
        if mao is None:
            self._retangulo(zbuf, x + 0.21, x + 0.29, quadril + 0.05, ombro, z + 0.03)
        else:
            # braço esticado do ombro até a mão, em segmentos com profundidade crescente
            ox, oy, oz = x + 0.22, ombro - 0.05, z
            hx, hy, hz = mao
            for t in np.linspace(0, 1, 12):
                px, py, pz = ox + (hx - ox) * t, oy + (hy - oy) * t, oz + (hz - oz) * t
                self._elipse(zbuf, px, py, 0.045, 0.045, pz)
            self._elipse(zbuf, hx, hy, 0.06, 0.08, hz)                   # mão

    def quadro(self, pessoa=None, caixa=None):
        """pessoa: dict(x, z, altura=1.75, mao=(x,y,z) ou None)
        caixa: dict(x, z, largura, altura) — objeto sem forma humana."""
        zbuf = self._fundo()
        if caixa:
            c = caixa
            self._retangulo(zbuf, c["x"] - c["largura"] / 2, c["x"] + c["largura"] / 2,
                            -ALTURA_CAMERA, -ALTURA_CAMERA + c["altura"], c["z"])
        if pessoa:
            self._pessoa(zbuf, pessoa["x"], pessoa["z"], pessoa.get("altura", 1.75), pessoa.get("mao"))
        if self.ruido:
            zbuf = zbuf + self.rng.normal(0, 1, zbuf.shape).astype(np.float32) * 0.0015 * zbuf ** 2
        mm = np.where(np.isfinite(zbuf) & (zbuf < 8), zbuf * 1000, 0)
        return mm.astype(np.uint16)
