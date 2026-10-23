#!/bin/bash

# shellcheck disable=SC2016

# Copyright 2026 Anton Karmanov, Daniil Konarev, Daniil Chistyakov 

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -eu -o pipefail

declare -r timestamp_template="+%Y-%m-%d %H:%M:%S"

declare script_dir
script_dir="$(dirname "${BASH_SOURCE[0]}")"

declare -r bridge_dir="${script_dir}/saltbox-bridge"
declare -r bridge_python_package_dir="${bridge_dir}/saltbox_bridge"

declare -r crt_file_name="redis-ca.crt"
declare -r salt_crt_destination="/etc/salt/ssl/${crt_file_name}"

declare -r correct_head_crt="-----BEGIN CERTIFICATE-----"
declare -r correct_tail_crt="-----END CERTIFICATE-----"

declare -r salt_version=3007.13
declare -r salt_pkgs=(
  "salt-common=${salt_version}"
  "salt-master=${salt_version}"
  "salt-minion=${salt_version}"
)

declare -r salt_pkg_pin_content="Package: salt-*
Pin: version ${salt_version}
Pin-Priority: 1001
"

declare -r salt_pkg_pin_path=/etc/apt/preferences.d/salt-pin-1001
declare -r salt_keyring_path=/etc/apt/keyrings/salt-archive-keyring.pgp
declare -r salt_apt_sources_path=/etc/apt/sources.list.d/salt.sources
declare -r salt_optional_path=/opt/saltstack
declare -r salt_pip_binary_path="${salt_optional_path}/salt/bin/pip3"

declare -r salt_sources_url=https://github.com/saltstack/salt-install-guide/releases/latest/download/salt.sources
declare -r gpg_salt_key_url=https://packages.broadcom.com/artifactory/api/security/keypair/SaltProjectKey/public
declare -r saltbox_bridge_repo_url=https://dev.saltbox.pro/saltbox/saltbox-bridge.git

declare -r dependencies=(curl gnupg git rsync netcat-openbsd gettext-base)

declare -ri default_redis_port=6379
declare -r ip_regex='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
declare -r port_regex='^[0-9]+$'

declare -r master_conf_path=/etc/salt/master
declare -r minion_conf_path=/etc/salt/minion
declare -r saltbox_conf_path=/etc/salt/saltbox

declare -r master_conf_tpl="${bridge_dir}/master/templates/master.conf.tpl"
declare -r minion_conf_tpl="${bridge_dir}/master/templates/minion.conf.tpl"
declare -r saltbox_conf_tpl="${bridge_dir}/master/templates/saltbox.conf.tpl"

declare -r roster_path=/srv/roster/roster
declare -r roster_tpl="${bridge_dir}/master/salt_master_local/files/roster"

# shellcheck disable=SC2155
declare -r master_conf_extra_tpl="$(cat <<'EOF'
user: root
salt_box_master_id: %s
EOF
)"

declare -r saltbox_conf_extra_tpl='redis_host: ${SALTBOX_IP} 
redis_ssl_ca_certs: '"${salt_crt_destination}"'
salt_conf_server: ${SALTBOX_IP}
sshfs_server: ${SALTBOX_IP}'

declare -r master_id_timestamp_format="+%Y%m%d-%H%M%S"

# shellcheck disable=SC2155
declare -r default_master_id="master-$(date "${master_id_timestamp_format}")"

declare -r salt_log_lvl_map=(
  "0:all"
  "1:info"
  "2:warning"
  "3:error"
  "4:critical"
  "5:quiet"
  "6:debug"
  "7:profile"
  "8:trace"
  "9:garbage"
)

declare -r default_entity_log_lvl="1"
declare -r default_redis_user="redis"

declare -A messages
declare -r log_pause_seconds=0.5

declare -r backspace_ascii=$'\x7f'

messages[tittle,en]='
   ####################################################
 ########################################################
##                                                      ##
##      Installing secondary Salt-Master service        ##
##                                                      ##
##                    [Salt.Box]                        ##
##                                                      ##
 #######################################################
   ####################################################
'

messages[tittle,ru]='
   ####################################################
 ########################################################
##                                                      ##
##      Установка стороннего Salt-Master сервиса        ##
##                                                      ##
##                    [Salt.Box]                        ##
##                                                      ##
 #######################################################
   ####################################################
'

messages[root_required,en]='This script must be run as root'
messages[root_required,ru]='Скрипт должен быть запущен от имени root'

messages[unknown_option,en]='Unknown option: %s'
messages[unknown_option,ru]='Неизвестный параметр: %s'

messages[crt_setup,en]='Redis certificate setup:
\t1 - Search for a certificate in the current directory
\t2 - Specify a path to the `redis-ca.crt` file
\tChoice [1/2] (default `1`): '

messages[crt_setup,ru]='Настройка сертификата Redis:
\t1 - Поиск сертификата в текущей директории
\t2 - Указать путь до файла `redis-ca.crt`
\tВыбор [1/2] (по умолчанию `1`): '

messages[crt_not_found,en]='Certificate `redis-ca.crt` not found!'
messages[crt_not_found,ru]='Сертификат `redis-ca.crt` не найден!'

messages[crt_found_success,en]='Certificate `redis-ca.crt` found successfully!'
messages[crt_found_success,ru]='Сертификат `redis-ca.crt` успешно найден!'

messages[crt_specify,en]='Specify the path to the `redis-ca.crt` file: '
messages[crt_specify,ru]='Укажите путь до файла `redis-ca.crt`: '

messages[crt_incorrect_body,en]='Incorrect certificate format!'
messages[crt_incorrect_body,ru]='Неверный формат сертификата!'

messages[crt_install_start,en]='Installing Redis certificate...'
messages[crt_install_start,ru]='Установка сертификата Redis...'

