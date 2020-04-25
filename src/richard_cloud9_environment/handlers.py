import logging
from time import sleep
import json
import base64
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

from .interface import (
    ProvisioningStatus
)

from .models import ResourceHandlerRequest, ResourceModel

# Use this logger to forward log messages to CloudWatch Logs.
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.DEBUG)
TYPE_NAME = "Richard::Cloud9::Environment"

resource = Resource(TYPE_NAME, ResourceModel)
test_entrypoint = resource.test_entrypoint

def get_preamble():
    return """Content-Type: multipart/mixed; boundary="//"
MIME-Version: 1.0

--//
Content-Type: text/cloud-config; charset="us-ascii"
MIME-Version: 1.0
Content-Transfer-Encoding: 7bit
Content-Disposition: attachment; filename="cloud-config.txt"

#cloud-config
cloud_final_modules:
- [scripts-user, always]

--//
Content-Type: text/x-shellscript; charset="us-ascii"
MIME-Version: 1.0
Content-Transfer-Encoding: 7bit
Content-Disposition: attachment; filename="userdata.txt"
    """

def get_name_from_request(request: ResourceHandlerRequest) -> str:
    if request.desiredResourceState.Name:
        return request.desiredResourceState.Name
    else:
        # import hashlib
        # from datetime import datetime
        # timestamp = datetime.now().strftime("%Y/%m/%d-%H:%M:%S").encode('utf-8')
        # m = hashlib.sha256(timestamp).hexdigest()[:6]
        m = "E"
        return "{}-{}".format(request.logicalResourceIdentifier, m)

def resize_ebs(instance_id: str, volume_size: int, ec2_client) -> None:
    instance = ec2_client.describe_instances(Filters=[{'Name': 'instance-id', 'Values': [instance_id]}])['Reservations'][0]['Instances'][0]
    block_volume_id = instance['BlockDeviceMappings'][0]['Ebs']['VolumeId']
    try:
        ec2_client.modify_volume(VolumeId=block_volume_id,Size=volume_size)
    except Exception as e:
        LOG.info(e)
        raise Exception(e)

