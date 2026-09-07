#!/usr/bin/env bash
# =============================================================================
#  install.sh - Instalador do TrueNAS Scale RPi para Debian 13 (Trixie)
#
#  Uso:
#    sudo ./install.sh                    # instala tudo, incluindo a UI Angular
#    sudo ./install.sh --no-ui            # não instala Node/Yarn nem compila a UI
#    sudo ./install.sh --with-cython      # compila extensões Cython
#    sudo ./install.sh --no-zfs           # pula instalação do OpenZFS
#    sudo ./install.sh --no-service       # não cria/ativa o systemd service
#    sudo ./install.sh --force            # ignora a checagem da versão Debian
#
#  Requisitos de rede: acesso a apt, NodeSource e registry npm (para a UI).
#  O build da UI pode levar 30-60 min em um Raspberry Pi.
#
#  O script deve ser executado a partir da pasta raiz do projeto (onde ele
#  está, junto com truenas/, run.py, config.json etc).
#
#  Não há prompts: a instalação é 100% automática (DEBIAN_FRONTEND=noninteractive).
#  Para remover, use o script irmão: sudo ./uninstall.sh
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
WITH_UI=1
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --with-cython) WITH_CYTHON=1 ;;
        --no-zfs)      WITH_ZFS=0 ;;
        --no-service)  WITH_SERVICE=0 ;;
        --no-ui)       WITH_UI=0 ;;
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
info "==> [1/7] Instalando dependências de sistema (apt)..."
export DEBIAN_FRONTEND=noninteractive

APT_BASE=(
    python3 python3-pip python3-dev python3-venv
    build-essential libffi-dev libssl-dev
    curl ca-certificates git
    pkg-config
)

# pyudev/pam precisam de headers de C
APT_BASE+=(libudev-dev libpam0g-dev)

apt-get update -y
apt-get install -y "${APT_BASE[@]}"

if [[ "$WITH_ZFS" -eq 1 ]]; then
    info "==> [2/7] Instalando OpenZFS (zfsutils-linux + zfs-dkms)..."
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
info "==> [3/7] Criando virtualenv e instalando dependências Python (core)..."
mkdir -p "$INSTALL_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
if ! "$VENV_DIR/bin/python" -m pip install websockets aiohttp orjson psutil bcrypt; then
    red "Falha ao instalar dependências Python do backend."
    exit 1
fi

info "     Dependências opcionais (falhas não bloqueiam)..."
OPTIONAL_DEPS=(pyudev netifaces pycryptodome)
for dep in "${OPTIONAL_DEPS[@]}"; do
    if "$VENV_DIR/bin/python" -m pip install "$dep"; then
        green "  OK: $dep"
    else
        yellow "  ignorado: $dep (opcional)"
    fi
done

# ---------------------------------------------------------------- 3. copia
info "==> [4/7] Copiando projeto para $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
# remove cópias antigas do frontend (evita node_modules/dist velhos e gigantes)
rm -rf "$INSTALL_DIR/webui-master"
cp -r "$SCRIPT_DIR"/truenas "$SCRIPT_DIR"/run.py "$SCRIPT_DIR"/setup.py \
      "$SCRIPT_DIR"/requirements.txt "$SCRIPT_DIR"/start.sh "$SCRIPT_DIR"/scripts \
      "$SCRIPT_DIR"/truenas-rpi.service "$INSTALL_DIR"/

if [[ -d "$SCRIPT_DIR/webui-master" ]]; then
    # copia sem node_modules/.git/.angular (node_modules pesa >1GB e, com o dist
    # pré-compilado, nem é necessário no RPi; se for recompilar, yarn install recria)
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --exclude='webui-master/node_modules' \
                 --exclude='webui-master/.git' \
                 --exclude='webui-master/.angular' \
                 "$SCRIPT_DIR/webui-master/" "$INSTALL_DIR/webui-master/"
    else
        mkdir -p "$INSTALL_DIR/webui-master"
        tar -C "$SCRIPT_DIR" --exclude='webui-master/node_modules' \
                 --exclude='webui-master/.git' \
                 --exclude='webui-master/.angular' \
                 -cf - webui-master | tar -C "$INSTALL_DIR" -xf -
    fi
    yellow "webui-master copiado (sem node_modules/.git; frontend Angular)."
