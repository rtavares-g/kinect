#!/bin/bash
# Instala/reinstala o Kinect do quarto (libfreenect + serviço kinect-quarto).
# Uso: ./install.sh   (rodar de dentro da pasta clonada do repositorio)

set -e

REPO_URL="https://github.com/rtavares-g/kinect.git"
INSTALL_DIR="$HOME/projetos/kinect"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    if [ ! -d "$INSTALL_DIR" ]; then
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    cd "$INSTALL_DIR"
else
    cd "$SCRIPT_DIR"
fi

sudo apt update
sudo apt install -y libfreenect0.5t64 libfreenect-bin python3-numpy python3-opencv python3-requests

# o pacote libfreenect traz a regra udev (grupo plugdev); garante o usuário no grupo
sudo usermod -aG plugdev,video "$USER"
sudo udevadm control --reload-rules && sudo udevadm trigger

mkdir -p "$HOME/.config/kinect"
chmod 700 "$HOME/.config/kinect"
if [ ! -f "$HOME/.config/kinect/ha.json" ]; then
    echo
    echo "==> Home Assistant (token em Perfil > Seguranca > Tokens de acesso de longa duracao)"
    read -rp "URL do HA [http://homeassistant.local]: " HA_URL
    HA_URL="${HA_URL:-http://homeassistant.local}"
    read -rsp "Token: " HA_TOKEN
    echo
    printf '{"url": "%s", "token": "%s"}\n' "$HA_URL" "$HA_TOKEN" > "$HOME/.config/kinect/ha.json"
    chmod 600 "$HOME/.config/kinect/ha.json"
fi
if [ ! -f "$HOME/.config/kinect/config.json" ]; then
    cp config.example.json "$HOME/.config/kinect/config.json"
fi

python3 teste_ha.py || echo "==> confira as entidades em ~/.config/kinect/config.json"

sed -e "s|__USER__|$USER|g" -e "s|__HOME__|$HOME|g" kinect-quarto.service | sudo tee /etc/systemd/system/kinect-quarto.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now kinect-quarto
systemctl status kinect-quarto --no-pager
