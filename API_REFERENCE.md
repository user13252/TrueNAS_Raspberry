# API Reference — TrueNAS Scale RPi

Referência completa das **412 chamadas RPC** registradas no servidor JSON-RPC.

- **Transporte:** WebSocket em `ws://<host>/api/current`
- **Protocolo:** JSON-RPC 2.0
- **Formato do request:**
  ```json
  {"jsonrpc": "2.0", "id": 1, "method": "service.query", "params": []}
  ```
- **Formato do response (sucesso):**
  ```json
  {"jsonrpc": "2.0", "id": 1, "result": { ... }}
  ```
- **Formato do response (erro):**
  ```json
  {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found", "data": {"method": "..."}}}
  ```

## Códigos de erro

| Código | Significado |
|---|---|
| `-32601` | Método não encontrado |
| `-32602` | Parâmetros inválidos |
| `-32000` | Erro interno / exceção no handler |
| `-32001` | Sem permissão (não autenticado ou RBAC) |
| `-32002` | Não autenticado |

## Autenticação

Antes de qualquer chamada autenticada, o cliente deve executar `auth.login_ex`:

```json
{
  "jsonrpc": "2.0", "id": 1,
  "method": "auth.login_ex",
  "params": [[{"mechanism": "PASSWORD_PLAIN", "username": "admin", "password": "admin"}]]
}
```

Resposta bem-sucedida:

```json
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "auth_result": "SUCCESS",
    "user_info": {"username": "admin", "privilege": {"web_shell": true}, "roles": ["FULL_ADMIN"]},
    "reconnect_token": "<hex>"
  }
}
```

> `auth_result` também pode ser `"OTP_NEEDED"` (2FA) ou `"DENIED"`.

Métodos livres de autenticação: `auth.login_ex`, `auth.login_ex_continue`, `core.set_options`.

---

## Namespaces

| Namespace | Descrição |
|---|---|
| `core.*` | Núcleo: jobs, subscribe, opções |
| `auth.*` | Autenticação e sessões |
| `system.*` | Sistema, tunables, NTP, init scripts |
| `pool.*` | Pools ZFS |
| `pool.dataset.*` | Datasets ZFS |
| `pool.snapshot.*` | Snapshots ZFS |
| `pool.snapshottask.*` | Tarefas periódicas de snapshot |
| `pool.scrub.*` / `pool.resilver.*` | Scrub / resilver |
| `disk.*` | Discos físicos |
| `boot.*` | Disco/boot-pool de boot |
| `zpool.query` | Informação do zpool |
| `interface.*` / `network.*` / `staticroute.*` | Rede |
| `service.*` | Serviços do sistema |
| `sharing.smb/nfs/s3/webdav.*`, `smb/nfs/s3.*` | Compartilhamentos |
| `iscsi.*` | iSCSI |
| `alert.*`, `alertservice.*`, `alertclasses.*` | Alertas |
| `filesystem.*` | Operações com arquivos |
| `user.*`, `group.*`, `privilege.*` | Identidade & RBAC |
| `app.*`, `docker.*`, `catalog.*`, `container.*` | Apps/containers |
| `vm.*`, `vm.device.*`, `vmware.*` | Virtualização |
| `replication.*`, `cloudsync.*`, `cloud_backup.*`, `rsynctask.*`, `snapshottask.*` | Proteção de dados |
| `reporting.*` | Métricas e grafos |
| `mail.*`, `snmp.*`, `ssh.*`, `ftp.*`, `ups.*` | Serviços auxiliares |
| `audit.*`, `api_key.*`, `keychaincredential.*` | Segurança/observabilidade |
| `certificate.*`, `acme.dns.authenticator.*`, `cloud_credential.*` | Certificados/credenciais |
| `failover.*`, `directoryservices.*`, `ldap.*`, `kerberos.*` | HA/domínio |
| `truenas.*`, `truecommand.*`, `tn_connect.*`, `support.*` | TrueNAS |
| `systemdataset.*`, `boot_id`, `device.get_info`, `kmip.*`, `enclosure2.*` | Infraestrutura |

---

## core.* — Núcleo

| Método | Params | Retorno |
|---|---|---|
| `core.set_options` | `options: dict` | `null` |
| `core.get_jobs` | `filters?, options?` | `list[Jobs]` |
| `core.job_abort` | `id: int` | `null` |
| `core.bulk` | `method, list[args]` | `list[Result]` |
| `core.download` | `url, filename, buffer` | `str` (id do job) |
| `core.resize_shell` | `id: int, row: int, col: int` | `null` |
| `core.subscribe` | `list[str] names` | `str` (sub_id) |
| `core.unsubscribe` | `list[str] sub_ids` | `null` |

## auth.* — Autenticação

