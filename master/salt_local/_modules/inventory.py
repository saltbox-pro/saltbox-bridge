# Copyright 2025-2026 Anton Karmanov

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

# Requires python>=3.7 :'=


from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from collections.abc import Generator
from functools import lru_cache

if sys.version_info >= (3, 9):
    from collections.abc import Iterable
else:
    from typing import Iterable

from enum import Enum
from typing import Any, ClassVar
from xml.etree import ElementTree

from salt.exceptions import (  # type: ignore[import-untyped]
    CommandExecutionError,
    CommandNotFoundError,
    SaltException,
    SaltInvocationError,
)

logger = logging.getLogger(__name__)

__grains__: dict[str, Any]
__salt__: dict[str, Any]


class InventoryAgentEnum(Enum):
    FI = 'fusioninventory'
    OCS = 'ocsinventory'


# FusionInventory has also:
#   - 'envs'
#   - 'operatingsystem' (has nested TZ)
#   - 'processes'
CATEGORIES = (
    'batteries',
    'bios',
    'controllers',
    'cpus',
    'drives',
    'hardware',
    'inputs',
    'local_groups',
    'local_users',
    'memories',
    'monitors',
    'networks',
    'printers',
    'slots',
    'softwares',
    'sounds',
    'storages',
    'usbdevices',
    'videos',
    'virtualmachines',
)

CATEGORY_LIST_SEPARATOR = ','
LOCAL_GROUPS_MEMBERS_SEPARATOR = ','


# Plain class because @dataclass may throw error on some Python versions because of Salt loader
class Field:  # ruff: ignore[class-as-data-structure]
    def __init__(self, name: str, value: Any) -> None:
        self.name = name
        self.value = value


class TransformationBase:
    """
    Inventory data fields transformations to make data consistent between agents.

    In base class it is possible to transform data for any agent including selective
    operations due to TransformationBase.agent. Subclasses are selective to its' agents.
    """
    _NON_CATEGORY_FIELDS: ClassVar = {'InputData', 'agent', 'process'}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Check names of transform methods to match category
        for member in dir(cls):
            if not member.startswith('_') and member not in cls._NON_CATEGORY_FIELDS and member not in CATEGORIES:
                msg = f'{cls.__name__}.{member} name does not match any category'
                raise SaltException(msg)

    InputData = Iterable[Field]
    # To use in base class for "if-based polymorphism"
    agent: InventoryAgentEnum

    @classmethod
    def process(cls, category: str, data) -> dict[str, Any]:
        fun = getattr(cls, category, cls._data_to_dict)
        return fun(data)

    @staticmethod
    def _data_to_dict(data: InputData) -> dict[str, Any]:
        return {f.name: f.value for f in data}

    @staticmethod
    def _rename_fields(data: InputData, mapping: dict[str, str]) -> Generator[Field]:
        for field in data:
            new_name = mapping.get(field.name)
            if new_name is not None:
                field.name = new_name
            yield field

    @classmethod
    def memories(cls, data: InputData) -> dict[str, Any]:
        map = cls._data_to_dict(data)
        if cls.agent is InventoryAgentEnum.FI:
            map.setdefault('numslots', 0)
        elif cls.agent is InventoryAgentEnum.OCS:
            map['numslots'] = int(map.get('numslots', 1)) - 1
        return map


