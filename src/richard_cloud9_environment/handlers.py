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
TYPE_NAME = "Richard::Cloud9::Environment"

resource = Resource(TYPE_NAME, ResourceModel)
test_entrypoint = resource.test_entrypoint

def get_name_from_request(request: ResourceHandlerRequest) -> str:
    if request.desiredResourceState.Name:
        return request.desiredResourceState.Name
    else:
        return request.logicalResourceIdentifier

def create_environemnt(request: ResourceHandlerRequest, session: SessionProxy) -> str:
    c9_client = session.client("cloud9")
    response = c9_client.create_environment_ec2(
        name=get_name_from_request(request),
        instanceType=request.desiredResourceState.InstanceType
    )
    print("environment id: {}".format(response['environmentId']))
    return response['environmentId']

def resize_ebs(instance_id: str, volume_size: int, ec2_client) -> None:
    instance = ec2_client.describe_instances(Filters=[{'Name': 'instance-id', 'Values': [instance_id]}])['Reservations'][0]['Instances'][0]
    block_volume_id = instance['BlockDeviceMappings'][0]['Ebs']['VolumeId']
    try:
        ec2_client.modify_volume(VolumeId=block_volume_id,Size=volume_size)
    except Exception as e:
        print(e)
        raise Exception(e)

def get_or_create_role(iam_client, role_name, instance_id, environemnt_id):
    try:
        response = iam_client.create_role(
            Path='/',
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(
                {
                    'Version': '2012-10-17',
                    'Statement': {
                        'Effect': 'Allow',
                        'Principal': {'Service': 'ec2.amazonaws.com'},
                        'Action': 'sts:AssumeRole'
                    }
                }),
            Description='EC2 Instance Profile Role',
            Tags=[
                {
                    'Key': 'EC2 Instance',
                    'Value': instance_id
                },
                {
                    'Key': 'Cloud9 Environment',
                    'Value': environemnt_id
                },
            ]
        )
    except iam_client.exceptions.EntityAlreadyExistsException as e:
        response = iam_client.get_role(RoleName=role_name)
    
    return response