| Método | Params | Retorno |
|---|---|---|
| `auth.login_ex` | `list[mechanism]` | `{auth_result, user_info, reconnect_token}` |
| `auth.login_ex_continue` | `token: str` | `{auth_result}` |
| `auth.me` | `[]` | `{username, roles, ...}` |
| `auth.generate_token` | `{expiry?, attrs?}` | `{token}` |
| `auth.sessions` | `[]` | `list[session]` |
| `auth.logout` | `[]` | `null` |
| `auth.terminate_session` | `id: str` | `null` |
| `auth.terminate_other_sessions` | `[]` | `null` |
| `auth.set_attribute` | `name, value` | `null` |
| `auth.twofactor.config` | `[]` | `{...}` |

## system.* — Sistema

| Método | Params | Retorno |
|---|---|---|
| `system.info` | `[]` | `{hostname, version, uptime, memory, cpu, ...}` |
| `system.product_type` | `[]` | `"SCALE"` |
| `system.is_freebsd` | `[]` | `false` |
| `system.is_enterprise` | `[]` | `false` |
| `system.is_ix_hardware` | `[]` | `false` |
| `system.hostname` | `[]` | `str` |
| `system.reboot` | `{delay?: int}` | `null` |
| `system.shutdown` | `{delay?: int}` | `null` |
| `system.reboot_info` | `[]` | `{delay, message}` |
| `system.config_reset` | `[]` | `null` |
| `system.general.config` / `.update` | `config?` / `config` | `{...}` |
| `system.advanced.config` / `.update` | — | `{...}` |
| `system.security.config` / `.update` | — | `{...}` |
| `system.update.check` / `.update` | — | `{...}` |
| `system.ntpserver.*` | CRUD | — |
| `system.tunable.*` | CRUD | — |
| `system.initshutdownscript.*` | CRUD | — |

## pool.* — Pools ZFS

| Método | Params | Retorno |
|---|---|---|
| `pool.query` | `filters?, options?` | `list[Pool]` |
| `pool.create` | `pool: dict` | `Pool` |
| `pool.update` | `id, pool` | `Pool` |
| `pool.delete` | *(alias)* | — |
| `pool.export` | `name, {cascade, destroy}` | `null` |
| `pool.import_pool` | `{name, scope, guid?, cache?, ...}` | `Pool` |
| `pool.import_disk` | `pool, {source, dest, passphrase}` | `null` |
| `pool.get_disks` | `[]` | `list[str]` |
| `pool.get_encrypted_disk_keys` | `[]` | `str` |
| `pool.attach` | `pool, {new_disk, passphrase}` | `null` |
| `pool.detach` | `pool, {disk}` | `null` |
| `pool.replace` | `pool, {label, new_disk}` | `null` |
| `pool.online` / `pool.offline` | `pool, disk` | `null` |
| `pool.expand` | `pool` | `null` |
| `pool.upgrade` | `pool` | `null` |
| `pool.scan` | `pool` | `null` |
| `pool.resilver.config` / `.update` | — | `{...}` |

## pool.dataset.* — Datasets ZFS

| Método | Params | Retorno |
|---|---|---|
| `pool.dataset.query` | `filters?, options?` | `list[Dataset]` |
| `pool.dataset.create` | `{name, pool?, type?, ...}` | `Dataset` |
| `pool.dataset.update` | `name, data` | `Dataset` |
| `pool.dataset.delete` | `name, {recursive?}` | `null` |
| `pool.dataset.child` | `id` | `Dataset` |
| `pool.dataset.process` | `{name, type}` | `list[str]` |
| `pool.dataset.rollback` | `name, snapshot` | `str` |
| `pool.dataset.promote` | `name` | `null` |
| `pool.dataset.set_quota` | `name, {volsize?, dataset_quota?}` | `null` |
| `pool.dataset.inherit_quota` | `name, {quota_type}` | `null` |
| `pool.dataset.permissions` | `name, {recursive}` | `{...}` |

## pool.snapshot.* — Snapshots ZFS

| Método | Params |
|---|---|
| `pool.snapshot.query` | `filters?, options?` |
| `pool.snapshot.create` | `{dataset, name, recursive?, vmware_sync?, ...}` |
| `pool.snapshot.delete` | `name, {recursive}` |
| `pool.snapshot.rollback` | `name` |
| `pool.snapshot.clone` | `{snapshot, dataset_dst}` |
| `pool.snapshot.hold` | `name, tag` |
| `pool.snapshot.release` | `name, tag` |

## pool.snapshottask.* / pool.scrub.* — Tarefas ZFS

| Método | Descrição |
|---|---|
| `pool.snapshottask.query/create/update/delete` | CRUD de tarefas periódicas |
| `pool.snapshottask.retention_validate` | valida retenção |
| `pool.scrub.query/create/update/delete/run` | Scrubs |

