# Running the Byoda pod on your own server.

Most of the testing of the Byoda pod occurs on VMs in AWS, Azure, and GCP but it is also possible to run the Byoda pod on a server in your home. In this setup, you use the local disk of the server to store your data. If you accidently delete that data, or the pod, or the disk in the server fails, you lose all your data in the pod! Keep in mind that running the pod on your own server can be a bit more complex to set up than running it on a newly created VM with no other software or services installed.

The hardware requirements for the pod are minimal: the CPU requirements are very low and just one 1GB of DRAM is required. The docker image is less than 1GB. When LOGLEVEL=DEBUG, the pod emits a lot of logs so do make sure to manage the size of the logfiles stored under /var/www/wwwroot when you run at this log level.

On the networking side, the requirements are:
1. The pod must be able to listen to and receive traffic from the Internet on the following ports:
    - 80/TCP: only needed if you set the 'CUSTOM_DOMAIN' variable with to use a certificate from Let's Encrypt
    - 443/TCP: When you use a web browser to manage your pod or use the services that you are a member of
    - 444/TCP. Other pods send queries to your port using this port
2. The pod must be able to connect out to Internet for the above ports and must be able to perform DNS queries. If you have a NAT function on your home router then you'll need to create mappings on your home router to forward traffic for these ports to your server.

If you already have an nginx webserver then you still may be able to use it together with your pod by volume mounting the /etc/nginx/conf.d directory in your pod and by setting the 'SHARED_WEBSERVER' environment variable in the docker-launch.sh script. Consider that running on a shared webserver lowers the security of the pod as anyone with shell access to your server will be able to bypass the cert-based authentication on your pod and, with root privileges, will be able to sniff the unencrypted data exchange between nginx and the application server.

The pod will add the following configuration files in the /etc/nginx/conf.d directory:
- account.conf: this is the virtual server that hosts the management page of the pod
- member-[uuid].conf: this is the virtual server for your membership of a service.
By setting the 'SHARED_WEBSERVER' environment variable, you stop the pod from running the nginx webserver in the pod and the script will make a port mapping for TCP port 8000 instead of ports 80, 443, and 444. Normally, the pod will reload the nginx process whenever it joins a service but that is not possible on a shared webserver. You'll have to remember to manually reload the nginx configuration (with ```sudo nginx -s reload```) everytime you join a service.

If you are already running an nginx service on your server -and- it listens to port 80 -and- you want to use a custom domain then you'll have to set the 'MANAGE_CUSTOM_DOMAIN_CERT' to the empty string and create and renew a Let's Encrypt certificate for the FQDN yourself. The startup script uses the following command to generate the cert:
```
pipenv run certbot certonly --standalone -n --agree-tos -m postmaster@${CUSTOM_DOMAIN} -d ${CUSTOM_DOMAIN}
```
You'll need to set the LETSENCRYPT_DIRECTORY variable in the docker-launch.sh script so that the pod can volume mount the directory with the Let's Encrypt cert in it. You should also install a cronjob that runs once a month to renew the cert, if it needs to be renewed.