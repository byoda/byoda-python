'''
Python module for directory and file management a.o. for secrets

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import os
from uuid import UUID
from logging import Logger, getLogger


from byoda.storage.filestorage import FileStorage

_LOGGER: Logger = getLogger(__name__)


class Paths:
    '''
    Filesystem path management. Provides a uniform interface
    to the location of various files
    '''

    __slots__: list[str] = [
        '_root_directory', '_account', '_network', 'service_id',
        'storage_driver', 'account_id'
    ]

    # Default value for the pirectory prepended to paths
    _ROOT_DIR: str = os.environ['HOME'] + '/.byoda/'

    # Templates for location of directories and files
    # all paths not starting with '/' will have the root directory prepended
    SECRETS_DIR          = 'private/'                       # noqa
    NETWORK_DIR          = 'network-{network}'              # noqa
    SERVICES_DIR         = 'network-{network}/services/'    # noqa

    NETWORK_ROOT_CA_CERT_FILE     = 'network-{network}/network-{network}-root-ca-cert.pem'                       # noqa
    NETWORK_ROOT_CA_KEY_FILE      = 'private/network-{network}-root-ca.key'                                      # noqa
    NETWORK_DATA_CERT_FILE        = 'network-{network}/network-{network}-data-cert.pem'                          # noqa
    NETWORK_DATA_KEY_FILE         = 'private/network-{network}-data.key'                                         # noqa
    NETWORK_ACCOUNTS_CA_CERT_FILE = 'network-{network}/network-{network}-accounts-ca-cert.pem'                   # noqa
    NETWORK_ACCOUNTS_CA_KEY_FILE  = 'private/network-{network}-accounts-ca.key'                                  # noqa
    NETWORK_SERVICES_CA_CERT_FILE = 'network-{network}/network-{network}-services-ca-cert.pem'                   # noqa
    NETWORK_SERVICES_CA_KEY_FILE  = 'private/network-{network}-services-ca.key'                                  # noqa

    ACCOUNT_DIR                     = 'network-{network}/account-{account}/'                                           # noqa
    ACCOUNT_CERT_FILE               = 'network-{network}/account-{account}/{account}-cert.pem'                         # noqa
    ACCOUNT_KEY_FILE                = 'private/network-{network}-account-{account}.key'                                # noqa
    ACCOUNT_DATA_CERT_FILE          = 'network-{network}/account-{account}/{account}-data-cert.pem'                    # noqa
    ACCOUNT_DATA_KEY_FILE           = 'private/network-{network}-account-{account}-data.key'                           # noqa
    ACCOUNT_DATA_SHARED_SECRET_FILE = 'network-{network}/account-{account}/network-{network}-pod-data.sharedsecret'    # noqa
    ACCOUNT_DATA_DIR                = 'private/network-{network}/account-{account}/data'                               # noqa

    SERVICE_DIR                  = 'network-{network}/services/service-{service_id}/'                                     # noqa
    SERVICE_FILE                 = 'network-{network}/services/service-{service_id}/service-contract.json'                # noqa
    SERVICE_CA_CERT_FILE         = 'network-{network}/services/service-{service_id}/network-{network}-service-{service_id}-ca-cert.pem'         # noqa
    SERVICE_MEMBERS_CA_CERT_FILE = 'network-{network}/services/service-{service_id}/network-{network}-service-{service_id}-members-ca-cert.pem' # noqa
    SERVICE_APPS_CA_CERT_FILE    = 'network-{network}/services/service-{service_id}/network-{network}-service-{service_id}-apps-ca-cert.pem'    # noqa
    SERVICE_DATA_CERT_FILE       = 'network-{network}/services/service-{service_id}/network-{network}-service-{service_id}-data-cert.pem'       # noqa
    SERVICE_CERT_FILE            = 'network-{network}/services/service-{service_id}/network-{network}-service-{service_id}-cert.pem'            # noqa
    SERVICE_CA_CERTCHAIN_FILE    = 'network-{network}/services/service-{service_id}/network-{network}-service-{service_id}-ca-certchain.pem'    # noqa
    SERVICE_CA_KEY_FILE          = 'private/network-{network}-service-{service_id}-ca.key'                                # noqa
    SERVICE_MEMBERS_CA_KEY_FILE  = 'private/network-{network}-service-{service_id}-member-ca.key'                         # noqa
    SERVICE_APPS_CA_KEY_FILE     = 'private/network-{network}-service-{service_id}-apps-ca.key'                           # noqa
    SERVICE_KEY_FILE             = 'private/network-{network}-service-{service_id}.key'                                   # noqa
    SERVICE_DATA_KEY_FILE        = 'private/network-{network}-service-{service_id}-data.key'                              # noqa
    SERVICE_MEMBER_DB_FILE       = 'network-{network}/services/service-{service_id}/membersdb.json'                       # noqa
    SERVICE_MEMBER_CERT_FILE     = 'network-{network}/services/service-{service_id}/member-certs/member-{member_id}-cert.pem'          # noqa
    SERVICE_MEMBER_DATACERT_FILE = 'network-{network}/services/service-{service_id}/member-certs/member-data-{member_id}-cert.pem'     # noqa

    APP_DIR                      = 'network-{network}/service-{service_id}/apps'                                          # noqa
    APP_CERT_FILE                = 'network-{network}/service-{service_id}/apps/app-{app_id}-cert.pem'                    # noqa
    APP_KEY_FILE                 = 'private/network-{network}/service-{service_id}/apps/app-{app_id}.key'                 # noqa
    APP_CERTCHAIN_FILE           = 'network-{network}/service-{service_id}/apps/app-{app_id}/app-{app_id}-certchain.pem'  # noqa
    APP_CSR_FILE                 = 'private/network-{network}/service-{service_id}/apps/app-{app_id}-csr.pem'             # noqa
    APP_DATA_CERT_FILE           = 'network-{network}/service-{service_id}/apps/app-data-{app_id}-cert.pem'               # noqa
    APP_DATA_KEY_FILE            = 'private/network-{network}/service-{service_id}/apps/app-data-{app_id}.key'            # noqa
    APP_DATA_CERTCHAIN_FILE      = 'network-{network}/service-{service_id}/apps/app-data-{app_id}-certchain.pem'          # noqa
    APP_DATA_CSR_FILE            = 'private/network-{network}/service-{service_id}/apps/app-data-{app_id}-csr.pem'        # noqa

    MEMBER_DIR                     = 'network-{network}/account-{account}/service-{service_id}/'                                                                # noqa
    MEMBER_SERVICE_FILE            = 'network-{network}/account-{account}/service-{service_id}/service-contract.json'                                           # noqa
    MEMBER_CERT_FILE               = 'network-{network}/account-{account}/service-{service_id}/network-{network}-member-{service_id}-cert.pem'                  # noqa
    MEMBER_KEY_FILE                = 'private/network-{network}-account-{account}-member-{service_id}.key'                                                      # noqa
    MEMBER_DATA_CERT_FILE          = 'network-{network}/account-{account}/service-{service_id}/network-{network}-member-{service_id}-data-cert.pem'             # noqa
    MEMBER_DATA_KEY_FILE           = 'private/network-{network}-account-{account}-member-{service_id}-data.key'                                                 # noqa
    MEMBER_DATA_DIR                = 'private/network-{network}/account-{account}/data/network-{network}-member-{member_id}'                                    # noqa
    MEMBER_DATA_FILE               = 'data-{service_id}-{member_id}.db'                                                                                         # noqa
    MEMBER_QUERY_CACHE_FILE        = 'querycache-{service_id}-{member_id}.db'                                                                                   # noqa
    MEMBER_COUNTER_CACHE_FILE      = 'countercache-{service_id}-{member_id}.db'                                                                                 # noqa
    MEMBER_DATA_CACHE_FILE         = 'cache-{service_id}-{member_id}.db'                                                                                        # noqa
    MEMBER_DATA_PROTECTED_FILE     = 'network-{network}/account-{account}/service-{service_id}/data/network-{network}-member-{service_id}-data.json.protected'  # noqa
    MEMBER_DATA_SHARED_SECRET_FILE = 'network-{network}/account-{account}/service-{service_id}/network-{network}-member-{service_id}-data.sharedsecret'         # noqa

    # Cert Downloads
    NETWORK_CERT_DOWNLOAD               = 'https://dir.{network}/root-ca.pem'                                                                       # noqa
    NETWORK_DATACERT_DOWNLOAD           = 'https://dir.{network}/root-data.pem'                                                                     # noqa
    SERVICE_DATACERT_DOWNLOAD           = 'https://service.service-{service_id}.{network}/network-{network}-service-{service_id}-data-cert.pem'     # noqa
    SERVICE_CACERT_DOWNLOAD             = 'https://service.service-{service_id}.{network}/network-{network}-service-{service_id}-ca-certchain.pem'  # noqa
    SERVICE_MEMBER_CERT_DOWNLOAD        = 'https://service.service-{service_id}.{network}/member-certs/member-{member_id}-cert.pem'                 # noqa
    SERVICE_MEMBER_DATACERT_DOWNLOAD    = 'https://service.service-{service_id}.{network}/member-certs/member-data-{member_id}-cert.pem'            # noqa
    SERVICE_CONTRACT_DOWNLOAD           = 'https://service.service-{service_id}.{network}/service-contract.json'                                    # noqa
    MEMBER_CERT_DOWNLOAD                = 'https://{member_id}.members-{service_id}.{network}/member-cert.pem'                                      # noqa
    MEMBER_DATACERT_DOWNLOAD            = 'https://{member_id}.members-{service_id}.{network}/member-data-cert.pem'                                 # noqa
    APP_CERT_DOWNLOAD                   = 'https://service.service-{service_id}.{network}/app-certs/apps-{app_id}-cert.pem'                # noqa
    APP_DATACERT_DOWNLOAD               = 'https://service.service-{service_id}.{network}/app-certs/app-data-{app_id}-cert.pem'            # noqa

    # CDN Paths
    CDN_ORIGINS_FILE        = '{origins_dir}/{service_id}-{account_id}-origins.json'                                  # noqa

    # APIs
    NETWORKACCOUNT_API      = 'https://dir.{network}/api/v1/network/account'                                          # noqa
    NETWORKSERVICE_API      = 'https://dir.{network}/api/v1/network/service/service_id/{service_id}'                  # noqa
    NETWORKSERVICE_POST_API = 'https://dir.{network}/api/v1/network/service'                                          # noqa
    NETWORKSERVICES_API     = 'https://dir.{network}/api/v1/network/services'                                         # noqa
    NETWORKMEMBER_API       = 'https://dir.{network}/api/v1/network/member'                                           # noqa
    SERVICEMEMBER_API       = 'https://service.service-{service_id}.{network}/api/v1/service/member'                  # noqa
    SERVICEAPP_API          = 'https://service.service-{service_id}.{network}/api/v1/service/app'                     # noqa
    SERVICEEMAILSEARCH_API  = 'https://service.service-{service_id}.{network}/api/v1/service/search/email'            # noqa
    SERVICEASSETSEARCH_API  = 'https://service.service-{service_id}.{network}/api/v1/service/search/asset'            # noqa
    PODACCOUNT_API          = 'https://{account_id}.accounts.{network}/api/v1/pod/account'                            # noqa
    PODACCOUNT_PROXY_API    = 'https://proxy.{network}/{account_id}/api/v1/pod/account'                               # noqa
    PODHEALTH_API           = 'https://{member_id}.members-{service_id}.{network}/api/v1/status'                      # noqa
    CDN_KEYS_API            = 'https://{fqdn}/api/v1/cdn/content_keys'                                                # noqa
    CDN_ORIGINS_API         = 'https://{fqdn}/api/v1/cdn/origins'                                                     # noqa

    # Content download URLs
    RESTRICTED_ASSET_POD_URL = 'https://{custom_domain}/restricted/{asset_id}/{filename}'                                             # noqa
    PUBLIC_ASSET_POD_URL     = 'https://{custom_domain}/public/{asset_id}/{filename}'                                                 # noqa
    PUBLIC_THUMBNAIL_POD_URL = 'https://{custom_domain}/public/{asset_id}/{filename}{ext}'                                            # noqa
    RESTRICTED_ASSET_CDN_URL = 'https://{cdn_fqdn}/restricted/{cdn_origin_site_id}/{service_id}/{member_id}/{asset_id}/{filename}'    # noqa
    PUBLIC_ASSET_CDN_URL     = 'https://{cdn_fqdn}/public/{cdn_origin_site_id}/{service_id}/{member_id}/{asset_id}/{filename}'        # noqa
    PUBLIC_THUMBNAIL_CDN_URL = 'https://{cdn_fqdn}/public/{cdn_origin_site_id}/{service_id}/{member_id}/{asset_id}/{filename}{ext}'   # noqa

    def __init__(self, root_directory: str = _ROOT_DIR,
                 account: str = None,
                 network: str = None,
                 service_id: int = None,
                 storage_driver: FileStorage = None) -> None:
        '''
        Initiate instance with root_dir and account parameters

        :param root_directory: optional, the root directory under which
        all other files and directories are stored
        :param network: optional, name of the network
        :param account: optional, name for the account. If no alias is
        specified then an UUID is generated and used as alias
        :param storage_driver: instance of FileStorage for persistence of data
        :returns: (none)
        :raises: (none)
        '''

        self._root_directory: str = root_directory

        self._account: str = account
        self._network: str = network
        self.service_id: int = service_id
        self.storage_driver: FileStorage
        if storage_driver:
            self.storage_driver = storage_driver
        else:
            self.storage_driver = FileStorage(self._root_directory)

    def get(self, path_template: str, service_id: int = None,
            member_id: UUID = None, account_id: UUID = None,
            app_id: UUID = None) -> str:
        '''
        Gets the file/path for the specified path_type

        :param path_template: string to be formatted
        :returns: full path to the directory
        :raises: KeyError if path_type is for a service
        and the service parameter is not specified
        '''

        if service_id is None:
            service_id = self.service_id

        if account_id is None:
            account_id = self._account

        if '{network}' in path_template and not self._network:
            raise ValueError('No network specified')
        if '{service_id}' in path_template and service_id is None:
            raise ValueError('No service specified')
        if '{account_id}' in path_template and not account_id:
            raise ValueError('No account specified')

        path: str = path_template.format(
            network=self._network,
            account=self._account,
            service_id=service_id,
            member_id=member_id,
            app_id=app_id
        )

        return path

    @staticmethod
    def resolve(path_template: str, network: str, service_id: int = None,
                member_id: UUID = None, account_id: UUID = None,
                account: str = None) -> str:
        '''
        Resolves variables in a string without requiring an instance
        of the Paths class. For file-system paths, this function does
        not prefix the path with the root directory such as specified
        for an instance of this class
        '''

        path: str = path_template.replace('{network}', network)

        if service_id is not None:
            path = path.replace('{service_id}', str(service_id))

        if member_id:
            path = path.replace('{member_id}', str(member_id))

        if account_id:
            path = path.replace('{account_id}', str(account_id))

        if account:
            path = path.replace('{account}', account)

        # Remove any unresolved variables in the template
        for param in '/{member_id}', '/{account_id}', '/{service_id}':
            if param in path:
                path = path.replace(param, '')

        return path

    async def exists(self, path_template: str, service_id: int = None,
                     member_alias: str = None) -> bool:
        '''
        Checks if a path exists

        :param path_template: string to be formatted
        :returns: whether the path exists
        :raises: KeyError if path_type is for a service and the service
        parameter is not specified
        '''

        return await self.storage_driver.exists(
            self.get(path_template, service_id=service_id)
        )

    async def _create_directory(self, path_template: str,
                                service_id: int = None) -> str:
        '''
        Ensures a directory exists. If it does not already exit
        then the directory will be created

        :param path_template: string to be formatted
        :returns: string with the full path to the directory
        :raises: ValueError if PathType.SERVICES_FILE or PathType.CONFIG_FILE
        is specified
        '''

        directory: str = self.get(
            path_template, service_id=service_id
        )

        if not await self.storage_driver.exists(directory):
            await self.storage_driver.create_directory(directory)

        return directory

    @property
    def root_directory(self) -> str:
        return self.get(self._root_directory)

    # Secrets directory
    def secrets_directory(self) -> str:
        return self.get(self.SECRETS_DIR)

    async def secrets_directory_exists(self) -> bool:
        return await self.exists(self.SECRETS_DIR)

    async def create_secrets_directory(self) -> str:
        return await self._create_directory(
            self._root_directory + '/' + self.SECRETS_DIR
        )

    # Network directory
    @property
    def network(self) -> str:
        return self._network

    @network.setter
    def network(self, value) -> None:
        self._network = value

    def network_directory(self) -> str:
        return self.get(self.NETWORK_DIR)

    async def network_directory_exists(self) -> bool:
        return await self.exists(self.NETWORK_DIR)

    async def create_network_directory(self) -> str:
        return await self._create_directory(
            self._root_directory + '/' + self.NETWORK_DIR
        )

    # Account directory
    @property
    def account(self) -> str:
        return self._account

    @account.setter
    def account(self, value) -> None:
        self._account = value

    def account_directory(self, account_id: UUID = None) -> str:
        return self.get(self.ACCOUNT_DIR, account_id=account_id)

    async def account_directory_exists(self) -> bool:
        return await self.exists(self.ACCOUNT_DIR)

    async def create_account_directory(self) -> str | None:
        if not await self.account_directory_exists():
            return await self._create_directory(
                self._root_directory + '/' + self.ACCOUNT_DIR
            )

    # service directory
    def service(self, service_id) -> str:
        return self.get(service_id)

    def service_directory(self, service_id) -> str:
        return self.get(self.SERVICE_DIR, service_id=service_id)

    async def service_directory_exists(self, service_id) -> bool:
        return await self.exists(self.SERVICE_DIR, service_id=service_id)

    async def create_service_directory(self, service_id) -> str:
        return await self._create_directory(
            self._root_directory + '/' + self.SERVICE_DIR,
            service_id=service_id
        )

    # Membership directory
    def member_directory(self, service_id) -> str:
        return self.get(
            self.MEMBER_DIR, service_id=service_id
        )

    async def member_directory_exists(self, service_id) -> bool:
        return await self.exists(
            self.MEMBER_DIR, service_id=service_id
        )

    async def create_member_directory(self, service_id) -> str:
        await self._create_directory(
            self._root_directory + '/' + self.MEMBER_DIR, service_id=service_id
        )
        return await self._create_directory(
            self.MEMBER_DIR + '/data', service_id=service_id
        )

    def member_service_file(self, service_id) -> str:
        return self.get(
            self.MEMBER_SERVICE_FILE, service_id=service_id
        )

    async def member_service_file_exists(self, service_id) -> bool:
        return await self.exists(
            self.MEMBER_SERVICE_FILE, service_id=service_id
        )

    async def create_member_service_directory(self, service_id) -> str:
        return await self._create_directory(
            self.MEMBER_SERVICE_FILE, service_id=service_id
        )

    # Service files
    def service_file(self, service_id) -> str:
        return self.get(self.SERVICE_FILE, service_id=service_id)

    async def service_file_exists(self, service_id) -> bool:
        return await self.exists(self.SERVICE_FILE, service_id=service_id)
