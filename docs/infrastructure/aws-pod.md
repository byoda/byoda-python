# Install the data pod on AWS


## Create an AWS account

##
Install the [AWS cli](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html#cliv2-linux-install)
Install the [ECS clu](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ECS_CLI_installation.html)
Install the [Copilot CLI](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/AWS_Copilot.html)

```
mkdir ~/tmp
cd ~/tmp
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
rm
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb
rm "session-manager-plugin.deb"
aws --version
```

## Enable API access
Go to https://console.aws.amazon.com/iam
- select Create User, enter the username
- select Programmatic Access
- select Attach Existing polcies directly
- select AdministratorAccess
- Unless you have a need to do so, do not specify a permission boundary
- Select next, add any tags you'd like to use, select Next
- Review the summary and click on 'Create User'

## Create object storage and container
Configure the AWS CLI for the user you just created. Enter the access key id, secret access key and default region name (ie. us-west-1) and default output (ie. json)
```
REGION="us-west-1"
aws configure --profile byoda
AWS Access Key ID [None]: <access key>
AWS Secret Access Key [None]: <secret key>
Default region name [None]: us-west-1
Default output format [None]: json
```

## Create the S3 storage bucket
```
BUCKET_PREFIX=$(LC_CTYPE=C tr -dc a-z0-9 </dev/urandom | head -c 24)
aws s3 mb s3://${BUCKET_PREFIX}-public
aws s3 mb s3://${BUCKET_PREFIX-private
aws s3api put-bucket-acl --bucket byoda-public --acl public-read

NETWORK="byoda.net"
ACCOUNT_ID=$(uuid)
ACCOUNT_SECRET=$(LC_CTYPE=C tr -dc a-zA-Z0-9 </dev/urandom | head -c 24)

```

## Create a role and an access policy so that the byoda pod has Read/Write access to the S3 buckets
See for more detail: https://aws.amazon.com/premiumsupport/knowledge-center/ec2-instance-access-s3-bucket/
In [AWS IAM console](https://console.aws.amazon.com/iam/home#/policies):
1- select policies
2- select create policy button
3- under VisualEditor, select service 'S3'
4- under actions, select 'All S3 actions (s3:*)'
5- under resources, add bucket twice, once for 'byoda-public' and once for 'byoda-private'
6- select next, next and then enter for 'Review policy'
  - Name: ecs-byoda-task-s3-access
  - Description: Give Fargate Byoda container access to its buckets
  - Summary:
  - select create policy
7- create role
  - type of trusted entity: AWS service
  - common use cases: Elastic Container Service
  - select your use case: Elastic Container Service Task
  - permissions 'ecs-byoda-task-s3-access'
  - select 'Create'




***Note that Fargate instructions are obsolete***

```
cat >aws-fargate-task.json <<EOF
{
    "family": "byoda-pod",
    "taskRoleArn": "arn:aws:iam::251110099714:role/byoda-pod-s3",
    "executionRoleArn": "arn:aws:iam::251110099714:role/ecsTaskExecutionRole",
    "networkMode": "awsvpc",
    "containerDefinitions": [
        {
            "name": "byoda-pod",
            "image": "byoda/pod-python:0.0.4",
            "portMappings": [
                {
                    "containerPort": 80,
                    "hostPort": 80,
                    "protocol": "tcp"
                }
            ],
            "environment": [
                {
                    "name": "NETWORK",
                    "value": "byoda.net"
                },
                {
                    "name": "CLOUD",
                    "value": "AWS"
                },
                {
                    "name": "BUCKET_PREFIX",
                    "value": "byoda"
                },
                {
                    "name": "ACCOUNT_ID",
                    "value": "beb6f914-904f-11eb-88ff-00155de02c92"
                },
                {
                    "name": "ACCOUNT_SECRET",
                    "value": "KYDVGirFhB4f0Gv"
                },
                {
                    "name": "PRIVATE_KEY_SECRET",
                    "value": "byoda"
                },
                {
                    "name": "LOGLEVEL",
                    "value": "DEBUG"
                }
            ],
            "essential": true
        }
    ],
    "requiresCompatibilities": [
        "FARGATE"
    ],
    "cpu": "256",
    "memory": "512"
}
EOF


## Fargate task definition
From [the guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ECS_AWSCLI_Fargate.html):
Task definition docs: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/create-task-definition.html

Not working yet:
    "environmentFiles": [
        {
            "type": "s3",
            "value": "arn:aws:s3:::byoda-private/bootstrap.env"
        }


REGION="us-west-1"
ZONE="${REGION}b"
BYODA_CLUSTER="byoda-cluster"
BYODA_SERVICE="podserver-service"
VPC_ID=$(aws ec2 describe-vpcs | jq -r '.Vpcs | .[] | select(.IsDefault == true) | .VpcId')
SUBNET_ID=$(aws ec2 describe-subnets | jq -r --arg ZONE $ZONE '.Subnets | .[] | select(.AvailabilityZone == $ZONE) | .SubnetId')
SG_ID=$(aws ec2 create-security-group --description byoda-sg --group-name byoda-sg --vpc-id ${VPC_ID} | jq -r .GroupId)
aws ec2 authorize-security-group-ingress --group-id ${SG_ID} --protocol tcp --port 80 --cidr 0.0.0.0/0
echo "VPC ID: ${VPC_ID} SUBNET ID: ${SUBNET_ID} Security-Group ID ${SG_ID}"

# Is this needed?
# aws iam --region ${REGION} create-role --role-name ecsTaskExecutionRole --assume-role-policy-document file://aws-task-execution-role.json
aws iam --region ${REGION} attach-role-policy --role-name ecsTaskExecutionRole --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
# Did the below line help ecs task to read environment file from S3 storage?
aws iam --region ${REGION} attach-role-policy --role-name ecsTaskExecutionRole --policy-arn <arn-of-ecs-byoda-task-s3-access>

aws ecs create-cluster --cluster-name ${BYODA_CLUSTER}
aws ecs register-task-definition --cli-input-json file://aws-fargate-task.json
aws ecs create-service \
    --cluster ${BYODA_CLUSTER} \
    --service-name ${BYODA_SERVICE} \
    --task-definition byoda-pod:6 \
    --desired-count 1 \
    --launch-type "FARGATE" \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-586ce03e],securityGroups=[${SG_ID}], assignPublicIp=ENABLED}"

# https://us-west-1.console.aws.amazon.com/ecs/home?region=us-west-1
aws ecs describe-services --cluster ${BYODA_CLUSTER} --services ${BYODA_SERVICE}
```

If you are testing and want to avoid AWS charges then do some clean up:
```
aws ecs delete-service --cluster ${BYODA_CLUSTER} --service ${BYODA_SERVICE} --force
aws ecs delete-cluster --cluster ${BYODA_CLUSTER}
