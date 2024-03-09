-- invoke this script using
--    redis-cli --ldb --eval redis.lua lists:recently_uploaded , assets 10 <cursor>
-- keys[1]: the name of the list
-- args[1]: the key prefix for the assets
-- args[2]: the number of assets to return
-- args[3]: the cursor to start after
-- args[4]: the filter name, ie. 'ingest_status'
-- args[5]: the filter value, ie. 'published'
local listkey = KEYS[1]
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

local pos = 0
if not (after == nil or after == '') then
    local cursor = key_prefix .. after
    pos = redis.call('LPOS', listkey, cursor)
    if pos == nil or not pos or pos == '' then
        pos = 0
        -- redis.log(redis.LOG_WARNING, 'Cursor ' .. cursor .. ' not found in list ' .. listkey)
    else
        -- redis.log(redis.LOG_WARNING, 'Found cursor ' .. cursor .. ' in list ' .. listkey .. ' at position ' .. pos)
        -- we do not want to start the list at the cursor but after
        pos = pos + 1
    end
end

--- Stores all not-expired assets
local assets = {}

-- total_assets: counter for total assets gathered so far
local total_assets = 0

-- page_offset: starting offset for the next LRANGE call
local page_offset = 0

while total_assets < first do
    -- asset_list: assets retrieved from Redis, but the list may have empty (expired) assets
    local asset_list = redis.call('LRANGE', listkey, pos + page_offset, pos + page_offset + first - 1)
    page_offset = page_offset + first
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
            if not filter_name or filter_name == nil or filter_name == ''  then
                table.insert(assets, asset_data)
                total_assets = total_assets + 1
            else
                local decoded_data = cjson.decode(asset_data)
                if decoded_data['node'][filter_name] == filter_value then
                    table.insert(assets, asset_data)
                    total_assets = total_assets + 1
                end
            end
        end
    end
    if asset_data_len < first then
        break
    end
end
return assets