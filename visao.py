"""Detecção de pessoa e da mão a partir do mapa de profundidade.

Pipeline (tudo em 320x240, metade da resolução do Kinect):

1. Fundo: média lenta da profundidade da cena, aprendida pixel a pixel onde
   não há pessoa. Um fundo por ângulo do motor (mexer o motor muda a cena).
2. Primeiro plano: pixels pelo menos `limiar_fundo_m` mais perto que o fundo.
3. Componentes conexos viram candidatos. Cada um é medido em metros
   (altura, largura) e passa por um teste de silhueta: cabeça mais
   estreita que os ombros. Essa é a validação "é humano".
4. Um candidato só vira pessoa *confirmada* depois de parecer humano por
   vários quadros seguidos e de ter se mexido (objetos parados, como uma
   cadeira ou um casaco, nunca se mexem e acabam absorvidos pelo fundo).
5. Mão: dentro da pessoa, pontos bem mais perto do sensor que o tronco
   (braço esticado para a frente). O ponto mais próximo é a mão.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

# intrínsecos aproximados da câmera de profundidade do Kinect v1 (640x480)
FX0, FY0, CX0, CY0 = 594.21, 591.04, 339.5, 242.7
ESCALA = 2  # processamos em 320x240
FX, FY, CX, CY = FX0 / ESCALA, FY0 / ESCALA, CX0 / ESCALA, CY0 / ESCALA


@dataclass
class Pessoa:
    mascara: np.ndarray            # bool 240x320, corpo + braço
    bbox: tuple                    # x, y, w, h em pixels (sem a mão)
    centro: tuple                  # x, y, z em metros (tronco)
    topo: tuple                    # x, y, z em metros (topo da cabeça)
    topo_px: int                   # linha do topo da cabeça
    base_px: int                   # linha mais baixa do corpo
    altura_m: float
    largura_m: float
    cabeca_ok: bool
    mao: tuple | None = None       # x, y, z em metros
    mao_px: tuple | None = None
    confirmada: bool = False
    id: int = 0
    extras: dict = field(default_factory=dict)


def para_3d(u, v, z):
    """Pixel (320x240) + profundidade em m -> metros, Y para cima."""
    return ((u - CX) * z / FX, -(v - CY) * z / FY, z)


class Visao:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.fundos: dict[int, np.ndarray] = {}
        self.desconhecido: dict[int, np.ndarray] = {}  # pixels do fundo ainda não vistos
        self.quadros_fundo: dict[int, int] = {}
        self.angulo = 0
        self.rastro = None          # Pessoa do quadro anterior
        self.sequencia_humano = 0
        self.deslocamento = 0.0     # quanto o candidato rastreado já andou (m)
        self.ultimo_centro = None
        self.confirmada = False
        self.proximo_id = 1
        self.id_atual = 0
        self.movimento = 0.0        # fração de pixels que mudaram no quadro
        self.cortado = False        # há um corpo com a cabeça para fora da imagem
        self._anterior = None
        self._kernel = np.ones((3, 3), np.uint8)
        self._kernel_fechar = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 7))

    # ------------------------------------------------------------------ fundo
    def mudar_angulo(self, graus: int) -> None:
        """Troca o fundo ativo. Se ainda não há fundo para o novo ângulo,
        desloca o atual na vertical (inclinar o Kinect θ graus move a cena
        ~FY·tan(θ) linhas) e marca as linhas que entraram como desconhecidas."""
        antigo = self.angulo
        self.angulo = graus
        self._anterior = None
        if graus in self.fundos or antigo not in self.fundos or not self.fundo_pronto_em(antigo):
            return
        dv = int(round(FY * np.tan(np.radians(graus - antigo))))
        bg = np.zeros_like(self.fundos[antigo])
        desc = np.ones(bg.shape, bool)
        h = bg.shape[0]
        if abs(dv) < h:
            if dv >= 0:   # inclinou para cima: a cena desce na imagem
                bg[dv:] = self.fundos[antigo][:h - dv]
                desc[dv:] = self.desconhecido[antigo][:h - dv]
            else:
                bg[:h + dv] = self.fundos[antigo][-dv:]
                desc[:h + dv] = self.desconhecido[antigo][-dv:]
        self.fundos[graus] = bg
        self.desconhecido[graus] = desc
        self.quadros_fundo[graus] = self.cfg["quadros_fundo_inicial"]

    def fundo_pronto_em(self, graus: int) -> bool:
        return self.quadros_fundo.get(graus, 0) >= self.cfg["quadros_fundo_inicial"]

    def fundo_pronto(self) -> bool:
        return self.fundo_pronto_em(self.angulo)

    def _atualizar_fundo(self, d, valido, pessoa_mask, outros_fg):
        bg = self.fundos.get(self.angulo)
        n = self.quadros_fundo.get(self.angulo, 0)
        if bg is None:
            bg = np.where(valido, d, 0).astype(np.float32)
            self.fundos[self.angulo] = bg
            self.desconhecido[self.angulo] = ~valido
            self.quadros_fundo[self.angulo] = 1
            return
        desc = self.desconhecido[self.angulo]
        a = 1.0 / (n + 1) if n < self.cfg["quadros_fundo_inicial"] else self.cfg["alfa_fundo"]
        livre = valido & ~pessoa_mask
        # o fundo guarda a superfície mais distante vista (a parede, não quem passou)
        novo = livre & (desc | (d > bg + 0.05))
        bg[novo] = d[novo]
        desc[novo] = False
        atual = livre & ~novo & ~outros_fg
        bg[atual] += a * (d[atual] - bg[atual])
        # objetos que pararam (não são pessoa) entram no fundo devagar
        lento = valido & outros_fg & ~pessoa_mask
        bg[lento] += self.cfg["alfa_objeto"] * (d[lento] - bg[lento])
        self.quadros_fundo[self.angulo] = n + 1
        if n + 1 == self.cfg["quadros_fundo_inicial"]:
            # nunca teve leitura no aprendizado inicial (longe demais, janela):
            # fundo "infinito", assim quem entrar ali aparece como primeiro plano
            bg[desc] = 99.0
            desc[:] = False

    # ---------------------------------------------------------------- análise
    def _medir(self, d, comp_mask):
        """Mede um candidato. Devolve dict ou None se pequeno demais."""
        cfg = self.cfg
        zs = d[comp_mask]
        if zs.size < cfg["min_pixels"]:
            return None
        z_tronco = float(np.median(zs))
        # a mão/braço esticado fica bem à frente do tronco; tira da silhueta
        frente = comp_mask & (d < z_tronco - cfg["mao_frente_m"])
        corpo = comp_mask & ~frente
        ys, xs = np.nonzero(corpo)
        if ys.size < cfg["min_pixels"]:
            return None
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        altura = (y1 - y0 + 1) * z_tronco / FY
        largura = (x1 - x0 + 1) * z_tronco / FX

        # silhueta: largura da cabeça x largura dos ombros
        px_m = FY / z_tronco
        def largura_faixa(a_m, b_m):
            r0 = int(y0 + a_m * px_m)
            r1 = max(r0 + 1, int(y0 + b_m * px_m))
            faixa = corpo[r0:r1]
            if faixa.size == 0:
                return 0.0
            larguras = faixa.sum(axis=1)
            larguras = larguras[larguras > 0]
            return float(np.median(larguras)) / FX * z_tronco if larguras.size else 0.0
        cabeca = largura_faixa(0.04, 0.16)
        ombros = largura_faixa(0.30, 0.45)
        cabeca_ok = (cfg["cabeca_min_m"] <= cabeca <= cfg["cabeca_max_m"]
                     and ombros >= cabeca * cfg["razao_ombro_cabeca"])

        humano = (cfg["altura_min_m"] <= altura <= cfg["altura_max_m"]
                  and cfg["largura_min_m"] <= largura <= cfg["largura_max_m"]
                  and cabeca_ok)

        cy = int(np.median(ys))
        cx = int(np.median(xs))
        topo_cols = np.nonzero(corpo[y0])[0]
        topo_u = float(topo_cols.mean()) if topo_cols.size else float(cx)
        z_topo = float(np.median(d[y0:y0 + max(2, int(0.15 * px_m)), x0:x1 + 1][
            corpo[y0:y0 + max(2, int(0.15 * px_m)), x0:x1 + 1]]))

        mao = mao_px = None
        if frente.sum() * (z_tronco / FX) ** 2 >= cfg["mao_area_min_m2"]:
            zf = d[frente]
            zmin = float(zf.min())
            ponta = frente & (d < zmin + cfg["mao_profundidade_m"])
            vy, vx = np.nonzero(ponta)
            u, v = float(vx.mean()), float(vy.mean())
            zm = float(np.median(d[ponta]))
            mao = para_3d(u, v, zm)
            mao_px = (int(u), int(v))

        return dict(
            mascara=comp_mask, bbox=(int(x0), int(y0), int(x1 - x0 + 1), int(y1 - y0 + 1)),
            centro=para_3d(cx, cy, z_tronco), topo=para_3d(topo_u, y0, z_topo),
            topo_px=int(y0), base_px=int(y1), altura_m=altura, largura_m=largura,
            cabeca_ok=cabeca_ok, humano=humano, mao=mao, mao_px=mao_px,
            cabeca_m=cabeca, ombros_m=ombros)

    def processar(self, profundidade_mm: np.ndarray) -> Pessoa | None:
        cfg = self.cfg
        d = profundidade_mm[::ESCALA, ::ESCALA].astype(np.float32) / 1000.0
        valido = (d >= cfg["alcance_min_m"]) & (d <= cfg["alcance_max_m"])

        # movimento bruto (usado como gatilho de presença pelo próprio Kinect)
        if self._anterior is not None:
            ambos = valido & self._anterior[1]
            mud = ambos & (np.abs(d - self._anterior[0]) > cfg["limiar_movimento_m"])
            self.movimento = float(mud.sum()) / max(1, int(ambos.sum()))
        self._anterior = (d, valido)

        bg = self.fundos.get(self.angulo)
        if bg is None or not self.fundo_pronto():
            self._atualizar_fundo(d, valido, np.zeros_like(valido), np.zeros_like(valido))
            return None

        desc = self.desconhecido[self.angulo]
        fg = valido & ~desc & (d < bg - cfg["limiar_fundo_m"])
        fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_OPEN, self._kernel)
        # o fechamento só serve para agrupar (ex.: cabeça separada do tronco
        # quando o pescoço some no ruído); a máscara final continua sendo fg
        juntos = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._kernel_fechar)
        n, rot, stats, _ = cv2.connectedComponentsWithStats(juntos, connectivity=8)
        fg_bool = fg.astype(bool)

        candidatos = []
        self.cortado = False
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < cfg["min_pixels"]:
                continue
            m = self._medir(d, (rot == i) & fg_bool)
            if m is not None:
                candidatos.append(m)
                # corpo grande encostado no topo da imagem: cabeça fora do quadro
                if (m["topo_px"] <= 1 and m["altura_m"] >= 0.8
                        and cfg["largura_min_m"] <= m["largura_m"] <= cfg["largura_max_m"]):
                    self.cortado = True

        escolhido = self._escolher(candidatos)
        if escolhido is not None:
            pessoa_mask = cv2.dilate(escolhido["mascara"].astype(np.uint8),
                                     self._kernel, iterations=3).astype(bool)
        else:
            pessoa_mask = np.zeros_like(fg_bool)
        self._atualizar_fundo(d, valido, pessoa_mask, fg_bool & ~pessoa_mask)

        if escolhido is None:
            self._perder()
            return None

        p = Pessoa(**{k: escolhido[k] for k in (
            "mascara", "bbox", "centro", "topo", "topo_px", "base_px", "altura_m",
            "largura_m", "cabeca_ok", "mao", "mao_px")})
        p.extras = {"cabeca_m": escolhido["cabeca_m"], "ombros_m": escolhido["ombros_m"]}
        p.confirmada = self.confirmada
        p.id = self.id_atual
        self.rastro = p
        return p

    def _escolher(self, candidatos):
        """Mantém o rastro da mesma pessoa e decide a confirmação."""
        cfg = self.cfg
        if not candidatos:
            return None
        if self.rastro is not None:
            px, _, pz = self.rastro.centro
            def dist(c):
                x, _, z = c["centro"]
                return np.hypot(x - px, z - pz)
            perto = [c for c in candidatos if dist(c) < cfg["salto_max_m"]]
            if perto:
                c = min(perto, key=dist)
                return self._seguir(c)
        humanos = [c for c in candidatos if c["humano"]]
        if not humanos:
            self._perder()
            return None
        c = max(humanos, key=lambda c: c["mascara"].sum())
        self._novo_rastro(c)
        return self._seguir(c)

    def _novo_rastro(self, c):
        self.sequencia_humano = 0
        self.deslocamento = 0.0
        self.ultimo_centro = c["centro"]
        self.confirmada = False
        self.id_atual = self.proximo_id
        self.proximo_id += 1

    def _seguir(self, c):
        if self.rastro is None and self.ultimo_centro is None:
            self._novo_rastro(c)
        if self.ultimo_centro is not None:
            dx = c["centro"][0] - self.ultimo_centro[0]
            dz = c["centro"][2] - self.ultimo_centro[2]
            self.deslocamento += float(np.hypot(dx, dz))
        self.ultimo_centro = c["centro"]
        if c["humano"]:
            self.sequencia_humano += 1
        elif not self.confirmada:
            self.sequencia_humano = 0
        if (not self.confirmada and self.sequencia_humano >= self.cfg["quadros_confirmar"]
                and (self.deslocamento >= self.cfg["deslocamento_confirmar_m"]
                     or c["mao"] is not None)):
            self.confirmada = True
        if not self.confirmada and not c["humano"] and self.sequencia_humano == 0:
            # candidato rastreado deixou de parecer gente antes de confirmar
            self._perder()
            return None
        return c

    def _perder(self):
        self.rastro = None
        self.ultimo_centro = None
        self.confirmada = False
        self.sequencia_humano = 0
        self.deslocamento = 0.0


def imagem_debug(profundidade_mm: np.ndarray, pessoa: Pessoa | None, texto: str = "") -> np.ndarray:
    d = profundidade_mm[::ESCALA, ::ESCALA].astype(np.float32)
    img = np.clip(255 - d / 4500 * 255, 0, 255).astype(np.uint8)
    img[d == 0] = 0
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if pessoa is not None:
        cor = (0, 200, 0) if pessoa.confirmada else (0, 200, 255)
        img[pessoa.mascara] = (img[pessoa.mascara] * 0.5 + np.array(cor) * 0.5).astype(np.uint8)
        x, y, w, h = pessoa.bbox
        cv2.rectangle(img, (x, y), (x + w, y + h), cor, 1)
        if pessoa.mao_px:
            cv2.circle(img, pessoa.mao_px, 6, (0, 0, 255), 2)
    if texto:
        cv2.putText(img, texto, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return img
