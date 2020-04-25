# import logging
# from dataclasses import dataclass
# from enum import Enum, auto
# from typing import Any, List, Mapping, MutableMapping, Optional, Type

from enum import Enum, auto
from typing import List

class _AutoName(Enum):
    def __str__(self):
        return '{}'.format(self.value)

    @staticmethod
    def _generate_next_value_(
        name: str, _start: int, _count: int, _last_values: List[str]
    ) -> str:
        return name

class ProvisioningStatus(str, _AutoName):
    ENVIRONMENT_CREATED = auto()
    RESIZED_INSTANCE = auto()
    STOPPED_INSTANCE = auto()
    RESTARTED_INSTANCE = auto()
    INSTANCE_STABLE = auto()