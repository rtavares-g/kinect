"""Simulador -> visão -> gestos -> controle, com o HA falso."""

import unittest

import config
from controle import Controle
from gestos import Gestos
from tests.falsos import HAFalso
from tests.simulador import Cena
from visao import Visao

FPS = 12


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

    def test_entra_no_quarto_liga_ar_e_sobe_temperatura(self):
        # entra andando
        for i in range(15):
            self.passo(dict(x=-0.8 + i * 0.05, z=2.4))
        self.assertEqual(self.c.estado, "observando")
        x = -0.1
        # mão parada acima da cabeça -> modo ar
        for _ in range(int(1.6 * FPS)):
            self.passo(dict(x=x, z=2.4, mao=(x + 0.1, 0.95, 2.0)))
        self.assertEqual(self.c.modo, "ar")
        # abaixa o braço, estica à frente e empurra -> liga o ar
        self.passo(dict(x=x, z=2.4))
        for _ in range(int(0.6 * FPS)):
            self.passo(dict(x=x, z=2.4, mao=(x + 0.1, 0.1, 2.05)))
        for k in range(4):
            self.passo(dict(x=x, z=2.4, mao=(x + 0.1, 0.1, 2.05 - 0.07 * (k + 1))))
        self.assertIn(("climate", "set_hvac_mode",
                       {"entity_id": "climate.ar_quarto", "hvac_mode": "cool"}), self.ha.chamadas)
        # desliza para cima -> +1 °C
        self.passo(dict(x=x, z=2.4))
        for _ in range(int(1.0 * FPS)):
            self.passo(dict(x=x, z=2.4))
        for _ in range(4):
            self.passo(dict(x=x, z=2.4, mao=(x + 0.1, -0.05, 1.9)))
        for k in range(5):
            self.passo(dict(x=x, z=2.4, mao=(x + 0.1, -0.05 + 0.08 * (k + 1), 1.9)))
        self.assertIn(("climate", "set_temperature",
                       {"entity_id": "climate.ar_quarto", "temperature": 23}), self.ha.chamadas)
        # sem comandos -> sai do modo por tempo
        for _ in range(int(11 * FPS)):
            self.passo(dict(x=x, z=2.4))
        self.assertIsNone(self.c.modo)
        self.assertEqual(self.c.estado, "observando")

    def test_luz_por_empurrar_e_pessoa_sai(self):
        for i in range(15):
            self.passo(dict(x=0.6 - i * 0.05, z=2.0))
        for _ in range(int(0.6 * FPS)):
            self.passo(dict(x=0, z=2.0, mao=(0.15, 0.1, 1.65)))
        for k in range(4):
            self.passo(dict(x=0, z=2.0, mao=(0.15, 0.1, 1.65 - 0.06 * (k + 1))))
        self.assertEqual(self.ha.chamadas, [("light", "toggle", {"entity_id": "light.modulo_dimmer_light_1"})])
        for _ in range(5):
            self.passo(None)
        self.assertEqual(self.c.estado, "ocioso")


if __name__ == "__main__":
    unittest.main()
