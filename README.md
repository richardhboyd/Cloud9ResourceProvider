# AWSQS::Cloud9::CustomEC2

Setting up a new environment
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r ./requirements.txt
```

Testing the handler
```bash
cfn submit --dry-run && \
python3 ./utils/credential_loader.py && \
sam local invoke TestEntrypoint --event sam-tests/00_create.json
```

Sample SSM Document to bootstrap the instance
```yaml
Resources:
  SSMDocument:
    Type: AWS::SSM::Document
    Properties: 
      Content: Yaml
      DocumentType: Command
      Content: 
        schemaVersion: '2.2'
        mainSteps:
        - action: aws:runShellScript
          name: C9bootstrap
          inputs:
            runCommand:
            - "#!/bin/bash"
            - date
            - sudo -H -u ec2-user bash -c "touch ~/environment/done.txt"
            - echo "Bootstrap completed with return code $?"
```

sample template to deploy a bootstrapped instance
```yaml
Resources:
  MyCloud9Environment:
    Type: Richard::Cloud9::CustomEC2
    Properties:
      BootstrapDocumentName: "SampleSSMDocument-SSMDocument-Aw2yPXJJ62J0"
      InstanceType: "t2.micro"
      Name: "vsztfeeeuihwcilh"
      OperatingSystem: "AMAZON_LINUX_2"
      Owner: "arn:aws:sts::537434832053:assumed-role/Feder08/redirect_session"
      PermissionsPolicy: "arn:aws:iam::537434832053:policy/MyAdminPolicy"
      Tags:
        - Key: "ATAG"
          Value: "AVALUE"
      VolumeSize: 20
```
