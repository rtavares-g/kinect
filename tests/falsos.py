"""Substitutos do Home Assistant e do Kinect para testes e --sem-ha."""

import logging

log = logging.getLogger("ha-falso")


class HAFalso:
    """Registra as chamadas em vez de mandar para o HA. `estados` simula
    o que o HA responderia em /api/states."""

    def __init__(self, estados=None):
        self.chamadas = []
        self.estados = estados or {}

    def estado(self, ent):
        return self.estados.get(ent)

    def servico_agora(self, dom, srv, dados):
        log.info("[sem HA] %s.%s %s", dom, srv, dados)
        self.chamadas.append((dom, srv, dados))
        return True

    def servico(self, dom, srv, dados):
        self.servico_agora(dom, srv, dados)

    def executar(self, funcao):
        funcao(self)

    def publicar_estado(self, ent, estado, attrs):
        pass
