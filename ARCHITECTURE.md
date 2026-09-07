# Arquitetura — TrueNAS Scale RPi

Este documento descreve como o backend implementa o protocolo esperado pela
web UI do TrueNAS Scale e como cada subsistema funciona internamente.

---

## 1. Visão Geral do Fluxo

### 1.1 Conexão principal (API)

O navegador abre um WebSocket em `ws://<host>/api/current`. Cada mensagem é um
JSON-RPC 2.0:

```
Client                                          Server (TrueNasApp)
  │  ws://host/api/current                          │
  │ ── {"jsonrpc":"2.0","id":1,                      │
  │     "method":"core.set_options",                 │
  │     "params":[{"legacy_jobs":false}]} ─────────► │ JsonRpcHandler.handle
  │                                                  │  middleware (skip: ok)
  │ ◄── {"jsonrpc":"2.0","id":1,"result":null} ────── │
  │                                                 │
  │ ── {"jsonrpc":"2.0","id":2,                      │
  │     "method":"auth.login_ex",                    │
  │     "params":[[{"mechanism":"PASSWORD_PLAIN",    │
  │                "username":"admin",                │
  │                "password":"admin"}]]} ─────────► │ authenticate_password
  │                                                 │ cria Session (token+reconnect)
  │ ◄── {"jsonrpc":"2.0","id":2,"result":{           │
  │       "auth_result":"SUCCESS",                   │
  │       "user_info":{...},"reconnect_token":"..."} │
  │                                                 │
  │   handle_api_websocket liga o token da sessão    │
  │   ao client_id (auth_token)                      │
  │                                                 │
  │ ── auth.me (params: []) ───────────────────────► │ middleware valida session + RBAC
  │ ◄── {"result":{"username":"admin","roles":[...]}}│
```

### 1.2 Estado da conexão

`TrueNasApp._connected_clients[cid]` armazena por cliente:

| Chave | Descrição |
|---|---|
| `websocket` | objeto da conexão |
| `auth_token` | token da sessão logada (ou `None`) |
| `connected_at` | timestamp |
| `client_options` | opções `core.set_options` do cliente |
| `queues` / `sub_ids` | registros de subscriptions do cliente |

No `finally` da conexão, `queues` e `sub_ids` são limpos de
`SubscriptionManager` garantindo que o push nunca acumule vazamentos.

---

## 2. Caminho do JSON-RPC (`rpc.py`)

`JsonRpcHandler.handle(message, context)`:

1. **Validação** — sem `method` → `-32600 Invalid Request`.
2. **Middleware** — cada middleware assíncrono em `_middleware` recebe
   `(method, params, context)`. Se retorna `False` → `-32001 Not permitted`.
3. **Resolução** — `method` não registrado → `-32601 Method not found`.
4. **Invoco** — os parâmetros são expandidos posicionalmente (`params` como
   lista) ou por nome (`params` como dict), e `context` é **sempre** passado
   como keyword `context=...`. Se o handler não aceitar `context`, ele é
   descartado e a chamada é repetida (fallback por `TypeError`).
5. **Resposta** — `{"jsonrpc":"2.0","id":..., "result":...}` ou `error`.

Notificação (sem `id`) não recebe resposta.

### Códigos de erro

| Código | Origem |
|---|---|
| `-32600` | request inválido |
| `-32601` | método não encontrado |
| `-32001` | negado no middleware (muitas vezes falta de login) |
| `-32000` | exceção no handler (com `data.errname` e `data.reason`) |
| custom | `JsonRpcError` lançado dentro de um handler |

---

## 3. Registro de métodos (`register_module`)

Um único módulo é registrado sob vários prefixos. Exemplo: `StorageModule`
é registrado como `pool`, `pool.dataset`, `pool.snapshot`, `disk`, `boot`,
etc. O mecanismo de registro tem 3 fontes, aplicadas em ordem:

