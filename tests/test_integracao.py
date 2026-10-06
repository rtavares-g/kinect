"""Simulador -> visão -> gestos -> controle, com o HA falso."""

import unittest

import config
from controle import Controle
from gestos import Gestos
from tests.falsos import HAFalso
from tests.simulador import Cena, mao_levantada
from visao import Visao

FPS = 12
DIR = "img_esq"   # mão direita do usuário aparece à esquerda da imagem


class TestIntegracao(unittest.TestCase):
    def setUp(self):
        cfg = config.carregar("/nao/existe")
        self.cena = Cena(semente=3)
        self.v = Visao(cfg["visao"])
        self.g = Gestos(cfg["gestos"])
        self.ha = HAFalso({"climate.ar_quarto": {"state": "off", "attributes": {"temperature": 22}}})
        self.t = 0.0
        self.c = Controle(cfg["controle"], self.ha, relogio=lambda: self.t)
        for _ in range(16):
            self.passo(None)

    def passo(self, pessoa):
        self.t += 1 / FPS
        p = self.v.processar(self.cena.quadro(pessoa=pessoa))
        conf = p is not None and p.confirmada
        self.c.pessoa(conf)
        for e in self.g.atualizar(self.t, p if conf else None):
            self.c.gesto(e)
        self.c.tick()
        return p

    def mao(self, x, z, s, dy=0.0, dz=0.0, celular=None):
        for _ in range(int(s * FPS)):
            self.passo(dict(x=x, z=z, maos={DIR: mao_levantada(x, z, DIR, dy=dy, dz=dz)}, celular=celular))

    def parado(self, x, z, s, celular=None):
        for _ in range(int(s * FPS)):
            self.passo(dict(x=x, z=z, celular=celular))

    def test_liga_ar_sobe_temperatura_e_sai_por_tempo(self):
        for i in range(15):                       # entra andando
            self.passo(dict(x=-0.8 + i * 0.05, z=2.4))
        self.assertEqual(self.c.estado, "observando")
        x, z = -0.1, 2.4
        self.mao(x, z, 1.8)                       # mão direita levantada e parada
        self.assertEqual(self.c.modo, "ar")
        self.parado(x, z, 0.3)                    # abaixa e levanta para o comando
        self.mao(x, z, 0.8)
        for k in range(4):                        # empurra -> liga o ar
            self.passo(dict(x=x, z=z, maos={DIR: mao_levantada(x, z, DIR, dz=-0.06 * (k + 1))}))
        self.assertIn(("climate", "set_hvac_mode",
                       {"entity_id": "climate.ar_quarto", "hvac_mode": "cool"}), self.ha.chamadas)
        self.mao(x, z, 1.0, dy=-0.2)              # mão um pouco mais baixa, parada
        for k in range(4):                        # desliza para cima -> +1 °C
            self.passo(dict(x=x, z=z, maos={DIR: mao_levantada(x, z, DIR, dy=-0.2 + 0.07 * (k + 1))}))
        self.assertIn(("climate", "set_temperature",
                       {"entity_id": "climate.ar_quarto", "temperature": 23}), self.ha.chamadas)
        self.parado(x, z, 11)                     # sem comandos -> sai do modo
        self.assertIsNone(self.c.modo)
        self.assertEqual(self.c.estado, "observando")

    def test_celular_na_mao_nao_dispara_nada(self):
        for i in range(15):
            self.passo(dict(x=0.6 - i * 0.05, z=2.0, celular="img_dir"))
        for k in range(int(8 * FPS)):             # mexendo no celular por 8 s
            self.passo(dict(x=0.0, z=2.0 + 0.01 * (k % 5), celular="img_dir"))
        self.assertEqual(self.ha.chamadas, [])
        self.assertEqual(self.c.estado, "observando")

    def test_empurrar_fora_do_modo_alterna_luz_e_pessoa_sai(self):
        for i in range(15):
            self.passo(dict(x=0.6 - i * 0.05, z=2.0))
        self.parado(0, 2.0, 0.5)
        self.mao(0, 2.0, 0.8)
        for k in range(4):
            self.passo(dict(x=0, z=2.0, maos={DIR: mao_levantada(0, 2.0, DIR, dz=-0.06 * (k + 1))}))
        self.assertEqual(self.ha.chamadas, [("light", "toggle", {"entity_id": "light.modulo_dimmer_light_1"})])
        for _ in range(5):
            self.passo(None)
        self.assertEqual(self.c.estado, "ocioso")


if __name__ == "__main__":
    unittest.main()
