# TrueNAS Scale RPi

Backend do TrueNAS Scale escrito em **Python 3** (compilável com **Cython**) para rodar em **Raspberry Pi**, servindo a interface web original do TrueNAS Scale (imutável - apenas consumida, nunca modificada).

O backend implementa o **middleware** que a web UI espera: um servidor **WebSocket JSON-RPC 2.0** em `/api/current`, o terminal via `/websocket/shell/`, e os demais endpoints HTTP auxiliares.

---

## ✨ Visão Geral

```
┌───────────────────────────────────────────────────────────────────┐
│  webui-master/  (TrueNAS Scale Web UI - Angular - NÃO MODIFICAR)  │
└───────────────────────────────┬───────────────────────────────────┘
                                │  ws://<ip>:80/api/current
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  truenas/  (este projeto - middleware Python)                      │
│                                                                    │
│   server.py  ── TrueNasApp                                         │
│   ├─ JsonRpcHandler     → encaminha "modulo.metodo" → handler     │
│   │   ├─ middleware auth → RBAC (6 roles)                         │
│   │   └─ 13 módulos → 412 métodos API registrados                │
│   ├─ AuthManager         users/sessions/tokens/reconnect          │
│   ├─ JobManager          jobs assíncronos long-running            │
│   ├─ SubscriptionManager evento push (collection_update)          │
│   ├─ ConfigStore         persistência JSON em data_dir            │
│   └─ ShellManager        ws://:8080  terminal PTY (bash)          │
│                                                                    │
│   backends/                                                        │
│   ├─ linux.py            comandos do SO (ip, lsblk, /proc,...)    │
│   ├─ zfs.py              wrappers completa de zfs/zpool           │
│   └─ config_store.py     persistência de configuração             │
└───────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Início Rápido (Raspberry Pi)

```bash
# 1. Instalar dependências
pip3 install websockets aiohttp orjson psutil bcrypt

# 2. Rodar (modo puro Python)
./start.sh
#  ou
python3 run.py
```

Acesso:
- WebSocket API: `ws://<ip-do-rpi>/api/current`
- Shell WebSocket: `ws://<ip-do-rpi>:8080`
- Login padrão: `admin` / `admin` (**troque imediatamente!**)

### Build Cython (performance otimizada)

```bash
pip3 install cython setuptools wheel
python3 setup.py build_ext --inplace
python3 run.py
```

O processo compila todos os `.py` para extensões `.so` nativas com otimizações
(`boundscheck=False`, `wraparound=False`, `initializedcheck=False`).

---

## 📚 Documentação

| Documento | Conteúdo |
|---|---|
| [README.md](README.md) | Este arquivo |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Arquitetura, fluxo de dados, protocolo |
| [API_REFERENCE.md](API_REFERENCE.md) | Todas as 412 chamadas RPC disponíveis |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Instalação completa no Raspberry Pi |
| [BUILD.md](BUILD.md) | Builds: Python puro, Cython, Docker, systemd |

---

## 🧩 Módulo Implementados

### Núcleo / Protocolo
| Módulo | Prefixo API | Métodos |
|---|---|---|
| Núcleo | `core.*` | `set_options`, `get_jobs`, `subscribe`, `unsubscribe`, `job_abort`, `bulk`, `download`, `resize_shell` |
| Autenticação | `auth.*` | `login_ex`, `login_ex_continue`, `me`, `generate_token`, `sessions`, `logout`, `terminate_session`, `terminate_other_sessions`, `set_attribute`, `twofactor.config` |

### Sistema
| Módulo | Prefixo API | Funcionalidade |
|---|---|---|
| Sistema | `system.*` | info, product_type, hostname, reboot, shutdown, general/advanced/security config, NTP, tunables, init scripts |
| Alertas | `alert.*`, `alertservice.*`, `alertclasses.*` | lista/dismiss/restore, serviços, classes, política, verificação automática de temperatura/disco |
| Serviços | `service.*` | query, update, control (19 serviços conhecidos) |

### Armazenamento (ZFS)
| Módulo | Prefixo API | Métodos |
|---|---|---|
| Pools | `pool.*` | query, create, export, import_pool, update, attach, detach, offline, online, replace, upgrade, scan, expand, get_disks |
| Datasets | `pool.dataset.*` | query, create, update, delete, child, process, rollback, promote, set_quota, inherit_quota, permissions |
| Snapshots | `pool.snapshot.*` | query, create, delete, clone, rollback, hold, release |
| Tasks de Snapshot | `pool.snapshottask.*` | query, create, update, delete, retention_validate |
| Scrub | `pool.scrub.*` | query, create, update, delete, run |
| Disks | `disk.*` | query, temperature_agg, update |
| ZPool | `zpool.query` | informações do pool |
| Boot | `boot.*` | query, pool_query, attach, detach, replace, online, offline |
| System Dataset | `systemdataset.*` | config, update |
| Resilver | `pool.resilver.*` | config, update |

