#!/usr/bin/env python3
"""Teste rápido do Kinect: profundidade, LED e motor.

Uso: python3 teste_hardware.py [--sem-motor]
Salva uma imagem da profundidade em /dev/shm/kinect/teste.jpg.
"""

import os
import sys
import time

import cv2
import numpy as np

import kinect_dev as kd
from visao import imagem_debug


def main():
    k = kd.Kinect()
    print("lendo profundidade...")
    t = time.monotonic()
    quadros = []
    for _ in range(30):
        quadros.append(k.profundidade())
    fps = 30 / (time.monotonic() - t)
    q = quadros[-1]
    validos = q[q > 0]
    print(f"  {fps:.1f} quadros/s, {validos.size / q.size:.0%} pixels com leitura")
    if validos.size:
        print(f"  distância: mín {validos.min()} mm, mediana {int(np.median(validos))} mm, máx {validos.max()} mm")
    os.makedirs("/dev/shm/kinect", exist_ok=True)
    cv2.imwrite("/dev/shm/kinect/teste.jpg", imagem_debug(q, None))
    print("  imagem em /dev/shm/kinect/teste.jpg")

    print("LED: verde, vermelho, amarelo")
    for modo in (kd.LED_VERDE, kd.LED_VERMELHO, kd.LED_AMARELO):
        k.led(modo)
        time.sleep(0.8)

    if "--sem-motor" not in sys.argv:
        print("motor: +10°, -10°, 0°")
        for a in (10, -10, 0):
            print("  ", a, "ok" if k.inclinar(a) else "FALHOU")
            time.sleep(2)
    k.parar()
    print("tudo certo")


if __name__ == "__main__":
    main()
