{#

This file is a part of Salt.Box Bridge component. It is an inner sync state is
ran by Bridge Agent service.

Pillars are passed by SaltCaller.sync_saltbox(). Some values (BUT NOT ALL)
respect saltbox.conf.

#}

{%- set ssh_dir = pillar.get('ssh_dir', '/var/lib/saltbox-bridge/ssh/') %}
{% set ssh_conf = ssh_dir + '/ssh.conf' %}
{% macro sync(name, src, dst) -%}
{{ name }}:
  rsync.synchronized:
    - name: {{ dst | yaml_squote }}
    - source: {{ src | yaml_squote }}
    - prepare: yes  # Create destination dir
    - delete: yes  # Purge unexisted on source
    - force: yes  # Delete non-empty dirs
    - additional_opts: [ '-e', "ssh -F '{{ ssh_conf }}'" ]
{% endmacro %}

update_ssh_config:
  file.managed:
    - name: {{ ssh_conf | yaml_squote }}
    - source:
      - 'salt://files/ssh.conf.jinja'
    - template: jinja
    - makedirs: yes

# Fetch SLS of Config.Boxes
{% set salt_src = pillar.get('salt_conf_source', '/srv/master/salt/') %}
{% set salt_dst = pillar.get('salt_conf_destination', '/srv/saltbox_salt/') %}
{{ sync(name='sync_salt', src='saltbox-salt-conf:' + salt_src, dst=salt_dst) }}

{% if pillar.get('salt_conf_custom_sync_on', True) %}
# User created files managed with FileBrowser
{% set custom_src = pillar.get('salt_conf_custom_source', '/srv/master/salt_custom/') %}
{% set custom_dst = pillar.get('salt_conf_custom_destination', '/srv/salt_custom/') %}
{{ sync(name='sync_salt_custom', src='saltbox-salt-conf:' + custom_src, dst=custom_dst) }}
{%- endif %}

{% if pillar.get('sshfs_sync_on', True) %}
# Extraneous files declared in Manifests of Config Boxes
# Local (Docker-based) Master need no to sync because of direct access
{% set sshfs_src = pillar.get('sshfs_source', '/srv/sshfs/') %}
{% set sshfs_dst = pillar.get('sshfs_destination', '/srv/sshfs/') %}
{{ sync(name='sync_sshfs', src='saltbox-sshfs:' + sshfs_src, dst=sshfs_dst) }}
{%- endif %}
