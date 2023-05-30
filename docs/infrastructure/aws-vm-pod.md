# Install the data pod on AWS

1. Create an AWS account

    Go to the [AWS new account page](https://aws.amazon.com/premiumsupport/knowledge-center/create-and-activate-aws-account/) and sign up.

2. Install AWS tools on a unix PC you have access to
    Install the [AWS cli](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html#cliv2-linux-install)
    Install the [ECS clu](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ECS_CLI_installation.html)
    Install the [Copilot CLI](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Copilot.html)

    ```bash
    mkdir ~/tmp
    cd ~/tmp
    curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    sudo apt-get install unzip
    unzip awscliv2.zip
    sudo ./aws/install
    rm awscliv2.zip
    curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
    sudo dpkg -i session-manager-plugin.deb
    rm "session-manager-plugin.deb"
    aws --version
    ```

3. Enable API access

    Go to [AWS IAM](https://console.aws.amazon.com/iam)

    - select Create User, enter the username
    - select Programmatic Access
    - select Attach Existing polcies directly
    - select AdministratorAccess
    - Unless you have a need to do so, do not specify a permission boundary
    - Select next, add any tags you'd like to use, select Next
    - Review the summary and click on 'Create User'

4. Create object storage and container

    Configure the AWS CLI for the user you just created. Enter the access key id, secret access key and default region name (ie. us-east-2) and default output (ie. json)

    ```bash
    aws configure --profile byoda
    AWS Access Key ID [None]: <access key>
    AWS Secret Access Key [None]: <secret key>
    Default region name [None]: us-east-2
    Default output format [None]: json
    ```

5. Create the VM

    To create an Ubuntu 22.04 VM, browse to the [Ubuntu AWS marketplace](https://aws.amazon.com/marketplace/server/procurement?productId=47489723-7305-4e22-8b22-b0d57054f216) and accept that you will get Ubuntu 22.04 for free.

    Now find the AWS image for Ubuntu 22.04:

    ```bash
    REGION="us-east-2"
    IMAGE_FILTER="Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server*"
    IMAGE_SORT='sort_by(Images, &CreationDate)[-1].{Name: Name, ImageId: ImageId, CreationDate: CreationDate, Owner:OwnerId}'
    AMI_ID=$(aws ec2 describe-images --output json --region $REGION --filters ${IMAGE_FILTER} --query "${IMAGE_SORT}" | jq -r .ImageId)
    echo "AWS Ubuntu 22.04 AWS image ID: ${AMI_ID}"
    ```

6. Create and import an SSH key

    ```bash
    export SSH_KEY=byoda-pod
    if [ ! -f ~/.ssh/id_ed25519-${SSH_KEY} ]; then
        ssh-keygen -t ed25519 -C ${SSH_KEY} -f ~/.ssh/id_ed25519-${SSH_KEY}
        aws ec2 import-key-pair --key-name ${SSH_KEY} --public-key-material fileb://~/.ssh/id_ed25519-${SSH_KEY}.pub --region ${REGION}
    fi
    ```

7. Create the VM:

    ```bash
    TAGS='ResourceType=instance,Tags=[{Key=Name,Value=byoda-pod-aws}]'
    INSTANCE_ID=$(aws ec2 run-instances \
        --instance-type t2.micro \
        --image-id ${AMI_ID} \
        --count 1 \
        --key-name ${SSH_KEY} \
        --tag-specifications "${TAGS}" \
        --region ${REGION} | jq -r '.Instances | .[] | .InstanceId')
    ```

8. Update the security group to allow SSH access from your public IP and HTTPS access from anywhere (the pod uses both port 443 and 444 for HTTPS access)

    ```bash
    PUBLIC_IP=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[*].Instances[*].PublicIpAddress' --region $REGION | jq -r '.[] | .[]'); echo "VM public IP: ${PUBLIC_IP}"
    VPC_ID=$(aws ec2 describe-instances --instance-ids $INSTANCE_ID --query 'Reservations[*].Instances[*].VpcId' --region $REGION | jq -r '.[] | .[]'); echo "VPC ID: ${VPC_ID}"
    SG_ID=$(aws ec2 describe-security-groups --region $REGION | jq -r '.SecurityGroups | . [] | .GroupId'); echo "Security Group ID: ${SG_ID}"

    MY_IP=$(curl -s ifconfig.co)
    aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 443 --cidr 0.0.0.0/0 --region ${REGION}
    aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 444 --cidr 0.0.0.0/0 --region ${REGION}
    aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 80 --cidr 0.0.0.0/0 --region ${REGION}
    aws ec2 authorize-security-group-ingress --group-id $SG_ID --protocol tcp --port 22 --cidr ${MY_IP}/32 --region ${REGION}
    ```

9. Create the S3 storage buckets

    ```bash
    export BUCKET_PREFIX=$(LC_CTYPE=C tr -dc a-z0-9 </dev/urandom | head -c 24)
    export UUID=$(uuid -v 4)
    export PRIVATE_BUCKET='byoda'
    export RESTRICTED_BUCKET="restricted-${UUID:24:12}"
    export PUBLIC_BUCKET='public'

    aws s3api create-bucket --bucket ${PRIVATE_BUCKET} --acl private --region ${REGION} --create-bucket-configuration LocationConstraint=${REGION}
    aws s3api create-bucket --bucket ${RESTRICTED_BUCKET} --acl public-read --region ${REGION} --create-bucket-configuration LocationConstraint=${REGION}
    aws s3api create-bucket --bucket ${PUBLIC_BUCKET} --acl public-read --region ${REGION} --create-bucket-configuration LocationConstraint=${REGION}

    cat >/tmp/restricted-bucket-policy.json <<'    EOF'
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::RESTRICTED_BUCKET/*"
            }
        ]
    }
    EOF

    sed -i "s|RESTRICTED_BUCKET|${RESTRICTED_BUCKET}|" /tmp/restricted-bucket-policy.json
    aws s3api put-bucket-policy --bucket ${RESTRICTED_BUCKET} file:///tmp/restricted-bucket-policy.json

    cat >/tmp/public-bucket-policy.json <<'    EOF'
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::${PUBLIC_BUCKET}/*"
            }
        ]
    }
    EOF

    sed -i "s|PUBLIC_BUCKET|${PUBLIC_BUCKET}|" /tmp/public-bucket-policy.json
    aws s3api put-bucket-policy --bucket ${PUBLIC_BUCKET} file:///tmp/public-bucket-policy.json

    ```

10. Validate you have remote access to the VM

    All done, just confirm that you can ssh to the VM:

    ```bash
    ssh -i ${SSH_KEY_FILE} azureuser@${PUBLIC_IP}
    ```

    If that works for you, you can continue with the remainder of the [tutorial](https://github.com/byoda/byoda-python/blob/master/README.md).
