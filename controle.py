"""Máquina de estados: gestos -> comandos no Home Assistant.

Estados:
- ocioso: ninguém confirmado na frente do Kinect (LED apagado).
- observando: pessoa confirmada (LED verde). Aceita os gestos de entrada
  dos modos e os atalhos (ex.: empurrar = liga/desliga a luz do quarto).
- modo <nome>: gerenciando um aparelho (LED verde piscando). Sai pelo
  gesto de saída, pelo gesto de entrada de outro modo (troca direto) ou
  por `timeout_modo_s` sem receber comando.

Cada comando executado pisca o LED em vermelho por um instante.
"""

import logging
import time

import kinect_dev as kd

log = logging.getLogger("controle")


def _clamp(v, a, b):
    return max(a, min(b, v))


class Acoes:
    """Traduz (tipo do aparelho, gesto) em chamadas de serviço do HA."""

    @staticmethod
    def climate(ha, ent: str, gesto: str, cfg: dict):
        def rodar(h):
            st = h.estado(ent)
            if st is None:
                return
            a = st["attributes"]
            ligado = st["state"] not in ("off", "unavailable", "unknown")
            modos = cfg.get("modos_hvac", ["cool", "dry", "fan_only", "auto"])
            if gesto == "empurrar":
                if ligado:
                    h.servico_agora("climate", "set_hvac_mode", {"entity_id": ent, "hvac_mode": "off"})
                else:
                    h.servico_agora("climate", "set_hvac_mode",
                                    {"entity_id": ent, "hvac_mode": cfg.get("modo_ao_ligar", "cool")})
            elif gesto in ("deslizar_cima", "deslizar_baixo"):
                atual = a.get("temperature") or cfg.get("temp_padrao", 23)
                passo = cfg.get("passo_temp", 1)
                nova = atual + (passo if gesto == "deslizar_cima" else -passo)
                nova = _clamp(nova, cfg.get("temp_min", 16), cfg.get("temp_max", 30))
                h.servico_agora("climate", "set_temperature", {"entity_id": ent, "temperature": nova})
            elif gesto in ("deslizar_direita", "deslizar_esquerda"):
                atual = st["state"] if st["state"] in modos else modos[-1]
                i = modos.index(atual)
                i = (i + (1 if gesto == "deslizar_direita" else -1)) % len(modos)
                h.servico_agora("climate", "set_hvac_mode", {"entity_id": ent, "hvac_mode": modos[i]})
        ha.executar(rodar)

    @staticmethod
    def fan(ha, ent: str, gesto: str, cfg: dict):
        def rodar(h):
            if gesto == "empurrar":
                h.servico_agora("fan", "toggle", {"entity_id": ent})
                return
            if gesto not in ("deslizar_cima", "deslizar_baixo"):
                return
            st = h.estado(ent)
            if st is None:
                return
            ligado = st["state"] == "on"
            pct = (st["attributes"].get("percentage") or 0) if ligado else 0
            passo = cfg.get("passo", 25)
            novo = pct + passo if gesto == "deslizar_cima" else pct - passo
            if novo <= 0:
                if ligado:
                    h.servico_agora("fan", "turn_off", {"entity_id": ent})
            else:
                h.servico_agora("fan", "set_percentage",
                                {"entity_id": ent, "percentage": _clamp(novo, passo, 100)})
        ha.executar(rodar)

    @staticmethod
    def light(ha, ent: str, gesto: str, cfg: dict):
        if gesto == "empurrar":
            ha.servico("light", "toggle", {"entity_id": ent})
        elif gesto == "deslizar_cima":
            ha.servico("light", "turn_on", {"entity_id": ent, "brightness_step_pct": cfg.get("passo", 20)})
        elif gesto == "deslizar_baixo":
            def rodar(h):
                st = h.estado(ent)
                if st and st["state"] == "on":
                    h.servico_agora("light", "turn_on",
                                    {"entity_id": ent, "brightness_step_pct": -cfg.get("passo", 20)})
            ha.executar(rodar)

    @staticmethod
    def alternar(ha, ent: str, gesto: str, cfg: dict):
        dominio = ent.split(".")[0]
        ha.servico(dominio if dominio in ("light", "switch", "fan") else "homeassistant",
                   "toggle", {"entity_id": ent})


GESTOS_DE_COMANDO = {"empurrar", "deslizar_cima", "deslizar_baixo",
                     "deslizar_direita", "deslizar_esquerda"}


class Controle:
    def __init__(self, cfg: dict, ha, led=None, relogio=time.monotonic):
        self.cfg = cfg
        self.ha = ha
        self.led = led or (lambda modo: None)
        self.relogio = relogio
        self.estado = "ocioso"
        self.modo = None
        self.ultimo_comando = 0.0
        self.flash_ate = 0.0
        self.ultimo_gesto = None
        self.entradas = {m["entrada"]: nome for nome, m in cfg["modos"].items()}
        self._led_atual = None

    # ------------------------------------------------------------------
    def pessoa(self, confirmada: bool):
        if confirmada and self.estado == "ocioso":
            self.estado = "observando"
            log.info("pessoa confirmada")
        elif not confirmada and self.estado != "ocioso":
            if self.modo:
                log.info("saindo do modo %s (pessoa sumiu)", self.modo)
            self.estado, self.modo = "ocioso", None
            log.info("ninguém na frente do Kinect")

    def gesto(self, nome: str):
        agora = self.relogio()
        self.ultimo_gesto = nome
        if self.estado == "ocioso":
            return
        log.info("gesto %s (estado %s)", nome, self.modo or self.estado)

        if nome in self.entradas:
            novo = self.entradas[nome]
            if self.modo == novo:
                self._sair("mesmo gesto de entrada")
            else:
                self.modo = novo
                self.estado = "modo"
                self.ultimo_comando = agora
                log.info("entrando no modo %s", novo)
                self._piscar(agora)
            return

        if self.modo:
            if nome == self.cfg["gesto_sair"]:
                self._sair("gesto de saída")
                return
            if nome in GESTOS_DE_COMANDO:
                m = self.cfg["modos"][self.modo]
                getattr(Acoes, m["tipo"])(self.ha, m["entidade"], nome, m)
                self.ultimo_comando = agora
                self._piscar(agora)
            return

        atalho = self.cfg["atalhos"].get(nome)
        if atalho:
            getattr(Acoes, atalho["acao"])(self.ha, atalho["entidade"], nome, atalho)
            self._piscar(agora)

    def tick(self):
        agora = self.relogio()
        if self.modo and agora - self.ultimo_comando > self.cfg["timeout_modo_s"]:
            self._sair("tempo esgotado")
        if agora < self.flash_ate:
            led = kd.LED_VERMELHO
        elif self.modo:
            led = kd.LED_VERDE_PISCANDO
        elif self.estado == "observando":
            led = kd.LED_VERDE
        else:
            led = kd.LED_DESLIGADO
        if led != self._led_atual:
            self.led(led)
            self._led_atual = led

    # ------------------------------------------------------------------
    def _sair(self, motivo):
        log.info("saindo do modo %s (%s)", self.modo, motivo)
        self.modo = None
        self.estado = "observando"

    def _piscar(self, agora):
        self.flash_ate = agora + 0.4

    def resumo(self) -> str:
        return self.modo or self.estado
