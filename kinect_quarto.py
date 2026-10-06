#!/usr/bin/env python3
"""Kinect do quarto: valida presença humana, segue a pessoa (inclinação) e
transforma gestos em comandos no Home Assistant (ar, ventilador, pendente e
luz do quarto).

Gatilho: o mmWave do presenca-quarto (estado.json) ou o próprio Kinect
vendo movimento. Sem presença por `ocioso_apos_s`, o laço cai para poucos
quadros por segundo.
"""

import argparse
import json
import logging
import os
import signal
import socket
import sys
import time

import cv2

import config
import kinect_dev as kd
from controle import Controle
from gestos import Gestos
from ha import HomeAssistant
from visao import Visao, imagem_debug

log = logging.getLogger("kinect")

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_ESTADO = os.path.join(PASTA, "estado.json")


def avisar_systemd(msg: str) -> None:
    """sd_notify sem biblioteca. Fora do systemd não faz nada."""
    endereco = os.environ.get("NOTIFY_SOCKET")
    if not endereco:
        return
    if endereco.startswith("@"):
        endereco = "\0" + endereco[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.setblocking(False)
            s.sendto(msg.encode(), endereco)
    except OSError:
        pass


class LeitorMmwave:
    def __init__(self, caminho: str):
        self.caminho = os.path.expanduser(caminho)
        self.lido_em = 0.0
        self.valor = False

    def presenca(self, agora: float) -> bool:
        if agora - self.lido_em >= 1.0:
            self.lido_em = agora
            try:
                with open(self.caminho) as f:
                    e = json.load(f)
                # estado velho (serviço parado) não conta
                self.valor = bool(e.get("presenca")) and time.time() - e.get("salvo_em", 0) < 120
            except (OSError, ValueError):
                self.valor = False
        return self.valor


def salvar_estado(dados: dict) -> None:
    tmp = ARQUIVO_ESTADO + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dados, f)
    os.replace(tmp, ARQUIVO_ESTADO)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sem-ha", action="store_true", help="não manda comandos (só registra)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    cfg = config.carregar()
    if args.sem_ha:
        from tests.falsos import HAFalso
        ha = HAFalso()
    else:
        ha = HomeAssistant.de_arquivo(config.ARQUIVO_HA)

    kinect = kd.Kinect()
    visao = Visao(cfg["visao"])
    gestos = Gestos(cfg["gestos"])
    controle = Controle(cfg["controle"], ha, led=kinect.led)
    mmwave = LeitorMmwave(cfg["presenca"]["estado_mmwave"])
    cp, cs, ch = cfg["presenca"], cfg["seguir"], cfg["ha"]

    rodando = True
    def parar(*_):
        nonlocal rodando
        rodando = False
    signal.signal(signal.SIGTERM, parar)
    signal.signal(signal.SIGINT, parar)

    debug = cfg.get("debug_imagem")
    if debug:
        os.makedirs(os.path.dirname(debug), exist_ok=True)

    falhas = 0
    ultima_presenca = time.monotonic()
    ultimo_tilt = 0.0
    ignorar_ate = 0.0
    ultimo_publicado = (None, 0.0)
    ultimo_salvo = 0.0
    quadros, t_fps, fps = 0, time.monotonic(), 0.0

    kinect.inclinar(0)
    visao.mudar_angulo(0)
    avisar_systemd("READY=1")
    log.info("rodando")

    while rodando:
        t0 = time.monotonic()
        avisar_systemd("WATCHDOG=1")
        try:
            prof = kinect.profundidade()
            falhas = 0
        except kd.ErroKinect as e:
            falhas += 1
            log.warning("%s (%d)", e, falhas)
            if falhas >= 6:
                log.error("Kinect não responde; saindo para o systemd reiniciar")
                break
            time.sleep(5)
            continue

        if t0 < ignorar_ate:          # motor se mexendo: quadros tremidos
            continue

        pessoa = visao.processar(prof)
        confirmada = pessoa is not None and pessoa.confirmada
        pres_mm = mmwave.presenca(t0)
        pres_kin = visao.movimento >= cp["movimento_kinect"]
        if pres_mm or pres_kin or confirmada:
            ultima_presenca = t0
        ativo = t0 - ultima_presenca < cp["ocioso_apos_s"]

        controle.pessoa(confirmada)
        for g in gestos.atualizar(t0, pessoa if confirmada else None):
            controle.gesto(g)
        controle.tick()

        # seguir a pessoa na vertical (o Kinect v1 só inclina)
        if (cs["ativo"] and controle.modo is None and t0 - ultimo_tilt >= cs["intervalo_s"]
                and (confirmada or visao.cortado)):
            h = prof.shape[0] // 2
            frac = pessoa.topo_px / h if confirmada else 0.0
            novo = kinect.angulo
            if frac < cs["topo_alto"]:
                novo += cs["passo_graus"]
            elif frac > cs["topo_baixo"]:
                novo -= cs["passo_graus"]
            novo = max(cs["angulo_min"], min(cs["angulo_max"], novo))
            if novo != kinect.angulo and kinect.inclinar(novo):
                log.info("inclinando para %d° (cabeça em %.0f%% da imagem)", novo, frac * 100)
                visao.mudar_angulo(novo)
                gestos.limpar()
                ultimo_tilt = t0
                ignorar_ate = t0 + 1.2

        # estado: arquivo local + sensor no HA
        quadros += 1
        if t0 - t_fps >= 5:
            fps, quadros, t_fps = quadros / (t0 - t_fps), 0, t0
        resumo = controle.resumo()
        if t0 - ultimo_salvo >= 1:
            ultimo_salvo = t0
            dados = {
                "estado": resumo, "pessoa": confirmada,
                "candidato": pessoa is not None,
                "mmwave": pres_mm, "movimento": round(visao.movimento, 3),
                "ativo": ativo, "angulo": kinect.angulo, "fps": round(fps, 1),
                "ultimo_gesto": controle.ultimo_gesto,
                "fundo_pronto": visao.fundo_pronto(),
                "salvo_em": time.time(),
            }
            if pessoa is not None:
                dados["pessoa_m"] = {"x": round(pessoa.centro[0], 2), "z": round(pessoa.centro[2], 2),
                                     "altura": round(pessoa.altura_m, 2),
                                     "mao": pessoa.mao is not None}
            salvar_estado(dados)
            if debug:
                cv2.imwrite(debug, imagem_debug(prof, pessoa, f"{resumo} {fps:.1f}fps {kinect.angulo}deg"))
        if resumo != ultimo_publicado[0] or t0 - ultimo_publicado[1] >= ch["publicar_a_cada_s"]:
            ultimo_publicado = (resumo, t0)
            ha.publicar_estado(ch["entidade_estado"], resumo, {
                "friendly_name": "Kinect quarto", "icon": "mdi:human-greeting",
                "pessoa": confirmada, "angulo": kinect.angulo,
                "ultimo_gesto": controle.ultimo_gesto})

        alvo = cp["fps_ativo"] if ativo else cp["fps_ocioso"]
        espera = 1.0 / alvo - (time.monotonic() - t0)
        if espera > 0:
            time.sleep(espera)

    log.info("encerrando")
    try:
        kinect.parar()
    except Exception:
        pass
    sys.exit(0 if not rodando else 1)


if __name__ == "__main__":
    main()