1. **`mapping`** — mapeia sufixo de API → nome do método. Ex.:
   `{"general.config": "general_config"}` registra `system.general.config`.
   Usado sempre que o nome do método não é derivável do nome de API.
2. **`include`** — registra métodos verbatim como `prefix.<nome>`. Usado p/ o
   `core.*` e `service.query/update/control`.
3. **auto-strip** — todo método `nome_publico` que começa com o último
   segmento do prefixo é registrado como `prefix.<resto>`.
   Ex.: `pool_query` → `pool.query`, `iscsi_portals_query` → `iscsi.portal.query`.

O auto-strip só registra métodos que começam com o último segmento do prefixo,
então registrar o mesmo módulo em `pool`, `pool.dataset` e `boot` produz
superfícies de API disjuntas, sem duplicação de nomes.

Resultado: **412 métodos** únicos registrados.

---

## 4. Auditoria de nomes

O checklist executado após o registro (e que passa 100%):

1. **Todos os métodos esperados existem** — cruzamento exaustivo do que a
   web UI chama (extraído de `webui-master/`) contra `_methods`.
2. **Nenhum nome estranho** — método com nome "errado" (`pool.pool_query`,
   `vmm.vm_query`, `ishare.validate_share`, etc.).
3. **Nenhum lixo** — métodos inválidos (ex.: `vmm.kind` — atributo não
   chamável) não são registrados.
4. **Nenhuma duplicação** — cada chamada tem exatamente 1 handler.

---

## 5. Autenticação e RBAC (`auth.py`)

### Usuários e senhas

- Banco em `users.json` dentro de `data_dir`.
- Primeiro boot cria `admin` com senha `admin` (hash bcrypt).
- `authenticate_password` verifica bcrypt; usuário travado (`locked`) é negado.

### Sessões

Cada sessão (`Session`) possui dois tokens:

| Token | Propósito |
|---|---|
| `token` | usado no header `Authorization: Bearer` ou como `auth_token` da conexão WS |
| `reconnect_token` | permite reconexão (`TOKEN_PLAIN`) após o browser recarregar |

- `generate_token(username, ttl)` — tokens efêmeros (API Keys).
- `authenticate_token` — valida sessão ou token curto com TTL.
- `authenticate_reconnect` — valida reconnect token contra sessões ativas.

### RBAC (hierarquia de papéis)

```
FULL_ADMIN
 ├─ SHARING_ADMIN ─┐
 ├─ STORAGE_ADMIN ─┼─── READ_ONLY
 ├─ NETWORK_ADMIN ─┤
 └─ VM_ADMIN ──────┘
```

- `READONLY_METHODS` — métodos de leitura liberados para qualquer papel.
- `METHOD_ROLES` — métodos de escrita exigem papel específico.
- Método fora das duas tabelas → só `FULL_ADMIN`.
- `FULL_ADMIN` passa em tudo.

### Middleware de autorização

```python
skip_auth = {"auth.login_ex", "auth.login_ex_continue", "core.set_options"}

token = context.auth_token (ou token)
session = AuthManager.get_session(token)   # senão: -32001
has_permission(session, method)            # senão: -32001
context["session"] = session
context["user"]     = session.user
```

Quando autorizado, os handlers recebem `context["session"]` e
`context["user"]` preenchidos.

---

## 6. Filtros de query (`query.py`)

Implementa o sistema de filtros do TrueNAS:

### Operadores suportados

| Op | Semântica |
|---|---|
| `=` `!=` `>` `>=` `<` `<=` | comparação |
| `~` | regex (`re.search`) |
| `in` / `nin` | contém / não contém |
| `rin` / `rnin` | algum do valor-list pertence / não pertence à lista |
| `^` / `!^` | começa com / não começa com |
| `$` / `!$` | termina com / não termina com |

Filtro OR: `["OR", [filtro1, filtro2]]`.

Acesso aninhado: `"parent.child"` percorre dicts, atributos e índices de lista.

