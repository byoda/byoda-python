# Running the Byoda pod on your own server.

Most of the testing of the Byoda pod occurs on VMs in AWS, Azure, and GCP but it is possible to run the Byoda pod on a server in your home. The hardware requirements are minimal: the CPU requirements are very low and one 1GB of DRAM is required. The docker image is less than 1.5GB. When DEBUG logging is enabled, the pod emits a lot of logs so do make sure to manage the size of those logfiles.

On the networking side, the requirements are:
1. The pod must be able to listen to and receive traffic from the Internet on the following ports:
    - 80/TCP: only needed if you set the 'CUSTOM_DOMAIN' variable to use a certificate from Let's Encrypt
    - 443/TCP: When you use a web browser to manage your pod or use the services that you are a member of
    - 444/TCP. Other pods send queries to your port using this port
2. The pod must be able to connect out to Internet for the above ports and must be able to perform DNS queries

If you have a NAT function on your home router then you'll need to create mappings on your home router to forward traffic for these ports to your server.

If you already have an nginx webserver then you still may be able to use it together with your pod by volume mounting the /etc/nginx/conf.d directory in your pod and by setting the 'SHARED_WEBSERVER' environment variable in the docker-launch.sh script. The pod will add the following configuration files in the directory:
- account.conf: this is the virtual server that hosts the management page of the pod
- virtualserver.conf.jinja2: this is a template used for generating a virtual server for each service that you join. Nginx ignores configuration files that do not have the '.conf' extension.
- member-[uuid].conf: this is the virtual server for your membership of a service.
By setting the 'SHARED_WEBSERVER' environment variable, you stop the pod from running the nginx webserver in the pod and the script will make a port mapping for TCP port 8000 instead of ports 80, 443, and 444.

If you are already running an nginx service on your server -and- it listens to port 80 -and- you want to use a custom domain then you'll have to set the 'MANAGE_CUSTOM_DOMAIN_CERT' to the empty string and create and renew a Let's Encrypt certificate for the FQDN yourself. The startup script uses the following command to generate the cert:
```
pipenv run certbot certonly --standalone -n --agree-tos -m postmaster@${CUSTOM_DOMAIN} -d ${CUSTOM_DOMAIN}
```

You should then also install a cronjob that runs once a month to renew the cert, if it needs to be renewed.