messages[crt_install_success,en]='Redis certificate installed successfully'
messages[crt_install_success,ru]='Сертификат Redis успешно установлен'

messages[crt_install_failed,en]='Failed to install Redis certificate!'
messages[crt_install_failed,ru]='Не удалось установить сертификат Redis!'

messages[help,en]='Install and connect a secondary Salt-Master to SaltBox.

Usage: ./saltbox-master-install.sh [--en_locale|--ru_locale] [-h|--help]
  --en_locale\t\tDisplay script text in English
  --ru_locale\t\tDisplay script text in Russian (default)
  -h|--help\t\tPrint this message

[NOTE] The script must be run as root.

What it does:
\t1. Installs required system packages (curl, git, rsync, gettext, etc.)
\t2. Installs Salt from the official APT repository
\t3. Clones or updates the saltbox-bridge repository (https://dev.saltbox.pro/saltbox/saltbox-bridge)
\t4. Syncs Bridge files into Salt directories and installs the Bridge python package
\t5. Checks connectivity to the SaltBox Redis instance
\t6. Renders master, minion and saltbox configs from Bridge templates
\t7. Enables and restarts the salt-master service

During the run you will be asked to:
\t- provide the `redis-ca.crt` certificate
\t- provide the SaltBox IP address and Redis port
\t- choose a Salt master ID and log levels for master/minion
\t- provide Redis credentials used by the SaltBox config
'
messages[help,ru]='Установка и подключение стороннего Salt-Master к SaltBox.

Использование: ./saltbox-master-install.sh [--en_locale|--ru_locale] [-h|--help]
  --en_locale\t\tОтображать текст скрипта на английском языке
  --ru_locale\t\tОтображать текст скрипта на русском языке (по умолчанию)
  -h|--help\t\tВывести это сообщение
 
[ПРИМЕЧАНИЕ] Скрипт должен быть запущен от имени root.
 
Что делает скрипт:
\t1. Устанавливает необходимые системные пакеты (curl, git, rsync, gettext и др.)
\t2. Устанавливает Salt из официального APT-репозитория
\t3. Клонирует или обновляет репозиторий saltbox-bridge (https://dev.saltbox.pro/saltbox/saltbox-bridge)
\t4. Синхронизирует файлы Bridge в директории Salt и устанавливает python пакет Bridge сервиса
\t5. Проверяет подключение к Redis-инстансу SaltBox
\t6. Формирует конфигурации master, minion и saltbox из шаблонов Bridge сервиса
\t7. Включает и перезапускает сервис salt-master

В процессе выполнения будет предложено:
\t- указать сертификат `redis-ca.crt`
\t- указать IP-адрес SaltBox и порт Redis
\t- выбрать ID для Salt мастера и уровни логирования для master/minion
\t- указать данные для подключения к Redis, используемые в SaltBox конфигурации
'

messages[master_entity_name,en]='Salt master'
messages[master_entity_name,ru]='Salt мастера'

messages[minion_entity_name,en]='Salt minion'
messages[minion_entity_name,ru]='Salt миньона'

messages[install_salt_deps,en]='Installing Salt dependencies...'
messages[install_salt_deps,ru]='Установка зависимостей Salt...'

messages[install_pkgs,en]='Installing packages: %s'
messages[install_pkgs,ru]='Установка пакетов: %s'

messages[install_pkgs_success,en]='Packages installed successfully'
messages[install_pkgs_success,ru]='Пакеты успешно установлены'

messages[install_pkgs_failed,en]='Failed to install packages!'
messages[install_pkgs_failed,ru]='Не удалось установить пакеты!'

messages[install_salt,en]="Installing Salt v${salt_version}..."
messages[install_salt,ru]="Установка Salt v${salt_version}..."

messages[keyring_installing,en]='Installing %s GPG key...'
messages[keyring_installing,ru]='Установка GPG-ключа %s...'

messages[keyring_install_success,en]='%s GPG key installed successfully'
messages[keyring_install_success,ru]='GPG-ключ %s успешно установлен'

messages[keyring_install_failed,en]='Failed to install %s GPG key!'
messages[keyring_install_failed,ru]='Не удалось установить %s GPG-ключ!'

messages[apt_sources_installing,en]='Installing %s APT sources...'
messages[apt_sources_installing,ru]='Установка списка источников APT для %s...'

messages[apt_sources_install_success,en]='%s APT sources installed successfully'
messages[apt_sources_install_success,ru]='Список источников APT для %s успешно установлен'

messages[apt_sources_install_failed,en]='Failed to install %s APT sources!'
messages[apt_sources_install_failed,ru]='Не удалось установить список источников APT для %s!'

messages[pin_installing,en]='Pinning %s package version...'
messages[pin_installing,ru]='Закрепление версии пакетов %s...'

messages[pin_install_success,en]='%s package version pinned successfully'
messages[pin_install_success,ru]='Версия %s пакетов успешно закреплена'

messages[install_salt_success,en]="Salt v${salt_version} installed successfully"
messages[install_salt_success,ru]="Salt v${salt_version} успешно установлен"

messages[specify_saltbox_ip,en]='Specify Saltbox IP address: '
messages[specify_saltbox_ip,ru]='Укажите IP-адрес SaltBox: '

messages[specify_saltbox_port,en]='Specify Redis port (default 6379): '
messages[specify_saltbox_port,ru]='Укажите Redis порт (по умолчанию 6379): '

messages[empty_value,en]='Value cannot be empty!'
messages[empty_value,ru]='Значение не может быть пустым!'

messages[invalid_ip_format,en]='Invalid IP address format!'
messages[invalid_ip_format,ru]='Неверный формат IP-адреса!'

messages[invalid_port_format,en]='Invalid port format!'
messages[invalid_port_format,ru]='Неверный формат порта!'

messages[check_redis_connection,en]='Checking Redis connection...'
messages[check_redis_connection,ru]='Проверка подключения к Redis...'

messages[check_redis_connection_success,en]='Redis connection successful'
messages[check_redis_connection_success,ru]='Подключение к Redis выполнено успешно'

messages[check_redis_connection_failed,en]='Failed to connect to Redis!'
messages[check_redis_connection_failed,ru]='Не удалось подключиться к Redis!'

messages[prepare_salt_dir,en]='Preparing Salt directories...'
messages[prepare_salt_dir,ru]='Подготовка Salt директорий...'

messages[prepare_salt_dir_success,en]='Salt directories prepared successfully'
messages[prepare_salt_dir_success,ru]='Директории Salt успешно подготовлены'

messages[prepare_salt_dir_failed,en]='Failed to prepare Salt directories!'
messages[prepare_salt_dir_failed,ru]='Не удалось подготовить Salt директории!'

messages[repo_cloning,en]='Cloning %s repository...'
messages[repo_cloning,ru]='Клонирование репозитория %s...'

messages[repo_clone_success,en]='%s cloned successfully'
messages[repo_clone_success,ru]='Репозиторий %s успешно клонирован'

messages[repo_clone_failed,en]='Failed to clone %s repository!'
messages[repo_clone_failed,ru]='Не удалось клонировать репозиторий %s!'

messages[saltbox_bridge_updating,en]='Updating saltbox-bridge repository...'
messages[saltbox_bridge_updating,ru]='Обновление репозитория saltbox-bridge...'

messages[saltbox_bridge_update_failed,en]='Failed to update saltbox-bridge repository'
messages[saltbox_bridge_update_failed,ru]='Не удалось обновить репозиторий saltbox-bridge'

messages[saltbox_bridge_dev_switch_failed,en]='Failed to switch to dev branch'
messages[saltbox_bridge_dev_switch_failed,ru]='Не удалось переключиться на ветку dev'

messages[prepare_salt_bridge,en]="Preparing SaltBox Bridge service..."
messages[prepare_salt_bridge,ru]="Настройка SaltBox Bridge сервиса..."

messages[use_local_bridge,en]='Use local saltbox-bridge repository? (y/n, default y): '
messages[use_local_bridge,ru]='Использовать локальный saltbox-bridge репозиторий? (y/n, по умолчанию y): '

messages[use_dev_branch,en]='Use dev branch? (y/n, default n): '
messages[use_dev_branch,ru]='Использовать ветку dev? (y/n, по умолчанию n): '

messages[bridge_has_uncommitted_changes,en]='The local saltbox-bridge has uncommitted changes!'
messages[bridge_has_uncommitted_changes,ru]='В локальном saltbox-bridge есть незакоммиченные изменения!'

messages[confirm_delete_bridge,en]='Confirm: delete and re-clone saltbox-bridge? (y/n, default n): '
messages[confirm_delete_bridge,ru]='Подтвердите: удалить и заново клонировать saltbox-bridge? (y/n, по умолчанию n): '

messages[bridge_delete_cancelled,en]='Deletion cancelled, using existing local copy'
messages[bridge_delete_cancelled,ru]='Удаление отменено, используется существующая локальная копия'

messages[bridge_will_be_deleted,en]='This will PERMANENTLY DELETE the local saltbox-bridge directory:'
messages[bridge_will_be_deleted,ru]='Локальная директория saltbox-bridge будет БЕЗВОЗВРАТНО УДАЛЕНА'

messages[confirm_delete_uncommitted,en]='Uncommitted changes will be lost. Delete anyway? (y/n, default n): '
messages[confirm_delete_uncommitted,ru]='Незакоммиченные изменения будут потеряны. Удалить несмотря на это? (y/n, по умолчанию n): '

messages[sync_bridge_files_start,en]='Syncing saltbox-bridge files...'
messages[sync_bridge_files_start,ru]='Синхронизация файлов saltbox-bridge...'

messages[sync_bridge_files_success,en]='saltbox-bridge files synced successfully'
messages[sync_bridge_files_success,ru]='Файлы saltbox-bridge успешно синхронизированы'

messages[sync_bridge_files_failed,en]='Failed to sync: %s'
messages[sync_bridge_files_failed,ru]='Не удалось синхронизировать: %s'

messages[roster_default_failed,en]='Failed to create default Salt SSH roster: %s'
messages[roster_default_failed,ru]='Не удалось создать ростер Salt SSH по умолчанию: %s'

messages[install_bridge_start,en]='Installing saltbox-bridge Python package...'
messages[install_bridge_start,ru]='Установка Python-пакета saltbox-bridge...'

messages[install_bridge_success,en]='saltbox-bridge package installed successfully'
messages[install_bridge_success,ru]='Пакет saltbox-bridge успешно установлен'

messages[install_bridge_failed,en]='Failed to install saltbox-bridge package!'
messages[install_bridge_failed,ru]='Не удалось установить пакет saltbox-bridge!'

messages[bridge_dir_not_found,en]='saltbox-bridge directory not found: %s'
messages[bridge_dir_not_found,ru]='Директория saltbox-bridge не найдена: %s'

messages[bridge_not_python_package,en]='saltbox-bridge directory is not a valid Python package:'
messages[bridge_not_python_package,ru]='Директория saltbox-bridge не является корректным Python-пакетом:'

messages[salt_pip_not_found,en]='Salt pip3 binary not found: %s'
messages[salt_pip_not_found,ru]='Бинарник pip3 из Salt не найден: %s'

messages[specify_master_id,en]='Specify Salt master ID (default: %s): '
messages[specify_master_id,ru]='Укажите ID для Salt мастера (по умолчанию: %s): '

messages[specify_log_lvl,en]='Specify %s log level:
\t0 - all (everything)
\t1 - info (default; normal log information)
\t2 - warning
\t3 - error
\t4 - critical
\t5 - quiet (nothing should be logged)
\t6 - debug (useful for debugging Salt code)
\t7 - profile (Salt performance profiling info)
\t8 - trace (detailed code debugging)
\t9 - garbage (even more debugging detail)
\tChoice [0-9] (default `1`): '

messages[specify_log_lvl,ru]='Укажите уровень логирования для %s:
\t0 - all (абсолютно всё)
\t1 - info (по умолчанию; обычная лог-информация)
\t2 - warning (предупреждения)
\t3 - error (ошибки)
\t4 - critical (критические ошибки)
\t5 - quiet (ничего не должно логироваться)
\t6 - debug (для отладки кода Salt)
\t7 - profile (информация о производительности Salt)
\t8 - trace (детальная отладка кода)
\t9 - garbage (максимально подробная отладка)
\tВыбор [0-9] (по умолчанию `1`): '

messages[specify_redis_user,en]='Specify Redis username (default: %s): '
messages[specify_redis_user,ru]='Укажите имя пользователя Redis (по умолчанию: %s): '

messages[specify_redis_password,en]='Specify Redis password: '
messages[specify_redis_password,ru]='Укажите пароль Redis: '

messages[setup_configs_start,en]='Setting up Salt configuration files...'
messages[setup_configs_start,ru]='Настройка конфигурационных файлов Salt...'

messages[master_conf_setup_start,en]='Writing master config...'
messages[master_conf_setup_start,ru]='Запись конфигурации мастера...'

messages[master_conf_setup_success,en]='Master config written successfully'
messages[master_conf_setup_success,ru]='Конфигурация мастера успешно записана'

messages[minion_conf_setup_start,en]='Writing minion config...'
messages[minion_conf_setup_start,ru]='Запись конфигурации миньона...'

messages[minion_conf_setup_success,en]='Minion config written successfully'
messages[minion_conf_setup_success,ru]='Конфигурация миньона успешно записана'

messages[saltbox_conf_setup_start,en]='Writing SaltBox config...'
messages[saltbox_conf_setup_start,ru]='Запись конфигурации SaltBox...'

messages[saltbox_conf_setup_success,en]='SaltBox config written successfully'
messages[saltbox_conf_setup_success,ru]='Конфигурация SaltBox успешно записана'

messages[config_template_not_found,en]='Config template not found:'
messages[config_template_not_found,ru]='Шаблон конфигурации не найден:'

messages[config_render_failed,en]='Failed to render config template:'
messages[config_render_failed,ru]='Не удалось обработать шаблон конфигурации: %s'

messages[setup_configs_start,en]='Setting up Salt configuration files...'
messages[setup_configs_start,ru]='Настройка конфигурационных файлов Salt...'

messages[setup_configs_success,en]='All Salt configuration files set up successfully'
messages[setup_configs_success,ru]='Все конфигурационные файлы Salt успешно настроены'

messages[config_written_to,en]='Config written to: %s'
messages[config_written_to,ru]='Конфигурация записана в: %s'

messages[system_service_enabling,en]='Enabling %s service...'
messages[system_service_enabling,ru]='Включение сервиса %s...'

messages[system_service_enable_failed,en]='Failed to enable %s service!'
messages[system_service_enable_failed,ru]='Не удалось включить сервис %s!'

messages[system_service_restarting,en]='Restarting %s service...'
messages[system_service_restarting,ru]='Перезапуск сервиса %s...'

messages[system_service_restart_failed,en]='Failed to restart %s service!'
messages[system_service_restart_failed,ru]='Не удалось перезапустить сервис %s!'

messages[system_service_not_active,en]='%s service is not active after restart!'
messages[system_service_not_active,ru]='Сервис %s не активен после перезапуска!'

messages[master_service_started_success,en]='salt-master service started successfully'
messages[master_service_started_success,ru]='Сервис salt-master успешно запущен'

messages[minion_service_disabling,en]='Disabling salt-minion service...'
messages[minion_service_disabling,ru]='Отключение сервиса salt-minion...'

messages[minion_service_disable_failed,en]='Failed to disable salt-minion service (non-critical)'
messages[minion_service_disable_failed,ru]='Не удалось отключить сервис salt-minion (не критично)'

messages[minion_service_disabled_success,en]='salt-minion service disabled successfully'
messages[minion_service_disabled_success,ru]='Сервис salt-minion успешно отключён'

messages[write_to_file,en]='Writing file: %s'
messages[write_to_file,ru]='Запись файла: %s'

messages[write_to_file_success,en]='File written successfully: %s'
messages[write_to_file_success,ru]='Файл успешно записан: %s'

messages[write_to_file_failed,en]='Failed to write file: %s'
messages[write_to_file_failed,ru]='Не удалось записать файл: %s'

messages[repo_remove_failed,en]='Failed to remove existing directory for %s!'
messages[repo_remove_failed,ru]='Не удалось удалить существующую директорию для %s!'

LOCALE="ru"

function display_help_msg() {
  local msg
  msg="$(extract_msg_from_aarr help)"
  printf "%b\n" "${msg}"
  exit 0
}

function extract_msg_from_aarr() {
  local key="${1}"
  local extracted_msg
  extracted_msg="${messages[${key},${LOCALE}]}"

  if [[ -z "${extracted_msg}" ]]; then
    extracted_msg="${messages[$key,en]}"
  fi
  printf "%s" "${extracted_msg}"
}

function log() {
  local level="${1}"
  local key="${2}"
  local extra="${3:-}"
  local pause="${4:-${log_pause_seconds}}"

  local timestamp
  timestamp=$(date "${timestamp_template}")

  local template
  template=$(extract_msg_from_aarr "${key}")

  local msg
  if [[ -n "${extra}" ]]; then
    # shellcheck disable=SC2059
    printf -v msg "${template}" "${extra}"
  else
    msg="${template}"
  fi

  local msg_pattern="[%s] [%s] %s\n"
  local output

  # shellcheck disable=SC2059
  printf -v output "${msg_pattern}" "${timestamp}" "${level}" "${msg}"

  if [[ "$level" == "INFO" ]]; then
    printf "%b" "${output}"
  else
    printf "%b" "${output}" >&2
  fi

  if [[ "${pause}" != "0" ]]; then
    sleep "${pause}"
  fi
}

function 00__is_root() {
  if [ "$EUID" -ne 0 ]; then
    log "WARN" root_required
    exit 1
  fi
}

function 01__display_tittle() {
  local tittle_str
  tittle_str="$(extract_msg_from_aarr tittle)"
  printf "%s\n\n" "${tittle_str}"
}

function check_redis_crt() {
  local path="${1}"
  if [[ -f "${path}" ]]; then
    log "INFO" crt_found_success
    
    local head_crt
    head_crt=$(head -n 1 "${path}")

    local tail_crt
    tail_crt=$(tail -n 1 "${path}")

    if [[ "${head_crt}" != "${correct_head_crt}" || \
          "${tail_crt}" != "${correct_tail_crt}" ]]; then
      log "ERROR" crt_incorrect_body
      return 1
    fi
  else
    log "ERROR" crt_not_found
    return 1
  fi
}

function search_redis_crt() {
  local path
  path="${script_dir}/${crt_file_name}"

  if ! check_redis_crt "${path}" 1>&2; then
    return 1
  fi
  printf "%s" "${path}"
}

function get_redis_crt() {
  local path
  local input_msg

  input_msg=$(log "INFO" crt_specify)
  read -erp "${input_msg}" path

  if ! check_redis_crt "${path}" 1>&2; then
    return 1
  fi
  printf "%s" "${path}"
}

function 02__setup_crt() {

  local path_to_crt
  local mode
  choice_msg=$(log "INFO" crt_setup)

  while true; do

    read -rp "${choice_msg}" mode
    mode="${mode:-1}"

    case "${mode}" in
      "1"|"Auto search in current dir")
        if ! path_to_crt=$(search_redis_crt) && [[ ! -f "${path_to_crt}" ]]; then
          continue
        fi
        break
        ;;
      "2"|"Specify path to certificate")
        if ! path_to_crt=$(get_redis_crt) && [[ ! -f "${path_to_crt}" ]]; then
          continue
        fi
        break
        ;;
      *)
        log "WARN" unknown_option "${mode}"
        ;;
    esac
  done

  log "INFO" crt_install_start 

  local crt_dirname
  crt_dirname=$(dirname "${salt_crt_destination}")

  mkdir_cmd=(mkdir -vp "${crt_dirname}")
  if ! run_indented "${mkdir_cmd[@]}"; then
    log "ERROR" crt_install_failed 
    exit 1
  fi

  cp_cmd=(cp -av "${path_to_crt}" "${salt_crt_destination}")

  if ! run_indented "${cp_cmd[@]}"; then
    log "ERROR" crt_install_failed
    exit 1
  fi
  log "INFO" crt_install_success
}