fi

# ----------------------------------------------------------- 3.5 cython
if [[ "$WITH_CYTHON" -eq 1 ]]; then
    info "==> [4.5] Compilando extensões Cython (pode demorar no RPi)..."
    "$VENV_DIR/bin/python" -m pip install cython
    (cd "$INSTALL_DIR" && "$VENV_DIR/bin/python" setup.py build_ext --inplace)
    green "Cython build concluído."
fi

# --------------------------------------------------------- 4. Node + UI build
UI_BUILD_OK=0
if [[ "$WITH_UI" -eq 1 ]] && [[ -d "$INSTALL_DIR/webui-master" ]]; then

    # Se já veio um dist pronto do projeto, não recompila (ganha 30-60 min).
    PREBUILT_DIST=""
    for d in \
        "$INSTALL_DIR/webui-master/dist" \
        "$INSTALL_DIR/webui-master/dist/browser" \
        "$INSTALL_DIR/webui-master/dist/webui" \
        "$INSTALL_DIR/webui-master/dist/webui/browser"; do
        if [[ -f "$d/index.html" ]]; then
            PREBUILT_DIST="$d"
            break
        fi
    done
    if [[ -n "$PREBUILT_DIST" ]]; then
        green "UI já compilada em $PREBUILT_DIST - pulando build (yarn install/ng build)."
        UI_BUILD_OK=1
    else
        info "==> [5/7] Sem dist pronto; instalando Node.js 24 + Yarn 4 (para a UI Angular)..."

    NODE_MAJOR=0
    if command -v node >/dev/null 2>&1; then
        NODE_MAJOR=$(node -e 'process.stdout.write(String(process.versions.node.split(".")[0]))' 2>/dev/null || echo 0)
        info "Node detectado: $(node --version 2>/dev/null || echo '?')"
    fi
    if [[ "$NODE_MAJOR" -lt 24 ]]; then
        yellow "Instalando Node.js 24 via NodeSource..."
        if curl -fsSL https://deb.nodesource.com/setup_24.x -o /tmp/truenas-nodesource.sh &&
           bash /tmp/truenas-nodesource.sh && apt-get install -y nodejs; then
            green "Node instalado: $(node --version)"
        else
            yellow "Falha ao instalar Node.js (verifique rede/repositório NodeSource)."
            yellow "A UI não será compilada neste momento. Reexecute o install.sh mais tarde"
            yellow "ou compile manualmente com: cd $INSTALL_DIR/webui-master && yarn build:prod"
            WITH_UI=0
        fi
    fi

    if [[ "$WITH_UI" -eq 1 ]]; then
        if command -v yarn >/dev/null 2>&1 && [[ "$(yarn -v 2>/dev/null | cut -c1)" == "4" ]]; then
            green "Yarn $(yarn -v) já instalado."
        elif command -v corepack >/dev/null 2>&1; then
            corepack enable
            corepack prepare yarn@4.9.2 --activate
            green "Yarn instalado via corepack: $(yarn -v 2>/dev/null)"
        else
            yellow "corepack não encontrado; instalando yarn via npm..."
            if ! npm install -g yarn@4.9.2; then
                yellow "Falha ao instalar Yarn. Pulando compilação da UI."
                WITH_UI=0
            fi
        fi
    fi

    if [[ "$WITH_UI" -eq 1 ]]; then
        info "==> [5/7] Instalando dependências e compilando a UI Angular..."
        info "     (pode levar 30-60 minutos em um Raspberry Pi)"
        if ( set -e
             export CI=1
             cd "$INSTALL_DIR/webui-master"
             # alguns scripts usam `git rev-parse --show-toplevel`; garanta um repo git
             [[ -d .git ]] || git init -q
             yarn install

             RAM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 4096)
             NODE_MAX=$(( RAM_MB * 700 / 1024 ))
             (( NODE_MAX < 2048 )) && NODE_MAX=2048
             (( NODE_MAX > 8192 )) && NODE_MAX=8192
             if [[ "$RAM_MB" -lt 4096 ]]; then
                 yellow "     Aviso: RAM ${RAM_MB}MB foi detectada. O build pode ser lento;"
                 yellow "     considere aumentar a swap (dphys-swapfile set 4096 && dphys-swapfile swapon)."
             fi
             green "     Memória total: ${RAM_MB}MB -> heap do Node: ${NODE_MAX}MB"

             yarn tn-icons
             node ./setup-production-env.js
             NODE_OPTIONS="--max-old-space-size=${NODE_MAX}" \
                 yarn ng build --configuration production --base-href /
             yarn tsx scripts/update-sw-version.ts
        ); then
            UI_BUILD_OK=1
            green "UI Angular compilada com sucesso."
        else
            UI_BUILD_OK=0
            yellow "AVISO: falha ao compilar a UI (veja os logs acima)."
            yellow "O backend/API segue funcionando. Para recompilar depois:"
            yellow "  cd $INSTALL_DIR/webui-master && sudo yarn build:prod"
        fi
    fi
