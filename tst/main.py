import subprocess
import json
from os import listdir
from os.path import isfile, join
import requests
import random
import string

def setup():
    response = requests.get('http://169.254.169.254/latest/meta-data/iam/security-credentials/AWSCloud9SSMAccessRole')
    credential_object = response.json()
    new_credential_blob = {
        "accessKeyId": credential_object['AccessKeyId'],
        "secretAccessKey": credential_object['SecretAccessKey'],
        "sessionToken": credential_object['Token']
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
            with open(new_path, 'w') as f:
                f.write(json.dumps(file_as_json, sort_keys=True, indent=4))
        else:
            print(f"empty file: {file}")

def main():
    try:
        setup()
    except Exception as e:
        print(e)
        raise(e)
    process = subprocess.run(['sam', 'local', 'invoke', 'TestEntrypoint', '--event', 'sam-tests/00_create.json'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    output = process.stdout
    parsed_output = json.loads(output)
    environment_id = parsed_output['callbackContext']['ENVIRONMENT_ID']
    environment_arn = parsed_output['resourceModel']['Arn']
    print(f'\n\n\n{environment_id}')

if __name__ == "__main__":
    main()