#! /bin/sh
# shellcheck disable=SC2016
#
set -eu
trap '[ $? -eq 0 ] && exit 0 || echo "ERROR on $0 line ${LINENO}"' EXIT


error() {
  >&2 echo "$1"
  exit 1
}

# Starting from 3008.5 Saltstack uses symlinks like master.pub -> MASTER_ID.pub
migrate_keypair() {(
  keydir="$1"
  pub_path="${keydir}/master.pub"
  pem_path="${keydir}/master.pem"
  if [ ! -f "$pub_path" ] || [ ! -f "$pem_path" ]; then
    echo "No master keypair to migrate"
    return
  fi
  pub_resolved=$(realpath -e "$pub_path")
  pem_resolved=$(realpath -e "$pem_path")
  cp "$pub_resolved" "${keydir}/${SALT_MASTER_ID}.pub"
  echo "Migrated: $pub_resolved -> $pub_resolved"
  cp "$pem_resolved" "${keydir}/${SALT_MASTER_ID}.pem"
  echo "Migrated: $pem_resolved -> $pem_resolved"
)}

if [ "$SALTBOX_DEV_MODE" = 1 ]; then
  chown -R "$(id -u):$(id -g)" "$SALTBOX_BRIDGE_SRC_PATH"

  uv --no-progress pip install --python="$SALT_PYTHON" --no-build-isolation --editable "$SALTBOX_BRIDGE_SRC_PATH"
  uv --no-progress pip install --python="$SALT_PYTHON" --no-build-isolation --editable "$SALTBOX_BRIDGE_MESSAGES_SRC_PATH"
fi

REDIS_PASSWORD="$(cat "$REDIS_PASSWORD_FILE")"
export REDIS_PASSWORD

mkdir --parents /etc/salt/master.d/
envsubst '$SALT_MASTER_ID,$SALT_MASTER_LOG_LEVEL' \
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

migrate_keypair '/etc/salt/pki/master'

echo "${0} args to eval: ${*}"
exec "$@"
