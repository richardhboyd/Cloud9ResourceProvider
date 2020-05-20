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
echo 'export JAVA_HOME=/usr/lib/jvm/java-11-amazon-corretto.x86_64' >> /home/ec2-user/.bashrc
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