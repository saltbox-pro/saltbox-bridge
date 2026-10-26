# syntax=docker/dockerfile:1
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
ARG SALT_VERSION='3008.3'
ARG SALT_TARBALL_SHA512='68cead550cbdb606cbe1204c6ac7ca4428c72eb8bc18fc7d7d9c16c51db26a1b3c1a237cf9c1ad63d8d4528a794afd6e2a31738ae49d075e279bf1044d54f753'
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
apt-get install --yes gettext git glibc-utils openssh-clients rsync gnupg
EOF
ENV PIP_CMD=salt-pip
# To avoid error messag on cleanup keys
RUN mkdir --parents /var/cache/salt/master/ /var/lib/saltbox-bridge/
COPY --chmod=755 master/entrypoint.sh /usr/local/bin/
COPY --chmod=644 master/config/master_id.conf /etc/salt/master.d/
COPY --chmod=u=rwX,go=rX master/templates/ /root/templates/
COPY --chmod=u=rwX,go=rX master/salt_master_local/ /srv/salt_master_local/
COPY --chmod=u=rwX,go=rX master/salt_local/ /srv/salt_local/
COPY --chmod=u=rwX,go=rX engines /srv/salt_extmod/engines/
COPY --chmod=u=rwX,go=rX runners /srv/salt_extmod/runners/
COPY --chmod=u=rwX,go=rX pillar /srv/salt_extmod/pillar/
ENV REDIS_USERNAME=redis
ENV REDIS_PASSWORD_FILE=
ENV SALT_MASTER_LOG_LEVEL=warning
ENV SALT_MINION_LOG_LEVEL=warning
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/usr/local/bin/salt-master"]
EXPOSE 4505 4506


FROM salt-master-base AS salt-master
LABEL name='saltbox-salt-master'
LABEL version='4.5'
LABEL release='1'
RUN \
  --mount=type=bind,target=/mnt/,readwrite \
  --mount=type=cache,target=/root/.cache/pip/ \
  "$PIP_CMD" install /mnt/saltbox_bridge/


FROM salt-master-base AS salt-master-dev
LABEL name='saltbox-salt-master-dev'
LABEL version='3.3'
LABEL release='1'
ENV SALTBOX_BRIDGE_SRC_PATH=/root/saltbox_bridge/
COPY saltbox_bridge/ "$SALTBOX_BRIDGE_SRC_PATH"
RUN --mount=type=cache,target=/root/.cache/pip/ \
  "$PIP_CMD" install uv

ENV SALTBOX_DEV_MODE=1
# Respective repository should be mounted
VOLUME /mnt/saltbox-bridge-messages/
ENV SALTBOX_BRIDGE_MESSAGES_SRC_PATH=/mnt/saltbox-bridge-messages/
RUN git config --global --add safe.directory '/mnt/*'


FROM salt-base AS salt-mock-minion
LABEL name='saltbox-salt-minion'
LABEL version='1.2'
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
ENV SALT_MASTER=salt-master
ENV MINION_ID_PREFIX=mock-minion
ENV SALT_MOCK_MINION_LOG_LEVEL=warning
# How often to rentry on master hostname lookup error (sec)
ENV SALT_MOCK_MINION_RETRY_DNS=30
ENTRYPOINT ["/usr/local/bin/minion_entrypoint.sh"]
CMD ["salt-minion"]
