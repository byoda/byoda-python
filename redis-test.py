import redis

r=redis.Redis('redis://192.168.1.13:6379')
r.zadd('channel', 'a', 0, 'b', 5, 'c', 8, 'd', 20)
res = r.zrange('channel', 0, -1, withscores=True)
print(res)
