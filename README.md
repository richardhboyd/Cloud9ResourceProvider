# Richard::Cloud9::Environment

````bash
VERSION=3.7.4
sudo yum update -y
sudo yum install gcc openssl-devel bzip2-devel libffi-devel -y
wget https://www.python.org/ftp/python/${VERSION}/Python-${VERSION}.tgz
tar xzf Python-${VERSION}.tgz
cd Python-${VERSION}
sudo ./configure --enable-optimizations
sudo make altinstall
cd ../
# Remove old symlinks
sudo rm -rf /etc/alternatives/pip
sudo rm -rf /etc/alternatives/python
# make new symlinks
sudo ln -s /usr/local/bin/pip${VERSION:0:3} /etc/alternatives/pip
sudo ln -s /usr/local/bin/python${VERSION:0:3} /etc/alternatives/python

sh -c "$(curl -fsSL https://raw.githubusercontent.com/Linuxbrew/install/master/install.sh)"
#### BREAK

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
````

Failures can be passed back to CloudFormation by either raising an exception from `cloudformation_cli_python_lib.exceptions`, or setting the ProgressEvent's `status` to `OperationStatus.FAILED` and `errorCode` to one of `cloudformation_cli_python_lib.HandlerErrorCode`. There is a static helper function, `ProgressEvent.failed`, for this common case.

## What's with the type hints?

We hope they'll be useful for getting started quicker with an IDE that support type hints. Type hints are optional - if your code doesn't use them, it will still work.
