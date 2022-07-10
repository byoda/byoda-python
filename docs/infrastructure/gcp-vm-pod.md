# Instructions for creating a VM on GCP are to be completed

1. Create an account with [Google Cloud](https://console.cloud.google.com/)
Create GCS storage
PREFIX=<random string of 8 characters>
create a GCP project
Go to 'Storage'
create storage account ${PREFIX}-private, set access control to 'uniform',  do not enable 'public access'
create storage account ${PREFIX}-public, set access control to 'uniform',  enable 'public access'

Go to IAM
Select Service Accounts
Create service account, make it 'Storage Object Admin'
