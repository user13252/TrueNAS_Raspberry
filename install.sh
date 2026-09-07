#!/usr/bin/env bash
# =============================================================================
#  install.sh - Instalador do TrueNAS Scale RPi para Debian 13 (Trixie)
#
#  Uso:
#    sudo ./install.sh                    # instala SO deps + Python + serviço
#    sudo ./install.sh --with-cython      # compila extensões Cython
#    sudo ./install.sh --no-zfs           # pula instalação do OpenZFS
#    sudo ./install.sh --no-service       # não cria/ativa o systemd service
#    sudo ./install.sh --force            # ignora a checagem da versão Debian
#
#  O script deve ser executado a partir da pasta raiz do projeto (onde ele
#  está, junto com truenas/, run.py, config.json etc).
# =============================================================================

set -euo pipefail

# ------------------------------------------------------------------ helpers
red()   { printf "\033[1;31m%s\033[0m\n" "$*"; }
green() { printf "\033[1;32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[1;33m%s\033[0m\n" "$*"; }
info()  { printf "\033[1;34m%s\033[0m\n" "$*"; }

die()   { red "ERRO: $*"; exit 1; }

# ------------------------------------------------------------ parse de args
WITH_CYTHON=0
WITH_ZFS=1
WITH_SERVICE=1
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --with-cython) WITH_CYTHON=1 ;;
        --no-zfs)      WITH_ZFS=0 ;;
        --no-service)  WITH_SERVICE=0 ;;
        --force)       FORCE=1 ;;
        *) die "argumento desconhecido: $arg" ;;
    esac
done

# ------------------------------------------------------------------ pré-checks
if [[ "$(id -u)" -ne 0 ]]; then
    die "execute como root: sudo ./install.sh"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/truenas-rpi"
VENV_DIR="$INSTALL_DIR/.venv"
DATA_DIR="/var/lib/truenas-rpi"
SERVICE_NAME="truenas-rpi"

if [[ ! -d "$SCRIPT_DIR/truenas" || ! -f "$SCRIPT_DIR/run.py" ]]; then
    die "rode o script dentro da pasta do projeto (contendo truenas/ e run.py)"
fi

# ----------------------------------------------------- detecção do Debian
. /etc/os-release 2>/dev/null || die "não foi possível ler /etc/os-release"
info "Detectado: $PRETTY_NAME (debian_version=$VERSION_ID, arch=$(dpkg --print-architecture))"

if [[ "$ID" != "debian" ]]; then
    yellow "AVISO: isso não é Debian ($ID). O script foi feito para Debian 13."
    [[ "$FORCE" -eq 1 ]] || die "use --force para continuar mesmo assim (corra por sua conta)"
    yellow "Continuando com --force..."
fi

if [[ "$VERSION_ID" != "13" ]] && [[ "$FORCE" -eq 0 ]]; then
    yellow "AVISO: este script é para Debian 13 (Trixie), vejo Debian $VERSION_ID."
    [[ "$FORCE" -eq 1 ]] || die "use --force para tentar em outra versão"
fi

# versão do Python
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 10 ]]; }; then
    die "Python >= 3.10 é necessário (encontrado: $PY_MAJOR.$PY_MINOR). Atualize o sistema."
fi
info "Python encontrado: $PY_MAJOR.$PY_MINOR"

# ---------------------------------------------------------------- 1. apt
info "==> [1/6] Instalando dependências de sistema (apt)..."
export DEBIAN_FRONTEND=noninteractive

APT_BASE=(
    python3 python3-pip python3-dev python3-venv
    build-essential libffi-dev libssl-dev
    curl ca-certificates
    pkg-config
)

# pyudev/pam precisam de headers de C
APT_BASE+=(libudev-dev libpam0g-dev)

apt-get update -y
apt-get install -y "${APT_BASE[@]}"

if [[ "$WITH_ZFS" -eq 1 ]]; then
    info "==> [2/6] Instalando OpenZFS (zfsutils-linux + zfs-dkms)..."
    if apt-get install -y zfsutils-linux zfs-dkms; then
        modprobe zfs 2>/dev/null && green "Módulo ZFS carregado." \
            || yellow "ZFS instalado; o módulo carrega após o reboot."
    else
        yellow "Falha ao instalar o ZFS. Pool.* continuarão vazios até instalar."
        yellow "Tente depois: sudo apt install zfsutils-linux zfs-dkms"
    fi
else
    yellow "OpenZFS pulado (--no-zfs)."
fi

