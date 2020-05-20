import json
import logging
import botocore
import boto3
import os
import errno
import hashlib
from datetime import datetime



logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def create_AL2_environment(env_name: str, owner_arn: str, instance_type: str, session):

  json_file = "/".join(botocore.__file__.split('/')[:-1]) + "/data/cloud9/2017-09-23/service-2.json"
  logger.warn(f"JSON File location: {json_file}")
  with open(json_file) as service_file:
    data = json.load(service_file)
  
  data['shapes']['CreateEnvironmentEC2Request']['members']['ideTemplateId'] = {"shape":"IdeTemplateId"}
  data['shapes']['IdeTemplateId'] = {"type":"string", "pattern":"^[a-zA-Z0-9]{8,32}$"}
  
  output_file = f"/tmp/data/cloud9/2017-09-23/service-2.json"
  logger.warn(f"Output File location: {output_file}")
  if not os.path.exists(os.path.dirname(output_file)):
      try:
          os.makedirs(os.path.dirname(output_file))
      except OSError as exc: # Guard against race condition
          if exc.errno != errno.EEXIST:
              raise
  
  with open(output_file, 'w+') as service_file:
    json.dump(data, service_file)

  os.environ['AWS_DATA_PATH'] = '/tmp/data/'
  session._session._register_data_loader()
  response = session.client('cloud9').create_environment_ec2(
    ownerArn=owner_arn,
    name=env_name,
    instanceType=instance_type,
    ideTemplateId="f5ec09dc16f0a23728e3cfee668658e8",
    automaticStopTimeMinutes=30
  )
  return response

if __name__ == "__main__":
  import boto3
  timestamp = datetime.now().strftime("%Y/%m/%d-%H:%M:%S").encode('utf-8')
  m = hashlib.sha256(timestamp).hexdigest()[:6]
  session = boto3.Session()
  identity = session.client('sts').get_caller_identity()
  logger.info(create_AL2_environment(env_name=f"TestEnv-{m}", owner_arn=identity['Arn'], instance_type="c5.large", session=session))