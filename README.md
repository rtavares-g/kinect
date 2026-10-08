# Kinect do quarto — Raspberry Pi

Kinect v1 (Xbox 360, modelo 1414/1473) no Raspberry Pi. Ele:

1. **detecta presença**, pelo mmWave do [`presenca-quarto`](../presenca-quarto)
   (`~/projetos/presenca-quarto/estado.json`) ou por movimento visto pelo próprio Kinect;
2. **valida se é humano** pela silhueta em profundidade: altura e largura em
   metros, cabeça mais estreita que os ombros, e o corpo precisa se mexer
   (cadeira, casaco e outros objetos parados nunca são confirmados);
3. **segue a pessoa** inclinando o motor (só quando a cabeça sai do quadro e
   nunca durante um gesto). O Kinect v1 só inclina para cima e para baixo;
   na horizontal ele rastreia dentro do campo de visão (~57°);
4. **reconhece gestos** e manda comandos para o **Home Assistant**.

Só a câmera de profundidade é usada (sem RGB), então funciona no escuro.

## Gestos

Só contam **mãos levantadas acima do ombro, ao lado da cabeça**. Mão no
colo, celular na frente do peito ou do rosto etc. são ignorados. "Direita" e
"esquerda" são do ponto de vista de quem faz o gesto.

| Gesto | Fora de um modo | Dentro de um modo |
|---|---|---|
| Levantar a **mão direita** e deixar parada (~1,2 s) | entra no modo **ar** | troca para o ar (ou sai, se já estiver nele) |
| Levantar a **mão esquerda** e deixar parada | entra no modo **ventilador** | troca / sai |
| Levantar **as duas mãos** e deixar paradas | entra no modo **pendente** | troca / sai |
| **Empurrar** (com a mão levantada e parada, avançar a palma para o Kinect) | liga/desliga o **pendente** | liga/desliga o aparelho do modo |
| Deslizar a mão levantada para **cima / baixo** | — | ar: temperatura ±1 °C · ventilador: velocidade ±25% · pendente: brilho ±20% |
| Deslizar para **direita / esquerda** | — | ar: próximo/anterior modo (frio, seco, ventilar, auto) |

O "segurar" só vale logo depois de levantar a mão. Quem deixa a mão parada
no ar entre um comando e outro não sai do modo sem querer. Para sair (ou
trocar de modo), **abaixa e levanta a mão de novo**. Sem nenhum comando por
**10 s**, o modo fecha sozinho.

## Entidades (Home Assistant)

Ficam em `~/.config/kinect/config.json` (copiado de `config.example.json`
pelo `install.sh`):

| Função | Entidade padrão |
|---|---|
| Ar | `climate.ar_quarto` |
| Ventilador | `fan.quarto_gui` |
| Pendente (modo e empurrar) | `light.modulo_dimmer_light_1` |

O serviço publica `sensor.kinect_quarto` no HA, com o estado (`ocioso`,
`observando`, `ar`, `ventilador`, `pendente`) e o último gesto. Dá para usar
em automações.

O token do HA fica em `~/.config/kinect/ha.json` (`{"url": ..., "token": ...}`,
fora do git).

## Instalação

```bash
git clone https://github.com/rtavares-g/kinect.git ~/projetos/kinect
cd ~/projetos/kinect && ./install.sh
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
(verde = confirmada, laranja = candidata), a linha dos ombros (azul) e as
mãos levantadas (círculos vermelhos).

```bash
journalctl -u kinect-quarto -f
```

## Ajustes comuns (`~/.config/kinect/config.json`)

- Direita/esquerda trocados: `"gestos": {"inverter_x": true}`.
- Não quer que o motor se mexa: `"seguir": {"ativo": false}`.
- Kinect no alto (ex.: em cima do armário): incline para baixo ao iniciar e
  libere os ângulos negativos, por exemplo
  `"seguir": {"angulo_inicial": -24, "angulo_min": -27, "angulo_max": 0}`.
  O ângulo é absoluto (o motor usa o acelerômetro): 0° é horizontal.
- Mudar o tempo para o modo fechar: `"controle": {"timeout_modo_s": 15}`.
- Os outros limites estão em `config.py` (`PADRAO`). Qualquer chave pode ser
  sobrescrita no `config.json`.

Depois de mudar: `sudo systemctl restart kinect-quarto`.
