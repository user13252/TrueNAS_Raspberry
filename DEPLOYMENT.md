# Deploy no Raspberry Pi — TrueNAS Scale RPi

Guia passo a passo para rodar o backend em hardware real com ZFS.

---

## 1. Hardware Recomendado

| Componente | Mínimo | Recomendado |
|---|---|---|
| Placa | Raspberry Pi 4 | Raspberry Pi 5 |
| RAM | 4 GB | 8 GB |
| SD/eMMC | 16 GB (SO) | 32 GB |
| Disco de dados | 1× USB-SATA | 2× (espelhado) em **USB3** |
| Alimentação | fonte 5V/3A | fonte oficial + SSD case |
| Rede | onboard | Gigabit |

> ZFS prefere **mais RAM e ECC**; em RPi sem ECC, use pelo menos um disk mirror
> e ative scrubs periódicos.

---

## 2. Instalar o SO (Raspberry Pi OS)

```bash
# Instalação padrão → 64-bit Lite (sem desktop)
# https://www.raspberrypi.com/software/
```

Na primeira inicialização:

```bash
sudo raspi-config
#  → System Options → Boot/Network → habilite SSH
#  → Performance → GPU Memory = 16 (libera RAM p/ ZFS)

sudo apt update && sudo apt full-upgrade -y
```

---

## 3. Instalar OpenZFS (obrigatório para pools)

O ZFS funciona no RPi 4/5 desde Linux 5.9+, basta o módulo de kernel.

```bash
# Habilita repositório backports se na versão estável faltar o módulo
sudo apt install -y zfs-dkms zfsutils-linux
sudo modprobe zfs

# Verifica
zpool version
```

Kernel headers são exigidos pelo DKMS (rebootar após instalar ZFS).

> Sem ZFS instalado, o backend funciona, mas `pool.*` retornam listas vazias
> (os comandos delegam para `zpool`/`zfs`).

---

## 4. Instalar o Backend

> ### ⚡ Instalação automática (Debian 13 / Trixie)
>
> ```bash
> # no RPi, dentro da pasta do projeto (copie o projeto antes):
> sudo ./install.sh                 # básico
> sudo ./install.sh --with-cython   # + build Cython
> sudo ./install.sh --no-zfs        # sem OpenZFS
> sudo ./install.sh --no-service    # não cria o systemd service
> sudo ./install.sh --force         # ignora checagem da versão Debian
> ```
>
> O `install.sh` instala as dependências de apt/pip (incluindo OpenZFS),
> copia o projeto para `/opt/truenas-rpi`, gera o `config.json`, instala e
> inicia o serviço systemd e verifica o registro dos 412 métodos.

### Manualmente:

```bash
sudo mkdir -p /opt/truenas-rpi
cd /opt/truenas-rpi

# Copie o projeto (git, rsync ou scp)
scp -r ./* user@<pi>:/opt/truenas-rpi/

# Dependências
cd /opt/truenas-rpi
pip3 install -r requirements.txt

# (Opcional) build Cython para performance
pip3 install cython setuptools wheel
python3 setup.py build_ext --inplace
```

---

## 5. Configurar

`config.json`:

```json
{
    "host": "0.0.0.0",
    "port": 80,
    "shell_port": 8080,
    "web_ui_path": "/opt/truenas-rpi/webui-master/dist/webui",
    "data_dir": "/var/lib/truenas-rpi",
    "max_shell_sessions": 5,
    "max_concurrent_calls": 20,
    "token_ttl": 604800,
    "reconnect_token_ttl": 604800,
    "short_token_ttl": 300
}
```

- `data_dir` = onde ficam `users.json` e `config.json` persistidos. Crie com os
  donos certos:

```bash
sudo mkdir -p /var/lib/truenas-rpi
```

---

## 6. Criar Pool (exemplo espelhado)

```bash
# Identifique os discos
lsblk                       # ou:
python3 -c "import truenas.backends.zfs as z; import asyncio; print(asyncio.run(z.zpool_list()))"

# Crie um pool espelhado
sudo zpool create tank mirror /dev/sda /dev/sdb

# Crie um dataset de exemplo
sudo zfs create tank/dados

# Ative compressão e dedupe desligado p/ RPi
sudo zfs set compression=lz4 tank
```

> O backend também pode criar pools via API:
> `pool.create({"name": "tank", "type": "mirror", "disks": ["/dev/sda", "/dev/sdb"]})`

---

## 7. Serviço Systemd (boot automático)

```bash
sudo cp truenas-rpi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now truenas-rpi
sudo systemctl status truenas-rpi
```

Logs:

```bash
journalctl -u truenas-rpi -f
```

---

## 8. Firewall (ufw) — se habilitado

```bash
sudo ufw allow 80/tcp      # API + UI
sudo ufw allow 8080/tcp    # WebSocket shell
sudo ufw allow 22/tcp      # SSH
sudo ufw allow 2049/tcp    # NFS (se exportar)
sudo ufw allow 445/tcp     # SMB (se compartilhar)
```

---

## 9. Primeiro Acesso

1. Abra a web UI: `http://<ip>/ui/`
2. Login: `admin` / `admin`
3. **Troque a senha imediatamente**:
   - `user.set_password({"username": "admin", "new_password": "..."})`, ou
   - remova `users.json` e reinicie (em último caso).

---

## 10. Performance / Estabilidade (RPi)

| Ajuste | Recomendação |
|---|---|
| GPU Memory | `raspi-config` → 16 MB |
| `vm.swappiness` | `echo 10 | sudo tee /proc/sys/vm/swappiness` |
| zfs ARC | `echo 'options zfs zfs_arc_max=2147483648' | sudo tee /etc/modprobe.d/zfs.conf` (1-2 GB) |
| Temp files | mova `data_dir` para SSD, não SD |
| Swap | evite swap em SD; se precisar, use dataset ZFS dedicado |
| Frequência dinâmica | `cpupower`/`cpufreq` no modo `ondemand` |

> ARC em RPi: defina `zfs_arc_max` para **≤ 50% da RAM** para não competir com
> o S.O. Em 4 GB: `zfs_arc_max=1610612736` (1,5 GB).

---

## 11. Backup / Restauração

Pasta a salvar (config + usuários):

```bash
sudo tar czf truenas-rpi-backup.tgz /var/lib/truenas-rpi
```

Restauração:

```bash
sudo tar xzf truenas-rpi-backup.tgz -C /
sudo systemctl restart truenas-rpi
```

---

## 12. Atualização

```bash
cd /opt/truenas-rpi
git pull                        # se clonado
sudo systemctl stop truenas-rpi
python3 setup.py build_ext --inplace   # se usar Cython
sudo systemctl start truenas-rpi
```

O `data_dir` (`/var/lib/truenas-rpi`) não é tocado pela atualização — as
configurações e usuários são preservados.

---

## 13. Troubleshooting específico do RPi

| Sintoma | Causa | Solução |
|---|---|---|
| `zpool` não existe | ZFS não instalado | `sudo apt install zfs-dkms zfsutils-linux` |
| `Cannot open pool: device is busy` | UUID/partição montada | `sudo zpool export` antes; use `by-id` |
| slow I/O em USB | cabo/USB3 ou power | USB3 dedicado, fonte boa |
| backend não sobe na porta 80 | porta em uso | `sudo netstat -tulpn | grep :80` |
| shell WebSocket desconecta | PTY indisponível | verifique `HAS_PTY` e use Linux |