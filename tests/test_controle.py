import unittest

import config
import kinect_dev as kd
from controle import Controle
from tests.falsos import HAFalso


class Relogio:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class TestControle(unittest.TestCase):
    def setUp(self):
        self.cfg = config.carregar("/nao/existe")["controle"]
        self.ha = HAFalso({
            "climate.ar_quarto": {"state": "off", "attributes": {"temperature": 23}},
            "fan.quarto_gui": {"state": "on", "attributes": {"percentage": 50}},
            "light.modulo_dimmer_light_2": {"state": "on", "attributes": {}},
        })
        self.leds = []
        self.r = Relogio()
        self.c = Controle(self.cfg, self.ha, led=self.leds.append, relogio=self.r)

    def test_ocioso_ignora_gestos(self):
        self.c.gesto("segurar_direita")
        self.c.gesto("empurrar")
        self.assertEqual(self.ha.chamadas, [])

    def test_atalho_luz(self):
        self.c.pessoa(True)
        self.c.gesto("empurrar")
        self.assertEqual(self.ha.chamadas, [("light", "toggle", {"entity_id": "light.modulo_dimmer_light_1"})])

    def test_modo_ar(self):
        self.c.pessoa(True)
        self.c.gesto("segurar_direita")
        self.assertEqual(self.c.modo, "ar")
        self.c.gesto("empurrar")
        self.c.gesto("deslizar_cima")
        self.c.gesto("deslizar_direita")
        self.assertEqual(self.ha.chamadas, [
            ("climate", "set_hvac_mode", {"entity_id": "climate.ar_quarto", "hvac_mode": "cool"}),
            ("climate", "set_temperature", {"entity_id": "climate.ar_quarto", "temperature": 24}),
            ("climate", "set_hvac_mode", {"entity_id": "climate.ar_quarto", "hvac_mode": "cool"}),
        ])

    def test_ar_desliga_e_limita_temperatura(self):
        self.ha.estados["climate.ar_quarto"] = {"state": "cool", "attributes": {"temperature": 30}}
        self.c.pessoa(True)
        self.c.gesto("segurar_direita")
        self.c.gesto("deslizar_cima")
        self.c.gesto("deslizar_esquerda")
        self.c.gesto("empurrar")
        self.assertEqual(self.ha.chamadas, [
            ("climate", "set_temperature", {"entity_id": "climate.ar_quarto", "temperature": 30}),
            ("climate", "set_hvac_mode", {"entity_id": "climate.ar_quarto", "hvac_mode": "auto"}),
            ("climate", "set_hvac_mode", {"entity_id": "climate.ar_quarto", "hvac_mode": "off"}),
        ])

    def test_modo_ventilador(self):
        self.c.pessoa(True)
        self.c.gesto("segurar_esquerda")
        self.c.gesto("deslizar_cima")
        self.c.gesto("deslizar_baixo")
        self.c.gesto("empurrar")
        self.assertEqual(self.ha.chamadas, [
            ("fan", "set_percentage", {"entity_id": "fan.quarto_gui", "percentage": 75}),
            ("fan", "set_percentage", {"entity_id": "fan.quarto_gui", "percentage": 25}),
            ("fan", "toggle", {"entity_id": "fan.quarto_gui"}),
        ])

    def test_ventilador_desligado_sobe_para_primeiro_passo(self):
        self.ha.estados["fan.quarto_gui"] = {"state": "off", "attributes": {"percentage": 80}}
        self.c.pessoa(True)
        self.c.gesto("segurar_esquerda")
        self.c.gesto("deslizar_cima")
        self.assertEqual(self.ha.chamadas, [
            ("fan", "set_percentage", {"entity_id": "fan.quarto_gui", "percentage": 25})])

    def test_modo_pendente(self):
        self.c.pessoa(True)
        self.c.gesto("segurar_ambas")
        self.c.gesto("deslizar_baixo")
        self.c.gesto("empurrar")
        self.assertEqual(self.ha.chamadas, [
            ("light", "turn_on", {"entity_id": "light.modulo_dimmer_light_2", "brightness_step_pct": -20}),
            ("light", "toggle", {"entity_id": "light.modulo_dimmer_light_2"}),
        ])

    def test_no_modo_empurrar_nao_e_atalho(self):
        self.c.pessoa(True)
        self.c.gesto("segurar_direita")
        self.c.gesto("empurrar")
        self.assertNotIn("light", [c[0] for c in self.ha.chamadas])

    def test_sair_por_repeticao_e_troca(self):
        self.c.pessoa(True)
        self.c.gesto("segurar_direita")
        self.assertEqual(self.c.modo, "ar")
        self.c.gesto("segurar_direita")
        self.assertIsNone(self.c.modo)
        self.c.gesto("segurar_direita")
        self.c.gesto("segurar_esquerda")
        self.assertEqual(self.c.modo, "ventilador")
        self.c.gesto("segurar_ambas")
        self.assertEqual(self.c.modo, "pendente")

    def test_timeout(self):
        self.c.pessoa(True)
        self.c.gesto("segurar_direita")
        self.r.t += 6
        self.c.gesto("deslizar_cima")      # comando renova o prazo
        self.r.t += 6
        self.c.tick()
        self.assertEqual(self.c.modo, "ar")
        self.r.t += 5
        self.c.tick()
        self.assertIsNone(self.c.modo)
        self.assertEqual(self.c.estado, "observando")

    def test_pessoa_some_sai_do_modo(self):
        self.c.pessoa(True)
        self.c.gesto("segurar_direita")
        self.c.pessoa(False)
        self.assertEqual((self.c.estado, self.c.modo), ("ocioso", None))

    def test_leds(self):
        self.c.tick()
        self.c.pessoa(True)
        self.c.tick()
        self.c.gesto("segurar_direita")
        self.c.tick()
        self.r.t += 1
        self.c.tick()
        self.assertEqual(self.leds, [kd.LED_DESLIGADO, kd.LED_VERDE, kd.LED_VERMELHO, kd.LED_VERDE_PISCANDO])


if __name__ == "__main__":
    unittest.main()
