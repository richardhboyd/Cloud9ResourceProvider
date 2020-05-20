import json
import logging
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from requests import Session
import hashlib
from datetime import datetime



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_AL2_environment(env_name: str, owner_arn: str, instance_type: str, credentials, region: str):
  s = Session()
  ENDPOINT = f'https://cloud9.{region}.amazonaws.com/'
  HEADERS = {
    'Content-Type': 'application/x-amz-json-1.1',
    'X-Amz-Target': 'AWSCloud9WorkspaceManagementService.CreateEnvironmentEC2'
  }
  timestamp = datetime.now().strftime("%Y/%m/%d-%H:%M:%S").encode('utf-8')
  request_body = {
      'name': env_name,
      'clientRequestToken': hashlib.sha256(timestamp).hexdigest(),
      'instanceType': instance_type,
      'ideTemplateId': 'f5ec09dc16f0a23728e3cfee668658e8',
      'automaticStopTimeMinutes': 30
      
  }
  sigv4 = SigV4Auth(credentials, 'cloud9', region)
  request = AWSRequest(method='POST', url=ENDPOINT, headers=HEADERS, data=json.dumps(request_body))
  sigv4.add_auth(request)
  prepped = request.prepare()
  prepped.hooks = {}
  prepped.path_url = "/"
  response = s.send(prepped)
  logger.info(f"Body: {prepped.body}\n\n")
  logger.info(f"Headers: {prepped.headers}\n\n")
  logger.info(f"Response: {response.text}\n")
  logger.info(f"Response: {response.status_code}\n")
  if response.status_code == 200:
    return response.json()
  else:
    raise Exception

if __name__ == "__main__":
  import boto3
  timestamp = datetime.now().strftime("%Y/%m/%d-%H:%M:%S").encode('utf-8')
  m = hashlib.sha256(timestamp).hexdigest()[:6]
  session = boto3.Session()
  credentials = session.get_credentials().get_frozen_credentials()
  identity = boto3.client('sts').get_caller_identity()
  create_AL2_environment(env_name=f"TestEnv-{m}", owner_arn=identity['Arn'], instance_type="c5.large", credentials=credentials, region='us-west-2')
