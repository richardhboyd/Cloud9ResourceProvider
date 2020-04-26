import logging
from time import sleep
import json
import base64
from typing import Any, Mapping, MutableMapping, Optional

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
if [ $(readlink -f /dev/xvda) = "/dev/xvda" ]
then
  # Rewrite the partition table so that the partition takes up all the space that it can.
  sudo growpart /dev/xvda 1
  # Expand the size of the file system.
  sudo resize2fs /dev/xvda1
else
  # Rewrite the partition table so that the partition takes up all the space that it can.
  sudo growpart /dev/nvme0n1
  # Expand the size of the file system.
  sudo resize2fs /dev/nvme0n1p1
fi
    """

def get_name_from_request(request: ResourceHandlerRequest) -> str:
    if request.desiredResourceState.Name:
        return request.desiredResourceState.Name
    else:
        import hashlib
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y/%m/%d-%H:%M:%S").encode('utf-8')
        m = hashlib.sha256(timestamp).hexdigest()[:6]
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
        LOG.info("starting ENVIRONMENT_CREATED with callback_context\n{}\nand request\n{}".format(callback_context, request))
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=request.desiredResourceState,
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
                progress.resourceModel.InstanceId = instance_id
                progress.callbackContext["INSTANCE_ID"] = instance_id
                progress.callbackContext["LOCAL_STATUS"] = ProvisioningStatus.INSTANCE_STABLE
        except Exception as e:
            LOG.info('throwing: {}'.format(e))
            raise(e)
        LOG.info("returning progress from ENVIRONMENT_CREATED {}".format(progress))
        return progress
 
    def INSTANCE_STABLE(self, request, callback_context, session) -> ProgressEvent:
        LOG.info("starting INSTANCE_STABLE with callback_context\n{}\nand request\n{}".format(callback_context, request))
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=request.desiredResourceState,
            callbackContext=callback_context,
            callbackDelaySeconds=15
        )
        instance_id = callback_context["INSTANCE_ID"]
        try: 
            ec2_client = session.client("ec2")
            if request.desiredResourceState.EBSVolumeSize:
                resize_ebs(instance_id, int(progress.resourceModel.EBSVolumeSize), ec2_client)
            progress.callbackContext["LOCAL_STATUS"] = ProvisioningStatus.RESIZED_INSTANCE
        except Exception as e:
            LOG.info('Can\'t resize instance: {}'.format(e))
            raise(e)
        LOG.info("returning progress from INSTANCE_STABLE {}".format(progress))
        return progress

    def RESIZED_INSTANCE(self, request, callback_context, session) -> ProgressEvent:
        LOG.info("starting RESIZED_INSTANCE with callback_context\n{}\nand request\n{}".format(callback_context, request))
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=request.desiredResourceState,
            callbackContext=callback_context,
            callbackDelaySeconds=15
        )
        LOG.info("starting RESIZED_INSTANCE with progress\n{}\nand request\n{}".format(progress, request))
        instance_id = callback_context["INSTANCE_ID"]
        LOG.info("instance id: {}".format(instance_id))
        ec2_client = session.client("ec2")
        instances = ec2_client.describe_instances(InstanceIds=[instance_id])
        instance_state = instances['Reservations'][0]['Instances'][0]['State']['Name']
        if instance_state == 'running':
            LOG.info("Instance Running, attempting to stop instance {}".format(instance_id))
            response = ec2_client.stop_instances(InstanceIds=[instance_id])
            progress.callbackContext["LOCAL_STATUS"] = ProvisioningStatus.STOPPED_INSTANCE
        else:
            LOG.info("Instance isn't running yet")
        LOG.info("returning progress from RESIZED_INSTANCE {}".format(progress))
        return progress
 
    def STOPPED_INSTANCE(self, request, callback_context, session) -> ProgressEvent:
        LOG.info("starting STOPPED_INSTANCE with callback_context\n{}\nand request\n{}".format(callback_context, request))
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=request.desiredResourceState,
            callbackContext=callback_context,
            callbackDelaySeconds=15
        )
        instance_id = callback_context["INSTANCE_ID"]
        ec2_client = session.client("ec2")
        # Verify that the instance is stopped
        instance_filter = ec2_client.describe_instances(Filters=[{'Name':'tag:aws:cloud9:environment', 'Values': [callback_context["ENVIRONMENT_ID"]]}])
        instance_state = instance_filter['Reservations'][0]['Instances'][0]['State']['Name']
        LOG.info("Instance State: {}".format(instance_state))
        if instance_state != 'stopped':
            LOG.info("instance is still running")
        else:
            LOG.info("instance stopped. Attempting to get current UserData from {}".format(instance_id))
            get_userdata_response = ec2_client.describe_instance_attribute(Attribute='userData', InstanceId=instance_id)
            user_data = base64.b64decode(get_userdata_response['UserData']['Value']).decode("utf-8")
            final_user_data = get_preamble() + user_data + base64.b64decode(request.desiredResourceState.UserData).decode("utf-8")
            ec2_client.modify_instance_attribute(InstanceId=instance_id, UserData={'Value': final_user_data})
            ec2_client.start_instances(InstanceIds=[instance_id])
            progress.callbackContext["LOCAL_STATUS"] = ProvisioningStatus.RESTARTED_INSTANCE
            LOG.info("exiting STOPPED_INSTANCE State")
        LOG.info("returning progress from STOPPED_INSTANCE {}".format(progress))
        return progress

    def RESTARTED_INSTANCE(self, request, callback_context, session) -> ProgressEvent:
        LOG.info("starting RESTARTED_INSTANCE with callback_context\n{}\nand request\n{}".format(callback_context, request))
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=request.desiredResourceState,
            callbackContext=callback_context,
            callbackDelaySeconds=15
        )
        instance_id = callback_context["INSTANCE_ID"]
        ec2_client = session.client("ec2")
        instances = ec2_client.describe_instances(InstanceIds=[instance_id])
        LOG.info("Getting Instance State")
        instance_state = instances['Reservations'][0]['Instances'][0]['State']['Name']
        if instance_state == 'running':
            LOG.info("Instance is running")
            progress.status = OperationStatus.SUCCESS
        LOG.info("returning progress from RESTARTED_INSTANCE {}".format(progress))
        return progress

@resource.handler(Action.CREATE)
def create_handler(
    session: Optional[SessionProxy], 
    request: ResourceHandlerRequest,
    callback_context: MutableMapping[str, Any],
) -> ProgressEvent:
    try:
        if isinstance(session, SessionProxy):
            if callback_context and callback_context["LOCAL_STATUS"]:
                LOG.info(callback_context)
                progress = Router().progress_to_step(request, callback_context, session)
                return progress
            else:
                LOG.info("starting NEW RESOURCE with request\n{}".format(request))
                progress: ProgressEvent = ProgressEvent(
                    status=OperationStatus.IN_PROGRESS,
                    resourceModel=request.desiredResourceState,
                    callbackContext=callback_context,
                    callbackDelaySeconds=15
                )
                c9_client = session.client("cloud9")
                env_name = get_name_from_request(request)
                if request.desiredResourceState.OwnerArn:
                    owner_arn = request.desiredResourceState.OwnerArn
                else:
                    owner_arn = "arn:aws:iam::{}:root".format(session.client('sts').get_caller_identity()['Account'])
                response = c9_client.create_environment_ec2(
                    name=env_name,
                    instanceType=request.desiredResourceState.InstanceType,
                    ownerArn=owner_arn
                )
                LOG.info("environment id: {}".format(response['environmentId']))
                model: ResourceModel = request.desiredResourceState
                model.Name = env_name
                model.EnvironmentId = response['environmentId']
                progress.callbackContext["ENVIRONMENT_NAME"] = env_name
                progress.callbackContext["ENVIRONMENT_ID"] = response['environmentId']
                progress.callbackContext["LOCAL_STATUS"] = ProvisioningStatus.ENVIRONMENT_CREATED
                progress.status = OperationStatus.IN_PROGRESS
                progress.resourceModel: ResourceModel = model
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
    session: Optional[SessionProxy], provider_session: Optional[SessionProxy], platform_session: Optional[SessionProxy],
    request: ResourceHandlerRequest,
    callback_context: MutableMapping[str, Any],
) -> ProgressEvent:
    # TODO: put code here
    return ProgressEvent(
        status=OperationStatus.SUCCESS,
        resourceModels=[],
    )
