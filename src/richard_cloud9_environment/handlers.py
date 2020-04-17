import logging
from time import sleep
from typing import Any, MutableMapping, Optional

from cloudformation_cli_python_lib import (
    Action,
    HandlerErrorCode,
    OperationStatus,
    ProgressEvent,
    Resource,
    SessionProxy,
    exceptions,
)

from .models import ResourceHandlerRequest, ResourceModel

# Use this logger to forward log messages to CloudWatch Logs.
LOG = logging.getLogger(__name__)
TYPE_NAME = "Richard::Cloud9::Environment"

resource = Resource(TYPE_NAME, ResourceModel)
test_entrypoint = resource.test_entrypoint

def resize_ebs(instance_id: str, volume_size: int, ec2_client) -> None:
    instance = ec2_client.describe_instances(Filters=[{'Name': 'instance-id', 'Values': [instance_id]}])['Reservations'][0]['Instances'][0]
    block_volume_id = instance['BlockDeviceMappings'][0]['Ebs']['VolumeId']
    try:
        ec2_client.modify_volume(VolumeId=block_volume_id,Size=volume_size)
    except Exception as e:
        print(e)
        raise Exception(e)

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
            if not request.desiredResourceState.Name:
                name = request.logicalResourceIdentifier
            else:
                name = request.desiredResourceState.Name

            c9_client = session.client("cloud9")
            response = c9_client.create_environment_ec2(
                name=name,
                instanceType=model.InstanceType
            )
            ec2_client = session.client("ec2")
            print("environment id: {}".format(response['environmentId']))
            instance_filter = ec2_client.describe_instances(Filters=[{'Name':'tag:aws:cloud9:environment', 'Values': [response['environmentId']]}])
            while len(instance_filter['Reservations']) <1:
                sleep(1)
                instance_filter = ec2_client.describe_instances(Filters=[{'Name':'tag:aws:cloud9:environment', 'Values': [response['environmentId']]}])
            instance_id = instance_filter['Reservations'][0]['Instances'][0]['InstanceId']
            if request.desiredResourceState.EBSVolumeSize:
                resize_ebs(instance_id, int(request.desiredResourceState.EBSVolumeSize), ec2_client)
            progress.resourceModel.InstanceId = instance_id
            
        # Setting Status to success will signal to cfn that the operation is complete
        progress.status = OperationStatus.SUCCESS
    except TypeError as e:
        # exceptions module lets CloudFormation know the type of failure that occurred
        raise exceptions.InternalFailure(f"was not expecting type {e}")
        # this can also be done by returning a failed progress event
        # return ProgressEvent.failed(HandlerErrorCode.InternalFailure, f"was not expecting type {e}")
    return progress


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
    return progress


@resource.handler(Action.DELETE)
def delete_handler(
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
