# Copyright 2025 Ivan Moshkov

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

from saltbox_bridge.job_runner_service import start as start_job_runner

__opts__: dict
__salt__: dict

LOGGER = logging.getLogger(__name__)


def __virtual__() -> bool | tuple[bool, str]:  # ruff: ignore[dunder-function-name]
    if __opts__['__role'] != 'master':  # ruff: ignore[undefined-name]
        return False, f'{__name__} runs on master only'
    return True


def start() -> None:
    """Start a salt.box service."""

    LOGGER.info('Starting salt.box job runner as an engine')
    start_job_runner(salt_opts=__opts__)  # ruff: ignore[undefined-name]
