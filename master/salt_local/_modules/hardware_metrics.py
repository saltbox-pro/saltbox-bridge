#! /bin/env/ python3

import abc
import inspect
import json
import logging
import subprocess
import typing
from pathlib import Path
from typing import Any, override

# from salt.utils.event import get_event
from salt.exceptions import CommandExecutionError, CommandNotFoundError

logger = logging.getLogger(__name__)
__virtualname__ = 'hardware_metrics'


def __virtual__():
    if __grains__['os'] not in ['Windows']:
        return __virtualname__
    return False, 'Unsupported distro'


def extract() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    collectors: list[BaseCollector] = CollectorFactory.create_all()
    for collector in collectors:
        try:
            data: dict[str, Any] = collector.get_data()
            payload[collector.key] = data
        except Exception:
            msg = f"Failed to collect data from '{collector.key}' collector"
            logger.exception(msg)

    # event = get_event("minion", opts=__opts__)
    # success = event.fire_event(data=payload, tag='foo')
    #
    # if not success:
    #     logger.error("Failed to send hardware metrics")
    #     return {"status": "failed", "message": "Failed to send event"}

    return {"status": "success", "metrics": payload}


class ShellExecutor(abc.ABC):

    @abc.abstractmethod
    def run_cmd(self, command: str | list[str], **kwargs) -> str:
        ...


class SubprocessShellExecutor(ShellExecutor):

    @override
    def run_cmd(self, command: str | list[str], **kwargs) -> str:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=True,
                text=True,
                **kwargs
            )
            return result.stdout
        except subprocess.CalledProcessError as ex:
            cmd_str: str = ' '.join(command)
            stderr: str = ex.stderr.strip()
            logger.error("CMD failed: '%s', STDERR: %s", cmd_str, stderr)
            msg = f'Command failed: "${cmd_str}"'
            raise CommandExecutionError(msg) from ex
        except FileNotFoundError as ex:
            cmd_str = command[0] if isinstance(command, list) else command
            msg = f"CMD not found: '{cmd_str}'"
            logger.error(msg)
            raise CommandNotFoundError(msg) from ex


class BaseCollector(abc.ABC):

    collectors: list[type['BaseCollector']] = []

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            BaseCollector.collectors.append(cls)

    def __init__(self, sh_executor: ShellExecutor | None = None) -> None:
        self._sh_executor = sh_executor or SubprocessShellExecutor()

    @property
    @abc.abstractmethod
    def key(self) -> str: ...

    @abc.abstractmethod
    def get_data(self) -> dict[str, Any]: ...


