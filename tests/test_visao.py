import unittest

import config
from tests.simulador import Cena, mao_levantada
from visao import Visao


def preparar(cena, visao, n=16):
    for _ in range(n):
        visao.processar(cena.quadro())


class TestVisao(unittest.TestCase):
    def setUp(self):
        self.cfg = config.carregar("/nao/existe")
        self.cena = Cena()
        self.v = Visao(self.cfg["visao"])
        preparar(self.cena, self.v)

    def test_sala_vazia_sem_pessoa(self):
        for _ in range(10):
            self.assertIsNone(self.v.processar(self.cena.quadro()))

    def test_pessoa_andando_e_confirmada(self):
        p = None
        for i in range(15):
            p = self.v.processar(self.cena.quadro(pessoa=dict(x=-0.4 + i * 0.04, z=2.3)))
        self.assertIsNotNone(p)
        self.assertTrue(p.cabeca_ok)
        self.assertTrue(p.confirmada)
        self.assertAlmostEqual(p.centro[2], 2.3, delta=0.15)

    def test_pessoa_parada_sem_gesto_nao_confirma(self):
        p = None
        for _ in range(15):
            p = self.v.processar(self.cena.quadro(pessoa=dict(x=0, z=2.3)))
        self.assertFalse(p is not None and p.confirmada)

    def test_pessoa_parada_com_mao_levantada_confirma(self):
        p = None
        for _ in range(15):
            p = self.v.processar(self.cena.quadro(
                pessoa=dict(x=0, z=2.3, maos={"img_esq": mao_levantada(0, 2.3, "img_esq")})))
        self.assertTrue(p.confirmada)

    def test_caixa_nao_e_humano(self):
        for i in range(30):
            p = self.v.processar(self.cena.quadro(caixa=dict(x=-0.5 + i * 0.03, z=2.0, largura=0.6, altura=1.2)))
            self.assertFalse(p is not None and p.confirmada)

    def test_maos_levantadas_localizadas(self):
        for lados in (["img_esq"], ["img_dir"], ["img_esq", "img_dir"]):
            v = Visao(self.cfg["visao"])
            preparar(self.cena, v)
            p = None
            for i in range(14):
                x = -0.2 + i * 0.03
                p = v.processar(self.cena.quadro(
                    pessoa=dict(x=x, z=2.2, maos={l: mao_levantada(x, 2.2, l) for l in lados})))
            self.assertEqual(sorted(p.maos), sorted(lados))
            for l in lados:
                for a, b in zip(p.maos[l][0], mao_levantada(x, 2.2, l)):
                    self.assertAlmostEqual(a, b, delta=0.07)

    def test_celular_no_peito_nao_e_mao(self):
        p = None
        for i in range(15):
            p = self.v.processar(self.cena.quadro(pessoa=dict(x=-0.3 + i * 0.04, z=2.0, celular="img_dir")))
        self.assertTrue(p.confirmada)
        self.assertEqual(p.maos, {})

    def test_cabeca_nao_vira_mao(self):
        p = None
        for i in range(15):
            p = self.v.processar(self.cena.quadro(pessoa=dict(x=-0.3 + i * 0.04, z=2.0)))
        self.assertEqual(p.maos, {})
        self.assertAlmostEqual(p.topo[0], p.centro[0], delta=0.08)

    def test_varias_distancias_e_alturas(self):
        for z in (1.8, 2.5, 3.2):
            for alt in (1.55, 1.9):
                v = Visao(self.cfg["visao"])
                preparar(self.cena, v)
                p = None
                for i in range(15):
                    p = v.processar(self.cena.quadro(pessoa=dict(x=-0.3 + i * 0.04, z=z, altura=alt)))
                self.assertTrue(p is not None and p.confirmada, f"z={z} altura={alt}")

    def test_cabeca_fora_do_quadro_pede_inclinacao(self):
        # perto e alto: a cabeça sai por cima da imagem; não dá para validar,
        # mas a visão avisa para o laço principal inclinar o Kinect para cima
        p = None
        for i in range(15):
            p = self.v.processar(self.cena.quadro(pessoa=dict(x=-0.3 + i * 0.04, z=1.2, altura=1.9)))
        self.assertFalse(p is not None and p.confirmada)
        self.assertTrue(self.v.cortado)

    def test_inclinar_mantem_fundo(self):
        for i in range(12):
            self.v.processar(self.cena.quadro(pessoa=dict(x=-0.3 + i * 0.04, z=2.2)))
        self.v.mudar_angulo(4)
        self.assertTrue(self.v.fundo_pronto())


if __name__ == "__main__":
    unittest.main()


class TestDeitado(unittest.TestCase):
    CAMA = dict(x=0.0, z=2.6, largura=1.9, altura=0.5)

    def setUp(self):
        self.cfg = config.carregar("/nao/existe")
        self.cena = Cena()
        self.v = Visao(self.cfg["visao"])
        for _ in range(20):
            self.v.processar(self.cena.quadro(caixas=[self.CAMA]))
        self.assertTrue(self.v.guardar_referencia())

    def ver(self, *caixas):
        r = None
        for _ in range(5):
            self.v.processar(self.cena.quadro(caixas=[self.CAMA, *caixas]))
            r = self.v.procurar_deitado()
        return r

    def test_cama_vazia(self):
        self.assertIsNone(self.ver())

    def test_pessoa_deitada(self):
        r = self.ver(dict(x=0.0, z=2.35, largura=1.7, altura=0.3, y0=0.5))
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r["comprimento_m"], 1.7, delta=0.25)

    def test_gato_na_cama_nao_conta(self):
        self.assertIsNone(self.ver(dict(x=0.3, z=2.4, largura=0.45, altura=0.25, y0=0.5)))

    def test_pessoa_deitada_ja_no_fundo_ainda_aparece(self):
        # deitada desde antes: o fundo vivo absorve, a referência do vazio não
        for _ in range(400):
            self.v.processar(self.cena.quadro(caixas=[self.CAMA, dict(x=0.0, z=2.35, largura=1.7, altura=0.3, y0=0.5)]))
        self.assertIsNotNone(self.v.procurar_deitado())
