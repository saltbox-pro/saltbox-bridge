# Copyright 2025 Anton Karmanov

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


from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, TypeAlias
from xml.etree import ElementTree

from salt.exceptions import (  # type: ignore[import-untyped]
    CommandExecutionError,
    CommandNotFoundError,
    SaltException,
    SaltInvocationError,
)

logger = logging.getLogger(__name__)


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
    'networks',
    'ports',
    'softwares',
    'sounds',
    'storages',
    'users',
    'videos',
    'virtualmachines',
)


@dataclass
class Field:
    name: str
    value: Any


class TransformationBase:
    """
    Inventory data fields transformations to make data consistent between agents.

    In base class it is possible to transform data for any agent including selective
    operations due to TransformationBase.agent. Subclasses are selective to its' agents.

    OCS Inventory Agent format is preffered for now.
    """
    _NON_CATEGORY_FIELDS: ClassVar = {'InputData', 'agent', 'process'}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Check names of transform methods to match category
        for member in dir(cls):
            if not member.startswith('_') and member not in cls._NON_CATEGORY_FIELDS and member not in CATEGORIES:
                msg = f'{cls.__name__}.{member} name does not match any category'
                raise SaltException(msg)

    InputData: TypeAlias = Iterable[Field]
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
            if (new_name := mapping.get(field.name)) is not None:
                field.name = new_name
            yield field

    @classmethod
    def local_groups(cls, data: InputData) -> dict[str, Any]:
        result = {}
        for field in data:
            if field.name == 'id':  # Bad model field
                result['gid'] = field.value
            elif field.name == 'member':
                result.setdefault('members', []).append(field.value)
            else:
                result[field.name] = field.value
        return result

    @classmethod
    def memories(cls, data: InputData) -> dict[str, Any]:
        map = cls._data_to_dict(data)
        if cls.agent is InventoryAgentEnum.FI:
            map.setdefault('numslots', 0)
        elif cls.agent is InventoryAgentEnum.OCS:
            map['numslots'] = map.get('numslots', 1) - 1
        return map


class OcsTransformations(TransformationBase):
    InputData: TypeAlias = TransformationBase.InputData
    agent = InventoryAgentEnum.OCS

    @classmethod
    def local_users(cls, data: InputData) -> dict[str, Any]:
        # FI has `gid` also, but OCS do not. `local_groups.name` may be matched with `local_user.login`
        return cls._data_to_dict(cls._rename_fields(data=data, mapping={'id_user': 'uid'}))


class FusionAgentTransformations(TransformationBase):
    agent = InventoryAgentEnum.FI
    InputData: TypeAlias = TransformationBase.InputData

    @classmethod
    def controllers(cls, data: InputData) -> dict[str, Any]:
        map = cls._data_to_dict(data)

        manufacturer = map.get('manufacturer')
        caption = map.get('caption')
        map['manufacturer'] = ' '.join(str(item) for item in (manufacturer, caption,) if item)

        vid = map.get('vendorid')
        pid = map.get('productid')
        map['pciid'] = ':'.join(str(item) for item in (vid, pid,) if item)

        return map

    @classmethod
    def cpus(cls, data: InputData) -> dict[str, Any]:
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
    def local_users(cls, data: InputData) -> dict[str, Any]:
        return cls._data_to_dict(cls._rename_fields(data=data, mapping={'id': 'uid'}))


def _validate_categories(categories: Iterable[str]) -> Iterable[str]:
    for cat in categories:
        if cat not in CATEGORIES:
            msg = f'Unsupported category {cat}, use available_categories() to check supported'
            raise SaltInvocationError(msg)
    return categories


def _element_to_dict(elem: ElementTree.Element, category: str) -> dict[str, Any]:
    data = [Field(name=child.tag.lower(), value=child.text or '') for child in elem]
    return INVENTORY_AGENT.transformations.process(category=category, data=data)


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


@dataclass
class InventoryAgent:
    name: InventoryAgentEnum
    bin: str
    inventory_args: list[str]
    transformations: type[TransformationBase]

    @property
    def inventory_cmd(self) -> list[str]:
        return [self.bin, *self.inventory_args]


KNOWN_AGENTS = (
    InventoryAgent(
        name=InventoryAgentEnum.FI,
        bin='fusioninventory-agent',
        inventory_args=['--scan-homedirs', '--local', '-'],
        transformations=FusionAgentTransformations
    ),
    InventoryAgent(
        name=InventoryAgentEnum.OCS,
        bin='ocsinventory-agent',
        inventory_args=['--scan-homedirs', '--stdout'],
        transformations=OcsTransformations,
    ),
)


def _lookup_inventory_agent() -> InventoryAgent:
    for agent in KNOWN_AGENTS:
        if shutil.which(agent.bin) is not None:
            return agent
    else:
        agents = tuple(agent.bin for agent in KNOWN_AGENTS)
        msg = f'Not found compatible inventory agent {agents}'
        raise CommandNotFoundError(msg)


INVENTORY_AGENT = _lookup_inventory_agent()


def get(only: list[str] | None = None, exclude: list[str] | None = None) -> dict[str, Any]:
    """
    Get inventory data

    only
        list of categories to return. All available if empty.
        See avaliable with `inventory.available_categories`.

    exclude
        Exclude specified categories from return. Affects `only` list.

    CLI Example:

    .. code-block:: bash

        salt '*' inventory.get exclude=['softwares','bios']
    """
    if only:
        categories = set(_validate_categories(only))
    else:
        categories = set(CATEGORIES)

    if exclude:
        categories -= set(_validate_categories(exclude))

    try:
        result = subprocess.run(INVENTORY_AGENT.inventory_cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as err:
        cmd_str = ' '.join(INVENTORY_AGENT.inventory_cmd)
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
    print(json.dumps(get(), indent=4))