function indent() {
  sed 's/^/\t│ /'
}

function run_indented() {
  local cmd_display
  cmd_display="$*"

  local border_char="─"
  local width=80

  local top_border
  printf -v top_border '%*s' "${width}" ''
  top_border="${top_border// /${border_char}}"

  printf "\t┌%s\n" "${top_border}"
  printf "\t│ %s\n" "${cmd_display}"
  printf "\t├%s\n" "${top_border}"

  "$@" 2>&1 | indent
  local exit_code="${PIPESTATUS[0]}"

  printf "\t└%s\n" "${top_border}"

  return "${exit_code}"
}

function display_framed() {
  local content="${1}"

  local border_char="─"
  local width=80

  local top_border
  printf -v top_border '%*s' "${width}" ''
  top_border="${top_border// /${border_char}}"

  printf "\t┌%s\n" "${top_border}"
  printf "%s\n" "${content}" | indent
  printf "\t└%s\n" "${top_border}"
}

function apt_install() {

  local pkgs=("${@}")
  local missing_pkgs=()
  local pkgs_str

  pkgs_str=$(printf ", %s" "${pkgs[@]}")
  pkgs_str="${pkgs_str:2}"

  log "INFO" install_pkgs "${pkgs_str}"

  for pkg in "${pkgs[@]}"; do
    if ! dpkg -s "${pkg}" &>/dev/null; then
      missing_pkgs+=("${pkg}")
    fi
  done

  if ! run_indented apt-get update ; then
    log "ERROR" install_pkgs_failed
  fi

  local apt_cmd
  apt_cmd=(apt-get install -y --no-install-recommends -V --show-progress "${missing_pkgs[@]}")

  if ! run_indented "${apt_cmd[@]}" ; then
    log "ERROR" install_pkgs_failed
    exit 1
  else
    log "INFO" install_pkgs_success
  fi
}