class Router(object):
    def progress_to_step(self, request, callback_context, session) -> ProgressEvent:
        method = getattr(self, str(callback_context["LOCAL_STATUS"]))
        return method(request, callback_context, session)
 
    def ENVIRONMENT_CREATED(self, request, callback_context, session) -> ProgressEvent:
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context,
            callbackDelaySeconds=15
        )
        environment_id = callback_context["ENVIRONMENT_ID"]
        LOG.info("environment id: {}".format(environment_id))
        try: 
            ec2_client = session.client("ec2")
            instance_filter = ec2_client.describe_instances(Filters=[{'Name':'tag:aws:cloud9:environment', 'Values': [environment_id]}])
            instance_id = instance_filter['Reservations'][0]['Instances'][0]['InstanceId']
            instance_state = instance_filter['Reservations'][0]['Instances'][0]['State']['Name']
            c9_client = session.client("cloud9")
            environment_status = c9_client.describe_environment_status(environmentId=environment_id)
            LOG.info("Checking Environment and instance status")
            if (environment_status['status'] == 'ready') and (instance_state == 'running'):
                LOG.info("environment is ready and instance is running")
                callback_context["LOCAL_STATUS"] = ProvisioningStatus.RESIZED_INSTANCE
                progress.resourceModel.InstanceId = instance_id
                progress.callbackContext = callback_context
                
        except Exception as e:
            LOG.info('throwing: {}'.format(e))
        return progress
 
    # def INSTANCE_STABLE(self, request, callback_context, session) -> ProgressEvent:
    #     model: ResourceModel = request.desiredResourceState
    #     progress: ProgressEvent = ProgressEvent(
    #         status=OperationStatus.IN_PROGRESS,
    #         resourceModel=model,
    #         callbackContext=callback_context,
    #         callbackDelaySeconds=30
    #     )
    #     instance_id = model.InstanceId
    #     try: 
    #         ec2_client = session.client("ec2")
    #         if request.desiredResourceState.EBSVolumeSize:
    #             resize_ebs(instance_id, request.desiredResourceState.EBSVolumeSize, ec2_client)
    #         callback_context["LOCAL_STATUS"] = ProvisioningStatus.RESIZED_INSTANCE
    #         progress.callbackContext = callback_context
    #     except Exception as e:
    #         LOG.info('Can\'t resize instance: {}'.format(e))
    #     return progress

    def RESIZED_INSTANCE(self, request, callback_context, session) -> ProgressEvent:
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context,
            callbackDelaySeconds=30
        )
        instance_id = model.InstanceId
        LOG.info("instance id: {}".format(instance_id))
        ec2_client = session.client("ec2")
        instances = ec2_client.describe_instances(InstanceIds=[instance_id])
        LOG.info("Getting Instance ID")
        instance_state = instances['Reservations'][0]['Instances'][0]['State']['Name']
        if instance_state == 'running':
            response = ec2_client.stop_instances(InstanceIds=[instance_id])
            callback_context["LOCAL_STATUS"] = ProvisioningStatus.STOPPED_INSTANCE
            progress.callbackContext = callback_context
        else:
            LOG.info("Instance isn't running yet")
            return progress

        return progress
 
    def STOPPED_INSTANCE(self, request, callback_context, session) -> ProgressEvent:
        LOG.info("Entering STOPPED_INSTANCE State")
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context,
            callbackDelaySeconds=30
        )
        instance_id = model.InstanceId
        commands = ['sudo growpart /dev/xvda 1; sudo resize2fs /dev/xvda1 || sudo resize2fs /dev/nvme0n1p1']
        ec2_client = session.client("ec2")
        # Verify that the instance is stopped
        instance_filter = ec2_client.describe_instances(Filters=[{'Name':'tag:aws:cloud9:environment', 'Values': [callback_context["ENVIRONMENT_ID"]]}])
        instance_state = instance_filter['Reservations'][0]['Instances'][0]['State']['Name']
        LOG.info("Instance State: {}".format(instance_state))
        if instance_state != 'stopped':
            LOG.info("instance is still running")
            return progress
        else:
            LOG.info("instance stopped. Attempting to get current UserData from {}".format(instance_id))
            get_userdata_response = ec2_client.describe_instance_attribute(Attribute='userData', InstanceId=instance_id)
            user_data = get_userdata_response['UserData']['Value']
            final_user_data = get_preamble() + user_data + base64.b64decode(model.UserData).decode("utf-8")
            ec2_client.modify_instance_attribute(InstanceId=instance_id, UserData={'Value': final_user_data})
            ec2_client.start_instances(InstanceIds=[instance_id])
            callback_context["LOCAL_STATUS"] = ProvisioningStatus.RESTARTED_INSTANCE
            progress.callbackContext = callback_context
            LOG.info("exiting STOPPED_INSTANCE State")
            return progress

    def RESTARTED_INSTANCE(self, request, callback_context, session) -> ProgressEvent:
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context,
            callbackDelaySeconds=30
        )
        instance_id = model.InstanceId
        ec2_client = session.client("ec2")
        instances = ec2_client.describe_instances(InstanceIds=[instance_id])
        LOG.info("Getting Instance ID")
        instance_state = instances['Reservations'][0]['Instances'][0]['State']['Name']
        if instance_state == 'running':
            LOG.info("Instance is running")
            progress.status = OperationStatus.SUCCESS
        return progress

@resource.handler(Action.CREATE)
def create_handler(session: Optional[SessionProxy], request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any],) -> ProgressEvent:
    try:
        if isinstance(session, SessionProxy):
            if callback_context:
                LOG.info(callback_context)
                progress = Router().progress_to_step(request, callback_context, session)
                return progress
            else:
                model: ResourceModel = request.desiredResourceState
                progress: ProgressEvent = ProgressEvent(
                    status=OperationStatus.IN_PROGRESS,
                    resourceModel=model,
                    callbackContext=callback_context,
                    callbackDelaySeconds=15
                )
                c9_client = session.client("cloud9")
                response = c9_client.create_environment_ec2(
                    name=get_name_from_request(request),
                    instanceType=request.desiredResourceState.InstanceType
                )
                LOG.info("environment id: {}".format(response['environmentId']))
                callback_context["ENVIRONMENT_ID"] = response['environmentId']
                callback_context["LOCAL_STATUS"] = ProvisioningStatus.ENVIRONMENT_CREATED
                progress.callbackContext=callback_context
                progress.status = OperationStatus.IN_PROGRESS
                return progress

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
    progress.status = OperationStatus.SUCCESS
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
    progress.status = OperationStatus.SUCCESS
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
