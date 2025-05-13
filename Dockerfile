# Copyright 2025 Anton Karmanov

# Licensed under the Apache License, Version 2.0.
# See LICENSE.txt file in the project root for license information.

# This file is a part of Salt.Box system.


ARG ALPINE_VERSION='3.20'
# Current 3.10 == 3.10.17 seems broken for now 2025-04-09
ARG PYTHON_VERSION='3.10.16'

# TODO Altlinux branch US49_altlinux
FROM python:${PYTHON_VERSION}-alpine${ALPINE_VERSION} AS salt-base
ARG SALT_VERSION='3006.9'
ARG BUILD_DEPS="gcc g++ autoconf make libffi-dev libgit2-dev"
# Base dependencies
RUN \
  --mount=type=cache,target=/var/cache/apk/,sharing=locked \
  apk add binutils libgit2 libffi openssl-dev
# pygit2 depends on specific libgit2 version
RUN \
  --mount=type=cache,target=/var/cache/apk/,sharing=locked \
  --mount=type=cache,target=/root/.cache/pip/ \
<<EOF
set -e
apk add $BUILD_DEPS
echo 'cython<3' > /root/constraint.txt
PIP_CONSTRAINT=/root/constraint.txt USE_STATIC_REQUIREMENTS=1 \
  pip3 install --no-build-isolation "salt==${SALT_VERSION}"
pip3 install 'pygit2==1.13.1'
rm /root/constraint.txt
apk del $BUILD_DEPS
EOF


FROM salt-base AS salt-master-base
RUN --mount=type=cache,target=/var/cache/apk/,sharing=locked \
  apk add gettext-envsubst openssh-keygen gnupg
ARG SUPERVISORD_VERSION='4.2.5'
RUN \
  --mount=type=bind,target=/mnt/,readwrite \
  --mount=type=cache,target=/root/.cache/pip/ \
  pip3 install "supervisor==${SUPERVISORD_VERSION}"
# To avoid error messag on cleanup keys
RUN mkdir --parents /var/cache/salt/master/
RUN mkdir --parents /var/lib/saltbox-bridge/
COPY --chmod=755 master/entrypoint.sh /usr/local/bin/
COPY master/supervisord.conf /etc/
COPY master/config/master_id.conf /etc/salt/master.d/
COPY master/templates/ /root/templates/
COPY master/states/ /srv/salt_local/
COPY engines /srv/salt_extmod/engines/
COPY runners /srv/salt_extmod/runners/
COPY pillar /srv/salt_extmod/pillar/
ENV REDIS_USERNAME=redis
ENV REDIS_PASSWORD_FILE=
ENV SALT_MASTER_LOG_LEVEL=warning
ENV SALT_MINION_LOG_LEVEL=warning
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/usr/local/bin/supervisord", "--config", "/etc/supervisord.conf"]
EXPOSE 4505 4506 8000


FROM salt-master-base AS salt-master
LABEL name='saltbox-salt-master'
LABEL version='3.0'
LABEL release='1'
RUN \
  --mount=type=bind,target=/mnt/,readwrite \
  --mount=type=cache,target=/root/.cache/pip/ \
  pip3 install /mnt/saltbox_bridge/



FROM salt-master-base AS salt-master-dev
LABEL name='saltbox-salt-master-dev'
LABEL version='2.0'
LABEL release='1'
ENV SALTBOX_BRIDGE_SRC_PATH=/root/saltbox_bridge/
ENV SALT_BOX_DEV_MODE=1
COPY saltbox_bridge/ $SALTBOX_BRIDGE_SRC_PATH
RUN \
  --mount=type=cache,target=/root/.cache/pip/ \
  pip3 install --editable "$SALTBOX_BRIDGE_SRC_PATH"


FROM salt-base AS salt-moc-minion
LABEL name='saltbox-salt-minion'
LABEL version='0.9'
RUN mkdir --parents /etc/salt/minion.d/
COPY --chmod=755 minion/minion_entrypoint.sh /usr/local/bin/
ENV SALT_MASTER=salt-master
ENV MINION_ID_PREFIX=moc-minion
ENV SALT_MOC_MINION_LOG_LEVEL=warning
# How often to rentry on master hostname lookup error (sec)
ENV SALT_MOC_MINION_RETRY_DNS=30
ENTRYPOINT ["/usr/local/bin/minion_entrypoint.sh"]
CMD ["/usr/local/bin/salt-minion"]
