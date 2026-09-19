module_dirs:
  - /srv/salt_extmod/
file_roots:
  base:
    - /srv/salt_custom/
    - /srv/salt_local/
    - /srv/saltbox_salt/
    - /srv/sshfs/  # Serve "big" files both with `ssh://` and `salt://`
file_ignore_glob:
  - '*/.git/*'
  - '*.pyc'
  - '*.swp'
auto_accept: true
# Allow minions to push files to the master (client file-manager download via cp.push).
file_recv: True
file_recv_max_size: 100
log_level: '${SALT_MASTER_LOG_LEVEL}'
log_level_logfile: 'quiet'
log_fmt_console: '%(asctime)s %(colorlevel)s %(colorname)s %(colormsg)s'
presence_events: True
minion_data_cache: True
job_cache: False
minimum_auth_version: 2
engines:
  - saltbox_delator: {}
  - saltbox_agent: {}
  - saltbox_job_runner: {}
gpg_keydir: '/etc/salt/gpgkeys'
ext_pillar:
  - core_pillar: {}

schedule:
  saltbox_delator_cleanup:
    hours: 3
    function: saltbox_delator.cleanup_expired_jobs

# vi: syn=yaml
