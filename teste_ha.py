#!/usr/bin/env python3
"""Confere se o token do HA funciona e se as entidades configuradas existem."""

import sys

import config
from ha import HomeAssistant


def main():
    cfg = config.carregar()
    ha = HomeAssistant.de_arquivo(config.ARQUIVO_HA)
    ents = [m["entidade"] for m in cfg["controle"]["modos"].values()]
    ents += [a["entidade"] for a in cfg["controle"]["atalhos"].values()]
    ok = True
    for e in ents:
        s = ha.estado(e)
        print(f"  {e}: {s['state'] if s else 'NÃO ENCONTRADA'}")
        ok &= s is not None
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
