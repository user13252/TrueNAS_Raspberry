# Build Instructions — TrueNAS Scale RPi

Guia completo de build e execução em diferentes modos e targets.

> **Para Debian 13 (Trixie), use o instalador automático: `sudo ./install.sh`.**
> Veja também [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 1. Modo Python Puro (Padrão)

Recomendado para desenvolvimento e debug. Não requer compilador.

```bash
# Dependências
pip3 install websockets aiohttp orjson psutil bcrypt
# ou, do requirements.txt:
pip3 install -r requirements.txt
```

```bash
chmod +x start.sh run.py
./start.sh            # equivalente a: python3 run.py
```

### Verificação de sintaxe (todos os módulos)

```bash
python3 -m compileall truenas
```

---

## 2. Build Cython (Otimizado)

Compila todos os módulos `truenas/` para extensões `.so` nativas. Reduz
overhead de interpretação nos loops quentes (query engine, JSON-RPC dispatch).

### Pré-requisitos (Raspberry Pi OS)

```bash
sudo apt update
sudo apt install -y python3-dev build-essential
pip3 install cython setuptools wheel
```

### Build

```bash
python3 setup.py build_ext --inplace   # build in-place no diretório do projeto
```

O `setup.py` usa diretivas de otimização:

```ini
language_level=3, boundscheck=False, wraparound=False,
initializedcheck=False, nonecheck=False, optimize.use_switch=True
```

Cada módulo em `truenas/**/*.py` vira um `*.so` ao lado. Se o Cython ou o
compilador faltar, o `setup.py` **degrada para Python puro** com um aviso.

### Build de release (sem artefatos temporários)

```bash
python3 setup.py build_ext --inplace
find . -name "*.c" -delete   # limpa fontes temporárias geradas pelo Cython
```

> Em produção, use `CONTRAPTÕES` limpas: rode o build em um ambiente isolado
> (chroot/Docker) para não deixar `.c` e `.py` misturados com os `.so`.

---

## 3. Install no Sistema (como package)

```bash
pip3 install .
# ou com build Cython primeiro:
python3 setup.py build_ext --inplace && pip3 install .

# Instala o comando global:
truenas-rpi
```

---

## 4. Serviço Systemd

Unit: `truenas-rpi.service`

```ini
[Unit]
Description=TrueNAS Scale RPi Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/truenas-rpi
Environment=TRUENAS_CONFIG=/opt/truenas-rpi/config.json
ExecStart=/usr/bin/python3 /opt/truenas-rpi/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# 1. instale os arquivos
sudo cp -r . /opt/truenas-rpi/

# 2. instale e habilite o serviço
sudo cp truenas-rpi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable truenas-rpi
sudo systemctl start truenas-rpi

# 3. verifique
sudo systemctl status truenas-rpi
journalctl -u truenas-rpi -f
```

⚠️ Porta 80 é privilegiada: rode como `root` ou use `cap_net_bind_service` /
redirecionamento na firewall (`80 → <porta-alta>`).

---

## 5. Docker

Sem `Dockerfile` no repositório ainda — use o `start.sh` como base expondo as
portas:

```bash
# Manual (a partir do diretório do projeto)
docker build -t truenas-rpi .
docker run -d --name truenas-rpi \
  -p 80:80 -p 8080:8080 \
  -v /mnt:/mnt \
  -v /dev:/dev --privileged \
  truenas-rpi
```

Pontos de atenção para ZFS dentro de container:
- `--privileged` (ou `--device` para os discos) para `zpool`/`zfs`.
- Montar `/mnt` (pools) como volume.
- Preferir **host networking** (`--network host`) para simplificar portas.

---

## 6. Testes

### Teste de importação/registro

```bash
python3 -c "
import truenas.config as cfg
cfg._DEFAULTS['data_dir'] = '/tmp/truenas_test'
from truenas.server import TrueNasApp
app = TrueNasApp()
print('Métodos registrados:', len(app.rpc_handler._methods))
"
# Esperado: 412
```

### Teste end-to-end via WebSocket (login → subscribe → push → logout)

```bash
python3 scripts/ws_test.py
```

Pré-requisito: usuário `admin`/`admin` criado (primeiro boot automático).

---

## 7. Troubleshooting

| Problema | Causa provável | Solução |
|---|---|---|
| `No module named websockets` | deps não instaladas | `pip3 install -r requirements.txt` |
| `CompileError` no `build_ext` | falta `python3-dev`/gcc | `sudo apt install -y python3-dev build-essential` |
| porta 80 ocupada | outro serviço web | ajuste `config.json` (`port`) |
| `Not permitted (-32001)` | token expirado / não logado | refaça `auth.login_ex` |
| ZFS não disponível | kernel sem OpenZFS | veja [DEPLOYMENT.md](DEPLOYMENT.md#o-zfs-no-raspberry-pi) |
| PTY não disponível | plataforma sem pty (`HAS_PTY=False`) | shell desabilitado, API segue normal |

---

## 8. Acesso Padrão

- WebSocket API: `ws://<ip>/api/current`
- WebSocket Shell: `ws://<ip>:8080`
- HTTP UI (estáticos): `http://<ip>/ui/`
- Login: `admin` / `admin` (**troque na primeira sessão**)