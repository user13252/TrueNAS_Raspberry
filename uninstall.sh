#!/usr/bin/env bash
# =============================================================================
#  uninstall.sh - Remove o TrueNAS Scale RPi do Debian 13 (Trixie)
#
#  Uso:
#    sudo ./uninstall.sh                     # remove serviço systemd + backend (/opt/truenas-rpi)
#    sudo ./uninstall.sh --purge-data        # também apaga dados/config (/var/lib/truenas-rpi)
#    sudo ./uninstall.sh --purge-node        # também desinstala Node.js 24 (NodeSource) e Yarn global
#    sudo ./uninstall.sh --purge-zfs         # também desinstala OpenZFS (zfsutils-linux, zfs-dkms)
#    sudo ./uninstall.sh --purge             # tudo acima (remoção completa)
#
#  Sem prompts; e sem flags, os dados são preservados por segurança.
# =============================================================================

set -euo pipefail

# ------------------------------------------------------------------ helpers
red()   { printf "\033[1;31m%s\033[0m\n" "$*"; }
green() { printf "\033[1;32m%s\033[0m\n" "$*"; }
yellow(){ printf "\033[1;33m%s\033[0m\n" "$*"; }
info()  { printf "\033[1;34m%s\033[0m\n" "$*"; }

die()   { red "ERRO: $*"; exit 1; }

# ------------------------------------------------------------ parse de args
PURGE_DATA=0
PURGE_NODE=0
PURGE_ZFS=0
PURGE_ALL=0
for arg in "$@"; do
    case "$arg" in
        --purge-data) PURGE_DATA=1 ;;
        --purge-node) PURGE_NODE=1 ;;
        --purge-zfs)  PURGE_ZFS=1 ;;
        --purge)      PURGE_ALL=1 ;;
        *) die "argumento desconhecido: $arg" ;;
    esac
done
if [[ "$PURGE_ALL" -eq 1 ]]; then
    PURGE_DATA=1; PURGE_NODE=1; PURGE_ZFS=1
fi

# ------------------------------------------------------------------ pré-checks
if [[ "$(id -u)" -ne 0 ]]; then
    die "execute como root: sudo ./uninstall.sh"
fi

INSTALL_DIR="/opt/truenas-rpi"
DATA_DIR="/var/lib/truenas-rpi"
SERVICE_NAME="truenas-rpi"

info "==> [1/5] Parando e removendo o serviço systemd..."
if [[ -f "/etc/systemd/system/$SERVICE_NAME.service" ]] || \
   systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}\.service"; then
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
    green "Serviço $SERVICE_NAME removido."
else
    yellow "Serviço não encontrado; continuando..."
fi

info "==> [2/5] Removendo backend ($INSTALL_DIR)..."
rm -rf "$INSTALL_DIR"
green "Backend removido."

if [[ "$PURGE_DATA" -eq 1 ]]; then
    info "==> [3/5] Removendo dados/config ($DATA_DIR)..."
    rm -rf "$DATA_DIR"
    green "Dados removidos."
else
    info "==> [3/5] Dados preservados ($DATA_DIR)."
    yellow "  Para apagá-los depois: sudo rm -rf $DATA_DIR"
fi

if [[ "$PURGE_NODE" -eq 1 ]]; then
    info "==> [4/5] Desinstalando Node.js 24 + Yarn (NodeSource)..."
    command -v npm >/dev/null 2>&1 && npm uninstall -g yarn@4.9.2 2>/dev/null || true
    apt-get remove -y nodejs 2>/dev/null || true
    rm -f /etc/apt/sources.list.d/nodesource.list \
          /etc/apt/sources.list.d/nodesource.list.dpkg-old \
          /etc/apt/keyrings/nodesource.gpg \
          /usr/share/keyrings/nodesource.gpg
    apt-get update -y
    green "Node.js/Yarn removidos."
else
    info "==> [4/5] Node.js/Yarn preservados (--purge-node para remover)."
fi

if [[ "$PURGE_ZFS" -eq 1 ]]; then
    info "==> [5/5] Desinstalando OpenZFS..."
    apt-get remove -y zfsutils-linux zfs-dkms 2>/dev/null || true
    apt-get autoremove -y 2>/dev/null || true
    green "OpenZFS removido (recarregue o módulo de kernel: modprobe zfs)."
else
    info "==> [5/5] OpenZFS preservado (--purge-zfs para remover)."
fi

echo ""
echo "==============================================================="
green "  DESINSTALAÇÃO CONCLUÍDA"
echo "==============================================================="
echo "  Serviço systemd : $SERVICE_NAME (removido)"
echo "  Backend         : $INSTALL_DIR (removido)"
if [[ "$PURGE_DATA" -eq 1 ]]; then
    echo "  Dados/config    : $DATA_DIR (removidos)"
else
    yellow "  Dados/config    : PRESERVADOS em $DATA_DIR"
fi
if [[ "$PURGE_NODE" -eq 1 ]]; then
    echo "  Node.js/Yarn    : removidos (NodeSource repo também)"
else
    yellow "  Node.js/Yarn    : PRESERVADOS"
fi
if [[ "$PURGE_ZFS" -eq 1 ]]; then
    echo "  OpenZFS         : removido"
else
    yellow "  OpenZFS         : PRESERVADO (módulo carregado na memória)"
fi
echo "==============================================================="