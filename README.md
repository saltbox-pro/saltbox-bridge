# Salt.Box bridge

## Description
Bridge component is a set of additional SaltStack modules to connect Salt
master to Salt.Box.

Currently supported salt-master versions:
- 3006.9

## Manual installation
0. Get Redis root certificate with command inside `saltbox-compose`:
  ```bash
  sudo docker compose cp redis-salt:/etc/redis/certs/ca.crt ./redis-ca.crt
  ```
1. Copy `saltbox-bridge` files and the `redis-ca.crt` to Salt master you want to connect.
2. Put `*.py` files from [`engines/`](./engines/) to Salt engines dir e.g.
  `/srv/salt_extmod/engines/`. 
3. Put  `*.py` files from [`runners/`](./runners/) to Salt runner modules dir
   e.g. `/srv/salt_extmod/runners/`.
4. Install the [`saltbox_bridge`](./salt\_box\_bridge\_service/) module:
  ```bash
  sudo pip3 install `./saltbox_bridge/`
  ```
5. Put `redis-ca.crt` from the first step e.g. to `/etc/salt/ssl/`


Owner for copied files should be the same as `salt-master` process user
(usually `root`).

Now tune the config of master.
```yaml
# /etc/salt/master

## Unique master identifier in Salt.Box
## Latin letters, digits, underscore, minus and dot
salt_master_id: UNIQUE_NAME

## Where subdirs with bridge modules are
module_dirs:
  - /srv/salt_extmod/

## Accept pubkeys from minions. Turn off to manage manually.
auto_accept: true

## Special minion precense periodic event means the minion is online
presence_events: True

## Set real values
engines:
  - saltbox_delator:
  - saltbox_agent:
ext_pillar:
  - redis_pillar:

## Strictly recommended to cleanup historical data
schedule:
  saltbox_delator_cleanup:
    hours: 3
    function: saltbox_delator.cleanup_expired_jobs
    kwargs:
      # Age of jobs to delete (sec)
      expire: 604800
      redis_host: redis-salt
```

Put `saltbox.conf` file to `/etc/salt/`:
```
# /etc/salt/saltbox.conf

# Redis conf:

## REDIS_HOST is host with deployed saltbox-compose
REDIS_HOST="REDIS_HOST"
## REDIS_USERNAME is REDIS_SALT_USERNAME from saltbox-compose `.env` file
REDIS_USERNAME="REDIS_USERNAME"
## REDIS_PASSWORD is in `secrets/redis_salt_password`
REDIS_PASSWORD="REDIS_PASSWORD"
REDIS_SSL_USE=True
## Where the cert had been saved before
REDIS_SSL_CA_CERTS="/etc/salt/ssl/redis-ca.crt"

# Salt.box bridge conf:

# Time to live for job returns and grains (sec)
EXPIRE=604800
```

Use `./make_master_id.sh` helper script to create id with hostname and timestamp
and save it to separate file __instead__ of specifying `salt_master_id` in the
main config manually.
