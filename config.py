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
        "alcance_max_m": 6.0,
        "limiar_fundo_m": 0.15,         # quanto mais perto que o fundo para ser "algo novo"
        "limiar_movimento_m": 0.08,
        "quadros_fundo_inicial": 15,
        "alfa_fundo": 0.02,
        "alfa_objeto": 0.004,           # ~10 s a 15 fps para absorver objeto parado
        "min_pixels": 250,
        "altura_min_m": 0.45,           # sentado na cama, pernas cobertas
        "altura_max_m": 2.3,
        "largura_min_m": 0.25,
        "largura_max_m": 1.4,
        "cabeca_min_m": 0.09,
        "cabeca_max_m": 0.35,
        "razao_ombro_cabeca": 1.4,
        "quadros_confirmar": 8,
        "falhas_perder": 6,             # quadros seguidos sem parecer gente até largar o candidato
        "deslocamento_confirmar_m": 0.15,
        "salto_max_m": 0.6,
        "mao_frente_m": 0.25,           # mão esticada: 25 cm à frente do peito
        "mao_lateral_m": 0.13,          # mão levantada: fora da faixa da cabeça
        "mao_altura_m": 0.12,           # ponta do braço levantado considerada mão
        "mao_area_min_m2": 0.004,
        "mao_profundidade_m": 0.08,
    },
    "gestos": {
        "inverter_x": True,             # a imagem do Kinect vem espelhada (conferido no teste 2)
        "historico_s": 2.0,
        "intervalo_max_s": 0.4,
        "janela_tronco_s": 0.6,
        "tronco_parado_m": 0.15,
        "pausa_entre_gestos_s": 0.8,
        "deslizar_janela_s": 0.6,
        "deslizar_dist_m": 0.25,        # horizontal
        "deslizar_dist_v_m": 0.18,      # vertical (a mão não pode descer abaixo do ombro)
        "deslizar_preparo_s": 0.6,
        "empurrar_janela_s": 0.4,
        "empurrar_dist_m": 0.15,
        "empurrar_desvio_m": 0.10,
        "empurrar_preparo_s": 0.6,
        "segurar_s": 1.2,
        "segurar_tolerancia_m": 0.06,
        "segurar_tolerancia_z_m": 0.20,  # profundidade da mão oscila mais que x/y
        "segurar_fresco_s": 1.5,        # segurar só vale até 1,2+1,5 s depois de levantar
    },
    "controle": {
        "timeout_modo_s": 10,
        "gesto_sair": "",               # sair = repetir o gesto de entrada ou esperar
        "modos": {
            "ar": {
                "entrada": "segurar_direita",
                "tipo": "climate",
                "entidade": "climate.ar_quarto",
                "modo_ao_ligar": "cool",
                "modos_hvac": ["cool", "dry", "fan_only", "auto"],
                "passo_temp": 1, "temp_min": 16, "temp_max": 30,
            },
            "ventilador": {
                "entrada": "segurar_esquerda",
                "tipo": "fan",
                "entidade": "fan.quarto_gui",
                "passo": 25,
            },
            "pendente": {
                "entrada": "segurar_ambas",
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