### Rede
| Módulo | Prefixo API | Funcionalidade |
|---|---|---|
| Interfaces | `interface.*` | query, create (PHY/VLAN/LAGG/Bridge), update, delete, checkin, commit, rollback, defaults, has_carp |
| Configuração | `network.configuration.*` | config, update, summary |
| Rotas | `staticroute.*` | query, create, update, delete |

### Compartilhamento
| Módulo | Prefixo API | Funcionalidade |
|---|---|---|
| SMB | `sharing.smb.*` + `smb.*` | CRUD de shares, share_precheck, geração de smb.conf |
| NFS | `sharing.nfs.*` + `nfs.*` | CRUD de shares, geração de /etc/exports |
| S3 | `sharing.s3.*` + `s3.*` | CRUD de buckets, config MinIO |
| WebDAV | `sharing.webdav.*` | CRUD de shares |
| iSCSI | `iscsi.*` | global, portal, target, extent, targetextent, initiator, auth, session |

### Dados / Aplicações
| Módulo | Prefixo API | Funcionalidade |
|---|---|---|
| Replicação | `replication.*` | query, create, update, delete, run, restore, list_datasets, list_naming_schemas |
| Cloud Sync | `cloudsync.*` | query, create, update, delete, run, providers, buckets, ls |
| Cloud Backup | `cloud_backup.*` | query, create, update, delete, run, list_snapshots, restore |
| Rsync | `rsynctask.*` | query, create, update, delete, run |
| Snapshots periódicos | `snapshottask.*` | query, create, update, delete, run, retention_validate |
| Apps/Docker | `app.*`, `docker.*`, `catalog.*`, `container.*` | CRUD de apps, config docker, catálogos, containers/imagens/stats |

### Virtualização
| Módulo | Prefixo API | Funcionalidade |
|---|---|---|
| VMs | `vm.*` | query, create, update, delete, start, stop, restart, reset, poweroff, resume, display_devices, display_web_uri, port_wizard, virtualization_details |
| Dispositivos VM | `vm.device.*` | query, create, update, delete, PCI/USB passthrough |
| VMware | `vmware.*` | query, create, update, delete, match_products, get_datastores |

### Usuários & Segurança
| Módulo | Prefixo API | Funcionalidade |
|---|---|---|
| Usuários | `user.*` | query, create, update, delete, get_user_obj, set_password, next_uid, setup_local_administrator |
| Grupos | `group.*` | query, create, update, delete, next_gid |
| Privilégios | `privilege.*` | query, create, update, delete, roles |

### Infraestrutura / Outros
| Módulo | Prefixo API | Funcionalidade |
|---|---|---|
| Filesystem | `filesystem.*` | listdir, stat, statfs, getacl, setacl, setperm, put, mkdir, unlink, rename, file_tail_follow, acltemplate.query, acl_is_trivial |
| Devices | `device.get_info` | informações de hardware (GPU) |
| Mail | `mail.*` | config, update, send |
| SNMP | `snmp.*` | config, update |
| SSH | `ssh.*` | config, update |
| FTP | `ftp.*` | config, update |
| UPS | `ups.*` | config, update |
| Reporting | `reporting.*` | graphs, get_data, realtime |
| API Keys | `api_key.*` | query, create, update, delete |
| Keychain | `keychaincredential.*` | CRUD de credenciais SSH + generate_ssh_key_pair |
| Failover | `failover.*` | config, status, disabled.reasons, reboot.info |
| Audit | `audit.*` | config, update, query, export, download_report |
| Certificados | `certificate.*`, `certificate.certificateauthority.*` | query |
| Directory Services | `directoryservices.*`, `ldap.*`, `kerberos.*` | status, cache_refresh, configs |
| TrueNAS | `truenas.*`, `truecommand.*`, `tn_connect.*` | EULA, production, console |
| Outros | `kmip.*`, `acme.dns.authenticator.*`, `cloud_credential.*`, `support.*`, `enclosure2.*` | configs |

---

## 🔐 Autenticação & RBAC

O sistema suporta **6 papéis** em hierarquia:

| Papel | Permissão |
|---|---|
| `FULL_ADMIN` | Tudo, inclui todos os abaixo |
| `SHARING_ADMIN` | Gerencia compartilhamentos |
| `STORAGE_ADMIN` | Gerencia pools/datasets/snapshots |
| `NETWORK_ADMIN` | Gerencia interfaces/redes |
| `VM_ADMIN` | Gerencia VMs |
| `READ_ONLY` | Apenas leitura |

O middleware de autenticação:
- Ignora `auth.login_ex`, `auth.login_ex_continue`, `core.set_options`
- Exige token de sessão válido para todo o resto
- Aplica a tabela RBAC por método (`METHOD_ROLES`)
- Injeta `context["session"]` e `context["user"]` nos handlers autenticados

