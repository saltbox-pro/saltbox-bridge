#! /bin/env/ python3

import abc
import asyncio
import inspect
import logging
import subprocess
import typing
from pathlib import Path
from types import CoroutineType
from typing import Any, override

from salt.exceptions import CommandExecutionError, CommandNotFoundError
from salt.utils.event import get_event

logger = logging.getLogger(__name__)
__virtualname__ = 'hardware_metrics'


def __virtual__():
    if __grains__['os'] not in ['Windows']:
        return __virtualname__
    return False, 'Unsupported distro'


async def schedule(extraction_delay: int) -> None:

    collectors: list[BaseCollector] = CollectorFactory.create_all()

    while True:

        payload: dict[str, any] = {}
        collector_to_extraction_task_coroutine: list[tuple[BaseCollector, CoroutineType[Any, Any, dict[str, Any]]]] = \
                [(collector, collector.get_data()) for collector in collectors]

        tasks: list[CoroutineType[Any, Any, dict[str, Any]]] = [task for _, task in collector_to_extraction_task_coroutine]
        results: list[dict[str, Any] | BaseException] = await asyncio.gather(*tasks, return_exceptions=True)

        for (collector, _), result in zip(collector_to_extraction_task_coroutine, results, strict=False):
            payload[collector.key] = result

        event = get_event("minion", opts=__opts__, io_loop=True)
        success = await event.fire_event_async(data=payload, tag='foo')

        if not success:
            logger.error("Failed to send hardware metrics")

        await asyncio.sleep(extraction_delay)


class ShellExecutor(abc.ABC):

    @abc.abstractmethod
    async def run_cmd(self, command: str | list[str], **kwargs) -> str:
        ...


class SubprocessShellExecutor(ShellExecutor):

    @override
    async def run_cmd(self, command: str | list[str], **kwargs) -> str:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
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


class AsyncIOWrapper:

    async def _async_run_io_op(self, func: typing.Callable, *args, **kwargs) -> typing.Any:
        return await asyncio.to_thread(func, *args, **kwargs)

    async def _read_file_content(self, path: Path) -> str:
        return await self._async_run_io_op(path.read_text)

    async def _read_file_lines(self, path: Path) -> list[str]:
        def _read_sync() -> list[str]:
            with path.open() as f:
                return f.readlines()
        return await self._async_run_io_op(_read_sync)