### Options (`apply_options`)

- `select` — projeta apenas os campos pedidos.
- `order_by` — lista de campos ordenáveis; prefixo `-` = descendente.
- `offset` + `limit` — paginação.

Exemplo real de chamada:
```python
pool.query([["status", "=", "ONLINE"], "OR", [["name", "^", "tank"]]],
           {"select": ["name", "size"], "order_by": ["-size"], "limit": 10})
```

---

## 7. Jobs (tarefas longas) (`jobs.py`)

Operações demoradas (export de pool, replicação, backup) rodam em background:

- `JobManager.create(method, args, func, queue)` cria `Job` com estado
  `RUNNING` e agenda `_run_job`.
- Estados: `PENDING → RUNNING → SUCCESS | FAILED | cancelled`.
- `progress` = `{"percent": ..., "description": ...}`.
- `core.get_jobs` lista jobs; `core.job_abort` sinaliza cancelamento
  (`asyncio.Event`).
- Ao terminar, `_notify_subscribers("core.get_jobs")` faz push via
  `collection_update` para quem assinou.

---

## 8. Subscriptions (push) (`subscriptions.py`)

O TrueNAS usa **subscription a coleções** para atualizar a UI em tempo real:

1. Cliente chama `core.subscribe([["service.query"]]))` → retorna `sub_id`.
2. `SubscriptionManager.subscribe` guarda `method` + `queues`.
3. Qualquer `collection_update` publicado para aquele `method` é colocado nas
   queues dos assinantes.
4. `core.unsubscribe([sub_id])` remove.
5. No `finally` da WebSocket, queues/sub_ids do cliente são removidos.

### Formato do push (mensagem não solicitada)

```json
{"jsonrpc": "2.0", "method": "collection_update",
 "params": {"msg": "changed", "cleared": false, "sub_id": "<uuid>", "collection": "service.query", "id": 7}}
```

As publicações são geradas em:
- `service.update` / `service.control` → `service.query`
- `JobManager` → `core.get_jobs`
- `AlertModule` → `alert.list`
- Alterações de apps/VM → suas coleções

---

## 9. Shell WebSocket (`shell/terminal.py`)

- Servidor real em `ws://<host>:8080` (`shell_port`).
- Usa um **PTY** (pseudo-terminal) para cada sessão, rodando `bash`.
- `core.resize_shell` ajusta dimensões da sessão.
- Em plataformas sem PTY (dev Windows), o módulo degrada
  (`HAS_PTY = False`) sem quebrar o import do pacote.
- Handshake de auth igual ao API (token do `auth_token`).

---

## 10. Endpoints HTTP (`server.py:start_http_server`)

Servido via `aiohttp` no mesmo `host:port`:

| Rota | Comportamento |
|---|---|
| `/api/current` | resposta 426 (upgrade para WebSocket é servido pelo `websockets`) |
| `/websocket/shell` | resposta 426 (analogamente) |
| `/api/boot_id` | `{"boot_id": "<uuid>"}` |
| `/api/docs` | skeleton do OpenAPI |
| `/ui/*` | arquivos estáticos da web UI (se `dist/webui` existir) |

---

## 11. Backends

### `backends/linux.py`

Camada de integração com o SO:

| Função | Fonte |
|---|---|
| `run_cmd` | `asyncio.create_subprocess_shell`, saída decodificada com `errors="replace"` |
| `get_system_info` | `uname`, `/proc/meminfo`, `/proc/cpuinfo`, `dpkg`/`free` |
| `get_disk_info` | `lsblk -Jb -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL,SERIAL` |
| `get_network_interfaces` | `ip -j link/addr`, `netifaces` quando disponível |
| `get_interfaces` | nameserver/gateway/DNS |
| `get_services` | `systemctl` (estado/startup do serviço) |
| `read_boot_id` | `/proc/sys/kernel/random/boot_id` |
| `get_cpu_percent` | delta do `/proc/stat` |
| `read_data_dir` / `write_file` | persistência simples |

