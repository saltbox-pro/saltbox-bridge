# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv

# Copyright 2025 Anton Karmanov

# Licensed under the Apache License, Version 2.0.
# See LICENSE.txt file in the project root for license information.

# This file is a part of Salt.Box system.

ARG BASE_IMG='registry.altlinux.org/alt/alt:p11'

# hadolint global ignore=DL3006,DL3064,DL3015
FROM "$BASE_IMG" AS salt-base

RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes curl=8.23.0-alt1 \
                      glibc-pthread=2.38.0.223.f053ff-alt1.p11.1 \
                      lsb-release=2.0-alt5 \
                      openssl=3.5.7-alt2 \
                      procps=4.0.6-alt1
EOF

ARG SALT_VERSION='3008.5'
ARG SALT_TARBALL_SHA512='23430d299cb1a04341b2402ff13b98f6fa83077872cc736d108f0837f2d1964a87ea1b7bae3359cb5da941f1f22296697a5be482acc138069b75f44a29b13899'
ARG _SALT_TARBALL_FILENAME="salt-${SALT_VERSION}-onedir-linux-x86_64.tar.xz"
ARG _SALT_BASE_ONEDIR_URL="https://packages.broadcom.com/artifactory/saltproject-generic/onedir"
ARG _SALT_ONEDIR_URL="${_SALT_BASE_ONEDIR_URL}/${SALT_VERSION}/${_SALT_TARBALL_FILENAME}"
ARG SALT_PATH_PREFIX='/opt'

ENV SALT_PYTHON="${SALT_PATH_PREFIX}/salt/bin/python3"
ENV SALT_EXTRAS_DIR="${SALT_PATH_PREFIX}/salt/extras"

WORKDIR /root/cache
SHELL ["/bin/bash", "-eo", "pipefail", "-c"]

RUN \
  --mount=type=cache,target=/root/cache/,sharing=locked \
<<EOF
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
apt-get install --yes gettext=0.21-alt2 \
                      git=2.50.1-alt1 \
                      glibc-utils=2.38.0.223.f053ff-alt1.p11.1 \
                      openssh-clients=9.6p1-alt7 \
                      rsync=3.2.7-alt7 \
                      gnupg=1.4.23-alt6
EOF

#NOTE: To avoid error messag on cleanup keys
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


FROM salt-master-base AS uv
RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked,id=apt \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked,id=apt-lists \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update

apt-get install --yes uv=0.10.7-alt1
EOF


FROM uv AS extras
WORKDIR /srv/saltbox-bridge/
COPY saltbox_bridge/ /srv/saltbox-bridge/
ARG UV_CACHE_DIR=/root/.cache/uv/
RUN --mount=type=cache,target="$UV_CACHE_DIR",id=uv \
  uv pip install \
    --python="$SALT_PYTHON" \
    --target="$SALT_EXTRAS_DIR" \
    --no-sources \
    . \
  ;


FROM salt-master-base AS salt-master
COPY --from=extras "$SALT_EXTRAS_DIR" "$SALT_EXTRAS_DIR"


FROM uv AS salt-master-dev
ENV SALTBOX_BRIDGE_SRC_PATH=/mnt/saltbox-bridge/saltbox_bridge/
COPY saltbox_bridge/ "$SALTBOX_BRIDGE_SRC_PATH"

ENV SALTBOX_DEV_MODE=1
VOLUME /mnt/saltbox-bridge-messages/
ENV SALTBOX_BRIDGE_MESSAGES_SRC_PATH=/mnt/saltbox-bridge-messages/
RUN git config --global --add safe.directory '/mnt/*'


FROM salt-base AS salt-mock-minion
LABEL name='saltbox-salt-minion'

RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes fusioninventory-agent=2.6-alt3 \
                      less=633-alt1
EOF

RUN mkdir --parents /etc/salt/minion.d/
COPY --chmod=755 minion/minion_entrypoint.sh /usr/local/bin/

ENV SALT_MASTER=salt-master
ENV MINION_ID_PREFIX=mock-minion
ENV SALT_MOCK_MINION_LOG_LEVEL=warning
#NOTE: How often to rentry on master hostname lookup error (sec)
ENV SALT_MOCK_MINION_RETRY_DNS=30

ENTRYPOINT ["/usr/local/bin/minion_entrypoint.sh"]
CMD ["salt-minion"]
