# Kinect do quarto — Raspberry Pi

Kinect v1 (Xbox 360, modelo 1414/1473) no Raspberry Pi. Ele:

1. **detecta presença**, pelo mmWave do [`presenca-quarto`](../presenca-quarto)
   (`estado.json`) ou por movimento visto pelo próprio Kinect;
2. **valida se é humano** pela silhueta em profundidade: altura e largura em
   metros, cabeça mais estreita que os ombros, e o corpo precisa se mexer
   (cadeira, casaco e outros objetos parados nunca são confirmados);
3. **segue a pessoa** inclinando o motor. O Kinect v1 só inclina para cima e
   para baixo; na horizontal ele rastreia dentro do campo de visão (~57°);
4. **reconhece gestos** e manda comandos para o **Home Assistant**.

Só a câmera de profundidade é usada (sem RGB), então funciona no escuro.

## Gestos

Todos os gestos são feitos com o **braço esticado para a frente**, na
direção do Kinect. "Direita" e "esquerda" são do ponto de vista de quem faz
o gesto.

| Gesto | Fora de um modo | Dentro de um modo |
|---|---|---|
| Mão parada **acima da cabeça** (1,2 s) | entra no modo **ar** | troca para o modo ar (ou sai, se já estiver nele) |
| Mão parada **à direita** do corpo (1,2 s) | entra no modo **ventilador** | troca / sai |
| Mão parada **à esquerda** do corpo (1,2 s) | entra no modo **pendente** | troca / sai |
| Mão parada **na frente do peito** (1,2 s) | — | **sai** do modo |
| **Empurrar** (mão parada avança rápido) | liga/desliga a **luz do quarto** | liga/desliga o aparelho do modo |
| Deslizar para **cima / baixo** | — | ar: temperatura ±1 °C · ventilador: velocidade ±25% · pendente: brilho ±20% |
| Deslizar para **direita / esquerda** | — | ar: próximo/anterior modo (frio, seco, ventilar, auto) |

Sem nenhum comando por **10 s**, o modo fecha sozinho.

LED do Kinect: apagado = ninguém · verde = pessoa confirmada · verde
piscando = dentro de um modo · vermelho rápido = gesto reconhecido/comando
enviado.

## Entidades (Home Assistant)

Ficam em `~/.config/kinect/config.json` (copiado de `config.example.json`
pelo `install.sh`):

| Função | Entidade padrão |
|---|---|
| Ar | `climate.ar_quarto` |
| Ventilador | `fan.quarto_gui` |
| Pendente | `light.modulo_dimmer_light_2` |
| Luz do quarto | `light.modulo_dimmer_light_1` |

O serviço publica `sensor.kinect_quarto` no HA, com o estado (`ocioso`,
`observando`, `ar`, `ventilador`, `pendente`) e o último gesto. Dá para usar
em automações.

O token do HA fica em `~/.config/kinect/ha.json` (`{"url": ..., "token": ...}`,
fora do git).

## Instalação

```bash
git clone https://github.com/rtavares-g/kinect.git ~/kinect
cd ~/kinect && ./install.sh
```

O Kinect precisa da **fonte de 12 V** dele. Só pela USB aparecem o motor e o
áudio, mas a câmera (`045e:02ae`) não. Confira com `lsusb | grep 045e`:
devem aparecer três dispositivos (Motor, Audio e **Camera**).

## Testes

```bash
python3 -m unittest discover -s tests -t .   # simulador, sem precisar do Kinect
python3 teste_hardware.py                     # profundidade, LED e motor
python3 teste_ha.py                           # token e entidades do HA
python3 kinect_quarto.py --sem-ha -v          # roda tudo, só registrando os comandos
```

Com o serviço rodando, `estado.json` mostra o que ele está vendo, e
`/dev/shm/kinect/debug.jpg` traz a imagem de profundidade com a pessoa
(verde = confirmada, laranja = candidata) e a mão (círculo vermelho).

```bash
journalctl -u kinect-quarto -f
```

## Ajustes comuns (`~/.config/kinect/config.json`)

- Direita/esquerda trocados: `"gestos": {"inverter_x": true}`.
- Não quer que o motor se mexa: `"seguir": {"ativo": false}`.
- Mudar o tempo para o modo fechar: `"controle": {"timeout_modo_s": 15}`.
- Os outros limites estão em `config.py` (`PADRAO`). Qualquer chave pode ser
  sobrescrita no `config.json`.

Depois de mudar: `sudo systemctl restart kinect-quarto`.