### `backends/zfs.py`

Todos os métodos `zfs`/`zpool` via `subprocess`:

| Função | Comando |
|---|---|
| `zpool_list` | `zpool list -H -o name,size,free,allocated,...` |
| `zpool_status` | `zpool status -P` |
| `zpool_create` | `zpool create ...` |
| `zpool_destroy` | `zpool destroy` |
| `zfs_list` | `zfs list -H -t all -o name,used,avail,...` |
| `zfs_snapshot` | `zfs snapshot` |
| `zfs_rollback` | `zfs rollback` |
| `zfs_set_property` | `zfs set` |
| `zfs_has_encryption` | `zfs get encryption` |

### `backends/config_store.py`

Persistência JSON atômica (`config.json` em `data_dir`) usada pelos módulos
para salvar `pool.dataset`, `interface`, `service`, `${tunable}`, `nginx`, etc.

---

## 12. Módulos de API (`modules/`)

| Classe | Instância | Registrado como |
|---|---|---|
| `CoreModule` | `core` | `core.*` (via `include`) |
| `SystemModule` | `system` | `system.*` (via `mapping`) |
| `StorageModule` | `storage` | `pool*`, `disk.*`, `boot.*`, `zpool.query`, `systemdataset.*` |
| `NetworkModule` | `network` | `interface.*`, `network.configuration.*`, `staticroute.*` |
| `ServiceModule` | `service` | `service.*` |
| `SharingModule` | `sharing` | `sharing.smb/nfs/s3/webdav.*`, `smb/nfs/s3.*`, `iscsi.*` |
| `AlertModule` | `alert` | `alert.*`, `alertservice.*`, `alertclasses.*` |
| `FilesystemModule` | `filesystem` | `filesystem.*`, `device.*` |
| `UserGroupModule` | `users` | `user.*`, `group.*`, `privilege.*` |
| `AppModule` | `app` | `app.*`, `docker.*`, `catalog.*`, `container.*` |
| `VmModule` | `vm` | `vm.*`, `vm.device.*`, `vmware.*` |
| `ReplicationModule` | `dataprotection` | `replication.*`, `cloudsync.*`, `cloud_backup.*`, `rsynctask.*`, `snapshottask.*` |
| `MiscModule` | `misc` | `mail/snmp/ssh/ftp/ups/reporting/api_key/...` |

---

## 13. Ciclo de vida do servidor

```
run.py
  └─ TrueNasApp()
       ├─ Config()            (config.json / env TRUENAS_CONFIG)
       ├─ AuthManager         (users.json)
       ├─ JobManager / SubscriptionManager / ConfigStore / ShellManager
       ├─ _register_modules() → 412 métodos
       └─ _register_auth_middleware()
  └─ app.run()
       ├─ WebSocket API em    ws://host:port/api/current
       ├─ WebSocket Shell em  ws://host:port:shell_port
       ├─ start_alert_checker (a cada 300s: temperatura/disco)
       ├─ signal handling (SIGINT/SIGTERM)
       └─ shutdown limpo
```

---

## 14. Decisões de compatibilidade

| Decisão | Motivo |
|---|---|
| `login_ex` retorna `auth_result` **direto** no `result` JSON-RPC | contrato real do TrueNAS; base da UI para SUCCESS/DENIED |
| `context` passado como kwarg nomeado (não `**context`) | handlers têm assinatura `(self, ..., context=None)`; evita `TypeError` com `auth_token` etc. |
| `errors="replace"` na decodificação de stdout | comandos em não-Linux (dev) emitem mensagens em outro charset |
| imports `pwd`/`grp`/`pty`/`fcntl`/`termios` opcionais | teste/desenvolvimento em Windows sem quebrar import |
| TTLs de token vindos do config | `token_ttl` (7 dias) vs `short_token_ttl` (5 min) |