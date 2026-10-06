"""Configuração: valores padrão + ~/.config/kinect/config.json por cima."""

import copy
import json
import os

PASTA = os.path.expanduser("~/.config/kinect")
ARQUIVO = os.path.join(PASTA, "config.json")
ARQUIVO_HA = os.path.join(PASTA, "ha.json")

PADRAO = {
    "visao": {
        "alcance_min_m": 0.5,
        "alcance_max_m": 4.5,
        "limiar_fundo_m": 0.15,         # quanto mais perto que o fundo para ser "algo novo"
        "limiar_movimento_m": 0.08,
        "quadros_fundo_inicial": 15,
        "alfa_fundo": 0.02,
        "alfa_objeto": 0.004,           # ~10 s a 15 fps para absorver objeto parado
        "min_pixels": 250,
        "altura_min_m": 0.6,            # sentado/meio corpo visível
        "altura_max_m": 2.3,
        "largura_min_m": 0.25,
        "largura_max_m": 1.4,
        "cabeca_min_m": 0.09,
        "cabeca_max_m": 0.35,
        "razao_ombro_cabeca": 1.4,
        "quadros_confirmar": 8,
        "deslocamento_confirmar_m": 0.15,
        "salto_max_m": 0.6,
        "mao_frente_m": 0.22,           # mão pelo menos 22 cm à frente do tronco
        "mao_area_min_m2": 0.004,
        "mao_profundidade_m": 0.08,
    },
    "gestos": {
        "inverter_x": False,            # true se direita/esquerda saírem trocados
        "zona_acima_m": 0.05,
        "zona_lado_m": 0.30,
        "historico_s": 2.0,
        "intervalo_max_s": 0.4,
        "janela_tronco_s": 0.6,
        "tronco_parado_m": 0.15,
        "pausa_entre_gestos_s": 0.8,
        "deslizar_janela_s": 0.6,
        "deslizar_dist_m": 0.25,
        "empurrar_janela_s": 0.4,
        "empurrar_dist_m": 0.12,
        "empurrar_desvio_m": 0.10,
        "empurrar_preparo_s": 0.4,
        "segurar_s": 1.2,
        "segurar_tolerancia_m": 0.06,
    },
    "controle": {
        "timeout_modo_s": 10,
        "gesto_sair": "segurar_centro",
        "modos": {
            "ar": {
                "entrada": "segurar_acima",
                "tipo": "climate",
                "entidade": "climate.ar_quarto",
                "modo_ao_ligar": "cool",
                "modos_hvac": ["cool", "dry", "fan_only", "auto"],
                "passo_temp": 1, "temp_min": 16, "temp_max": 30,
            },
            "ventilador": {
                "entrada": "segurar_direita",
                "tipo": "fan",
                "entidade": "fan.quarto_gui",
                "passo": 25,
            },
            "pendente": {
                "entrada": "segurar_esquerda",
                "tipo": "light",
                "entidade": "light.modulo_dimmer_light_2",
                "passo": 20,
            },
        },
        "atalhos": {
            "empurrar": {"acao": "alternar", "entidade": "light.modulo_dimmer_light_1"},
        },
    },
    "seguir": {
        "ativo": True,
        "angulo_min": -15,
        "angulo_max": 20,
        "passo_graus": 4,
        "intervalo_s": 3.0,
        "topo_alto": 0.06,              # cabeça acima de 6% da imagem -> sobe
        "topo_baixo": 0.40,             # cabeça abaixo de 40% -> desce
    },
    "presenca": {
        "estado_mmwave": "~/presenca-quarto/estado.json",
        "movimento_kinect": 0.02,        # fração de pixels mudando = presença
        "ocioso_apos_s": 60,             # sem presença por isso -> modo econômico
        "fps_ativo": 12,
        "fps_ocioso": 2,
    },
    "ha": {
        "entidade_estado": "sensor.kinect_quarto",
        "publicar_a_cada_s": 30,
    },
    "debug_imagem": "/dev/shm/kinect/debug.jpg",
}


def _mesclar(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and k != "modos" and k != "atalhos":
            _mesclar(base[k], v)
        else:
            base[k] = v
    return base


def carregar(caminho: str = ARQUIVO) -> dict:
    cfg = copy.deepcopy(PADRAO)
    if os.path.exists(caminho):
        with open(caminho) as f:
            _mesclar(cfg, json.load(f))
    return cfg
