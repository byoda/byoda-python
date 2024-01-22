-- invoke with:
--   redis-cli --eval delete_redis_key_prefix.lua , assets:*
--   redis-cli --eval delete_redis_key_prefix.lua , lists:*
if ARGV[1] == nil or not ARGV[1] or ARGV[1] == '' then
    return 0
end

local matches = redis.call('KEYS', ARGV[1])

local result = 0
for _,key in ipairs(matches) do
    result = result + redis.call('DEL', key)
end

return result