## disk.* / boot.* / zpool

| Método | Descrição |
|---|---|
| `disk.query` | lista discos (`lsblk`) |
| `disk.temperature_agg` | temperatura agregada |
| `disk.update` | atualiza atributos |
| `boot.query` | configuração do boot |
| `boot.pool_query` | estado do boot pool |
| `boot.attach/detach/replace/online/offline` | gestão do boot pool |
| `zpool.query` | info compacta do zpool |

## interface.* / network.* — Rede

| Método | Params | Retorno |
|---|---|---|
| `interface.query` | `filters?, options?` | `list[Interface]` |
| `interface.create` | `interface: dict` | `Interface` |
| `interface.update` | `id, data` | `Interface` |
| `interface.delete` | `id` | `null` |
| `interface.commit` | `{rollback?: bool}` | `null` |
| `interface.checkin` | `[]` | `str` |
| `interface.rollback` | `[]` | `null` |
| `interface.defaults` | `[]` | `{...}` |
| `interface.has_carp` | `interface: str` | `bool` |
| `network.configuration.config` | `[]` | `{nameservers, ipv4gateway, ...}` |
| `network.configuration.update` | `config` | `{...}` |
| `network.configuration.summary` | `[]` | `{...}` |
| `staticroute.query/create/update/delete` | CRUD | — |

## service.* — Serviços

| Método | Params | Retorno |
|---|---|---|
| `service.query` | `filters?, options?` | `list[Service]` |
| `service.update` | `service, {enable, state}` | `Service` |
| `service.control` | `service, {on_off|start|stop|restart}` | `bool` |

Serviços conhecidos (19): `cifs`, `ftp`, `iscsitarget`, `nfs`, `smartd`, `sshd`, `domaincontroller`, `lldp`, `snmp`, `rsync`, `s3`, `s3_update`, `webdav`, `webshell`, `netsmb`, `ldap`, `dynamicdns`, `glusterd`, `kubernetes`.

## Compartilhamentos

### sharing.smb.* / smb.*
| Método | Params |
|---|---|
| `sharing.smb.query/create/update/delete` | CRUD |
| `sharing.smb.config` / `config_update` | config global |
| `sharing.smb.share_precheck` / `precheck` | validação de share |
| `smb.query/create/update/delete/config/config_update` | aliases diretas |

### sharing.nfs.* / nfs.*
| Método | Params |
|---|---|
| `sharing.nfs.query/create/update/delete` | CRUD |
| `sharing.nfs.config` / `config_update` | config global |

### sharing.s3.* / s3.*
| Método | Params |
|---|---|
| `sharing.s3.query/create/update/delete` | CRUD buckets |
| `sharing.s3.config` / `config_update` | config MinIO |

### sharing.webdav.*, iscsi.*
- `sharing.webdav.query/create/update/delete`
- `iscsi.global.config/update`, `iscsi.portal.*`, `iscsi.initiator.*`, `iscsi.auth.*`, `iscsi.extent.*`, `iscsi.target.*`, `iscsi.targetextent.*`, `iscsi.session.query`

## alert.* / alertservice.* / alertclasses.*

| Método | Descrição |
|---|---|
| `alert.list` | lista alertas ativos |
| `alert.list_categories` | categorias com exclusões |
| `alert.dismiss` / `alert.restore` | `id>list` |
| `alert.policy` / `policy_update` | política de alertas |
| `alertservice.query/create/update/delete/test` | serviços de notificação |
| `alertclasses.config` / `update` | classes e severidades |

## filesystem.* — Arquivos

| Método | Params | Retorno |
|---|---|---|
| `filesystem.listdir` | `path, {limit?, offset?}` | `list[Entry]` |
| `filesystem.stat` | `path` | `{...}` |
| `filesystem.statfs` | `path` | `{...}` |
| `filesystem.getacl` / `setacl` | `path, acl?` | `{...}` |
| `filesystem.setperm` | `path, {mode, ...}` | `null` |
| `filesystem.mkdir` | `path, mode?` | `null` |
| `filesystem.unlink` | `path, options?` | `null` |
| `filesystem.rename` | `{path, new_name, ...}` | `null` |
| `filesystem.put` | `path, data, mode?` | `null` |
| `filesystem.file_tail_follow` | `path, offset` | `str?` |
| `filesystem.acltemplate.query` | `[]` | `list[template]` |
| `filesystem.acl_is_trivial` | `path` | `bool` |
| `device.get_info` | `[]` | informações de GPU/hardware |

## user.* / group.* / privilege.*

