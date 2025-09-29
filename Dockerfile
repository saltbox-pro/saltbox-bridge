# check=skip=SecretsUsedInArgOrEnv

# Copyright 2025 Anton Karmanov

# Licensed under the Apache License, Version 2.0.
# See LICENSE.txt file in the project root for license information.

# This file is a part of Salt.Box system.

ARG BASE_IMG='registry.altlinux.org/alt/alt:p11'

FROM "$BASE_IMG" AS salt-base
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes curl glibc-pthread lsb-release openssl procps
EOF
ARG SALT_VERSION='3006.9'
ARG SALT_TARBALL_SHA512='26cc4a5377c643ba7a20250040e5d95336398c1060d8102aa016269f360027a46416f2b0f6f2343dc928bbcdb712f00f6618ce6572ba88643b1a32487ae0f03b'
ARG _SALT_TARBALL_FILENAME="salt-${SALT_VERSION}-onedir-linux-x86_64.tar.xz"
ARG _SALT_ONEDIR_URL="https://packages.broadcom.com/artifactory/saltproject-generic/onedir/$SALT_VERSION/${_SALT_TARBALL_FILENAME}"
ARG SALT_PATH_PREFIX='/opt'
RUN \
  --mount=type=cache,target=/root/cache/,sharing=locked \
<<EOF
set -e
cd /root/cache/
if [ ! -f "$_SALT_TARBALL_FILENAME" ];
  then curl -LOf "$_SALT_ONEDIR_URL";
else
  2>&1 echo "Using cached ${_SALT_TARBALL_FILENAME}"
fi
echo "${SALT_TARBALL_SHA512} ${_SALT_TARBALL_FILENAME}" | sha512sum --check
tar -xavf "${_SALT_TARBALL_FILENAME}" --directory="${SALT_PATH_PREFIX}/"
find "${SALT_PATH_PREFIX}/salt/" -maxdepth 1 -type f -executable -exec ln -s {} /usr/local/bin/ \;
ln -s "${SALT_PATH_PREFIX}/salt/bin/python3" /usr/local/bin/
EOF

FROM salt-base AS salt-master-base
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes gettext git glibc-utils openssh-clients rsync
EOF
ENV PIP_CMD=salt-pip
# To avoid error messag on cleanup keys
RUN mkdir --parents /var/cache/salt/master/ /var/lib/saltbox-bridge/
COPY --chmod=755 master/entrypoint.sh /usr/local/bin/
COPY master/config/master_id.conf /etc/salt/master.d/
COPY master/templates/ /root/templates/
COPY master/salt_master_local/ /srv/salt_master_local/
COPY master/salt_local/ /srv/salt_local/
COPY engines /srv/salt_extmod/engines/
COPY runners /srv/salt_extmod/runners/
COPY pillar /srv/salt_extmod/pillar/
ENV REDIS_USERNAME=redis
ENV REDIS_PASSWORD_FILE=
ENV SALT_MASTER_LOG_LEVEL=warning
ENV SALT_MINION_LOG_LEVEL=warning
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/usr/local/bin/salt-master"]
EXPOSE 4505 4506


FROM salt-master-base AS salt-master
LABEL name='saltbox-salt-master'
LABEL version='4.3'
LABEL release='1'
RUN \
  --mount=type=bind,target=/mnt/,readwrite \
  --mount=type=cache,target=/root/.cache/pip/ \
  "$PIP_CMD" install /mnt/saltbox_bridge/


FROM salt-master-base AS salt-master-dev
LABEL name='saltbox-salt-master-dev'
LABEL version='3.1'
LABEL release='1'
ENV SALTBOX_BRIDGE_SRC_PATH=/root/saltbox_bridge/
COPY saltbox_bridge/ "$SALTBOX_BRIDGE_SRC_PATH"
RUN --mount=type=cache,target=/root/.cache/pip/ \
  "$PIP_CMD" install uv

ENV SALTBOX_DEV_MODE=1
# Respective repository should be mounted
VOLUME /mnt/saltbox-bridge-messages/
ENV SALTBOX_BRIDGE_MESSAGES_SRC_PATH=/mnt/saltbox-bridge-messages/


FROM salt-base AS salt-mock-minion
LABEL name='saltbox-salt-minion'
LABEL version='1.1'
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes fusioninventory-agent less
EOF
RUN mkdir --parents /etc/salt/minion.d/
COPY --chmod=755 minion/minion_entrypoint.sh /usr/local/bin/
COPY minion/templates/ /root/templates/
ENV SALT_MASTER=salt-master
ENV MINION_ID_PREFIX=mock-minion
ENV SALT_MOCK_MINION_LOG_LEVEL=warning
ENV MINION_HARDWARE_METRICS_EXTRACTION_DELAY=20
# NOTE: How often to rentry on master hostname lookup error (sec)
ENV SALT_MOCK_MINION_RETRY_DNS=30
ENTRYPOINT ["/usr/local/bin/minion_entrypoint.sh"]
CMD ["salt-minion"]