class OcsTransformations(TransformationBase):
    agent = InventoryAgentEnum.OCS

    @classmethod
    def local_users(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        # FI has `gid` also, but OCS do not. `local_groups.name` may be matched with `local_user.login`
        return cls._data_to_dict(cls._rename_fields(data=data, mapping={'id_user': 'uid'}))

    @classmethod
    def local_groups(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        result = {}
        for field in data:
            if field.name == 'id_group':
                result['gid'] = field.value
            elif field.name == 'member':
                members = str(field.value).split(',')
                members.sort()
                result['members'] = LOCAL_GROUPS_MEMBERS_SEPARATOR.join(members)
            else:
                result[field.name] = field.value
        return result

    @classmethod
    def storages(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        result = cls._data_to_dict(data)
        disksize = result.get('disksize')
        if disksize is not None:
            result['disksize'] = int(float(disksize))
        return result

    @classmethod
    def usbdevices(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        return cls._data_to_dict(cls._rename_fields(data=data, mapping={'description': 'caption'}))


class FusionAgentTransformations(TransformationBase):
    agent = InventoryAgentEnum.FI

    @classmethod
    def controllers(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        map = cls._data_to_dict(data)

        manufacturer = map.get('manufacturer')
        caption = map.get('caption')
        map['manufacturer'] = ' '.join(str(item) for item in (manufacturer, caption,) if item)

        vid = map.get('vendorid')
        pid = map.get('productid')
        map['pciid'] = ':'.join(str(item) for item in (vid, pid,) if item)

        return map

    @classmethod
    def cpus(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        renamed = cls._rename_fields(
            data=data,
            mapping={
                'arch': 'cpuarch',
                'core': 'cores',
                'name': 'type',
                'thread': 'threads',
            }
        )

        return cls._data_to_dict(renamed)

    @classmethod
    def local_groups(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        result = {}
        members = []
        for field in data:
            if field.name == 'id':  # Bad model field
                result['gid'] = field.value
            elif field.name == 'member':
                members.append(field.value)
            else:
                result[field.name] = field.value
        members.sort()
        result['members'] = LOCAL_GROUPS_MEMBERS_SEPARATOR.join(members)
        return result

    @classmethod
    def local_users(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        return cls._data_to_dict(cls._rename_fields(data=data, mapping={'id': 'uid'}))

    @classmethod
    def networks(cls, data: TransformationBase.InputData) -> dict[str, Any]:
        result = cls._data_to_dict(data)

        speed = result.get('speed')
        if speed is not None:
            speed = int(speed)
            if abs(speed) >= 1000:
                speed_str = f'{speed // 1000} Gbps'
            else:
                speed_str = f'{speed} Mbps'
            result['speed'] = speed_str

        ipaddress6 = result.pop('ipaddress6', None)
        if not result.get('ipaddress') and ipaddress6 is not None:
            result['ipaddress'] = ipaddress6
            result['ipmask'] = result.pop('ipmask6', '')
            result['ipsubnet'] = result.pop('ipsubnet6', '')

        return result


def _validate_categories(categories: Iterable[str]) -> Iterable[str]:
    for cat in categories:
        if cat not in CATEGORIES:
            msg = f'Unsupported category {cat}, use available_categories() to check supported'
            raise SaltInvocationError(msg)
    return categories


def _element_to_dict(elem: ElementTree.Element, category: str) -> dict[str, Any]:
    data = [Field(name=child.tag.lower(), value=child.text or '') for child in elem]
    ia = _lookup_inventory_agent()
    return ia.transformations.process(category=category, data=data)


def _inventory_to_dict(data: str, categories: Iterable[str] = CATEGORIES) -> dict[str, Any]:
    parsed: dict[str, Any] = {}

    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as err:
        raise SaltException(err) from err

    xpath = 'CONTENT'
    content = root.find(xpath)
    if content is None:
        msg = f'Not found {xpath} tag in agent output'
        raise SaltException(msg)

    for category in categories:
        parsed[category] = [
            _element_to_dict(s, category)
            for s in content.findall(category.upper())
        ]

    return parsed


class InventoryAgent:
    def __init__(
        self,
        name: InventoryAgentEnum,
        bin: str,
        inventory_args: list[str],
        transformations: type[TransformationBase],
    ) -> None:
        self.name = name
        self.bin = bin
        self.inventory_args = inventory_args
        self.transformations = transformations
        self.inventory_cmd = self.bin, *self.inventory_args


def _get_known_agents() -> list[InventoryAgent]:
    kernel = __grains__['kernel'].lower()

    if kernel == 'windows':
        prog_files = __salt__['cmd.shell']('echo %ProgramFiles%')
        fi_bin = rf'{prog_files}\FusionInventory-Agent\fusioninventory-agent.bat'
    else:
        fi_bin = 'fusioninventory-agent'

    agents = [
        InventoryAgent(
            name=InventoryAgentEnum.FI,
            bin=fi_bin,
            inventory_args=['--scan-homedirs', '--local', '-'],
            transformations=FusionAgentTransformations
        ),
    ]
    if kernel != 'windows':
        agents.append(
            InventoryAgent(
                name=InventoryAgentEnum.OCS,
                bin='ocsinventory-agent',
                inventory_args=['--scan-homedirs', '--stdout'],
                transformations=OcsTransformations,
            ),
        )
    return agents


@lru_cache(maxsize=None)
def _lookup_inventory_agent() -> InventoryAgent:
    known_agents = _get_known_agents()
    for agent in known_agents:
        if shutil.which(agent.bin) is not None:
            logger.info('Using %s', agent.bin)
            return agent
    else:
        agents = tuple(agent.bin for agent in known_agents)
        msg = f'Not found any compatible inventory agent executable {agents}'
        raise CommandNotFoundError(msg)


def agent_bin() -> str:
    """
    Which agent executable file will be used to collect the data by inventory.get

    CLI Example:

    .. code-block:: bash

        salt '*' inventory.agent_bin
    """
    return _lookup_inventory_agent().bin


def get(only='', exclude='') -> dict[str, Any]:
    """
    Get inventory data

    only
        list of categories to return. All available if empty.
        See avaliable with `inventory.available_categories`.

    exclude
        Exclude specified categories from return. Affects `only` list.

    CLI Example:

    .. code-block:: bash

        salt '*' inventory.get exclude='softwares,bios'
    """
    if only:
        only_set = set(_validate_categories(only.split(CATEGORY_LIST_SEPARATOR)))
        categories = only_set
    else:
        categories = set(CATEGORIES)

    if exclude:
        exclude_set = set(_validate_categories(exclude.split(CATEGORY_LIST_SEPARATOR)))
        categories -= exclude_set

    agent = _lookup_inventory_agent()
    try:
        result = subprocess.run(agent.inventory_cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as err:
        cmd_str = ' '.join(agent.inventory_cmd)
        logger.error('Command failed: "%s", stderr follows', cmd_str)
        for line in err.stderr.decode().splitlines():
            logger.error(line)
        msg = f'Command failed: "{cmd_str}"'
        raise CommandExecutionError(msg) from None

    return _inventory_to_dict(result.stdout.decode(), categories=categories)


def available_categories() -> Iterable[str]:
    """
    List supported categories of inventory data
    """
    return CATEGORIES


if __name__ == '__main__':
    import json

    try:
        _ = __grains__
    except NameError:
        # Stub context
        __grains__ = {
            'kernel': 'Linux'
        }
        __salt__ = {}

    print(json.dumps(get(), indent=4))
