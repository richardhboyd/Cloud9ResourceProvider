import inspect
import logging
from time import sleep
import json
import base64
from typing import Any, MutableMapping, Optional
from functools import singledispatch

from cloudformation_cli_python_lib import (
    Action,
    HandlerErrorCode,
    OperationStatus,
    ProgressEvent,
    Resource,
    SessionProxy,
    exceptions,
    identifier_utils,
)

from .interface import (
    ProvisioningStatus,
    EnvironmentCreated,
    RoleCreated,
    ProfileAttached,
    CommandSent,
    InstanceStable,
    ResizedInstance
)

from .models import ResourceHandlerRequest, ResourceModel

# Use this logger to forward log messages to CloudWatch Logs.
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
TYPE_NAME = "Richard::Cloud9::CustomEC2"

resource = Resource(TYPE_NAME, ResourceModel)
test_entrypoint = resource.test_entrypoint

def get_or_create_role(iam_client, role_name, instance_id, environment_id) -> str:
    try:
        response = iam_client.create_role(
            Path='/cdk/cloud9/environment',
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(
                {
                    'Version': '2012-10-17',
                    'Statement': {
                        'Effect': 'Allow',
                        'Principal': {'Service': ['ec2.amazonaws.com', 'cloud9.amazonaws.com']},
                        'Action': 'sts:AssumeRole'
                    }
                }),
            Description='EC2 Instance Profile Role for Cloud9 to create environment',
        )
    except iam_client.exceptions.EntityAlreadyExistsException as _:
        response = iam_client.get_role(RoleName=role_name)
    return response['Role']['RoleName']

@singledispatch
def create(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    LOG.info("starting NEW RESOURCE with request\n{}".format(request))
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    progress.callbackContext["LOCAL_STATUS"] = EnvironmentCreated()
    return progress

@create.register(EnvironmentCreated)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    progress.callbackContext["LOCAL_STATUS"] = RoleCreated()
    return progress
    
@create.register(RoleCreated)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    progress.callbackContext["LOCAL_STATUS"] = ResizedInstance()
    return progress

@create.register(ResizedInstance)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    progress.callbackContext["LOCAL_STATUS"] = InstanceStable()
    return progress

@create.register(InstanceStable)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    progress.callbackContext["LOCAL_STATUS"] = ProfileAttached()
    return progress

@create.register(ProfileAttached)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    progress.callbackContext["LOCAL_STATUS"] = CommandSent()
    return progress

@create.register(CommandSent)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )

    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.SUCCESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    return progress

@resource.handler(Action.CREATE)
def create_handler(
    session: Optional[SessionProxy],
    request: ResourceHandlerRequest,
    callback_context: MutableMapping[str, Any],
) -> ProgressEvent:
    model = request.desiredResourceState
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=model,
    )
    try:
        if isinstance(session, SessionProxy):
            if callback_context:
                provisioning_state = ProvisioningStatus._deserialize(callback_context.get("LOCAL_STATUS"))
            else:
                provisioning_state = None
            progress = create(provisioning_state, request, callback_context, session)
            LOG.info(f"returning from dispatch: {progress}")
            return progress
    except TypeError as e:
        raise exceptions.InternalFailure(f"was not expecting type {e}")


@resource.handler(Action.UPDATE)
def update_handler(
    session: Optional[SessionProxy],
    request: ResourceHandlerRequest,
    callback_context: MutableMapping[str, Any],
) -> ProgressEvent:
    model = request.desiredResourceState
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=model,
    )
    # TODO: put code here
    return read_handler(session, request, callback_context)


@resource.handler(Action.DELETE)
def delete_handler(
    session: Optional[SessionProxy],
    request: ResourceHandlerRequest,
    callback_context: MutableMapping[str, Any],
) -> ProgressEvent:
    model = request.desiredResourceState
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=None,
    )
    # TODO: put code here
    return progress


@resource.handler(Action.READ)
def read_handler(
    session: Optional[SessionProxy],
    request: ResourceHandlerRequest,
    callback_context: MutableMapping[str, Any],
) -> ProgressEvent:
    model = request.desiredResourceState
    # TODO: put code here
    return ProgressEvent(
        status=OperationStatus.SUCCESS,
        resourceModel=model,
    )


@resource.handler(Action.LIST)
def list_handler(
    session: Optional[SessionProxy],
    request: ResourceHandlerRequest,
    callback_context: MutableMapping[str, Any],
) -> ProgressEvent:
    # TODO: put code here
    return ProgressEvent(
        status=OperationStatus.SUCCESS,
        resourceModels=[],
    )