| Método | Params | Retorno |
|---|---|---|
| `user.query` | `filters?, options?` | `list[User]` |
| `user.create` | `user: dict` | `User` |
| `user.update` | `id, data` | `User` |
| `user.delete` | `id, {delete_group}` | `null` |
| `user.get_user_obj` | `username` | `User` |
| `user.set_password` | `{username, new_password}` | `null` |
| `user.next_uid` | `[]` | `int` |
| `user.has_local_administrator_set` | `[]` | `bool` |
| `user.setup_local_administrator` | `{username, password}` | `null` |
| `group.query/create/update/delete` | CRUD | `Group` |
| `group.next_gid` | `[]` | `int` |
| `privilege.query/create/update/delete` | CRUD | — |
| `privilege.roles` | `[]` | `list[str]` |

## app.* / docker.* / container.* / catalog.*

| Método | Descrição |
|---|---|
| `app.query/available/app.available_apps` | apps instalados/disponíveis |
| `app.create/update/delete/start/stop` | gestão de apps |
| `app.categories` | categorias de apps |
| `docker.config` / `update` / `state` | config e estado do Docker |
| `container.query/image.query/metrics/stats/prune` | containers e imagens |
| `catalog.query/create/update/delete/sync/sync_all/train` | catálogos |

## vm.* / vm.device.* / vmware.*

| Método | Params |
|---|---|
| `vm.query/create/update/delete` | CRUD |
| `vm.start/stop/restart/reset/poweroff` | controle de power |
| `vm.resume` | resume |
| `vm.display_devices` | dispositivos DFU |
| `vm.display_web_uri` | URI para novo display |
| `vm.port_wizard` / `vm.vnc_port_wizard` | escolha de portas |
| `vm.virtualization_details` | `{supported}` |
| `vm.device.query/create/update/delete` | dispositivos |
| `vm.device.pci_passthrough_choices` / `usb_passthrough_choices` | opções |
| `vmware.query/create/update/delete` | integração VMware |
| `vmware.match_products` / `get_datastores` | assistência |

## Proteção de dados

| Método | Descrição |
|---|---|
| `replication.query/create/update/delete/run/restore` | replicalção ZFS |
| `replication.list_datasets` / `list_naming_schemas` | auxiliares |
| `cloudsync.query/create/update/delete/run` | cloud sync |
| `cloudsync.providers` / `buckets` / `ls` | assistência |
| `cloud_backup.query/create/update/delete/run/restore` | cloud backup |
| `cloud_backup.list_snapshots` | assistência |
| `rsynctask.query/create/update/delete/run` | tarefas rsync |
| `snapshottask.query/create/update/delete/run` | snapshots periódicos |

## reporting.*

| Método | Params | Retorno |
|---|---|---|
| `reporting.graphs` | `[]` | `list[Graph]` |
| `reporting.get_data` | `{start, end, reports}` | `{...}` |
| `reporting.realtime` | `[]` | `{cpu, memory, ...}` (0.5s) |

## Outros (configs + serviços)

| Método | Params |
|---|---|
| `mail.config/update/send` | email |
| `snmp.config/update` | SNMP |
| `ssh.config/update` | SSH |
| `ftp.config/update` | FTP |
| `ups.config/update` | UPS |
| `audit.config/update/query/export/download_report` | auditoria |
| `api_key.query/create/update/delete` | API keys |
| `keychaincredential.query/create/update/delete` | credenciais |
| `keychaincredential.generate_ssh_key_pair` | par de chaves |
| `certificate.query` / `certificate.ca_query` / `certificate.certificateauthority.query` | certificados |
| `acme.dns.authenticator.query` | autenticadores DNS |
| `cloud_credential.query/create/update/delete/verify` | credenciais cloud |
| `failover.config/status/disabled.reasons/reboot.info` | HA |
| `directoryservices.status/cache_refresh` | AD/LDAP |
| `ldap.config/update` | LDAP |
| `kerberos.config` / `kerberos.realm.query` / `kerberos.keytab.query` | Kerberos |
| `systemdataset.config/update` | system dataset |
| `boot_id` | `str` |
| `kmip.config` | KMIP |
| `enclosure2.query` | sensores/encubertura |
| `tn_connect.config` | TrueNAS Connect |
| `truecommand.config` | TrueCommand |
| `truenas.eula_accepted/set_eula_accepted/is_production` | EULA/produção |
| `support.query` | suporte |

---

## Subscriptions (eventos push)

Uma vez que `core.subscribe` retorna um `sub_id`, o servidor emite eventos
**não solicitados** no mesmo WebSocket:

```json
{
  "jsonrpc": "2.0",
  "method": "collection_update",
  "params": {"msg": "changed", "cleared": false, "collection": "service.query", "sub_id": "<uuid>"}
}
```

Suportado para `service.query`, `alert.list`, `core.get_jobs`, `app.query`,
`vm.query`, `reporting.realtime` e qualquer query registrada via
`subscriptions.py`.