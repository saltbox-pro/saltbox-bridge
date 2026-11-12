#! /bin/sh
# shellcheck disable=SC2016
#
set -eu
trap '[ $? -eq 0 ] && exit 0 || echo "ERROR on $0 line ${LINENO}"' EXIT


error() {
  >&2 echo "$1"
  exit 1
}

_migrate_key() {(
  path="$1"
  dir="$(dirname "$path")"
  suf="${path##*.}"
  resolved=$(realpath -e "$path")
  tgt="${dir}/${SALT_MASTER_ID}.${suf}"
  if [ "$resolved" = "$tgt" ]; then
    echo "Already OK: $tgt"
    return
  elif [ "$resolved" -ef "$tgt" ]; then
    echo "Files are same: ${resolved} == ${tgt}"
    return
  fi
  cp "$resolved" "$tgt"
  ln -srf "$resolved" "$tgt"
  echo "Migrated: ${resolved} -> ${tgt}"
)}

# Starting from 3008.5 Saltstack uses symlinks like master.pub -> MASTER_ID.pub.
# Migration resolves $SALT_MASTER_ID changin and so on.
migrate_keypair() {(
  keydir="$1"
  pub_path="${keydir}/master.pub"
  pem_path="${keydir}/master.pem"
  if [ ! -f "$pub_path" ] || [ ! -f "$pem_path" ]; then
    echo "No Master keypair to migrate"
    return
  fi
  _migrate_key "$pub_path"
  _migrate_key "$pem_path"
)}

dev_mode="${SALTBOX_DEV_MODE:-0}"
if [ "$dev_mode" = 1 ]; then
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