function 04__install_deps() {
  log "INFO" install_salt_deps
  apt_install "${dependencies[@]}"
}

function write_to_file() {

  local content="${1}"
  local file_path=${2}

  local dir_path
  dir_path="$(dirname "${file_path}")"

  if ! mkdir -p "${dir_path}"; then
    log "ERROR" write_to_file_failed "${file_path}"
    exit 1
  fi

  log "INFO" write_to_file "${file_path}"
  display_framed "${content}"

  if ! printf "%s\n" "${content}" > "${file_path}"; then
    log "ERROR" write_to_file_failed "${file_path}"
    exit 1
  fi
  log "INFO" write_to_file_success "${file_path}"
}

function pin_apt_version() {

  local pin_content="${1}"
  local pin_file_path="${2}"
  local package_name="${3}"

  log "INFO" pin_installing "${package_name}"
  write_to_file "${pin_content}" "${pin_file_path}"
  log "INFO" pin_install_success "${package_name}"
}

function add_gpg_keyring() {
  local gpg_url="${1}"
  local keyring_destination_path="${2}"
  local package_name="${3}"

  local curl_cmd
  curl_cmd=(curl -fsSL "${gpg_url}")

  mkdir -p /etc/apt/keyrings

  log "INFO" keyring_installing "${package_name}"

  if ! "${curl_cmd[@]}" | gpg --dearmor > "${keyring_destination_path}"; then
    log "ERROR" keyring_install_failed "${package_name}"
    exit 1
  fi
  log "INFO" keyring_install_success "${package_name}"
}