Autenticação por mecanismos:
- `PASSWORD_PLAIN` — nome de usuário + senha (bcrypt)
- `TOKEN_PLAIN` — reconnect token para reconexão automática

---

## 📦 Configuração (`config.json`)

```json
{
    "host": "0.0.0.0",
    "port": 80,
    "shell_port": 8080,
    "web_ui_path": "./webui-master/dist/webui",
    "data_dir": "/var/lib/truenas-rpi",
    "max_shell_sessions": 5,
    "max_concurrent_calls": 20,
    "token_ttl": 604800,
    "reconnect_token_ttl": 604800,
    "short_token_ttl": 300
}
```

Defina o caminho via variável de ambiente `TRUENAS_CONFIG` (o service do systemd já o faz).

---

## 🧪 Testes

Todos os testes de registro, login, RBAC, query engine, jobs e o ciclo completo
de WebSocket (login → auth.me → subscribe → collection_update → unsubscribe →
logout → negação) são executados e passam:

```bash
# Verificação rápida de sintaxe de todos os arquivos
python -m compileall truenas

# Teste end-to-end (WebSocket local)
python scripts/ws_test.py
```

---

## 📁 Estrutura do Projeto

```
truenas-rpi/
├── run.py                    # Entry point
├── setup.py                  # Build Cython (python setup.py build_ext --inplace)
├── config.json               # Configuração do servidor
├── requirements.txt          # Dependências
├── start.sh                  # Script de início (bash)
├── truenas-rpi.service       # Unit do systemd
├── BUILD.md                  # Guia de builds
├── README.md                 # Este arquivo
├── ARCHITECTURE.md           # Arquitetura detalhada
├── API_REFERENCE.md          # Referência das 400+ APIs RPC
├── DEPLOYMENT.md             # Deploy no Raspberry Pi
│
├── truenas/
│   ├── __init__.py
│   ├── server.py             # TrueNasApp (servidores WS + registro de módulos)
│   ├── rpc.py                # JsonRpcHandler (JSON-RPC 2.0 + middleware)
│   ├── auth.py               # AuthManager, Session, RBAC
│   ├── config.py             # Config singleton (config.json)
│   ├── jobs.py               # JobManager (tarefas assíncronas)
│   ├── query.py              # Engine de filtros/ordenação/limites
│   ├── subscriptions.py      # SubscriptionManager (collection_update)
│   │
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── linux.py          # Comandos do SO + informações do sistema
│   │   ├── zfs.py            # Tudo de zfs/zpool
│   │   └── config_store.py   # Persistência JSON
│   │
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── core.py           # core.*
│   │   ├── system.py         # system.*
│   │   ├── storage.py        # pool.*, dataset.*, snapshot.*, disk.*, boot.*
│   │   ├── network.py        # interface.*, network.*, staticroute.*
│   │   ├── service.py        # service.*
│   │   ├── sharing.py        # sharing.smb/nfs/s3/webdav.*, smb/nfs/s3.*, iscsi.*
│   │   ├── alert.py          # alert.*, alertservice.*, alertclasses.*
│   │   ├── filesystem.py     # filesystem.*, device.*
│   │   ├── users.py          # user.*, group.*, privilege.*
│   │   ├── app.py            # app.*, docker.*, catalog.*, container.*
│   │   ├── vm.py             # vm.*, vm.device.*, vmware.*
│   │   ├── dataprotection.py # replication.*, cloudsync.*, cloud_backup.*, rsynctask.*, snapshottask.*
│   │   └── misc.py           # mail, snmp, ssh, ftp, ups, reporting, api_key, ...
│   │
│   └── shell/
│       ├── __init__.py
│       └── terminal.py       # ShellManager (PTY bash via WebSocket)
│
└── webui-master/             # Web UI do TrueNAS (IMUTÁVEL - não editar)
```

---

## ⚠️ Notas Importantes

1. **A web UI (`webui-master/`) é imutável** — este projeto apenas implementa o
   middleware/backend que ela consome.
2. **Alvo:** Raspberry Pi OS (Linux). Foi testado em Windows para desenvolvimento;
   recursos como ZFS, PTY shell e `pwd` requerem Linux.
3. **Credencial padrão `admin`/`admin`** é criada no primeiro boot — troque na
   primeira sessão.
4. **ZFS no Raspberry Pi** requer OpenZFS (veja [DEPLOYMENT.md](DEPLOYMENT.md)).
5. **Cython** requer compilador C no alvo (`gcc`/`build-essential`).

---

## 📝 Licença

Este projeto é um backend independente escrito do zero. A web UI em
`webui-master/` pertence aos seus respectivos donos (TrueNAS/iXsystems) e foi
incluída apenas como assets de frontend.