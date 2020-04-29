# DON'T USE IN PRODUCTION
I haven't yet scoped down the IAM permissions and I do wayyyyy too much logging for any normal person to consider using this for any `real` work.

# Richard::Cloud9::Environment

## Using
````bash
# Register the type
REG_TOKEN=$(aws cloudformation register-type --type RESOURCE --type-name Richard::Cloud9::Environment --schema-handler-package s3://rhb-blog/provider-types/richard-cloud9-environment.zip)

aws cloudformation describe-type-registration --registration-token $REG_TOKEN  --query "ProgressStatus"
````

Once this returns `"COMPLETE"` you are ready to use the Type.
### Example Template
````yaml
AWSTemplateFormatVersion: 2010-09-09
Resources:
  JSIITest:
    Type: Richard::Cloud9::Environment
    Properties:
      InstanceType: c5.large
      EBSVolumeSize: 50
      OwnerArn: !Sub "arn:aws:sts::${AWS::AccountId}:assumed-role/[ROLE_NAME]/[SESSION_NAME]"
      SSHKeyLocation: "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:your/secret/here"
      UserData: 
        Fn::Base64: |
          cd /
          VERSION=3.7.4
          yum update -y
          yum install gcc openssl-devel bzip2-devel libffi-devel -y
          wget https://www.python.org/ftp/python/${VERSION}/Python-${VERSION}.tgz
          tar xzf Python-${VERSION}.tgz
          cd Python-${VERSION}
          echo "Building Python"
          ./configure --enable-optimizations
          echo "Installing Python"
          make altinstall
          cd ../
          # Remove old symlinks
          rm -rf /etc/alternatives/pip
          rm -rf /etc/alternatives/python
          # make new symlinks
          ln -s /usr/local/bin/pip${VERSION:0:3} /etc/alternatives/pip
          ln -s /usr/local/bin/python${VERSION:0:3} /etc/alternatives/python
          ## Java
          wget https://corretto.aws/downloads/latest/amazon-corretto-8-x64-linux-jdk.rpm
          yum localinstall amazon-corretto*.rpm
          ## User Local stuff (brew HATES to be run by root)
          cd /home/ec2-user/
          echo "Creating user-script"
          cat <<'EOF' > ./script.sh
          export HOME=/home/ec2-user/
          CI=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"
          test -d ~/.linuxbrew && eval $(~/.linuxbrew/bin/brew shellenv)
          test -d /home/linuxbrew/.linuxbrew && eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)
          test -r ~/.bash_profile && echo "eval \$($(brew --prefix)/bin/brew shellenv)" >>~/.bash_profile
          echo "eval \$($(/home/linuxbrew/.linuxbrew/bin/brew --prefix)/bin/brew shellenv)" >>~/.profile
          npm uninstall -g aws-sam-local
          sudo pip uninstall aws-sam-cli
          sudo rm -rf $(which sam)
          brew tap aws/tap
          brew install aws-sam-cli
          ln -sf $(which sam) ~/.c9/bin/sam
          npm uninstall -g typescript
          npm install -g typescript
          tsc --version
          git config --global user.name "YOUR NAME HERE"
          git config --global user.email "YOUR EMAIL HERE"
          EOF
          echo "Running user-script"
          chmod +x ./script.sh
          runuser -l  ec2-user -c './script.sh'
          echo "done" >> /home/ec2-user/environment/DONE.txt
````

### Deploy Template
If you save that template as `MyTemplate.yaml`, you can deploy it with the following command:
````bash
aws cloudformation deploy --stack-name MyCustomCloud9 --template-file MyTemplate.yaml
````

This will deploy and set up your Cloud9 Environment and may return a success message before your userdata section has completed. Personally, I address this my having my userdata write a file in my `$HOME` directory when it finishes.

---
## Developing
This section is for making changes to the Resource Provider and most users shouldn't have to worry about this. It's just a collection of my notes.
````bash
sudo echo "ec2-user ALL=(root:root) NOPASSWD:ALL" > /etc/sudoers.d/custom
sudo -u root -s
VERSION=3.7.4
yum update -y
yum install gcc openssl-devel bzip2-devel libffi-devel -y
wget https://www.python.org/ftp/python/${VERSION}/Python-${VERSION}.tgz
tar xzf Python-${VERSION}.tgz
cd Python-${VERSION}
./configure --enable-optimizations
make altinstall
cd ../
# Remove old symlinks
rm -rf /etc/alternatives/pip
rm -rf /etc/alternatives/python
# make new symlinks
ln -s /usr/local/bin/pip${VERSION:0:3} /etc/alternatives/pip
ln -s /usr/local/bin/python${VERSION:0:3} /etc/alternatives/python
exit
````
````bash
CI=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"
test -d ~/.linuxbrew && eval $(~/.linuxbrew/bin/brew shellenv)
test -d /home/linuxbrew/.linuxbrew && eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)
test -r ~/.bash_profile && echo "eval \$($(brew --prefix)/bin/brew shellenv)" >>~/.bash_profile
echo "eval \$($(/home/linuxbrew/.linuxbrew/bin/brew --prefix)/bin/brew shellenv)" >>~/.profile
npm uninstall -g aws-sam-local
sudo pip uninstall aws-sam-cli
sudo rm -rf $(which sam)
brew tap aws/tap
brew install aws-sam-cli
/home/linuxbrew/.linuxbrew/bin/sam
ln -sf $(which sam) ~/.c9/bin/sam
ls -la ~/.c9/bin/sam

pip install cloudformation-cli --user
pip install git+https://github.com/aws-cloudformation/aws-cloudformation-rpdk-python-plugin.git#egg=cloudformation-cli-python-plugin --user
git clone https://github.com/aws-cloudformation/cloudformation-cli-python-plugin.git
cd cloudformation-cli-python-plugin
./package_lib.sh
cd ../Cloud9ResourceProvider/
cp ../cloudformation-cli-python-plugin/cloudformation-cli-python-lib-0.0.1.tar.gz .

cfn submit --set-default
aws cloudformation deploy --template-file tests/integ-final.yaml --stack-name LateOtter001
````
