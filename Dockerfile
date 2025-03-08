ARG BASE_IMG='registry.altlinux.org/alt/alt:p11'

FROM "$BASE_IMG" AS salt-master
LABEL name='salt-box-salt-master'
LABEL version='2.0'

RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes gettext python3-module-pygit2 salt-master
EOF

COPY docker/config/master_id.conf /etc/salt/master.d/
COPY docker/templates/ /root/templates/

COPY engines /srv/salt_extmod/engines/
COPY runners /srv/salt_extmod/runners/
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/

ENV REDIS_USERNAME=redis
ENV REDIS_PASSWORD_FILE=
ENV SALT_MASTER_LOG_LEVEL=warning
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["salt-master"]
EXPOSE 4505 4506 8000


FROM "$BASE_IMG" AS salt-minion
LABEL name='salt-box-salt-minion'
LABEL version='2.0'

RUN \
  --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
<<EOF
set -e
mkdir --parents /var/cache/apt/archives/partial/ /var/lib/apt/lists/partial/
apt-get update
apt-get install --yes salt-minion
EOF

COPY docker/minion/minion.yaml /etc/salt/minion.d/minion.conf
CMD ["/usr/bin/salt-minion"]