class Router(object):
    def progress_to_step(self, argument, request, callback_context, session) -> ProgressEvent:
        method = getattr(self, str(argument), lambda: "Invalid month")
        return method(request, callback_context, session)
 
    def ENVIRONMENT_CREATED(self, request, callback_context, session) -> ProgressEvent:
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context
        )
        environment_id = callback_context["ENVIRONMENT_ID"]
        print("environment id: {}".format(environment_id))
        try: 
            ec2_client = session.client("ec2")
            instance_filter = ec2_client.describe_instances(Filters=[{'Name':'tag:aws:cloud9:environment', 'Values': [environment_id]}])
            print("Getting Instance ID")
            instance_id = instance_filter['Reservations'][0]['Instances'][0]['InstanceId']
            print("Instance ID: {}".format(instance_id))
            if progress.resourceModel.EBSVolumeSize:
                resize_ebs(instance_id, int(progress.resourceModel.EBSVolumeSize), ec2_client)
            progress.resourceModel.InstanceId = instance_id
            callback_context["LOCAL_STATUS"] = ProvisioningStatus.RESIZED_INSTANCE
            progress.callbackContext = callback_context
        except Exception as e:
            print(e)
        return progress
 
    def RESIZED_INSTANCE(self, request, callback_context, session) -> ProgressEvent:
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context
        )
        instance_id = progress.resourceModel.InstanceId
        print("instance id: {}".format(instance_id))
        try:
            iam_client = session.client("iam")
            print("creating IAM Role")
            create_role_response = get_or_create_role(iam_client, '{}-InstanceProfileRole'.format(get_name_from_request(request)), instance_id, callback_context["ENVIRONMENT_ID"])
            print("Attatching managed policy to Role")
            attatch_policy_response = iam_client.attach_role_policy(
                RoleName=create_role_response['Role']['RoleName'],
                PolicyArn='arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'
            )
            print("Creating Instance Profile")
            create_instance_profile_response = iam_client.create_instance_profile(
                InstanceProfileName='{}-InstanceProfile'.format(get_name_from_request(request))
            )
            print("Attatching Role to Instance Profile")
            response = iam_client.add_role_to_instance_profile(
                InstanceProfileName='{}-InstanceProfile'.format(get_name_from_request(request)),
                RoleName=create_role_response['Role']['RoleName']
            )
            print("Associating Instance Profile with Instance")
            sleep(15)
            ec2_client = session.client("ec2")
            associate_profile_response = ec2_client.associate_iam_instance_profile(
                IamInstanceProfile={
                    'Arn': create_instance_profile_response['InstanceProfile']['Arn']
                },
                InstanceId=instance_id
            )
            callback_context["ASSOCIATION_ID"] = associate_profile_response['IamInstanceProfileAssociation']['AssociationId']
            callback_context["LOCAL_STATUS"] = ProvisioningStatus.ASSOCIATED_PROFILE
            progress.callbackContext = callback_context
        except Exception as e:
            print(e)
        return progress
 
    def ASSOCIATED_PROFILE(self, request, callback_context, session) -> ProgressEvent:
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context
        )
        instance_id = progress.resourceModel.InstanceId
        commands = ['sudo growpart /dev/xvda 1; sudo resize2fs /dev/xvda1 || sudo resize2fs /dev/nvme0n1p1']
        if model.UserData:
            commands.extend(base64.b64decode(model.UserData).decode("utf-8").split('\n'))
        ssm_client = session.client('ssm')
        print("Sending command to %s : %s" % (instance_id, commands))
        try:
            send_command_response = ssm_client.send_command(
                InstanceIds=[instance_id], 
                DocumentName='AWS-RunShellScript', 
                Parameters={'commands': commands},
                CloudWatchOutputConfig={
                    'CloudWatchLogGroupName': 'ssm-output-{}'.format(instance_id),
                    'CloudWatchOutputEnabled': True
                }
            )
            callback_context["RUN_COMMAND_ID"] = send_command_response['Command']['CommandId']
            callback_context["LOCAL_STATUS"] = ProvisioningStatus.SENT_COMMAND
            if progress.resourceModel.Async:
                progress.status = OperationStatus.SUCCESS
        except ssm_client.exceptions.InvalidInstanceId:
            print("Failed to execute SSM command. This happens some times when the box isn't ready yet. we'll retry in a minute.")
        return progress

    def SENT_COMMAND(self, request, callback_context, session) -> ProgressEvent:
        model: ResourceModel = request.desiredResourceState
        progress: ProgressEvent = ProgressEvent(
            status=OperationStatus.IN_PROGRESS,
            resourceModel=model,
            callbackContext=callback_context
        )
        command_id = callback_context["RUN_COMMAND_ID"]
        instance_id = progress.resourceModel.InstanceId
        ssm_client = session.client('ssm')
        response = ssm_client.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        if response['Status'] in ['Pending', 'InProgress', 'Delayed']:
            return progress
        else:
            progress.status = OperationStatus.SUCCESS

@resource.handler(Action.CREATE)
def create_handler(session: Optional[SessionProxy], request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any],) -> ProgressEvent:
    
    model: ResourceModel = request.desiredResourceState
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=model
    )

    try:
        if isinstance(session, SessionProxy):
            if callback_context:
                print(callback_context)
                a = Router()
                progress = a.progress_to_step(callback_context["LOCAL_STATUS"], request, callback_context, session)
                return progress
            
            else:
                response = create_environemnt(request, session)
                callback_context["ENVIRONMENT_ID"] = response
                callback_context["LOCAL_STATUS"] = ProvisioningStatus.ENVIRONMENT_CREATED
                progress.callbackContext=callback_context
                progress.status = OperationStatus.IN_PROGRESS

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