fi
fi

# ------------------------------------------------------- config.json
# web_ui_path deve apontar para o dist real do Angular (varia conforme a versão)
WEBUI_DIST=""
for d in \
    "$INSTALL_DIR/webui-master/dist" \
    "$INSTALL_DIR/webui-master/dist/browser" \
    "$INSTALL_DIR/webui-master/dist/webui" \
    "$INSTALL_DIR/webui-master/dist/webui/browser"; do
    if [[ -f "$d/index.html" ]]; then
        WEBUI_DIST="$d"
        break
    fi
done
if [[ -z "$WEBUI_DIST" ]]; then
    WEBUI_DIST="$INSTALL_DIR/webui-master/dist"
    yellow "dist da UI ainda não existe; usando caminho padrão ($WEBUI_DIST)."
fi

mkdir -p "$DATA_DIR"
if [[ ! -f "$INSTALL_DIR/config.json" ]]; then
    cat > "$INSTALL_DIR/config.json" <<EOF
{
    "host": "0.0.0.0",
    "port": 80,
    "shell_port": 8080,
    "web_ui_path": "$WEBUI_DIST",
    "data_dir": "$DATA_DIR",
    "log_level": "INFO",
    "max_shell_sessions": 5,
    "max_concurrent_calls": 20,
    "token_ttl": 604800,
    "reconnect_token_ttl": 604800,
    "short_token_ttl": 300
}
EOF
fi

# garante/atualiza o web_ui_path (idempotente, preserva demais ajustes)
"$VENV_DIR/bin/python" - "$INSTALL_DIR/config.json" "$WEBUI_DIST" <<'PY'
import json
import sys

path, dist = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    data = {}
data["web_ui_path"] = dist
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)
PY
green "web_ui_path definido para: $WEBUI_DIST"

# ---------------------------------------------------------------- 5. service
if [[ "$WITH_SERVICE" -eq 1 ]]; then
    info "==> [6/7] Instalando serviço systemd ($SERVICE_NAME)..."
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
info "==> [7/7] Verificação do registro de métodos..."
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
if [[ "$UI_BUILD_OK" -eq 1 ]]; then
    green "  Web UI           : http://${HOST_IP:-<ip>}/  (compilada e servida na raiz)"
else
    yellow "  Web UI           : NÃO compilada (backend/API OK). Reexecute install.sh para tentar."
fi
echo "  API (interno)    : ws://${HOST_IP:-<ip>}/api/current  (mesmo origin apenas)"
echo ""
echo "  Login padrão     : admin / admin   ⚠️  TROQUE JÁ A SENHA!"
echo "---------------------------------------------------------------"
echo "  Comandos úteis:"
echo "    sudo systemctl status $SERVICE_NAME"
echo "    journalctl -u $SERVICE_NAME -f"
echo "    sudo systemctl restart $SERVICE_NAME"
echo "    sudo ./uninstall.sh               # remover serviço e backend"
echo "    sudo ./uninstall.sh --purge-data  # também apaga os dados (/var/lib/truenas-rpi)"
echo "  Reboot após a instalação do ZFS (se aplicável): sudo reboot"
echo "==============================================================="