class BaseCollector(abc.ABC, AsyncIOWrapper):

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

    async def get_data(self) -> dict[str, Any]:
        try:
            data = await self._get_data()
            return data
        except BaseException as ex:
            self._handle_extraction_err(ex)
            return {}

    @abc.abstractmethod
    async def _get_data(self) -> dict[str, Any]: ...

    def _handle_extraction_err(self, ex: BaseException) -> None:
        msg = f"Failed to collect data from '{self.key}' collector"
        logger.error(msg, exc_info=ex)


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
    async def _get_data(self) -> dict[str, Any]:

        thread_loads_task = self._get_cpu_thread_loads()
        temps_task = self._get_cpu_temps_from_thermal_zones()
        freqs_task = self._get_cpu_thread_frequencies()

        thread_loads, temps, freqs = await asyncio.gather(
            thread_loads_task,
            temps_task,
            freqs_task,
            return_exceptions=True
        )

        return {
            'cpu_thread_loads': thread_loads,
            'cpu_temp': {
                # 'per_threads': '_get_cpu_temp_per_threads',
                'thermal_zone': temps
                },
            'cpu_threads_frequency_mhz': freqs
        }

    async def _get_cpu_thread_loads(self) -> dict[str, float]:
        cpu_loads: dict[str, float] = {}
        cpu_stats: dict[str, list[int]] = await self._get_cpu_stats_data()
        for cpu, stats in cpu_stats.items():
            total_time: int = sum(stats)
            idle_time: int = stats[3]
            load: float = (total_time - idle_time) / total_time * 100
            cpu_loads[cpu] = load
        return cpu_loads

    async def _get_cpu_stats_data(self) -> dict[str, list[int]]:

        lines: list[str] = await self._read_file_lines(self._CPU_STATS_PATH)

        cpu_stats: dict[str, list[int]] = {}
        for line in lines:
            if line.startswith("cpu"):
                parts = line.split()
                cpu_id = parts[0]
                stats = list(map(int, parts[1:]))
                cpu_stats[cpu_id] = stats
        return cpu_stats

    async def _get_cpu_temps_from_thermal_zones(self) -> dict[str, float]:

        temps: dict[str, float] = {}

        read_tasks = []

        for zone in self._THERMAL_PATH.glob(pattern=self._THERMAL_ZONE_PATH_REGEX):
            type_path = zone / "type"
            temp_path = zone / "temp"
            if type_path.exists() and temp_path.exists():
                read_tasks.append(self._read_thermal_zone_data(type_path, temp_path))

        results = await asyncio.gather(*read_tasks, return_exceptions=True)
        for result in results:
            # if isinstance(result, BaseException):
            #     continue
            zone_type, temp = result
            temps[zone_type] = temp

        return temps

    async def _read_thermal_zone_data(self, type_path: Path, temp_path: Path) -> tuple[str, float]:
        type_content, temp_content = await asyncio.gather(
            self._read_file_content(type_path),
            self._read_file_content(temp_path)
        )
        zone_type = type_content.strip()
        if self._KEY in zone_type.lower():
            return zone_type, int(temp_content.strip()) / 1000
        msg = "Zone type '%s' is not CPU related"
        raise ValueError(msg, zone_type)

    async def _get_cpu_thread_frequencies(self) -> dict[str, float]:
        freqs: dict[str, float] = {}
        read_tasks = []

        for freq_path in self._CPU_SYSTEM_DEVICE_PATH.glob(pattern=self._CPU_FREQUENCY_SCALING_PATH_REGEX):
            if freq_path.exists():
                read_tasks.append(self._read_cpu_frequency_data(freq_path))

        results = await asyncio.gather(*read_tasks, return_exceptions=True)
        for result in results:
            # if isinstance(result, BaseException):
            #     continue
            cpu_id, freq_mhz = result
            freqs[cpu_id] = freq_mhz

        return freqs

    async def _read_cpu_frequency_data(self, freq_path: Path) -> tuple[str, float]:
        cpu_id: str = freq_path.parent.parent.name
        file_content: str = await self._read_file_content(freq_path)
        freq_khz: int = int(file_content)
        freq_mhz: float = freq_khz / 1000
        return cpu_id, freq_mhz


