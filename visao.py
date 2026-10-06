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
5. Cabeça: sobe do peito (parte mais grossa da silhueta) seguindo o
   contorno até onde ele afina (pescoço) e continua até o topo.
6. Mãos: o que sobra da silhueta acima da linha dos ombros, fora da
   cabeça. A ponta de cada braço levantado é uma mão.
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
    maos: dict = field(default_factory=dict)  # "img_esq"/"img_dir" -> (xyz, px)
    ombro_px: int = 0
    confirmada: bool = False
    id: int = 0
    extras: dict = field(default_factory=dict)


def para_3d(u, v, z):
    """Pixel (320x240) + profundidade em m -> metros, Y para cima."""
    return ((u - CX) * z / FX, -(v - CY) * z / FY, z)


def _trechos(linha: np.ndarray):
    """Trechos contínuos True de uma linha: lista de (início, fim exclusivo)."""
    dif = np.diff(np.concatenate(([0], linha.astype(np.int8), [0])))
    return list(zip(np.nonzero(dif == 1)[0], np.nonzero(dif == -1)[0]))


def _subir_ate_cabeca(mascara: np.ndarray, cx: int, cy: int):
    """Sobe do peito seguindo o trecho central da silhueta linha a linha:
    onde ela afina é o pescoço, e o que continua para cima é a cabeça.
    Segue o corpo mesmo inclinado. Devolve (y_topo, y_pescoço, máscara da
    cabeça, x do centro da cabeça, largura da cabeça em px) ou None."""
    trechos = _trechos(mascara[cy])
    atual = next(((a, b) for a, b in trechos if a <= cx < b), None)
    if atual is None:
        return None
    larg_peito = atual[1] - atual[0]
    cabeca = np.zeros_like(mascara)
    pescoco = None
    larg_cab = 0
    topo = cy
    for r in range(cy - 1, -1, -1):
        a0, b0 = atual
        c0 = (a0 + b0) / 2
        # entre os trechos que encostam no anterior, o mais perto do centro
        # (acima dos ombros há braço, pescoço, braço: queremos o do meio)
        vizinhos = [(a, b) for a, b in _trechos(mascara[r]) if min(b, b0) > max(a, a0)]
        if not vizinhos:
            break
        # até o pescoço, a referência é a coluna do peito (o braço levantado
        # colado na cabeça não puxa a subida para o lado); depois, a cabeça
        ref = cx if pescoco is None else c0
        melhor = min(vizinhos, key=lambda t: abs((t[0] + t[1]) / 2 - ref))
        a, b = melhor
        if pescoco is None:
            if b - a < 0.6 * larg_peito:
                pescoco = r
                larg_cab = b - a
        else:
            # braço encostado na cabeça alarga o trecho: corta em volta do centro
            c = (a0 + b0) / 2
            limite = max(larg_cab, b0 - a0) * 0.9
            a, b = max(a, int(c - limite)), min(b, int(c + limite) + 1)
            larg_cab = max(larg_cab, b - a)
        if pescoco is not None:
            cabeca[r, a:b] = True
        atual = (a, b)
        topo = r
    if pescoco is None or not cabeca.any():
        return None
    xs = np.nonzero(cabeca.any(axis=0))[0]
    return topo, pescoco, cabeca, int((xs.min() + xs.max()) // 2), int(larg_cab)


class Visao:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.fundos: dict[int, np.ndarray] = {}
        self.desconhecido: dict[int, np.ndarray] = {}  # pixels do fundo ainda não vistos
        self.quadros_fundo: dict[int, int] = {}
        self.angulo = 0
        self.rastro = None          # Pessoa do quadro anterior
        self.sequencia_humano = 0
        self.falhas_humano = 0
        self.origem = (0.0, 0.0, 0.0)
        self.deslocamento = 0.0     # quanto o candidato rastreado já andou (m)
        self.ultimo_centro = None
        self.confirmada = False
        self.proximo_id = 1
        self.id_atual = 0
        self.movimento = 0.0        # fração de pixels que mudaram no quadro
        self.cortado = False        # há um corpo com a cabeça para fora da imagem
        self._anterior = None
        self._reancorar = None
        self.maior_candidato = None
        self.referencias: dict[int, np.ndarray] = {}   # quarto vazio, por ângulo
        self.deitado_mascara = None
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
        # o deslocamento não é perfeito (o Kinect gira pela base, não pela
        # lente): no primeiro quadro novo, tudo fora da pessoa é reaprendido
        regiao = np.zeros(bg.shape, bool)
        m = self.rastro.mascara if self.rastro is not None else self.maior_candidato
        if m is not None and abs(dv) < h:
            if dv >= 0:
                regiao[dv:] = m[:h - dv]
            else:
                regiao[:h + dv] = m[-dv:]
            z = float(self.rastro.centro[2]) if self.rastro is not None else 2.0
            r = max(3, int(0.35 * FX / z))
            kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
            regiao = cv2.dilate(regiao.astype(np.uint8), kern).astype(bool)
        self._reancorar = regiao

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
    def _medir(self, d, comp_mask, ox=0, oy=0):
        """Mede um candidato. Devolve dict ou None se pequeno demais.

        Braços levantados atrapalham o "topo" da silhueta, então primeiro
        acha a coluna do tronco (a mais alta em pixels) e a cabeça perto
        dela; o resto acima da linha dos ombros, para os lados, são mãos.
        """
        cfg = self.cfg
        zs = d[comp_mask]
        if zs.size < cfg["min_pixels"]:
            return None
        z0 = float(np.median(zs))
        ys, xs = np.nonzero(comp_mask)
        x0, x1 = xs.min(), xs.max()
        px_x = FX / z0
        px_y = FY / z0

        # tronco = parte mais grossa da silhueta (máximo da transformada de
        # distância); braços e pernas são finos, a cabeça é menor que o peito
        dist = cv2.distanceTransform(comp_mask.astype(np.uint8), cv2.DIST_L2, 3)
        cy_t, cx_t = np.unravel_index(int(np.argmax(dist)), dist.shape)
        cx_t = int(cx_t)

        cols = np.arange(comp_mask.shape[1])
        # o pescoço às vezes some por uma ou duas linhas no ruído: sobe por uma
        # versão fechada da silhueta
        fechada = cv2.morphologyEx(comp_mask.astype(np.uint8), cv2.MORPH_CLOSE,
                                   self._kernel_fechar).astype(bool)
        cab = _subir_ate_cabeca(fechada, cx_t, int(cy_t))
        if cab is None:
            # sem cabeça reconhecível neste quadro: mede assim mesmo (não é
            # "humano" agora, mas uma pessoa já confirmada continua rastreada)
            topo_m = int(np.nonzero(comp_mask.any(axis=1))[0].min())
            cab = (topo_m, int(topo_m + 0.25 * px_y), np.zeros_like(comp_mask), cx_t, 0)
        y_cab, y_pescoco, cabeca_mask, cx_cab, larg_cab_px = cab
        y_ombro = int(y_pescoco + 0.05 * px_y)

        # profundidade do tronco medida no peito (não nas pernas sobre a cama)
        peito = comp_mask[y_ombro:int(y_ombro + 0.3 * px_y)]
        peito = peito & (np.abs(cols - cx_t) <= int(0.2 * px_x))[None, :]
        zp = d[y_ombro:int(y_ombro + 0.3 * px_y)][peito]
        z_tronco = float(np.median(zp)) if zp.size > 20 else z0
        px_x = FX / z_tronco
        px_y = FY / z_tronco

        frente = comp_mask & (d < z_tronco - cfg["mao_frente_m"])
        corpo = comp_mask & ~frente
        ys_c = np.nonzero(corpo)[0]
        if ys_c.size < cfg["min_pixels"]:
            return None
        y1 = int(ys_c.max())
        altura = (y1 - y_cab + 1) / px_y

        def largura_linhas(r0, r1, faixa_m=None):
            bloco = corpo[max(0, r0):max(r0 + 1, r1)]
            if faixa_m is not None:
                bloco = bloco & (np.abs(cols - cx_t) <= int(faixa_m * px_x))[None, :]
            if bloco.size == 0:
                return 0.0
            larguras = bloco.sum(axis=1)
            larguras = larguras[larguras > 0]
            return float(np.median(larguras)) / px_x if larguras.size else 0.0
        cabeca = larg_cab_px / px_x
        ombros = largura_linhas(int(y_ombro + 0.04 * px_y), int(y_ombro + 0.20 * px_y))
        largura = ombros
        cabeca_ok = (cfg["cabeca_min_m"] <= cabeca <= cfg["cabeca_max_m"]
                     and ombros >= cabeca * cfg["razao_ombro_cabeca"])
        humano = (cfg["altura_min_m"] <= altura <= cfg["altura_max_m"]
                  and cfg["largura_min_m"] <= largura <= cfg["largura_max_m"]
                  and cabeca_ok)

        z_topo = float(np.median(d[cabeca_mask])) if cabeca_mask.any() else z_tronco
        cy = int(y_ombro + 0.25 * px_y)

        # mãos levantadas: o que sobra acima da linha dos ombros, fora da cabeça
        maos = {}
        acima = np.zeros_like(comp_mask)
        acima[:max(0, y_pescoco)] = True   # acima do pescoço: tira a faixa dos ombros
        sem_cabeca = cv2.dilate(cabeca_mask.astype(np.uint8), self._kernel, iterations=2).astype(bool)
        area_px = z_tronco ** 2 / (FX * FY)
        lateral = int(cfg["mao_lateral_m"] * px_x)
        for nome, lado in (("img_esq", cols < cx_cab - lateral), ("img_dir", cols > cx_cab + lateral)):
            reg_lado = (comp_mask & acima & ~sem_cabeca & lado[None, :]).astype(np.uint8)
            n, rot, st, _ = cv2.connectedComponentsWithStats(reg_lado, connectivity=8)
            melhor = None
            for i in range(1, n):
                if st[i, cv2.CC_STAT_AREA] * area_px < cfg["mao_area_min_m2"]:
                    continue
                if melhor is None or st[i, cv2.CC_STAT_TOP] < st[melhor, cv2.CC_STAT_TOP]:
                    melhor = i
            if melhor is None:
                continue
            ponta = rot == melhor
            ponta[int(st[melhor, cv2.CC_STAT_TOP] + cfg["mao_altura_m"] * px_y):] = False
            vy, vx = np.nonzero(ponta)
            u, v = float(vx.mean()), float(vy.mean())
            # mão pequena e longe: a borda mistura fundo/cabeça; usa só pontos
            # perto do corpo e pega os mais próximos (a palma)
            zs = d[ponta]
            zs = zs[np.abs(zs - z_tronco) < 0.7]
            zm = float(np.percentile(zs, 30)) if zs.size else z_tronco
            maos[nome] = (para_3d(u + ox, v + oy, zm), (int(u) + ox, int(v) + oy))

        mao = mao_px = None
        if maos:
            mao, mao_px = min(maos.values(), key=lambda m: m[1][1])

        return dict(
            mascara=comp_mask, offset=(ox, oy),
            bbox=(int(x0) + ox, int(y_cab) + oy, int(x1 - x0 + 1), int(y1 - y_cab + 1)),
            centro=para_3d(cx_t + ox, cy + oy, z_tronco), topo=para_3d(cx_cab + ox, y_cab + oy, z_topo),
            topo_px=y_cab + oy, base_px=y1 + oy, altura_m=altura, largura_m=largura,
            cabeca_ok=cabeca_ok, humano=humano, mao=mao, mao_px=mao_px, maos=maos,
            ombro_px=y_ombro + oy, cabeca_m=cabeca, ombros_m=ombros)

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
        if self._reancorar is not None:
            fora = ~self._reancorar
            bg[fora & valido] = d[fora & valido]
            desc[fora] = ~valido[fora]    # sem leitura agora: aprende depois
            self._reancorar = None
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
            x, y, w, h = (int(v) for v in stats[i, :4])
            m0 = 4
            ya, yb = max(0, y - m0), min(d.shape[0], y + h + m0)
            xa, xb = max(0, x - m0), min(d.shape[1], x + w + m0)
            m = self._medir(d[ya:yb, xa:xb], (rot[ya:yb, xa:xb] == i) & fg_bool[ya:yb, xa:xb], xa, ya)
            if m is not None:
                candidatos.append(m)
                # corpo grande encostado no topo da imagem: cabeça fora do quadro
                if (m["topo_px"] <= 1 and m["altura_m"] >= 0.8
                        and cfg["largura_min_m"] <= m["largura_m"] <= cfg["largura_max_m"]):
                    self.cortado = True

        for c in candidatos:   # máscara de volta ao tamanho da imagem
            ox, oy = c["offset"]
            cheia = np.zeros(d.shape, bool)
            mh, mw = c["mascara"].shape
            cheia[oy:oy + mh, ox:ox + mw] = c["mascara"]
            c["mascara"] = cheia
        self.maior_candidato = (max(candidatos, key=lambda c: c["mascara"].sum())["mascara"]
                                if candidatos else None)
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
            "largura_m", "cabeca_ok", "mao", "mao_px", "maos", "ombro_px")})
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
        self.origem = c["centro"]
        self.falhas_humano = 0
        self.sequencia_humano = 0
        self.deslocamento = 0.0
        self.ultimo_centro = c["centro"]
        self.confirmada = False
        self.id_atual = self.proximo_id
        self.proximo_id += 1

    def _seguir(self, c):
        if self.rastro is None and self.ultimo_centro is None:
            self._novo_rastro(c)
        # deslocamento líquido desde que o rastro começou (o centro tremendo
        # quadro a quadro não deve contar como "se mexeu")
        ox, _, oz = self.origem
        self.deslocamento = max(self.deslocamento,
                                float(np.hypot(c["centro"][0] - ox, c["centro"][2] - oz)))
        self.ultimo_centro = c["centro"]
        if c["humano"]:
            self.sequencia_humano += 1
            self.falhas_humano = 0
        else:
            self.sequencia_humano = max(0, self.sequencia_humano - 1)
            self.falhas_humano += 1
        if (not self.confirmada and self.sequencia_humano >= self.cfg["quadros_confirmar"]
                and (self.deslocamento >= self.cfg["deslocamento_confirmar_m"] or c["maos"])):
            self.confirmada = True
        if not self.confirmada and self.falhas_humano >= self.cfg["falhas_perder"]:
            # candidato deixou de parecer gente antes de confirmar
            self._perder()
            return None
        return c

    def _perder(self):
        self.rastro = None
        self.ultimo_centro = None
        self.confirmada = False
        self.sequencia_humano = 0
        self.deslocamento = 0.0

    # ------------------------------------------------- pessoa deitada (cama)
    # Deitado e coberto, a silhueta não tem "cabeça mais estreita que os
    # ombros" na vertical e, parada, acaba no fundo aprendido. Por isso a
    # comparação é com uma referência do quarto VAZIO (guardada quando o
    # mmWave diz que não há ninguém) e a validação é só pelo tamanho: um
    # volume novo do tamanho de uma pessoa deitada, não de um gato.

    def guardar_referencia(self, pasta: str | None = None) -> bool:
        """Guarda o fundo atual como referência do quarto vazio (por ângulo)."""
        if not self.fundo_pronto():
            return False
        ref = np.where(self.desconhecido[self.angulo], 0, self.fundos[self.angulo]).astype(np.float32)
        self.referencias[self.angulo] = ref
        if pasta:
            import os
            os.makedirs(pasta, exist_ok=True)
            np.save(os.path.join(pasta, f"referencia_{self.angulo}.npy"), ref)
        return True

    def carregar_referencias(self, pasta: str) -> int:
        import glob
        import os
        for f in glob.glob(os.path.join(pasta, "referencia_*.npy")):
            try:
                ang = int(os.path.basename(f)[len("referencia_"):-4])
                self.referencias[ang] = np.load(f)
            except (ValueError, OSError):
                continue
        return len(self.referencias)

    def procurar_deitado(self) -> dict | None:
        """Maior volume novo (vs. a referência do quarto vazio) com tamanho de
        pessoa deitada no último quadro, ou None."""
        cfg = self.cfg
        ref = self.referencias.get(self.angulo)
        if ref is None or self._anterior is None:
            return None
        d, valido = self._anterior
        self.deitado_mascara = None
        novo = valido & (ref > 0) & (d < ref - cfg["deitado_altura_m"])
        novo = cv2.morphologyEx(novo.astype(np.uint8), cv2.MORPH_OPEN, self._kernel)
        n, rot, st, _ = cv2.connectedComponentsWithStats(novo, connectivity=8)
        melhor = None
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] < cfg["min_pixels"]:
                continue
            if st[i, cv2.CC_STAT_TOP] <= 1:
                continue   # encostado no topo da imagem: teto/borda, não gente
            ys, xs = np.nonzero(rot == i)
            zs = d[ys, xs]
            dif = float(np.median(ref[ys, xs] - zs))
            if dif < cfg["deitado_dif_media_m"]:
                continue   # só uma película de ruído sobre a referência
            area = float(((zs / FX) * (zs / FY)).sum())
            if area < cfg["deitado_area_min_m2"]:
                continue
            X = (xs - CX) * zs / FX
            Y = -(ys - CY) * zs / FY
            def faixa(v):
                a, b = np.percentile(v, [3, 97])
                return float(b - a)
            dx, dy, dz = faixa(X), faixa(Y), faixa(zs)
            comprimento = max(float(np.hypot(dx, dz)), dy)
            if dy < cfg["deitado_altura_visivel_m"]:
                continue   # faixa fina (borda de móvel, prateleira)
            if not (cfg["deitado_comprimento_min_m"] <= comprimento <= cfg["deitado_comprimento_max_m"]):
                continue
            if melhor is None or area > melhor["area_m2"]:
                self.deitado_mascara = rot == i
                melhor = {"area_m2": round(area, 2), "comprimento_m": round(comprimento, 2),
                          "z_m": round(float(np.median(zs)), 2), "dif_m": round(dif, 2),
                          "pixels": int(st[i, cv2.CC_STAT_AREA])}
        return melhor


def imagem_debug(profundidade_mm: np.ndarray, pessoa: Pessoa | None, texto: str = "",
                 deitado: np.ndarray | None = None) -> np.ndarray:
    d = profundidade_mm[::ESCALA, ::ESCALA].astype(np.float32)
    img = np.clip(255 - d / 4500 * 255, 0, 255).astype(np.uint8)
    img[d == 0] = 0
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if pessoa is not None:
        cor = (0, 200, 0) if pessoa.confirmada else (0, 200, 255)
        img[pessoa.mascara] = (img[pessoa.mascara] * 0.5 + np.array(cor) * 0.5).astype(np.uint8)
        x, y, w, h = pessoa.bbox
        cv2.rectangle(img, (x, y), (x + w, y + h), cor, 1)
        for _, px in pessoa.maos.values():
            cv2.circle(img, px, 6, (0, 0, 255), 2)
        cv2.line(img, (x, pessoa.ombro_px), (x + w, pessoa.ombro_px), (255, 128, 0), 1)
    if deitado is not None:
        img[deitado] = (img[deitado] * 0.5 + np.array((255, 0, 255)) * 0.5).astype(np.uint8)
    if texto:
        cv2.putText(img, texto, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return img
