import unittest
from types import SimpleNamespace

import config
from gestos import Gestos

FPS = 12


def pessoa(mao, centro=(0.0, 0.0, 2.2), topo_y=0.75):
    return SimpleNamespace(mao=mao, centro=centro, topo=(0.0, topo_y, 2.2))


class TestGestos(unittest.TestCase):
    def setUp(self):
        self.cfg = config.carregar("/nao/existe")["gestos"]
        self.g = Gestos(self.cfg)
        self.t = 0.0

    def rodar(self, posicoes, centro=(0.0, 0.0, 2.2)):
        evs = []
        for m in posicoes:
            self.t += 1 / FPS
            evs += self.g.atualizar(self.t, pessoa(m, centro))
        return evs

    def parada(self, pos, s):
        return [pos] * int(s * FPS)

    def linha(self, a, b, s):
        n = max(2, int(s * FPS))
        return [tuple(a[k] + (b[k] - a[k]) * i / (n - 1) for k in range(3)) for i in range(n)]

    # x da câmera: positivo = esquerda do usuário (Kinect de frente para ele)
    def test_segurar_acima(self):
        self.assertEqual(self.rodar(self.parada((0.0, 0.85, 1.7), 1.6)), ["segurar_acima"])

    def test_segurar_direita_do_usuario(self):
        self.assertEqual(self.rodar(self.parada((-0.45, 0.1, 1.7), 1.6)), ["segurar_direita"])

    def test_segurar_esquerda_do_usuario(self):
        self.assertEqual(self.rodar(self.parada((0.45, 0.1, 1.7), 1.6)), ["segurar_esquerda"])

    def test_segurar_centro(self):
        self.assertEqual(self.rodar(self.parada((0.05, 0.1, 1.7), 1.6)), ["segurar_centro"])

    def test_segurar_dispara_uma_vez(self):
        self.assertEqual(self.rodar(self.parada((0.05, 0.1, 1.7), 4)), ["segurar_centro"])

    def test_deslizar_direita_e_cima(self):
        a = (0.2, 0.1, 1.7)
        evs = self.rodar(self.parada(a, 0.3) + self.linha(a, (-0.2, 0.1, 1.7), 0.35))
        self.assertEqual(evs, ["deslizar_direita"])
        self.t += 1
        b = (0.0, -0.1, 1.7)
        evs = self.rodar(self.parada(b, 0.3) + self.linha(b, (0.0, 0.25, 1.7), 0.35))
        self.assertEqual(evs, ["deslizar_cima"])

    def test_deslizar_esquerda_e_baixo(self):
        a = (-0.2, 0.1, 1.7)
        self.assertEqual(self.rodar(self.parada(a, 0.3) + self.linha(a, (0.15, 0.1, 1.7), 0.35)),
                         ["deslizar_esquerda"])
        self.t += 1
        b = (0.0, 0.3, 1.7)
        self.assertEqual(self.rodar(self.parada(b, 0.3) + self.linha(b, (0.0, -0.05, 1.7), 0.35)),
                         ["deslizar_baixo"])

    def test_empurrar(self):
        a = (0.05, 0.1, 1.8)
        evs = self.rodar(self.parada(a, 0.6) + self.linha(a, (0.05, 0.1, 1.6), 0.25))
        self.assertEqual(evs, ["empurrar"])

    def test_andando_nao_gera_gesto(self):
        evs = []
        for i in range(40):
            self.t += 1 / FPS
            c = (-1.0 + i * 0.05, 0.0, 2.2)
            evs += self.g.atualizar(self.t, pessoa((c[0] + 0.1, 0.1 + 0.01 * (i % 3), 1.7), c))
        self.assertEqual(evs, [])

    def test_sem_mao_limpa(self):
        self.rodar(self.parada((0.05, 0.1, 1.7), 1.0))
        self.rodar([None])
        self.assertEqual(self.rodar(self.parada((0.05, 0.1, 1.7), 1.0)), [])


if __name__ == "__main__":
    unittest.main()
