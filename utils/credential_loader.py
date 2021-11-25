from os import listdir
from os.path import isfile, join
import requests
import json
import random
import string
import boto3

def main():
    # client = boto3.client('sts')
    # sts_response = client.get_caller_identity()
    # owner_arn = sts_response['Arn']
    owner_arn = 'arn:aws:sts::537434832053:assumed-role/Feder08/redirect_session'
    response = requests.get('http://169.254.169.254/latest/meta-data/iam/security-credentials/AWSCloud9SSMAccessRole')
    credential_object = response.json()
    # new_credential_blob = {
    #     "accessKeyId": credential_object['AccessKeyId'],
    #     "secretAccessKey": credential_object['SecretAccessKey'],
    #     "sessionToken": credential_object['Token']
    # }
    new_credential_blob = {
        "accessKeyId": "",
        "secretAccessKey": "",
        "sessionToken": ""
    }
    environment_name = ''.join(random.choice(string.ascii_lowercase) for _ in range(16))
    mypath = "./sam-tests"
    test_files = [f for f in listdir(mypath) if isfile(join(mypath, f))]
    for file in test_files:
        new_path = f'{mypath}/{file}'
        with open(new_path) as f:
            filestring = f.read()
        if len(filestring) > 0:
            file_as_json = json.loads(filestring)
            file_as_json['credentials'] = new_credential_blob
            file_as_json['request']['desiredResourceState']['Name'] = environment_name
            file_as_json['request']['desiredResourceState']['Owner'] = owner_arn
            file_as_json['request']['desiredResourceState']['OperatingSystem'] = 'AMAZON_LINUX_2'
            file_as_json['request']['desiredResourceState']['InstanceType'] = 't2.micro'
            file_as_json['request']['desiredResourceState']['VolumeSize'] = "20"
            file_as_json['request']['desiredResourceState']['BootstrapDocumentName']= 'SampleSSMDocument-SSMDocument-Aw2yPXJJ62J0'
            file_as_json['request']['desiredResourceState']['PermissionsPolicy'] = 'arn:aws:iam::537434832053:policy/MyAdminPolicy'
            file_as_json['request']['desiredResourceState']['Tags'] = [{"Key": "ATAG", "Value":"AVALUE"}]
            with open(new_path, 'w') as f:
                f.write(json.dumps(file_as_json, sort_keys=True, indent=4))
        else:
            print(f"empty file: {file}")

if __name__ == "__main__":
    main()