{#

This file is a part of Salt.Box Bridge component. It is an inner sync state is
ran by Bridge Agent service.

Pillars are passed by SaltCaller.sync_saltbox().

#}

{%- set ssh_dir = pillar['ssh_dir'] %}
{% set ssh_conf = ssh_dir + '/ssh.conf' %}
{% macro sync(name, src, dst) -%}
{{ name }}_destination:
  file.directory:
    - name: {{ dst | yaml_squote }}
    - makedirs: yes

{{ name }}:
  module.run:
    - rsync.rsync:
      - src: {{ src | yaml_squote }}
      - dst: {{ dst | yaml_squote }}
      - delete: yes
      - force: yes
      - additional_opts: [ '-e', "ssh -F '{{ ssh_conf }}'" ]
    - require:
      - file: {{ name }}_destination
{% endmacro %}

update_ssh_config:
  file.managed:
    - name: {{ ssh_conf | yaml_squote }}
    - source:
      - 'salt://files/ssh.conf.jinja'
    - template: jinja
    - makedirs: yes

# Fetch SLS of Config.Boxes
{% set salt_src = pillar['salt_conf_source'] %}
{% set salt_dst = pillar['salt_conf_destination'] %}
{{ sync(name='sync_salt', src='saltbox-salt-conf:' + salt_src, dst=salt_dst) }}

{% if pillar['salt_conf_custom_sync_on'] %}
# User created files managed with FileBrowser
{% set custom_src = pillar['salt_conf_custom_source'] %}
{% set custom_dst = pillar['salt_conf_custom_destination'] %}
{{ sync(name='sync_salt_custom', src='saltbox-salt-conf:' + custom_src, dst=custom_dst) }}
{%- endif %}

{% if pillar['sshfs_sync_on'] %}
# Extraneous files declared in Manifests of Config Boxes
# Local (Docker-based) Master need no to sync because of direct access
{% set sshfs_src = pillar['sshfs_source'] %}
{% set sshfs_dst = pillar['sshfs_destination'] %}
{{ sync(name='sync_sshfs', src='saltbox-sshfs:' + sshfs_src, dst=sshfs_dst) }}
{%- endif %}
