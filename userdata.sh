cd /
VERSION=3.7.4
yum update -y
yum install gcc openssl-devel bzip2-devel libffi-devel -y
wget --quiet https://www.python.org/ftp/python/${VERSION}/Python-${VERSION}.tgz
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
wget --quiet https://corretto.aws/downloads/latest/amazon-corretto-8-x64-linux-jdk.rpm
yum localinstall amazon-corretto*.rpm -y
## Install Maven
wget --quiet https://www-us.apache.org/dist/maven/maven-3/3.6.3/binaries/apache-maven-3.6.3-bin.tar.gz -P /tmp
tar xf /tmp/apache-maven-3.6.3-bin.tar.gz -C /opt
ln -s /opt/apache-maven-3.6.3 /opt/maven
## User Local stuff (brew HATES to be run by root)
cd /home/ec2-user/
echo "Creating user-script"
cat <<'EOF' > ./script.sh
aws configure set profile.default.region us-west-2
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
# Install Hugo
wget --quiet https://github.com/gohugoio/hugo/releases/download/v0.62.1/hugo_0.62.1_Linux-64bit.tar.gz
tar -xvzf hugo_0.62.1_Linux-64bit.tar.gz
sudo mv hugo /usr/local/bin/
# Set up git credentials
git config --global user.name "Richard Boyd"
git config --global user.email rhboyd@amazon.com
aws secretsmanager get-secret-value --secret-id dev/github/richardhboyd --query "SecretString" --output text > ~/.ssh/github
chmod 400 ~/.ssh/github
echo "IdentityFile ~/.ssh/github" > ~/.ssh/config
chmod 400 ~/.ssh/config
# Set up Maven Environment Variables
echo 'export JAVA_HOME=/usr/lib/jvm/java-1.8.0-amazon-corretto' >> /home/ec2-user/.bashrc
echo 'export M2_HOME=/opt/maven' >> /home/ec2-user/.bashrc
echo 'export MAVEN_HOME=/opt/maven' >> /home/ec2-user/.bashrc
echo 'export PATH=${M2_HOME}/bin:${PATH}' >> /home/ec2-user/.bashrc
EOF
echo "Running user-script"
chmod +x ./script.sh
runuser -l  ec2-user -c './script.sh'
cat <<'EOF' >> /home/ec2-user/environment/README.md
## Hugo
hugo serve --bind=0.0.0.0 -p 8080 -b PREVIEW_URL --appendPort=false --disableFastRender
EOF