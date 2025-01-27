-- invoke this script using
--    redis-cli --ldb --eval redis.lua lists:recently_uploaded , assets 10 <cursor>
-- keys[1]: the name of the list
-- args[1]: the key prefix for the assets
-- args[2]: the number of assets to return
-- args[3]: the cursor to start after
-- args[4]: the filter name, ie. 'ingest_status'
-- args[5]: the filter value, ie. 'published'
local redis_key = KEYS[1]
local key_prefix = ARGV[1]
local first = ARGV[2]
local after = ARGV[3]
local filter_name = ARGV[4]
local filter_value = ARGV[5]

if first == nil then
    first = 20
else
    first = tonumber(first)
end

local page_size = 100
if first > page_size then
    page_size = first
end

-- the list is in ascending order with newest last
-- we want to start at the end of the list and work backwards
-- ZRANGE is inclusive so 0, 1 will return 2 elements
local start_pos = -1 - page_size + 1
local end_pos = -1
if not (after == nil or after == '') then
    local cursor = key_prefix .. after
    local zrank = redis.call('ZRANK', redis_key, cursor)
    if not zrank or zrank == nil or zrank == '' then
        redis.log(redis.LOG_WARNING, 'Cursor ' .. cursor .. ' not found in list ' .. redis_key)
    else
        local list_len = redis.call('ZCARD', redis_key)
        end_pos = zrank - list_len - 1
        redis.log(redis.LOG_WARNING, 'Found cursor ' .. cursor .. ' in list ' .. redis_key .. ' of length ' .. list_len .. ' at position ' .. zrank)
        -- we do not want to start the list at the cursor but before
    end
end


-- Stores all not-expired assets
local assets = {}

-- total_assets: counter for total assets gathered so far
local total_assets = 0

-- page_offset: starting expiration for the next ZRANGE call
local page_offset = end_pos

while total_assets < first do
    -- asset_list: assets retrieved from Redis, but the list may have empty (expired) assets
    -- as we want newest / best assets, we use negative indices for ZRANGE

    local range_start = page_offset - page_size + 1
    local range_end = page_offset
    redis.log(redis.LOG_WARNING, 'start: ' .. range_start .. ', end ' .. range_end)
    local asset_list = redis.call('ZRANGE', redis_key, range_start, range_end, 'REV')
    page_offset = page_offset + page_size
    if asset_list == nil or not asset_list then
        break
    end

    -- asset_data: a single asset retrieved from Redis, that may be empty (expired)
    local asset_data

    -- asset_data_len: counter for total assets gathered by LRANGE. If it is < first, we have reached the end of the list
    local asset_data_len = 0

    local i
    local asset_key
    for i, asset_key in ipairs(asset_list) do
        if total_assets >= first then
            break
        end
        asset_data_len = asset_data_len + 1
        asset_data = redis.call('JSON.GET', asset_key)
        if not (asset_data == nil or not asset_data or asset_data == '') then
            local decoded_data = cjson.decode(asset_data)
            local ingest_status = decoded_data['node']['ingest_status']
            if ingest_status == 'published' or ingest_status == 'external' then
                if not filter_name or filter_name == nil or filter_name == '' then
                    table.insert(assets, asset_data)
                    total_assets = total_assets + 1
                else
                    if decoded_data['node'][filter_name] == filter_value then
                        table.insert(assets, asset_data)
                        total_assets = total_assets + 1
                    end
                end
            end
        end
    end
    if asset_data_len < first then
        break
    end
end
return assets