# ----------------------------------------------------------- 2. venv + pip
info "==> [3/6] Criando virtualenv e instalando dependências Python (core)..."
mkdir -p "$INSTALL_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install websockets aiohttp orjson psutil bcrypt

info "==> [3/6] Dependências opcionais (falhas não bloqueiam)..."
OPTIONAL_DEPS=(pyudev netifaces pycryptodome)
for dep in "${OPTIONAL_DEPS[@]}"; do
    if "$VENV_DIR/bin/python" -m pip install "$dep"; then
        green "  OK: $dep"
    else
        yellow "  ignorado: $dep (opcional)"
    fi
done

# ---------------------------------------------------------------- 3. copia
info "==> [4/6] Copiando projeto para $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR"/truenas "$SCRIPT_DIR"/run.py "$SCRIPT_DIR"/setup.py \
      "$SCRIPT_DIR"/requirements.txt "$SCRIPT_DIR"/start.sh "$SCRIPT_DIR"/scripts \
      "$SCRIPT_DIR"/truenas-rpi.service "$INSTALL_DIR"/

if [[ -d "$SCRIPT_DIR/webui-master" ]]; then
    cp -r "$SCRIPT_DIR/webui-master" "$INSTALL_DIR/webui-master"
    yellow "webui-master copiado (frontend Angular - compilação necessária p/ servir UI)."
fi

# config.json - só se não existir (não sobrescreve ajustes feitos antes)
mkdir -p "$DATA_DIR"
if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
    cat > "$INSTALL_DIR/config.json" <<EOF
{
    "host": "0.0.0.0",
    "port": 80,
    "shell_port": 8080,
    "web_ui_path": "$INSTALL_DIR/webui-master/dist/webui",
    "data_dir": "$DATA_DIR",
    "log_level": "INFO",
    "max_shell_sessions": 5,
    "max_concurrent_calls": 20,
    "token_ttl": 604800,
    "reconnect_token_ttl": 604800,
    "short_token_ttl": 300
}
EOF
else
    yellow "config.json já existe em $INSTALL_DIR - mantendo o atual."
fi

# ---------------------------------------------------------------- 4. cython
if [[ "$WITH_CYTHON" -eq 1 ]]; then
    info "==> [4.5] Compilando extensões Cython (pode demorar no RPi)..."
    "$VENV_DIR/bin/python" -m pip install cython
    (cd "$INSTALL_DIR" && "$VENV_DIR/bin/python" setup.py build_ext --inplace)
    green "Cython build concluído."
fi

# ---------------------------------------------------------------- 5. service
if [[ "$WITH_SERVICE" -eq 1 ]]; then
    info "==> [5/6] Instalando serviço systemd ($SERVICE_NAME)..."
    cp "$INSTALL_DIR/truenas-rpi.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME" || {
        red "Falha ao iniciar o serviço. Veja: journalctl -u $SERVICE_NAME -e"
        exit 1
    }
    green "Serviço ativo: $(systemctl is-active $SERVICE_NAME)"
else
    yellow "Serviço systemd pulado (--no-service). Rode manualmente com:"
    yellow "  cd $INSTALL_DIR && sudo $VENV_DIR/bin/python run.py"
fi

# ---------------------------------------------------------------- 6. verificação
info "==> [6/6] Verificação do registro de métodos..."
"$VENV_DIR/bin/python" -c "
import sys; sys.path.insert(0, '$INSTALL_DIR')
import truenas.config as cfg
cfg._DEFAULTS['data_dir'] = '$DATA_DIR'
from truenas.server import TrueNasApp
app = TrueNasApp()
print('Métodos registrados:', len(app.rpc_handler._methods))
" || red "Problema ao importar o módulo (veja os logs acima)."

HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo "==============================================================="
green "  INSTALAÇÃO CONCLUÍDA"
echo "==============================================================="
echo "  Pasta do projeto : $INSTALL_DIR"
echo "  Dados/config     : $DATA_DIR"
echo "  API (WebSocket)  : ws://${HOST_IP:-<ip>}/api/current"
echo "  Shell WebSocket  : ws://${HOST_IP:-<ip>}:8080"
echo "  UI local         : http://${HOST_IP:-<ip>}/ui/  (após build do Angular)"
echo ""
echo "  Login padrão     : admin / admin   ⚠️  TROQUE JÁ A SENHA!"
echo "---------------------------------------------------------------"
echo "  Comandos úteis:"
echo "    sudo systemctl status $SERVICE_NAME"
echo "    journalctl -u $SERVICE_NAME -f"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "  Reboot após a instalação do ZFS (se aplicável): sudo reboot"
echo "==============================================================="