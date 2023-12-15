#!/usr/bin/env python3

'''
Tool to call Data APIs against a pod

This tool does not use the Byoda modules so has no dependency
on the 'byoda-python' repository to be available on the local
file system

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import yaml
import argparse

from anyio import run

from byoda.datamodel.network import Network
from byoda.datamodel.service import Service
from byoda.datamodel.schema import Schema

from byoda.datacache.asset_cache import AssetCache
from byoda.datacache.kv_cache import KVCache
# from byoda.models.data_api_models import EdgeResponse
# from byoda.models.data_api_models import PageInfoResponse
# from byoda.models.data_api_models import QueryResponseModel
from podserver.codegen.pydantic_service_4294929430_1 import asset as Asset

from byoda.storage.filestorage import FileStorage

from byoda.servers.service_server import ServiceServer

from byoda.util.paths import Paths
from byoda.util.test_tooling import is_test_uuid

from byoda import config

WORK_DIR: str = 'tmp/byoda_clean_service_assets'


async def main(args) -> None:
    raise NotImplementedError('This tool is not yet implemented')
    parser = argparse.ArgumentParser()
    parser.add_argument('--redis', '-r', type=str, default=None)
    parser.add_argument('--debug', '-d', action='store_true', default=False)
    parser.add_argument('--verbose', '-v', action='store_true', default=False)
    parser.add_argument('--root-directory', type=str, default=WORK_DIR)
    parser.add_argument('--list', '-l', default='test')
    args = parser.parse_args()

    config.debug = True

    config_file = os.environ.get('CONFIG_FILE', 'config.yml')
    with open(config_file) as file_desc:
        app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    app_config['svcserver']['root_dir'] = WORK_DIR
    if args.redis:
        app_config['svcserver']['cache'] = args.redis

    network = Network(app_config['svcserver'], app_config['application'])

    service_id: int = app_config['svcserver']['service_id']

    network.paths = Paths(
        network=network.name,
        root_directory=args.root_directory,
        service_id=service_id
    )

    server = await ServiceServer.setup(network, app_config)
    config.server = server

    storage = FileStorage(app_config['svcserver']['root_dir'])
    await network.load_network_secrets(storage_driver=storage)

    service = Service(network=network, service_id=service_id)
    if not await service.paths.service_file_exists(service.service_id):
        await service.download_schema(save=True)

    server.service: Service = service
    schema_file: str = service.paths.service_file(service_id)
    await server.service.load_schema(
        filepath=schema_file, verify_contract_signatures=False
    )
    schema: Schema = service.schema
    schema.get_data_classes(with_pubsub=False)
    schema.generate_data_models('svcserver/codegen', datamodels_only=True)

    cache = await AssetCache.setup(
        app_config['svcserver']['cache'], service, 'asset',
        KVCache.DEFAULT_CACHE_EXPIRATION
    )
    print(cache)
    list_name = args.list
    len = cache.len(list_name)
    for counter in range(0, len):
        asset: Asset = cache.get(list_name, counter)
        if is_test_uuid(asset.asset_id):
            if asset.title is None and not asset.video_thumbnails:
                print(f'asset_id: {asset.asset_id}')
                cache.delete(list_name, asset.asset_id)


if __name__ == '__main__':
    run(main, sys.argv)
