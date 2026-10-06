import unittest
from types import SimpleNamespace

import config
from gestos import Gestos

FPS = 12
# Kinect de frente: a mão direita do usuário aparece à esquerda da imagem
DIR, ESQ = "img_esq", "img_dir"


def pessoa(maos, centro=(0.0, 0.0, 2.2)):
    return SimpleNamespace(maos={k: (v, (0, 0)) for k, v in maos.items()},
                           centro=centro, topo=(0.0, 0.75, 2.2))


class TestGestos(unittest.TestCase):
    def setUp(self):
        self.cfg = config.carregar("/nao/existe")["gestos"]
        self.g = Gestos(self.cfg)
        self.t = 0.0

    def rodar(self, quadros, centro=(0.0, 0.0, 2.2)):
        evs = []
        for maos in quadros:
            self.t += 1 / FPS
            evs += self.g.atualizar(self.t, pessoa(maos, centro))
        return evs

    def parada(self, lado, pos, s):
        return [{lado: pos}] * int(s * FPS)

    def linha(self, lado, a, b, s):
        n = max(2, int(s * FPS))
        return [{lado: tuple(a[k] + (b[k] - a[k]) * i / (n - 1) for k in range(3))} for i in range(n)]

    def baixar(self, s=0.3):
        return [{}] * int(s * FPS)

    # x da câmera: negativo = esquerda da imagem = direita do usuário
    def test_segurar_direita(self):
        self.assertEqual(self.rodar(self.parada(DIR, (-0.3, 0.7, 2.1), 1.6)), ["segurar_direita"])

    def test_segurar_esquerda(self):
        self.assertEqual(self.rodar(self.parada(ESQ, (0.3, 0.7, 2.1), 1.6)), ["segurar_esquerda"])

    def test_segurar_ambas(self):
        q = [{DIR: (-0.3, 0.7, 2.1), ESQ: (0.3, 0.7, 2.1)}] * int(1.6 * FPS)
        self.assertEqual(self.rodar(q), ["segurar_ambas"])

    def test_inverter_x(self):
        self.cfg["inverter_x"] = True
        self.assertEqual(self.rodar(self.parada(DIR, (-0.3, 0.7, 2.1), 1.6)), ["segurar_esquerda"])

    def test_segurar_dispara_uma_vez_e_nao_vale_com_mao_esquecida_no_ar(self):
        self.assertEqual(self.rodar(self.parada(DIR, (-0.3, 0.7, 2.1), 6)), ["segurar_direita"])

    def test_abaixar_e_levantar_de_novo_dispara_de_novo(self):
        q = self.parada(DIR, (-0.3, 0.7, 2.1), 1.6) + self.baixar() + self.parada(DIR, (-0.3, 0.7, 2.1), 1.6)
        self.assertEqual(self.rodar(q), ["segurar_direita", "segurar_direita"])

    def test_mao_tremendo_nao_segura(self):
        q = [{DIR: (-0.3 + 0.05 * (i % 4), 0.7, 2.1)} for i in range(int(2 * FPS))]
        self.assertEqual(self.rodar(q), [])

    def test_deslizar_cima_e_baixo(self):
        a = (-0.3, 0.6, 2.1)
        evs = self.rodar(self.parada(DIR, a, 0.8) + self.linha(DIR, a, (-0.3, 0.85, 2.1), 0.3))
        self.assertEqual(evs, ["deslizar_cima"])
        self.t += 1
        b = (-0.3, 0.85, 2.1)
        self.assertEqual(self.rodar(self.parada(DIR, b, 0.3) + self.linha(DIR, b, (-0.3, 0.62, 2.1), 0.3)),
                         ["deslizar_baixo"])

    def test_deslizar_direita_e_esquerda(self):
        a = (-0.2, 0.7, 2.1)
        self.assertEqual(self.rodar(self.parada(DIR, a, 0.8) + self.linha(DIR, a, (-0.5, 0.7, 2.1), 0.35)),
                         ["deslizar_direita"])
        self.t += 1
        b = (-0.5, 0.7, 2.1)
        self.assertEqual(self.rodar(self.parada(DIR, b, 0.3) + self.linha(DIR, b, (-0.2, 0.7, 2.1), 0.35)),
                         ["deslizar_esquerda"])

    def test_levantar_a_mao_nao_e_deslizar_cima(self):
        # a mão aparece já subindo (levantando o braço) e depois para
        q = self.linha(DIR, (-0.3, 0.45, 2.1), (-0.3, 0.75, 2.1), 0.4) + self.parada(DIR, (-0.3, 0.75, 2.1), 1.5)
        self.assertEqual(self.rodar(q), ["segurar_direita"])

    def test_empurrar(self):
        a = (-0.3, 0.7, 2.1)
        evs = self.rodar(self.parada(DIR, a, 0.8) + self.linha(DIR, a, (-0.3, 0.7, 1.9), 0.25))
        self.assertEqual(evs, ["empurrar"])

    def test_andando_nao_gera_gesto(self):
        evs = []
        for i in range(40):
            self.t += 1 / FPS
            c = (-1.0 + i * 0.05, 0.0, 2.2)
            evs += self.g.atualizar(self.t, pessoa({DIR: (c[0] - 0.3, 0.7 + 0.01 * (i % 3), 2.1)}, c))
        self.assertEqual(evs, [])

    def test_mao_frente_ignorada(self):
        q = [{"frente": (0.0, 0.4, 1.8)}] * int(2 * FPS)
        self.assertEqual(self.rodar(q), [])


if __name__ == "__main__":
    unittest.main()
