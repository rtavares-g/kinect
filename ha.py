"""Cliente mínimo da API REST do Home Assistant.

As chamadas vão para uma fila e são feitas numa thread separada, para o
laço da visão nunca travar esperando a rede.
"""

import json
import logging
import queue
import threading

import requests

log = logging.getLogger("ha")


class HomeAssistant:
    def __init__(self, url: str, token: str, timeout: float = 5.0):
        self.url = url.rstrip("/")
        self.sessao = requests.Session()
        self.sessao.headers["Authorization"] = "Bearer " + token
        self.timeout = timeout
        self.fila: queue.Queue = queue.Queue(maxsize=50)
        threading.Thread(target=self._trabalhador, daemon=True, name="ha").start()

    @classmethod
    def de_arquivo(cls, caminho: str):
        with open(caminho) as f:
            c = json.load(f)
        return cls(c["url"], c["token"])

    # síncrono (usado pelos testes e pelo laço de controle para ler estado)
    def estado(self, entidade: str) -> dict | None:
        try:
            r = self.sessao.get(f"{self.url}/api/states/{entidade}", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.warning("falha lendo %s: %s", entidade, e)
            return None

    def servico_agora(self, dominio: str, servico: str, dados: dict) -> bool:
        log.info("HA %s.%s %s", dominio, servico, dados)
        try:
            r = self.sessao.post(f"{self.url}/api/services/{dominio}/{servico}",
                                 json=dados, timeout=self.timeout)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            log.warning("falha em %s.%s %s: %s", dominio, servico, dados, e)
            return False

    # assíncrono
    def servico(self, dominio: str, servico: str, dados: dict) -> None:
        self._enfileirar(("servico", dominio, servico, dados))

    def executar(self, funcao) -> None:
        """Roda funcao(self) na thread do HA (para ações que leem estado antes)."""
        self._enfileirar(("funcao", funcao))

    def publicar_estado(self, entidade: str, estado: str, atributos: dict) -> None:
        self._enfileirar(("estado", entidade, estado, atributos))

    def _enfileirar(self, item):
        try:
            self.fila.put_nowait(item)
        except queue.Full:
            log.warning("fila do HA cheia, descartando %s", item[:2])

    def _trabalhador(self):
        while True:
            item = self.fila.get()
            try:
                if item[0] == "servico":
                    _, dom, srv, dados = item
                    self.servico_agora(dom, srv, dados)
                elif item[0] == "funcao":
                    item[1](self)
                else:
                    _, ent, est, attrs = item
                    self.sessao.post(f"{self.url}/api/states/{ent}",
                                     json={"state": est, "attributes": attrs},
                                     timeout=self.timeout)
            except Exception as e:  # nunca deixa a thread morrer
                log.warning("erro no trabalhador do HA: %s", e)
