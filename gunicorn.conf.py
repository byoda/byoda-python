import multiprocessing

# Sample config file:
# https://gist.github.com/HacKanCuBa/275bfca09d614ee9370727f5f40dab9e

# BIND parameter is set in systemd file

forwarded_allow_ips = "127.0.0.1"

workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "uvicorn.workers.UvicornWorker"
