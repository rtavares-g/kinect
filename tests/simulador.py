"""Gera quadros de profundidade sintéticos (640x480, mm) parecidos com os
do Kinect: parede, chão e uma pessoa com cabeça, tronco, braços e pernas,
com mãos levantadas (`maos`) ou segurando um celular na frente do peito."""

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

    def _braco(self, zbuf, ombro, mao):
        """Braço do ombro até a mão, em segmentos com profundidade interpolada."""
        ox, oy, oz = ombro
        hx, hy, hz = mao
        for t in np.linspace(0, 1, 14):
            self._elipse(zbuf, ox + (hx - ox) * t, oy + (hy - oy) * t, 0.045, 0.045, oz + (hz - oz) * t)
        self._elipse(zbuf, hx, hy, 0.06, 0.08, hz)

    def _pessoa(self, zbuf, x, z, altura, maos, celular):
        chao = -ALTURA_CAMERA
        topo = chao + altura
        ombro = topo - 0.26
        quadril = topo - 0.85
        self._elipse(zbuf, x, topo - 0.12, 0.085, 0.12, z)               # cabeça
        self._retangulo(zbuf, x - 0.05, x + 0.05, ombro, topo - 0.2, z)   # pescoço
        self._retangulo(zbuf, x - 0.21, x + 0.21, quadril, ombro, z + 0.02)  # tronco
        self._retangulo(zbuf, x - 0.17, x - 0.02, chao, quadril, z + 0.03)   # pernas
        self._retangulo(zbuf, x + 0.02, x + 0.17, chao, quadril, z + 0.03)
        lados = {"img_esq": -1, "img_dir": 1}
        for nome, sinal in lados.items():
            ox = x + sinal * 0.22
            if nome in maos:
                self._braco(zbuf, (ox, ombro - 0.03, z), maos[nome])
            elif celular == nome:
                # antebraço dobrado segurando o celular na frente do peito
                self._braco(zbuf, (ox, ombro - 0.3, z), (x + sinal * 0.05, ombro - 0.2, z - 0.28))
            else:
                self._retangulo(zbuf, min(ox, ox + sinal * 0.08), max(ox, ox + sinal * 0.08),
                                quadril + 0.05, ombro, z + 0.03)       # braço caído

    def quadro(self, pessoa=None, caixa=None):
        """pessoa: dict(x, z, altura=1.75, maos={"img_esq"|"img_dir": (x,y,z)},
                       celular="img_esq"|"img_dir"|None)
        caixa: dict(x, z, largura, altura) — objeto sem forma humana."""
        zbuf = self._fundo()
        if caixa:
            c = caixa
            self._retangulo(zbuf, c["x"] - c["largura"] / 2, c["x"] + c["largura"] / 2,
                            -ALTURA_CAMERA, -ALTURA_CAMERA + c["altura"], c["z"])
        if pessoa:
            self._pessoa(zbuf, pessoa["x"], pessoa["z"], pessoa.get("altura", 1.75),
                         pessoa.get("maos", {}), pessoa.get("celular"))
        if self.ruido:
            zbuf = zbuf + self.rng.normal(0, 1, zbuf.shape).astype(np.float32) * 0.0015 * zbuf ** 2
        mm = np.where(np.isfinite(zbuf) & (zbuf < 8), zbuf * 1000, 0)
        return mm.astype(np.uint16)


def mao_levantada(x_pessoa, z_pessoa, lado, altura=1.75, dx=0.0, dy=0.0, dz=0.0):
    """Posição de uma mão levantada ao lado da cabeça (lado da imagem)."""
    sinal = -1 if lado == "img_esq" else 1
    topo = -ALTURA_CAMERA + altura
    return (x_pessoa + sinal * 0.32 + dx, topo - 0.05 + dy, z_pessoa - 0.05 + dz)
