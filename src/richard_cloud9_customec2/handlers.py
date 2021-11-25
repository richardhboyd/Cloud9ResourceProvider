import inspect
import logging
from time import sleep
import json
import base64
import botocore
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
    NewProfileCreated,
    DefaultProfileDetached,
    ProfileAttached,
    CommandSent,
    InstanceStable,
    ResizedInstance
)

from .models import ResourceHandlerRequest, ResourceModel

# Use this logger to forward log messages to CloudWatch Logs.
LOG = logging.getLogger(__name__)
LOG.setLevel(logging.DEBUG)
TYPE_NAME = "Richard::Cloud9::CustomEC2"

resource = Resource(TYPE_NAME, ResourceModel)
test_entrypoint = resource.test_entrypoint

def get_or_create_role(iam_client, role_name) -> str:
    parameters = {}
    parameters['Path'] = '/service-role/'
    parameters['RoleName'] = role_name
    parameters['AssumeRolePolicyDocument'] = json.dumps(
      {
        'Version': '2012-10-17',
        'Statement': {
          'Effect': 'Allow',
          'Principal': {'Service': 'ec2.amazonaws.com'},
          'Action': 'sts:AssumeRole'
        }
      }
    )
    parameters['Tags'] = []
    parameters['Tags'].append({"Key": "AWSQS-ENVIRONMENT", "Value": "True"})
    parameters['Description'] = 'EC2 Instance Profile Role'
    try:
        response = iam_client.create_role(**parameters)
    except iam_client.exceptions.EntityAlreadyExistsException as e:
        response = iam_client.get_role(RoleName=role_name)
    return response['Role']['RoleName']

def get_or_attach_managed_policies(iam_client, managed_policies, role_name: str) -> None:
    iam_response = iam_client.list_attached_role_policies(RoleName=role_name)
    attached_policies = iam_response['AttachedPolicies']
    flattened_attached_policies = list(map(lambda x: x['PolicyArn'], attached_policies))
    for policy in managed_policies:
        if policy not in flattened_attached_policies:
            LOG.info(f"Attaching policy: {policy}")
            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy
            )
        else:
            LOG.info("The managed policy was already attached so we're going to do nothing")
    return
    

