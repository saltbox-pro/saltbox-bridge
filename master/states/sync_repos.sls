update_gitfs_conf:
  file.managed:
    - name: '/etc/salt/master.d/gitfs.conf'
    - source:
      - 'salt://files/gitfs.conf.jinja'
    - template: jinja
    - makedirs: yes

{% if pillar.get('sshfs_sync_on', True) %}
  {% set sshfs_src = pillar.get('sshfs_source', '/srv/sshfs/') %}
  {% set sshfs_dst = pillar.get('sshfs_destination', '/srv/sshfs/') %}
  {%- set var_dir = pillar.get('var_dir', '/var/lib/saltbox-bridge/') %}

  {% set ssh_conf = var_dir + '/ssh/sshfs_ssh.conf' %}

sync_sshfs:
  file.managed:  # FIXMED
    - name: {{ ssh_conf | yaml_squote }}
    - source:
      - 'salt://files/sshfs_ssh.conf.jinja'
    - template: jinja
    - makedirs: yes
  rsync.synchronized:
    - name: {{ sshfs_dst | yaml_squote }}
    - source: {{ ('saltbox-sshfs:' + sshfs_src) | yaml_squote }}
    - prepare: yes  # Create destination dir
    - delete: yes  # Purge unexisted on source
    - force: yes  # Delete non-empty dirs
    - additional_opts:
      - '-e'
      - "ssh -F '{{ ssh_conf }}'"
{%- endif %}

update_fileserver:
  cmd.run:
    - name: 'salt-run fileserver.update gitfs'

#notify:
  #notify:
