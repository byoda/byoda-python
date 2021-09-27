# Bring your own data & algorithms

## Intro
Byoda is a mew and radically different social media platform:
- Your data is stored in your own data pod.
- You can select the algorithm(s) that generate your content feed for you.
- Anyone can develop apps and services on the platform.
- The code for the reference implementation of the various components is open source.

This repo hosts the reference implementation (in Python) of the Byoda directory server and the data pod. For more information about Byoda, please read the [wiki](https://github.com/StevenHessing/byoda/wiki)

## Status
The directory server is supporting the registration API for pods using CA signed certs and DNS hosting. It does not yet support the APIs for services.
The pod is currently bootstrapping and running in a container in a public cloud and hosting GraphQL API for accessing data for the 'Default' (0) service. The pod currently supports AWS S3 object storage.

## Tech overview
The platform consists of:
- A directory server hosts REST APIs for registration, Certificate Authority, and DNS services for pods and services
- A data pod runs in public clouds or in home-networks and exposes both GraphQL APIs and REST APIs. The data pod encrypts all stored data using the Fernet encryption algorithm
- Services implement apps and websites and host APIs to deliver features and capabilities to the people on the platform.

The exchange of data between pods and services is controlled by a data contract. A service specifies in the data contract what data is stored for it in the data pod. The data contract is defined by a service and you have to accept the data contract when you become a member of the service. The data contract leverages the [JSON-Schema](https://json-schema.org/) vocabulary, enriched with additional constructs to define access control for the data. The data pod translates the JSON Schema to host a GraphQL API for each service that it has become a member of.

## Hosting the data pod
The data pod is available as a Docker container that can run on AWS Fargate/ECS. The data pod uses object storage for storing data. It currently only supports AWS S3 storage. Over time, the plan is to add support for additional clouds, i.e Google Cloud Storage and Azure Storage Accounts. The pod software can also run on a host to enable local testing on a developer workstation

## Peer to peer networkling
The data pod hosts both GraphQL and REST APIs. Apps and services uses GraphQL for managing data in the pod. The REST APIs will be used for:
- peer-to-peer queries traveling the pods in the network
- management of the pod, password recovery etc.