class DiskCollector(BaseCollector):

    _KEY = 'disk'
    _DISK_SIZE_CMD = 'df'
    _DISK_SIZE_CMD_ARGS: typing.ClassVar[list[str]] = ['-T', '-P']

    _DF_IDX_FILESYSTEM = 0
    _DF_IDX_TYPE = 1
    _DF_IDX_TOTAL_CAPACITY = 2
    _DF_IDX_USED = 3
    _DF_IDX_AVAILABLE = 4
    _DF_IDX_MOUNT_PATH = 6

    _DISK_IO_STATS_PATH = Path('/proc/diskstats')
    _IO_IDX_DEVICE_NAME = 2
    _IO_IDX_SECTORS_READ = 5
    _IO_IDX_SECTORS_WRITTEN = 9
    _SECTOR_SIZE_BYTES = 512

    _SKIPPED_DISK_TYPES: typing.ClassVar[list[str]] = ['tmpfs', 'devtmpfs', 'sysfs', 'pstore']

    def __init__(self, sh_executor: ShellExecutor | None = None) -> None:
        super().__init__(sh_executor)
        self._last_disk_io_stats: dict[str, dict[str, int]] = {}

    @property
    @override
    def key(self) -> str:
        return self._KEY

    @override
    async def _get_data(self) -> dict[str, Any]:
        df_data_task = self._get_disk_free_data()
        disk_bps_task = self._get_disk_io_byte_per_sec()
        df_data, disk_bps = await asyncio.gather(df_data_task, disk_bps_task)
        return self._merge_disk_free_data_with_io_bps(df_data, disk_bps)

    async def _get_disk_free_data(self) -> dict[str, dict[str, str | float]]:

        disk_data: dict[str, dict[str, str | float]] = {}

        cmd = [self._DISK_SIZE_CMD, *self._DISK_SIZE_CMD_ARGS]
        output: str = await self._sh_executor.run_cmd(cmd)
        output_lines: list[str] = output.strip().split('\n')[1:]

        for output_line in output_lines:
            parts = output_line.split()
            if len(parts) > 7:
                continue
            try:
                disk_type: str = parts[self._DF_IDX_TYPE]
                if disk_type not in self._SKIPPED_DISK_TYPES:
                    filesystem: str = parts[self._DF_IDX_FILESYSTEM]
                    current_disk: dict[str, str | float] = {}
                    current_disk['type'] = parts[self._DF_IDX_TYPE]
                    current_disk['total_capacity_mb'] = float(parts[self._DF_IDX_TOTAL_CAPACITY]) / 1024
                    current_disk['used_mb'] = float(parts[self._DF_IDX_USED]) / 1024
                    current_disk['available_mb'] = float(parts[self._DF_IDX_AVAILABLE]) / 1024
                    current_disk['mounted'] = parts[self._DF_IDX_MOUNT_PATH]
                    disk_data[filesystem] = current_disk
            except ValueError as ex:
                logger.error("Conversion error from '%s' command output", cmd)
                raise ex

        return disk_data

    async def _get_disk_io_byte_per_sec(self) -> dict[str, dict[str, float]]:

        current_disk_stats: dict[str, dict[str, int]] = await self._get_disk_io_stats()
        disk_io_stats_per_sec: dict[str, dict[str, float]] = {}

        for device, stats in current_disk_stats.items():
            prev_read_sectors: int = self._last_disk_io_stats.get(device, {}).get('read_sectors', 0)
            prev_written_sectors: int = self._last_disk_io_stats.get(device, {}).get('writen_sectors', 0)

            read_sectors: int = stats['read_sectors']
            written_sectors: int = stats['writen_sectors']

            read_bps: int = (read_sectors - prev_read_sectors) * self._SECTOR_SIZE_BYTES
            written_bps: int = (written_sectors - prev_written_sectors) * self._SECTOR_SIZE_BYTES

            disk_io_stats_per_sec[device] = {
                'read_bps': read_bps,
                'write_bps': written_bps
            }
        self._last_disk_io_stats = current_disk_stats
        return disk_io_stats_per_sec

    async def _get_disk_io_stats(self) -> dict[str, dict[str, int]]:

        stats: dict[str, dict[str, int]] = {}
        lines = await self._read_file_lines(self._DISK_IO_STATS_PATH)

        for line in lines:
            parts: list[str] = line.split()
            if len(parts) != 20:
                continue
            device_name: str = parts[self._IO_IDX_DEVICE_NAME]
            read_sectors = int(parts[self._IO_IDX_SECTORS_READ])
            writen_sectors = int(parts[self._IO_IDX_SECTORS_WRITTEN])
            stats[device_name] = {
                'read_sectors': read_sectors,
                'writen_sectors': writen_sectors
            }
        return stats

    def _merge_disk_free_data_with_io_bps(
            self,
            disk_free_data: dict[str, dict[str, str | float]],
            disk_io_bps_data: dict[str, dict[str, float]],
        ) -> dict[Any, Any]:

        merged_data = {}
        for device, _ in disk_free_data.items():
            merged_data: dict = disk_free_data.copy()
            normalized_device_name = device.removeprefix('/dev/')
            if normalized_device_name in disk_io_bps_data:
                merged_data[device].update(disk_io_bps_data[normalized_device_name])
        return merged_data


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
