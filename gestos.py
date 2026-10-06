"""Reconhecimento de gestos a partir da posição da mão ao longo do tempo.

Gestos (todos com o braço esticado para a frente, na direção do Kinect):

- segurar_<zona>: mão parada por `segurar_s` segundos. A zona é a posição
  da mão em relação ao corpo, do ponto de vista de quem faz o gesto:
  acima (na altura da cabeça ou mais alto), direita, esquerda ou centro.
- deslizar_<direção>: mão anda rápido para cima/baixo/direita/esquerda.
- empurrar: mão parada avança rápido em direção ao Kinect.

Enquanto a pessoa está andando (tronco se deslocando), nada é reconhecido.
"""

from collections import deque


class Gestos:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mao = deque()      # (t, x, y, z) — x já no sentido do usuário
        self.tronco = deque()   # (t, x, z)
        self.espera_ate = 0.0
        self.travado_segurar = False

    def limpar(self):
        self.mao.clear()
        self.travado_segurar = False

    def zona(self, mao, pessoa) -> str:
        cfg = self.cfg
        sx = -1.0 if not cfg["inverter_x"] else 1.0
        rel_x = (mao[0] - pessoa.centro[0]) * sx
        rel_y = mao[1] - pessoa.topo[1]
        if rel_y > -cfg["zona_acima_m"]:
            return "acima"
        if rel_x > cfg["zona_lado_m"]:
            return "direita"
        if rel_x < -cfg["zona_lado_m"]:
            return "esquerda"
        return "centro"

    def atualizar(self, t: float, pessoa) -> list[str]:
        cfg = self.cfg
        if pessoa is None:
            self.limpar()
            self.tronco.clear()
            return []

        self.tronco.append((t, pessoa.centro[0], pessoa.centro[2]))
        while self.tronco and t - self.tronco[0][0] > cfg["janela_tronco_s"]:
            self.tronco.popleft()
        _, x0, z0 = self.tronco[0]
        andando = abs(pessoa.centro[0] - x0) + abs(pessoa.centro[2] - z0) > cfg["tronco_parado_m"]

        if pessoa.mao is None or andando:
            self.limpar()
            return []

        if self.mao and t - self.mao[-1][0] > cfg["intervalo_max_s"]:
            self.limpar()       # buraco no rastreio: recomeça do zero
        sx = -1.0 if not cfg["inverter_x"] else 1.0
        x, y, z = pessoa.mao
        self.mao.append((t, x * sx, y, z))
        while self.mao and t - self.mao[0][0] > cfg["historico_s"]:
            self.mao.popleft()

        if t < self.espera_ate:
            return []

        ev = self._deslizar(t) or self._empurrar(t)
        if ev:
            self.espera_ate = t + cfg["pausa_entre_gestos_s"]
            self.mao.clear()
            self.travado_segurar = False
            return [ev]

        ev = self._segurar(t, pessoa)
        return [ev] if ev else []

    # ----------------------------------------------------------------------
    def _deslizar(self, t):
        cfg = self.cfg
        _, xa, ya, _ = self.mao[-1]
        melhor = None
        for (ti, xi, yi, _) in self.mao:
            if t - ti > cfg["deslizar_janela_s"]:
                continue
            dx, dy = xa - xi, ya - yi
            if abs(dx) >= cfg["deslizar_dist_m"] and abs(dx) > 2 * abs(dy):
                melhor = "deslizar_direita" if dx > 0 else "deslizar_esquerda"
                break
            if abs(dy) >= cfg["deslizar_dist_m"] and abs(dy) > 2 * abs(dx):
                melhor = "deslizar_cima" if dy > 0 else "deslizar_baixo"
                break
        return melhor

    def _empurrar(self, t):
        cfg = self.cfg
        if t - self.mao[0][0] < cfg["empurrar_preparo_s"] + cfg["empurrar_janela_s"] * 0.5:
            return None
        _, xa, ya, za = self.mao[-1]
        for (ti, xi, yi, zi) in self.mao:
            if t - ti > cfg["empurrar_janela_s"]:
                continue
            if (zi - za >= cfg["empurrar_dist_m"]
                    and abs(xa - xi) + abs(ya - yi) < cfg["empurrar_desvio_m"]):
                return "empurrar"
            break
        return None

    def _segurar(self, t, pessoa):
        cfg = self.cfg
        if t - self.mao[0][0] < cfg["segurar_s"]:
            return None
        recentes = [s for s in self.mao if t - s[0] <= cfg["segurar_s"]]
        xs = [s[1] for s in recentes]
        ys = [s[2] for s in recentes]
        zs = [s[3] for s in recentes]
        espalhamento = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        if espalhamento > cfg["segurar_tolerancia_m"]:
            self.travado_segurar = False
            return None
        if self.travado_segurar:
            return None
        self.travado_segurar = True
        return "segurar_" + self.zona(pessoa.mao, pessoa)