function add_apt_source() {
  
  local source_url="${1}"
  local source_destination_path="${2}"
  local package_name="${3}"

  log "INFO" apt_sources_installing "${package_name}"

  if ! curl -fsSL "${source_url}" > "${source_destination_path}"; then
    log "ERROR" apt_sources_install_failed "${package_name}"
    exit 1
  fi
  log "INFO" apt_sources_install_success "${package_name}"
}

function 05__install_salt() {

  local package_name="Salt"

  log "INFO" install_salt

  add_gpg_keyring "${gpg_salt_key_url}" "${salt_keyring_path}" "${package_name}"
  add_apt_source "${salt_sources_url}" "${salt_apt_sources_path}" "${package_name}"

  pin_apt_version "${salt_pkg_pin_content}" "${salt_pkg_pin_path}" "${package_name}"
  apt_install "${salt_pkgs[@]}"

  log "INFO" install_salt_success
}

function is_valid_port() {
  local port="${1}"
  if [[ ! "${port}" =~ ${port_regex} ]] ||
     (( "${port}" < 1 || "${port}" > 65535 )); then
    return 1
  fi
  return 0
}

function is_valid_ip() {
  local ip="${1}"

  if [[ ! "${ip}" =~ ${ip_regex} ]]; then
    return 1
  fi

  local octet
  for octet in ${ip//./ }; do
    if (( octet > 255 )); then
      return 1
    fi
  done

  return 0
}

function get_validated_input() {

  local info_msg_key="${1}"
  local error_msg_key="${2}"
  local validator="${3}"
  local default_value="${4:-}"

  local prompt
  prompt=$(log "INFO" "${info_msg_key}" "${default_value}")

  local value="${default_value}"

  while true; do
    read -rp "${prompt}" value
    value="${value:-"${default_value}"}"

    if "${validator}" "${value}"; then
      break
    fi

    if [[ -z "${value}" ]]; then
      log "ERROR" empty_value
    else
      log "ERROR" "${error_msg_key}"
    fi
  done

  printf "%s" "${value}"
}

function 03__check_redis_connection() {

  local saltbox_ip
  saltbox_ip="$(get_validated_input \
    specify_saltbox_ip \
    invalid_ip_format \
    is_valid_ip)"

  local saltbox_redis_port
  saltbox_redis_port="$(get_validated_input \
    specify_saltbox_port \
    invalid_port_format \
    is_valid_port \
    "${default_redis_port}")"

  log "INFO" check_redis_connection

  local netcat_cmd
  netcat_cmd=(nc -vz "${saltbox_ip}" "${saltbox_redis_port}")

  if ! run_indented "${netcat_cmd[@]}"; then
    log "ERROR" check_redis_connection_failed
    exit 1
  fi
  export SALTBOX_IP="${saltbox_ip}"
  log "INFO" check_redis_connection_success
}

function 06__prepare_salt_dir() {

  local dirs=(
    /srv/salt_extmod/{engines,runners,pillar}
    /srv/salt_master_local
    /srv/salt_local
    /srv/salt_custom
    /srv/saltbox_salt
    /srv/sshfs
    /srv/roster
    /var/lib/saltbox-bridge
    /etc/salt/ssl
  )
  log "INFO" prepare_salt_dir

  for dir in "${dirs[@]}"; do
    cmd=(mkdir -pv "${dir}")
    if ! run_indented "${cmd[@]}"; then
      log "ERROR" prepare_salt_dir_failed
      exit 1
    fi
  done
  log "INFO" prepare_salt_dir_success
}

function clone_repository() {
  
  local source_url="${1}"
  local destination="${2}"
  local repo_name="${3}"

  if [[ -d "${destination}" ]]; then
    local remove_cmd
    remove_cmd=(rm -rvf "${destination}")

    if ! run_indented "${remove_cmd[@]}"; then
      log "ERROR" repo_remove_failed "${repo_name}"
      exit 1
    fi
  fi

  log "INFO" repo_cloning "${repo_name}"

  local git_clone_cmd
  git_clone_cmd=(git clone "${source_url}" "${destination}")

  if ! run_indented "${git_clone_cmd[@]}"; then
    log "ERROR" repo_clone_failed "${repo_name}"
    exit 1
  fi
  log "INFO" repo_clone_success "${repo_name}"
}

function update_saltbox_bridge() {
  local dir="${1}"

  if [[ -d "${dir}/.git" ]]; then
    log "INFO" saltbox_bridge_updating

    local git_pull_cmd
    git_pull_cmd=(git -C "${dir}" pull)

    if ! run_indented "${git_pull_cmd[@]}"; then
      log "WARN" saltbox_bridge_update_failed
    fi
  fi
}

function switch_dev_branch_if_requested() {

  local dir="${1}"
  local use_dev
  local prompt

  prompt="$(log "INFO" use_dev_branch)"
  read -rp "${prompt}" use_dev

  if [[ "${use_dev}" == "y" ]]; then

    local git_switch_cmd
    git_switch_cmd=(git -C "${dir}" switch dev)

    if ! run_indented "${git_switch_cmd[@]}"; then
      log "WARN" saltbox_bridge_dev_switch_failed
    fi
  fi
}

function bridge_has_uncommitted_changes() {
  local dir="${1}"

  if [[ -d "${dir}/.git" ]]; then
    local unstaged_status
    local staged_status

    if git -C "${dir}" diff --quiet 2>/dev/null; then
      unstaged_status=0
    else
      unstaged_status=1
    fi

    if git -C "${dir}" diff --cached --quiet 2>/dev/null; then
      staged_status=0
    else
      staged_status=1
    fi

    if [[ "${unstaged_status}" == "1" ]] ||
       [[ "${staged_status}" == "1" ]]; then
      return 0
    else
      return 1
    fi
  else
    return 1
  fi
}

function confirm_delete_local_bridge() {
  local dir="${1}"
  local confirm
  local confirm_prompt

  log "WARN" bridge_will_be_deleted

  if bridge_has_uncommitted_changes "${dir}"; then
    log "WARN" bridge_has_uncommitted_changes
    confirm_prompt="$(log "WARN" confirm_delete_uncommitted)"
  else
    confirm_prompt="$(log "WARN" confirm_delete_bridge)"
  fi

  read -rp "${confirm_prompt}" confirm
  confirm="${confirm:-n}"

  if [[ "${confirm}" == "y" ]]; then
    return 0
  else
    return 1
  fi
}

function 07__prepare_saltbox_bridge() {

  local repo_name="SaltBox Bridge"
  local use_local
  local prompt

  log "INFO" prepare_salt_bridge

  if [[ -d "${bridge_dir}" ]]; then

    prompt="$(log "INFO" use_local_bridge)"
    read -rp "${prompt}" use_local
    use_local="${use_local:-y}"

    if [[ "${use_local}" != "y" ]]; then
      if confirm_delete_local_bridge "${bridge_dir}"; then
        clone_repository "${saltbox_bridge_repo_url}" "${bridge_dir}" "${repo_name}"
      else
        log "INFO" bridge_delete_cancelled
      fi
    fi
  else
    clone_repository "${saltbox_bridge_repo_url}" "${bridge_dir}" "${repo_name}"
  fi
  update_saltbox_bridge "${bridge_dir}"
  switch_dev_branch_if_requested "${bridge_dir}"
}

function 08__sync_bridge_files() {

  local -A targets
  targets['engines/']=/srv/salt_extmod/engines/
  targets['runners/']=/srv/salt_extmod/runners/
  targets['pillar/']=/srv/salt_extmod/pillar/
  targets['master/salt_master_local/']=/srv/salt_master_local/
  targets['master/salt_local/']=/srv/salt_local/

  log "INFO" sync_bridge_files_start

  local source
  for source in "${!targets[@]}"; do

    local destination
    destination="${targets["${source}"]}"

    local full_source="${bridge_dir}/"${source}

    local rsync_cmd
    rsync_cmd=(rsync -av --delete "${full_source}" "${destination}")

    if ! run_indented "${rsync_cmd[@]}"; then
      log "ERROR" sync_bridge_files_failed "${source}"
    fi
  done

  if [[ ! -f "${roster_path}" ]]; then
    local cp_cmd
    cp_cmd=(cp -v "${roster_tpl}" "${roster_path}")

    if ! run_indented "${cp_cmd[@]}"; then
      log "ERROR" roster_default_failed "${roster_path}"
    fi
  fi
  log "INFO" sync_bridge_files_success
}

function 09__install_bridge() {

  log "INFO" install_bridge_start

  if [[ ! -d "${bridge_python_package_dir}" ]]; then
    log "ERROR" bridge_dir_not_found "${bridge_python_package_dir}"
    exit 1
  fi

  if [[ ! -f "${bridge_python_package_dir}/pyproject.toml" ]]; then
    log "ERROR" bridge_not_python_package "${bridge_python_package_dir}"
    exit 1
  fi

  if [[ ! -x "${salt_pip_binary_path}" ]]; then
    log "ERROR" salt_pip_not_found "${salt_pip_binary_path}"
    exit 1
  fi

  local pip_cmd
  pip_cmd=("${salt_pip_binary_path}" install "${bridge_python_package_dir}" --upgrade)

  if ! run_indented "${pip_cmd[@]}"; then
    log "ERROR" install_bridge_failed
    exit 1
  fi
  log "INFO" install_bridge_success
}

function render_config_template() {

  local template_path="${1}"
  local destination_path="${2}"
  local extra_content="${3:-}"

  if [[ ! -f "${template_path}" ]]; then
    log "ERROR" config_template_not_found "${template_path}"
    exit 1
  fi

  local rendered_content
  if ! rendered_content=$(envsubst < "${template_path}"); then
    log "ERROR" config_render_failed "${template_path}"
    exit 1
  fi

  local extended_content="${rendered_content}"
  if [[ -n "${extra_content}" ]]; then
    extended_content="${extended_content}"$'\n'"${extra_content}"
  fi
  printf "%s" "${extended_content}" > "${destination_path}"

  log "INFO" config_written_to "${destination_path}"
  display_framed "${extended_content}"
}

# NOTE: https://docs.saltproject.io/en/latest/ref/configuration/logging/index.html
function specify_log_lvl() {

  local prompt_key="${1}"
  local entity_name_key="${2}"
  local default_choice="${3}"
  shift 3
  local -a level_map=("${@}")

  local entity_name=""
  if [[ -n "${entity_name_key}" ]]; then
    entity_name="$(extract_msg_from_aarr "${entity_name_key}")"
  fi

  local prompt
  prompt=$(log "INFO" "${prompt_key}" "${entity_name}")

  local choice
  local pair
  local key
  local val

  while true; do
    read -rp "${prompt}" choice
    choice="${choice:-${default_choice}}"

    for pair in "${level_map[@]}"; do
      key="${pair%%:*}"
      val="${pair#*:}"
      if [[ "${choice}" == "${key}" ]]; then
        printf "%s" "${val}"
        return 0
      fi
    done
    log "ERROR" unknown_option "${choice}"
  done
}

function read_pwd_with_asterisks() {
  local prompt="${1}"
  local pwd=""
  local input_char

  local tty_dir=/dev/tty

  printf "%s" "${prompt}" > "${tty_dir}"

  while IFS= read -rsn 1 input_char < "${tty_dir}"; do
    if [[ -z "${input_char}" ]]; then
      # Enter pressed
      break
    fi

    if [[ "${input_char}" == "${backspace_ascii}" ]]; then
      if [[ -n "${pwd}" ]]; then
        pwd="${pwd%?}"
        printf "\b \b" > "${tty_dir}"
      fi
      continue
    fi
    pwd+="${input_char}"
    printf "*" > "${tty_dir}"
  done

  printf "\n" > "${tty_dir}"
  printf "%s" "${pwd}"
}

function 10__setup_configs() {

  log "INFO" setup_configs_start

  local master_id_prompt
  master_id_prompt="$(log "INFO" specify_master_id "${default_master_id}")"

  local master_id
  read -rp "${master_id_prompt}" master_id
  master_id="${master_id:-${default_master_id}}"

  master_log_lvl=$(specify_log_lvl \
    specify_log_lvl \
    master_entity_name \
    "${default_entity_log_lvl}" \
    "${salt_log_lvl_map[@]}")

  minion_log_lvl=$(specify_log_lvl \
    specify_log_lvl \
    minion_entity_name \
    "${default_entity_log_lvl}" \
    "${salt_log_lvl_map[@]}")

  export SALT_MASTER_LOG_LEVEL="${master_log_lvl}"
  export SALT_MINION_LOG_LEVEL="${minion_log_lvl}"

  log "INFO" master_conf_setup_start

  # shellcheck disable=SC2059
  printf -v master_conf_extra "${master_conf_extra_tpl}" "${master_id}"
  render_config_template "${master_conf_tpl}" "${master_conf_path}" "${master_conf_extra}"

  log "INFO" minion_conf_setup_start
  render_config_template "${minion_conf_tpl}" "${minion_conf_path}"

  log "INFO" saltbox_conf_setup_start

  local redis_user_prompt
  redis_user_prompt="$(log "INFO" specify_redis_user "${default_redis_user}")"

  local redis_user
  read -rp "${redis_user_prompt}" redis_user
  redis_user="${redis_user:-${default_redis_user}}"

  local redis_pwd_prompt
  redis_pwd_prompt="$(log "INFO" specify_redis_password)"

  local redis_pwd
  while true; do
    redis_pwd=$(read_pwd_with_asterisks "${redis_pwd_prompt}")
    if [[ -n "${redis_pwd}" ]]; then
      break
    fi
    log "WARN" empty_value
  done

  export REDIS_USERNAME="${redis_user}"
  export REDIS_PASSWORD="${redis_pwd}" # TODO: check Redis connection using username and password

  local saltbox_conf_extra
  saltbox_conf_extra=$(envsubst <<< "${saltbox_conf_extra_tpl}")
  render_config_template "${saltbox_conf_tpl}" "${saltbox_conf_path}" "${saltbox_conf_extra}"

  log "INFO" setup_configs_success
}

function enable_system_service() {
  local service_name="${1}"

  log "INFO" system_service_enabling "${service_name}"

  local enable_cmd
  enable_cmd=(systemctl enable "${service_name}")

  if ! run_indented "${enable_cmd[@]}"; then
    log "ERROR" system_service_enable_failed "${service_name}"
    exit 1
  fi

  log "INFO" system_service_restarting "${service_name}"

  local restart_cmd
  restart_cmd=(systemctl restart "${service_name}")

  if ! run_indented "${restart_cmd[@]}"; then
    log "ERROR" system_service_restart_failed "$service_name"
    exit 1
  fi

  local is_active_cmd
  is_active_cmd=(systemctl is-active --quiet "${service_name}")

  if ! run_indented "${is_active_cmd[@]}" ; then
    log "ERROR" master_service_not_active "${service_name}"
    exit 1
  fi
}

function 11__enable_master_service() {
  
  local service_name="salt-master"
  enable_system_service "${service_name}"
  log "INFO" master_service_started_success

  log "INFO" minion_service_disabling
  local disable_minion_cmd
  disable_minion_cmd=(systemctl disable --now salt-minion)

  if ! run_indented "${disable_minion_cmd[@]}"; then
    log "WARN" minion_service_disable_failed
  else
    log "INFO" minion_service_disabled_success
  fi
}

function compleate_stages() {
  00__is_root
  01__display_tittle
  02__setup_crt
  03__check_redis_connection
  04__install_deps
  05__install_salt
  06__prepare_salt_dir
  07__prepare_saltbox_bridge
  08__sync_bridge_files
  09__install_bridge
  10__setup_configs
  11__enable_master_service
}

for i in "$@"; do
  case "$i" in
    --en_locale)
      LOCALE="en"
      ;;
    --ru_locale)
      LOCALE="ru"
      ;;
    -h|--help)
      display_help_msg
      ;;
    -*)
      log "WARN" unknown_option "${i}"
      ;;
  esac
done

readonly LOCALE
compleate_stages