@singledispatch
def create(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    LOG.info("starting NEW RESOURCE with request\n{}".format(request))
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    # Check if service-linked role exists
    iam_client = session.client("iam")
    role_name = get_or_create_role(iam_client, 'AWSCloud9SSMAccessRole')
    
    # Check Role for managed policies, attach them if they don't exist
    managed_policies = [
        'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
        'arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy'
        ]
    get_or_attach_managed_policies(iam_client, managed_policies, role_name)

    # Create SSM instance
    cloud9_client = session.client("cloud9")
    # TODO: If Name isn't supplied, generate one (maybe ensure we don't duplicate names)
    # TODO: Expose stop time
    # TODO: Expose VPC configuration
    # TODO: Expose Description
    parameters = {}
    parameters['name'] = request.desiredResourceState.Name
    parameters['instanceType'] = request.desiredResourceState.InstanceType
    parameters['ownerArn'] = request.desiredResourceState.Owner
    parameters['connectionType'] ='CONNECT_SSM'
    if request.desiredResourceState.OperatingSystem == 'AMAZON_LINUX_2':
        parameters['imageId'] = 'amazonlinux-2-x86_64'
    elif request.desiredResourceState.OperatingSystem == 'AMAZON_LINUX':
        parameters['imageId'] = 'amazonlinux-1-x86_64'
    elif request.desiredResourceState.OperatingSystem == 'UBUNTU_18_04':
        parameters['imageId'] = 'ubuntu-18.04-x86_64'
    else:
        # Something is wrong
        pass
    if request.desiredResourceState.Tags is not None:
        parameters['tags'] = request.desiredResourceState._serialize_list(request.desiredResourceState.Tags)
    else:
        parameters['tags'] = []
    parameters['tags'].append({"Key": "AWSQS-ENVIRONMENT", "Value": "True"})
    if True:
        parameters['automaticStopTimeMinutes'] = 123
    if False:
        parameters['description'] = ''
        parameters['subnetId'] = ''
    LOG.info(f"parameters: {parameters}")
    response = cloud9_client.create_environment_ec2(**parameters)

    progress.callbackContext["ENVIRONMENT_ID"] = response['environmentId']

    response = cloud9_client.describe_environments(environmentIds=[progress.callbackContext["ENVIRONMENT_ID"]])
    if len(response['environments']) > 0:
        environment_arn = response['environments'][0]['arn']
        progress.resourceModel.Arn = environment_arn
        progress.callbackContext["LOCAL_STATUS"] = EnvironmentCreated()
    else:
        progress.status = OperationStatus.FAILED
        progress.message = f"no environments found for environmnet id: {progress.callbackContext['ENVIRONMENT_ID']}"

    return progress

@create.register(EnvironmentCreated)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    # Create new IAM Role
    iam_client = session.client("iam")
    role_name = get_or_create_role(iam_client, f'{callback_context["ENVIRONMENT_ID"]}-instance-role')
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
    # Get instance id
    ec2_client = session.client("ec2")
    response = ec2_client.describe_instances(
        Filters=[
            {
                'Name': 'tag:aws:cloud9:environment',
                'Values': [
                    callback_context['ENVIRONMENT_ID'],
                ]
            },
        ]
    )
    try:
        instance_id = response['Reservations'][0]['Instances'][0]['InstanceId']
        ebs_volume_id = response['Reservations'][0]['Instances'][0]['BlockDeviceMappings'][0]['Ebs']['VolumeId']
        progress.callbackContext["INSTANCE_ID"] = instance_id
        progress.callbackContext["VOLUME_ID"] = ebs_volume_id
    except Exception as e:
        LOG.info(f"Unable to determine EC2 Instance ID or EBS Volume ID for environment {callback_context['ENVIRONMENT_ID']}")
        LOG.info(f"error: {e}")
        progress.status = OperationStatus.FAILED
        return progress
    if request.desiredResourceState.VolumeSize is not None:
        # resize EBS Volume
        response = ec2_client.modify_volume(
            VolumeId=ebs_volume_id,
            Size=request.desiredResourceState.VolumeSize
        )
        LOG.info(f"response: {response}")
    else:
        # No need to resize instance
        pass
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
    ssm_client = session.client('ssm')
    response = ssm_client.get_inventory(
        Filters=[
            {
                'Key': 'AWS:InstanceInformation.InstanceId',
                'Values': [
                    callback_context['INSTANCE_ID'],
                ],
                'Type': 'Equal'
            },
        ],
    )
    if len(response['Entities']) > 0:
        progress.message = "instance stable"
        progress.callbackContext["LOCAL_STATUS"] = InstanceStable()
    else:
        LOG.info(f"Instance not ready")
        LOG.info(f"response: {response}")
        progress.callbackDelaySeconds=30
    return progress
    
    
@create.register(InstanceStable)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    # Attach Role to instance
    iam_client = session.client("iam")
    role_name = get_or_create_role(iam_client, f'{callback_context["ENVIRONMENT_ID"]}-instance-role')
    # Attach required policies
    managed_policies = [
        'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
        'arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy'
        ]
    if progress.resourceModel.PermissionsPolicy is not None:
        managed_policies.append(progress.resourceModel.PermissionsPolicy)
    get_or_attach_managed_policies(iam_client, managed_policies, role_name)
    
    try:
        parameters = {}
        parameters['InstanceProfileName'] = f'{callback_context["ENVIRONMENT_ID"]}-instance-profile'
        if request.desiredResourceState.Tags is not None:
            parameters['Tags'] = request.desiredResourceState._serialize_list(request.desiredResourceState.Tags)
        else:
            parameters['Tags'] = []
        parameters['Tags'].append({"Key": "AWSQS-ENVIRONMENT", "Value": "True"})
        LOG.info(parameters)
        response = iam_client.create_instance_profile(**parameters)

        LOG.info(f"Instance Profile created, waiting to stabilize")
        LOG.info(f"response: {response}")
        progress.callbackDelaySeconds=30
        # progress.callbackContext["INSTANCE_PROFILE_ID"] = response['InstanceProfile']['InstanceProfileId']

    except iam_client.exceptions.EntityAlreadyExistsException as _:
        get_instance_response = iam_client.get_instance_profile(InstanceProfileName=f'{callback_context["ENVIRONMENT_ID"]}-instance-profile')
        instance_profile_name = get_instance_response['InstanceProfile']['InstanceProfileName']
        attached = False
        for role in get_instance_response['InstanceProfile']['Roles']:
            if role_name == role['RoleName']:
                attached = True
        if attached == False:
            response = iam_client.add_role_to_instance_profile(
                InstanceProfileName=instance_profile_name,
                RoleName=role_name
            )
        progress.callbackContext["INSTANCE_PROFILE_ID"] = get_instance_response['InstanceProfile']['InstanceProfileId']
        progress.callbackContext["LOCAL_STATUS"] = NewProfileCreated()
        return progress

    except Exception as e:
        LOG.info(f"error creating instance profile: {e}")
        progress.message = f"error creating instance profile: {e}"
        progress.status = OperationStatus.FAILED

    return progress

@create.register(NewProfileCreated)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    ec2_client = session.client("ec2")
    if 'DEFAULT_ASSOCIATION_ID' in callback_context:
        try:
            response = ec2_client.describe_iam_instance_profile_associations(
                AssociationIds=[
                    callback_context['DEFAULT_ASSOCIATION_ID'],
                ]
            )
            if response['IamInstanceProfileAssociations'][0]['State'] != 'disassociated':
                progress.callbackDelaySeconds=60
            else:
                progress.callbackContext["LOCAL_STATUS"] = DefaultProfileDetached()
        except botocore.exceptions.ClientError as error:
            if error.response['Error']['Code'] == 'InvalidAssociationID.NotFound':
                LOG.info(f"error getting association status: {error}")
                progress.callbackContext["LOCAL_STATUS"] = DefaultProfileDetached()
            else:
                LOG.info(error.response['Error'])
                return progress
        return progress
    else:
        response = ec2_client.describe_iam_instance_profile_associations(
            Filters=[
                {
                    'Name': 'instance-id',
                    'Values': [callback_context['INSTANCE_ID']]
                },
            ]
        )
        default_association_id = response['IamInstanceProfileAssociations'][0]['AssociationId']
        disassociate_response = ec2_client.disassociate_iam_instance_profile(
            AssociationId=default_association_id
        )
        progress.callbackContext["DEFAULT_ASSOCIATION_ID"] = default_association_id
        return progress


@create.register(DefaultProfileDetached)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    ec2_client = session.client("ec2")
    if 'ASSOCIATION_ID' in callback_context:
        response = ec2_client.describe_iam_instance_profile_associations(
            AssociationIds=[
                callback_context['ASSOCIATION_ID'],
            ]
        )
        if response['IamInstanceProfileAssociations'][0]['State'] == 'associating':
            progress.callbackDelaySeconds=60
        else:
            progress.callbackContext["LOCAL_STATUS"] = ProfileAttached()
    else:
        response = ec2_client.associate_iam_instance_profile(
            IamInstanceProfile={'Name': f'{callback_context["ENVIRONMENT_ID"]}-instance-profile'},
            InstanceId=callback_context['INSTANCE_ID']
        )
        progress.callbackContext["ASSOCIATION_ID"] = response['IamInstanceProfileAssociation']['AssociationId']

    return progress

@create.register(ProfileAttached)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    if progress.resourceModel.BootstrapDocumentName is not None:
        document_name = progress.resourceModel.BootstrapDocumentName
        ssm_client = session.client("ssm")
        response = ssm_client.describe_document(Name=document_name)
        if 'Document' in response and response['Document'] is not None:
            if response['Document']['Name'] != document_name:
                progress.message = "Document names don't match"
                progress.status = OperationStatus.FAILED
            else:
                parameters = {}
                parameters['InstanceIds'] = [progress.callbackContext["INSTANCE_ID"]]
                parameters['DocumentName'] = document_name
                response = ssm_client.send_command(**parameters)
                command_id = response['Command']['CommandId']
                progress.callbackContext["COMMAND_ID"] = command_id
                progress.callbackContext["LOCAL_STATUS"] = CommandSent()
        else:
            progress.message = f"Document named {document_name} doesn't exist"
            progress.status = OperationStatus.FAILED
    else:
        progress.message = "skipping send command because document was not provided"
        progress.status = OperationStatus.SUCCESS
    
    return progress

@create.register(CommandSent)
def _(obj: ProvisioningStatus, request: ResourceHandlerRequest, callback_context: MutableMapping[str, Any], session: SessionProxy):
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.IN_PROGRESS,
        resourceModel=request.desiredResourceState,
        callbackContext=callback_context,
        callbackDelaySeconds=15
    )
    ssm_client = session.client("ssm")
    response = ssm_client.get_command_invocation(
        CommandId=progress.callbackContext["COMMAND_ID"],
        InstanceId=progress.callbackContext["INSTANCE_ID"]
    )
    
    if response['Status'] == 'Success':
        progress.status = OperationStatus.SUCCESS
    elif response['Status'] in ['Pending', 'InProgress', 'Delayed']:
        progress.callbackDelaySeconds=60
    elif response['Status'] in ['Cancelled', 'TimedOut', 'Failed', 'Cancelling']:
        progress.message = f"command {progress.callbackContext['COMMAND_ID']} did not succeed"
        progress.status = OperationStatus.FAILED
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
            try:
                progress = create(provisioning_state, request, callback_context, session)
            except Exception as e:
                raise(e)
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
    # progress: ProgressEvent = ProgressEvent(
    #     status=OperationStatus.IN_PROGRESS,
    #     resourceModel=model,
    # )
    progress: ProgressEvent = ProgressEvent(
        status=OperationStatus.SUCCESS,
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
    environment_id = model.Arn.split(":")[-1]
    cloud9_client = session.client("cloud9")
    try:
        cloud9_client.delete_environment(environmentId=environment_id)
    except Exception as _:
        pass
    try:
        iam_client = session.client("iam")
        role_name = f'{environment_id}-instance-role'
        instance_profile_name = f'{environment_id}-instance-profile'
        iam_client.remove_role_from_instance_profile(
            InstanceProfileName=instance_profile_name,
            RoleName=role_name
        )
        iam_client.delete_instance_profile(InstanceProfileName=instance_profile_name)
        iam_response = iam_client.list_attached_role_policies(RoleName=role_name)
        attached_policies = iam_response['AttachedPolicies']
        for policy in attached_policies:
            iam_client.detach_role_policy(
                RoleName=role_name,
                PolicyArn=policy['PolicyArn']
            )
        iam_client.delete_role(RoleName=role_name)
    except Exception as e:
        LOG.info(e)
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
