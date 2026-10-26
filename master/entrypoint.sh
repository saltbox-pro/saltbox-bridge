#! /bin/sh
# shellcheck disable=SC2016
#
set -e
trap '[ $? -eq 0 ] && exit 0 || echo "ERROR on $0 line ${LINENO}"' EXIT


error() {
  >&2 echo "$1"
  exit 1
}

if [ "$SALTBOX_DEV_MODE" = 1 ]; then
  # Update install
  chown -R "$(id -u):$(id -g)" "$SALTBOX_BRIDGE_SRC_PATH"

  # `salt-pip` needs --target='' for editable, but uv does not
  python3 -m uv --no-progress pip install --no-build-isolation --editable "$SALTBOX_BRIDGE_SRC_PATH"
  python3 -m uv --no-progress pip install --no-build-isolation --editable "$SALTBOX_BRIDGE_MESSAGES_SRC_PATH"
fi

[ -z "$REDIS_USERNAME" ] && error 'Missing REDIS_USERNAME value'
[ -z "$REDIS_PASSWORD_FILE" ] && error 'Missing REDIS_PASSWORD_FILE value'

REDIS_PASSWORD="$(cat "$REDIS_PASSWORD_FILE")"
export REDIS_PASSWORD

mkdir --parents /etc/salt/master.d/
envsubst '$SALT_MASTER_LOG_LEVEL' \
  < /root/templates/master.conf.tpl \
  > /etc/salt/master.d/master.conf

envsubst '$SALT_MINION_LOG_LEVEL' \
  < /root/templates/minion.conf.tpl \
  > /etc/salt/minion

envsubst '$REDIS_USERNAME $REDIS_PASSWORD' \
  < /root/templates/saltbox.conf.tpl \
  > /etc/salt/saltbox

if [ ! -f /srv/roster/roster ]; then
  mkdir --parents /srv/roster/
  cp /srv/salt_master_local/files/roster /srv/roster/roster
fi

echo "${0} args to eval: ${*}"
exec "$@"
