import pytest

from .context import interface


def test_base_resource_model__serialize():
    brm = interface.EnvironmentCreated()
    print()
    print(brm._serialize())
    print(interface.ProvisioningStatus._deserialize(brm._serialize()))
    print(isinstance(interface.ProvisioningStatus._deserialize(brm._serialize()), interface.EnvironmentCreated))

    assert True