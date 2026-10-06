"""Reconhecimento de gestos a partir das mãos levantadas.

Só contam mãos levantadas acima da linha dos ombros, ao lado da cabeça.
Mão no colo, celular na frente do peito ou do rosto etc. são ignorados.

Gestos ("direita"/"esquerda" do ponto de vista de quem faz o gesto):

- segurar_direita / segurar_esquerda / segurar_ambas:
  levantar a mão (ou as duas) e deixar parada por `segurar_s`. Só vale logo
  depois de levantar; quem fica com a mão parada no ar entre um comando e
  outro não dispara de novo. Para repetir, abaixa e levanta outra vez.
- deslizar_<cima|baixo|direita|esquerda>: com a mão já levantada, mover
  rápido nessa direção.
- empurrar: com a mão já levantada e parada, avançar a palma rápido em
  direção ao Kinect.

Enquanto a pessoa está andando (tronco se deslocando), nada é reconhecido.
"""

from collections import deque


class Gestos:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mao = deque()      # (t, x, y, z) — x já no sentido do usuário
        self.tronco = deque()   # (t, x, z)
        self.lado = None        # qual mão está sendo seguida
        self.inicio = 0.0       # quando essa mão foi levantada
        self.ambas_desde = None
        self.espera_ate = 0.0
        self.segurou = False

    def limpar(self):
        self.mao.clear()
        self.lado = None
        self.segurou = False
        self.ambas_desde = None

    def _nome_lado(self, chave: str) -> str:
        # Kinect de frente para a pessoa: a mão direita dela aparece à
        # esquerda da imagem (a menos que a imagem venha espelhada)
        direita = "img_esq" if not self.cfg["inverter_x"] else "img_dir"
        return "direita" if chave == direita else "esquerda"

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

        maos = {k: v for k, v in (pessoa.maos or {}).items() if k in ("img_esq", "img_dir")}
        if andando or not maos:
            self.limpar()
            return []

        laterais = [k for k in ("img_esq", "img_dir") if k in maos]
        if len(laterais) == 2:
            self.ambas_desde = self.ambas_desde or t
        else:
            self.ambas_desde = None

        if self.lado not in maos or (self.mao and t - self.mao[-1][0] > cfg["intervalo_max_s"]):
            # mão nova (ou a anterior abaixou): começa um rastro do zero
            self.mao.clear()
            self.segurou = False
            self.lado = laterais[0]
            self.inicio = t

        sx = -1.0 if not cfg["inverter_x"] else 1.0
        x, y, z = maos[self.lado][0]
        self.mao.append((t, x * sx, y, z))
        while self.mao and t - self.mao[0][0] > cfg["historico_s"]:
            self.mao.popleft()

        if t < self.espera_ate:
            return []

        ev = self._deslizar(t) or self._empurrar(t)
        if ev:
            self.espera_ate = t + cfg["pausa_entre_gestos_s"]
            self.mao.clear()
            self.segurou = True   # depois de um comando, segurar não vale até levantar de novo
            return [ev]

        ev = self._segurar(t)
        if ev:
            self.espera_ate = t + cfg["pausa_entre_gestos_s"]
            return [ev]
        return []

    # ----------------------------------------------------------------------
    def _deslizar(self, t):
        cfg = self.cfg
        _, xa, ya, _ = self.mao[-1]
        for (ti, xi, yi, _) in self.mao:
            if t - ti > cfg["deslizar_janela_s"]:
                continue
            if ti - self.inicio < cfg["deslizar_preparo_s"]:
                continue   # o próprio movimento de levantar a mão não conta
            dx, dy = xa - xi, ya - yi
            if abs(dx) >= cfg["deslizar_dist_m"] and abs(dx) > 2 * abs(dy):
                return "deslizar_direita" if dx > 0 else "deslizar_esquerda"
            if abs(dy) >= cfg["deslizar_dist_v_m"] and abs(dy) > 2 * abs(dx):
                return "deslizar_cima" if dy > 0 else "deslizar_baixo"
        return None

    def _empurrar(self, t):
        cfg = self.cfg
        _, xa, ya, za = self.mao[-1]
        for (ti, xi, yi, zi) in self.mao:
            if t - ti > cfg["empurrar_janela_s"]:
                continue
            if ti - self.inicio < cfg["empurrar_preparo_s"]:
                continue
            if (zi - za >= cfg["empurrar_dist_m"]
                    and abs(xa - xi) + abs(ya - yi) < cfg["empurrar_desvio_m"]):
                return "empurrar"
            return None
        return None

    def _segurar(self, t):
        cfg = self.cfg
        if self.segurou or t - self.inicio < cfg["segurar_s"]:
            return None
        if t - self.inicio > cfg["segurar_s"] + cfg["segurar_fresco_s"]:
            return None   # mão está levantada há tempo demais (ficou parada no ar)
        recentes = [s for s in self.mao if t - s[0] <= cfg["segurar_s"]]
        if len(recentes) < 3:
            return None
        espalhamento = max(max(s[i] for s in recentes) - min(s[i] for s in recentes)
                           for i in (1, 2, 3))
        if espalhamento > cfg["segurar_tolerancia_m"]:
            return None
        self.segurou = True
        if self.ambas_desde is not None and t - self.ambas_desde >= cfg["segurar_s"] * 0.7:
            return "segurar_ambas"
        return "segurar_" + self._nome_lado(self.lado)