class CpuCollector(BaseCollector):

    _KEY = 'cpu'

    _CPU_SYSTEM_DEVICE_PATH = Path('/sys/devices/system/cpu')
    _CPU_FREQUENCY_SCALING_PATH_REGEX = 'cpu*/cpufreq/scaling_cur_freq'
    _CPU_SYS_PATH = Path('/sys/devices/system/cpu')
    _THERMAL_PATH = Path('/sys/class/thermal')
    _THERMAL_ZONE_PATH_REGEX = 'thermal_zone*'
    _CPU_STATS_PATH = Path('/proc/stat')

    @property
    @override
    def key(self) -> str:
        return self._KEY

    @override
    def get_data(self) -> dict[str, Any]:
        return {
            'cpu_thread_loads': self._get_cpu_thread_loads(),
            'cpu_temp': {
                # 'per_threads': '_get_cpu_temp_per_threads',
                'thermal_zone': self._get_cpu_temps_from_thermal_zones()
                },
            'cpu_threads_frequency_mhz': self._get_cpu_thread_frequencies()
        }

    def _get_cpu_thread_loads(self) -> dict[str, float]:
        cpu_loads: dict[str, float] = {}
        cpu_stats: dict[str, list[int]] = self._get_cpu_stats_data()
        for cpu, stats in cpu_stats.items():
            total_time: int = sum(stats)
            idle_time: int = stats[3]
            load: float = (total_time - idle_time) / total_time * 100
            cpu_loads[cpu] = load
        return cpu_loads

    def _get_cpu_stats_data(self) -> dict[str, list[int]]:
        with Path.open(self._CPU_STATS_PATH) as f:
            lines: list[str] = f.readlines()

        cpu_stats: dict[str, list[int]] = {}
        for line in lines:
            if line.startswith("cpu"):
                parts = line.split()
                cpu_id = parts[0]
                stats = list(map(int, parts[1:]))
                cpu_stats[cpu_id] = stats
        return cpu_stats

    def _get_cpu_temps_from_thermal_zones(self) -> dict[str, float]:
        temps: dict[str, float] = {}
        for zone in self._THERMAL_PATH.glob(pattern=self._THERMAL_ZONE_PATH_REGEX):
            type_path = zone / "type"
            temp_path = zone / "temp"
            if type_path.exists() and temp_path.exists():
                with Path.open(type_path) as f:
                    zone_type = f.read().strip()
                if "cpu" in zone_type.lower():
                    with Path.open(temp_path) as f:
                        temps[zone_type] = int(f.readline()) / 1000
        return temps

    def _get_cpu_thread_frequencies(self) -> dict[str, float]:
        freqs: dict[str, float] = {}
        for freq in self._CPU_SYSTEM_DEVICE_PATH.glob(pattern=self._CPU_FREQUENCY_SCALING_PATH_REGEX):
            if freq.exists():
                cpu_id: str = freq.parent.parent.name
                with Path.open(freq) as f:
                    freq_khz: int = int(f.readline())
                    freq_mhz: float = freq_khz / 1000
                    freqs[cpu_id] = freq_mhz
        return freqs


class DiskCollector(BaseCollector):

    _KEY = 'disk'
    _DISK_CMD = 'df'
    _DISK_CMD_ARGS: typing.ClassVar[list[str]] = ['-T', '-P']

    _IDX_FILESYSTEM = 0
    _IDX_TYPE = 1
    _IDX_TOTAL_CAPACITY = 2
    _IDX_USED = 3
    _IDX_AVAILABLE = 4
    _IDX_MOUNT_PATH = 6

    @property
    @override
    def key(self) -> str:
        return self._KEY

    @override
    def get_data(self) -> dict[str, Any]:
        return self._get_disk_free_data()

    def _get_disk_free_data(self) -> dict[str, dict[str, str | float]]:

        disk_data: dict[str, dict[str, str | float]] = {}

        cmd = [self._DISK_CMD, *self._DISK_CMD_ARGS]
        output: str = self._sh_executor.run_cmd(cmd)
        output_lines = output.strip().split('\n')[1:]

        for output_line in output_lines:
            parts = output_line.split()
            if len(parts) > 7:
                continue
            try:
                filesystem = parts[self._IDX_FILESYSTEM]
                current_disk: dict[str, str | float] = {}
                current_disk['type'] = parts[self._IDX_TYPE]
                current_disk['total_capacity_mb'] = float(parts[self._IDX_TOTAL_CAPACITY]) / 1024
                current_disk['used_mb'] = float(parts[self._IDX_USED]) / 1024
                current_disk['available_mb'] = float(parts[self._IDX_AVAILABLE]) / 1024
                current_disk['mounted'] = parts[self._IDX_MOUNT_PATH]
                disk_data[filesystem] = current_disk
            except ValueError as ex:
                logger.error("Conversion error from '%s' command output", cmd)
                raise ex

        return disk_data

    def _get_disk_write_data(self) -> dict[str, float]: ...

    def _get_disk_read_data(self) -> dict[str, float]: ...


class CollectorFactory:
    @staticmethod
    def create_all() -> list[BaseCollector]:
        collectors = []
        for collector_cls in BaseCollector.collectors:
            try:
                instance: BaseCollector = collector_cls()
                collectors.append(instance)
            except Exception:
                logger.exception("Failed to instantiate '%s' collector", collector_cls.__name__)
        return collectors


if __name__ == '__main__':
    data = extract()
    print(json.dumps(obj=data, indent=4))
