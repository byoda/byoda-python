Create GCS storage
PREFIX=<random string of 8 characters>
create a GCP project
Go to 'Storage'
create storage account ${PREFIX}-private, set access control to 'uniform',  do not enable 'public access'
create storage account ${PREFIX}-public, set access control to 'uniform',  enable 'public access'

Go to IAM
Select Service Accounts
Create service account, make it 'Storage Object Admin'
