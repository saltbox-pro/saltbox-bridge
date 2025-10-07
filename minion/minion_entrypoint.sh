#! /bin/sh
set -e

trap '[ $? -eq 0 ] && exit 0 || echo "ERROR on $0 line ${LINENO}"' EXIT

id_conf='/etc/salt/minion.d/id.conf'

rand() {
  head -c 64 /dev/urandom | md5sum | head -c 12
}

if [ ! -f "$id_conf" ]; then
  minion_id="${MINION_ID_PREFIX}-$(rand)"
  echo "id: ${minion_id}" > "$id_conf"
fi

cat << EOF > /etc/salt/minion
master: '${SALT_MASTER}'
log_level: '${SALT_MOCK_MINION_LOG_LEVEL}'
master_tries: -1  # Prevents exception on unanswered master IP
retry_dns: ${SALT_MOCK_MINION_RETRY_DNS}
EOF

exec "$@"
