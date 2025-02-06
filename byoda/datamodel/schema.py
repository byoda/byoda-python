'''
Class for modeling the (JSON) schema to validating data

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
import sys
import orjson

from typing import Self
from copy import deepcopy
from types import CodeType
from typing import TypeVar
from typing import Optional
from types import ModuleType
from dataclasses import dataclass
from logging import Logger, getLogger


import jinja2

from fastapi import FastAPI

from byoda.datamodel.dataclass import SchemaDataItem

from byoda.storage import FileStorage

from byoda.secrets.network_data_secret import NetworkDataSecret
from byoda.secrets.service_data_secret import ServiceDataSecret
from byoda.secrets.secret import Secret
from byoda.secrets.data_secret import DataSecret

from byoda.util.message_signature import MessageSignature
from byoda.util.message_signature import ServiceSignature
from byoda.util.message_signature import NetworkSignature
from byoda.util.message_signature import SignatureType

from byoda.exceptions import ByodaDataClassReferenceNotFound

from byoda import config

_LOGGER: Logger = getLogger(__name__)

Service = TypeVar('Service')

CODEGEN_DIRECTORY: str = 'podserver/codegen'

MAX_SCHEMA_SIZE = 1000000


@dataclass
class ListenRelation:
    class_name: str
    destination_class: str
    relations: Optional[list[str]] = None
    feed_class: str | None = None


class Schema:
    CLASSES_FILEPATH: str = 'podserver/codegen/data_classes.py'
    SCHEMA_TEMPLATE_DIRECTORY: str = 'podserver/templates'

    # TODO: figure out why enabling __slots__ throws an error on
    # service_id
    # __slots__ = [
    #     'json_schema', 'data_classes', 'verified_signatures',
    #     'service_id', 'version', 'name', 'owner', 'website', 'supportemail',
    #     'description', 'cors_origins', 'schema_id', 'validator',
    #     '_verified_signatures', '_service_signature', '_network_signature',
    #     'validator', 'service_data_secret', 'network_data_secret',
    #     'listen_relations', 'pydantic_requests'
    # ]

    def __init__(self, schema: dict, verify_signatures: bool = True) -> None:
        '''
        Construct a schema. The number of class properties is kept
        to a minimum to avoid these properties from getting out of
        sync with the json schema.

        The signatures on the data contract will not
        be checked in the constructor as we do not know yet what the
        service_id is of the schema and this means we can't use the data
        secret yet of that service to verify the signature.
        '''

        # This is the schema as read and deserialized from a file to a dict
        self.json_schema: dict = schema

        self.data_classes: dict[str:SchemaDataItem] = {}

        # Note that we have getters/setters for the top-level properties
        if self.service_id is None:
            raise ValueError('Schema must have a Service ID')

        if self.version is None:
            raise ValueError('Schema must have a version')

        if not self.name:
            raise ValueError('Schema must have a name')

        if not self.owner:
            raise ValueError('Schema must have an owner')

        if not self.website:
            raise ValueError('Schema must have a website')

        if not self.supportemail:
            raise ValueError('Schema must have a support email address')

        if not self.description:
            raise ValueError('Schema must have a description')

        if not self.cors_origins:
            raise ValueError('Schema must have a list of CORS Origins')

        self.schema_id: str = self.json_schema['jsonschema'].get('$id')
        if not self.schema_id:
            raise ValueError('JSON Schema must have an "$id" field')

        # This stores all the pydantic requests for each
        # object or array data_class and each request type
        # (query, append, mutate, update, delete, updates, counter)
        self.pydantic_requests: dict[str, dict[str, str]] = {}

        # Should we verify signatures (always true, except in test cases)
        self.verify_signatures: bool = verify_signatures

        self.verified_signatures: set[MessageSignature] = set()
        self._service_signature: ServiceSignature | None = None
        self._network_signature: NetworkSignature | None = None

        self.service_data_secret: ServiceDataSecret | None = None
        self.network_data_secret: NetworkDataSecret | None = None

    def as_dict(self) -> dict:
        '''
        Get the metadata of the schema as dict
        '''

        # BUG: does not include follow_relations field
        data: dict[str, str | int | list[str]] = {
            'service_id': self.service_id,
            'version': self.version,
            'name': self.name,
            'owner': self.owner,
            'website': self.website,
            'supportemail': self.supportemail,
            'description': self.description,
            'cors_origins': self.cors_origins,
        }

        return data

    # BUG: as_string returns bytes
    def as_string(self) -> bytes:
        '''
        Returns the schema as a string of json data presented
        for creating or verifying a signature for the schema
        '''

        return orjson.dumps(
            self.json_schema, option=orjson.OPT_SORT_KEYS | orjson.OPT_INDENT_2
        )

    @staticmethod
    async def get_schema(filepath: str, storage_driver: FileStorage,
                         service_data_secret: ServiceDataSecret,
                         network_data_secret: NetworkDataSecret,
                         verify_contract_signatures: bool = True) -> Self:
        '''
        Facory to read schema from a file
        '''

        _LOGGER.debug(f'Loading schema from {filepath}')
        data: str = await storage_driver.read(filepath)
        json_schema: dict[str, any] = orjson.loads(data)

        schema = Schema(
            json_schema, verify_signatures=verify_contract_signatures
        )
        schema.service_data_secret = service_data_secret
        schema.network_data_secret = network_data_secret

        schema.load(
            verify_contract_signatures=verify_contract_signatures
        )

        return schema

    def load(self, verify_contract_signatures: bool = True) -> None:
        '''
        Load a schema from a dict
        '''

        if not verify_contract_signatures:
            return

        try:
            self._service_signature = ServiceSignature.from_dict(
                self.json_schema['signatures'].get(
                    SignatureType.SERVICE.value
                ),
                data_secret=self.service_data_secret
            )
            _LOGGER.info(
                f'Service signature for service {self.service_id} '
                f'was created on {self._service_signature.timestamp}'
            )
        except ValueError:
            _LOGGER.exception(
                'No Service signature in contract for service '
                f'{self.service_id}'
            )
            if not (config.debug
                    and os.environ.get('LOCAL_SERVICE_CONTRACT')):
                raise

        try:
            self._network_signature = NetworkSignature.from_dict(
                self.json_schema['signatures'].get(
                    SignatureType.NETWORK.value
                ),
                data_secret=self.network_data_secret
            )
        except ValueError:
            _LOGGER.exception(
                'No Network signature in contract for service '
                f'{self.service_id}'
            )
            if not (config.debug
                    and os.environ.get('LOCAL_SERVICE_CONTRACT')):
                raise

    async def save(self, filepath: str, storage_driver: FileStorage):
        '''
        Write a schema to a JSON file, ie. when an account becomes
        a member of the service that the schema belongs to
        '''

        await storage_driver.write(filepath, self.as_string())

    def create_signature(self, secret: DataSecret,
                         signature_type: SignatureType,
                         hash_algo: str = 'SHA256') -> None:
        '''
        Generate a signature for the data contract. The network will only
        sign a service contract if:
        - the service already has signed it.
        - TODO: the network did not sign a data contract for the service with
        the same version number
        '''

        if 'signatures' not in self.json_schema:
            self.json_schema['signatures'] = {}

        if self.json_schema['signatures'].get(SignatureType.NETWORK.value):
            raise ValueError('Network signature already exists')

        if signature_type == SignatureType.SERVICE:
            if self.json_schema['signatures'].get(SignatureType.SERVICE.value):
                raise ValueError('Service signature already exists')

            message_signature = ServiceSignature(secret, hash_algo=hash_algo)
        else:
            message_signature = NetworkSignature(secret, hash_algo=hash_algo)

        schema_str: bytes = self.as_string()
        message_signature.sign_message(schema_str)

        # Add the signature to the original JSON Schema
        self.json_schema['signatures'][signature_type.value] = \
            message_signature.as_dict()

    def verify_signature(self, secret: Secret, signature_type: SignatureType,
                         hash_algo: str = 'SHA256') -> None:
        '''
        Verifies the signature of the data contract. The signature by the
        service only covers the data contract, the signature by the network
        covers both the data contract and the signature by the service.
        :raises: ValueError
        '''

        schema: dict[str, object] = self.json_schema

        if 'signatures' not in schema:
            raise ValueError('No signatures in the schema')

        # signature_type.value might be 'service' in which case
        # we check the same thing twice but that's ok
        if (SignatureType.SERVICE.value not in schema['signatures']
                or (signature_type == SignatureType.NETWORK and
                    SignatureType.NETWORK.value not in schema['signatures'])):
            raise ValueError(
                f'Missing signature in JSON Schema: {signature_type.value}'
            )

        original_schema = None
        if SignatureType.NETWORK.value in schema['signatures']:
            # A signature of a schema never covers the network signature so
            # we remove it from the schema
            original_schema: dict[str, object] = deepcopy(schema)
            signature: MessageSignature = NetworkSignature.from_dict(
                schema['signatures'].pop(SignatureType.NETWORK.value),
                data_secret=self.network_data_secret
            )

        if signature_type == SignatureType.SERVICE:
            if not original_schema:
                original_schema = deepcopy(schema)
            # A signature of a schema by a service does not cover the
            # signature of the service so we temporarily remove it
            if not secret or not secret.cert:
                secret = self.service_data_secret

            signature = ServiceSignature.from_dict(
                schema['signatures'].pop(
                    SignatureType.SERVICE.value
                ),
                data_secret=secret
            )

        schema_str: str = self.as_string()
        signature.verify_message(schema_str, secret, hash_algo=hash_algo)

        # Restore the original schema after we popped the signature
        self.json_schema = original_schema

        self.verified_signatures.add(signature_type)

    def get_data_classes(self, with_pubsub: bool = True
                         ) -> dict[str, object]:
        '''
        Finds all objects in the JSON schema for which we will
        need to generate pydantic classes

        :param pubsub: whether to create a PubSub instance for the class
        :returns:
        '''

        _LOGGER.debug('Parsing data classes of the schema')

        # TODO: SECURITY check that urlparse.netloc matches the entity_id for
        # the service

        # First we go over the 'defined' classes
        classes: dict[str, dict] = self.json_schema['jsonschema'].get(
            "$defs", {}
        )

        for iteration in (1, 2, 3):
            classes_todo: dict = {}
            for class_name, class_properties in classes.items():
                _LOGGER.debug(f'Parsing defined class {class_name}')
                try:
                    dataclass: SchemaDataItem = SchemaDataItem.create(
                        class_name, class_properties, self, self.data_classes,
                        with_pubsub=with_pubsub
                    )
                    if dataclass:
                        self.data_classes[class_name] = dataclass
                except ByodaDataClassReferenceNotFound:
                    _LOGGER.debug(
                        f'Adding class {class_name} for creation '
                        'in the next iteration'
                    )
                    classes_todo[class_name] = class_properties

            classes = deepcopy(classes_todo)
            _LOGGER.debug(
                f'classes remaining after iteration {iteration}: '
                f'{len(classes)}'
            )
            if not len(classes):
                # All classes have been generated
                break

        if classes_todo:
            raise ValueError(
                'Could not resolve circular class definition for classes: '
                + ', '.join(classes_todo.keys())
            )

        # now we iterate over the top-level classes
        properties: dict[str, any] = \
            self.json_schema['jsonschema']['properties']
        for class_name, class_properties in properties.items():
            _LOGGER.debug(f'Parsing class {class_name}')
            dataclass = SchemaDataItem.create(
                class_name, class_properties, self, self.data_classes,
                with_pubsub=with_pubsub
            )
            if dataclass:
                self.data_classes[class_name] = dataclass

        return self.data_classes

    def get_data_class(self, class_name: str) -> SchemaDataItem | None:
        '''
        Gets a data class by name

        :param class_name: the name of the data class
        :returns: the data class or None if not found
        :raises: (none)
        '''

        return self.data_classes.get(class_name)

    def generate_data_models(self, codegen_dir: str = CODEGEN_DIRECTORY,
                             datamodels_only: bool = False) -> None:
        '''
        Generates the REST APIs for managing data of the membership

        :param codegen_dir: location where the generated code should be stored
        :returns: (none)
        :raises: ValueError
        '''

        _LOGGER.debug('Generating data models')
        if (self.verify_signatures
                and not (SignatureType.NETWORK in self.verified_signatures and
                         SignatureType.SERVICE in self.verified_signatures)):
            raise ValueError('Schema signatures have not been verified')

        _LOGGER.debug('Generating REST Data APIs')

        environment: jinja2.Environment = self._get_jinja2_environment()

        # Generate one file with the data model for the schema
        header_file: str = 'podserver/templates/pydantic_data_model_header.py'
        with open(header_file) as file_desc:
            data_model_contents: str = file_desc.read()

        class_name: str
        data_class: SchemaDataItem
        for class_name, data_class in self.data_classes.items():
            try:
                source_code: str = data_class.get_pydantic_data_model(
                    environment
                )
                data_model_contents += f'\n{source_code}'
            except NotImplementedError:
                _LOGGER.error(
                    f'Failed to generate pydantic model for {class_name}'
                )

        data_model_code_filename: str = (
            f'{codegen_dir}/pydantic_service_{self.service_id}_'
            f'{self.version}.py'
        )

        module_name: str = self.get_module_name()
        self.generate_module(
            data_model_contents, module_name, data_model_code_filename
        )

        if datamodels_only:
            _LOGGER.debug('Not generating data APIs')
            return

        # Generate one file per data class
        for class_name, data_class in self.data_classes.items():
            if data_class.defined_class:
                continue

            code: str = data_class.get_pydantic_request_model(environment)
            request_type_filename: str = (
                f'{codegen_dir.rstrip("/")}'
                f'/pydantic_{self.service_id}_{self.version}_{class_name}.py'
            )

            class_module_name: str = self.get_module_name(class_name)
            self.generate_module(
                code, class_module_name, request_type_filename
            )

    def get_module_name(self, class_name: str | None = None) -> str:
        '''
        Gets the name of the module for a data class

        :param class_name: the name of the data class, if omitted,
        returns the name of the class with all the Pydantic models
        :returns: the name of the requested module
        '''

        module_name: str
        if class_name is None:
            module_name = f'pydantic_{self.service_id}_{self.version}'
        else:
            module_name = \
                f'pydantic_{self.service_id}_{self.version}_{class_name}'

        return module_name

    def generate_module(self, source_code: str, module_name: str,
                        codegen_filename: str) -> None:
        '''
        Generates module from source code in a module and adds it to
        the list of modules

        :param source_code: the python code generated from the code template
        :param module_name: the name of the module
        :param codegen_filename: the filename for the generated code
        '''

        os.makedirs(os.path.dirname(codegen_filename), exist_ok=True)
        with open(codegen_filename, 'w') as file_desc:
            file_desc.write(source_code)

        compiled_code: CodeType = compile(
            source_code, codegen_filename, 'exec'
        )
        module: ModuleType = ModuleType(module_name)

        # This trick keeps the result of the parsed code out of
        # globals() and locals()
        sys.modules[module_name] = module

        # Now we execute the code as being part of the module we
        # generated
        exec(compiled_code, module.__dict__)

    def get_module(self, class_name: str | None = None) -> ModuleType:
        '''
        Gets the module for a data class

        :param class_name: the name of the data class
        :returns: the module for the data class
        '''

        module_name: str = self.get_module_name(class_name)
        module: ModuleType = sys.modules[module_name]

        return module

    def enable_data_apis(self, app: FastAPI) -> None:
        '''
        Generate & enable the REST Data APIs for the schema

        :param app: the app to which the API routes should be added to
        '''

        self.generate_data_models()

        for class_name, data_class in self.data_classes.items():
            if data_class.defined_class:
                continue

            module_name: str = (
                f'pydantic_{self.service_id}_{self.version}_{class_name}'
            )
            module: ModuleType = sys.modules[module_name]

            app.include_router(module.router)

    def _get_jinja2_environment(self) -> jinja2.Environment:
        '''
        Sets up Jinja2 Environment with appropriate settings
        '''

        loader = jinja2.FileSystemLoader(Schema.SCHEMA_TEMPLATE_DIRECTORY)
        environment = jinja2.Environment(
            loader=loader, trim_blocks=True, autoescape=True,
            extensions=['jinja2.ext.do', 'jinja2.ext.loopcontrols'],
        )

        return environment

    # Getter/Setters for
    # - service_id
    # - version
    # - name
    # - description
    # - owner
    # - website
    # - supportemail
    # - cors_origins
    # - service_signature
    # - network_signature
    # - listen_relations
    # - signatures (only has a getter)

    @property
    def service_id(self):
        '''
        Gets the service_id for the service contract
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['service_id']

    @service_id.setter
    def service_id(self, value: int) -> None:
        '''
        Sets the service_id for the service contract
        '''

        if not isinstance(value, int):
            try:
                value = int(value)
            except ValueError:
                raise ValueError(
                    f'Service ID must be an int, not of type {type(value)}'
                )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['service_id'] = value

    @property
    def version(self) -> int:
        '''
        Gets the version of the service contract
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['version']

    @version.setter
    def version(self, value: int) -> None:
        '''
        Sets the version of the service contract
        '''

        if not isinstance(value, int):
            try:
                value = int(value)
            except ValueError:
                raise ValueError(
                    f'Version must be an int, not of type {type(value)}'
                )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['version'] = value

    @property
    def name(self) -> str:
        '''
        Gets the name of the service
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['name']

    @name.setter
    def name(self, value: str) -> None:
        '''
        Sets the name of the service
        '''

        if value and not isinstance(value, str):
            raise ValueError(
                f'Version must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['name'] = value

    @property
    def description(self) -> str:
        '''
        Gets the description for the service
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['description']

    @description.setter
    def description(self, value: str) -> None:
        '''
        Sets the description for the service
        '''

        if value and not isinstance(value, str):
            raise ValueError(
                f'Description must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['description'] = value

    @property
    def owner(self) -> str:
        '''
        Gets the name of the owner of the service, ie. a person,
        an organization or a company
        '''
        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['owner']

    @owner.setter
    def owner(self, value: str) -> None:
        '''
        Sets the name of the owner of the service, ie. a person,
        an organization or a company
        '''

        if value and not isinstance(value, str):
            raise ValueError(
                f'Name must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['owner'] = value

    @property
    def website(self) -> str:
        '''
        Gets the URL for the website for the service
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['website']

    @website.setter
    def website(self, value: str) -> None:
        '''
        Sets the URL for the website for the service
        '''

        if value and not isinstance(value, str):
            raise ValueError(
                f'Name must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['website'] = value

    @property
    def supportemail(self: str) -> str:
        '''
        Gets the email address for getting support for the service
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['supportemail']

    @supportemail.setter
    def supportemail(self, value: str):
        '''
        Sets the email address for getting support for the service
        '''

        if value and not isinstance(value, str):
            raise ValueError(
                f'Support email must be an str, not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['supportemail'] = value

    @property
    def listen_relations(self) -> list[ListenRelation]:
        '''
        Gets the relations to other pods for which a pod should open
        websockets connections for updates and the class name that
        the updates should be requested for
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        relations: list[ListenRelation] = []

        for data in self.json_schema.get('listen_relations', []):
            relations.append(
                ListenRelation(
                    class_name=data['class_name'],
                    relations=data.get('relations'),
                    destination_class=data['destination_class'],
                    feed_class=data['feed_class'],
                )
            )

        return relations

    @property
    def cors_origins(self):
        '''
        Gets the permitted CORS Origins
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['cors_origins']

    @cors_origins.setter
    def cors_origins(self, values: list[str]):
        '''
        Sets the permitted CORS Origins
        '''

        if values and not isinstance(values, list):
            raise ValueError(
                'CORS Origins must be a list of str, not of type '
                f'{type(values)}'
            )

        for value in values:
            if not isinstance(value, str):
                raise ValueError(
                    'CORS Origins must be a list of str, not of type '
                    f'{type(value)}'
                )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self.json_schema['cors_origins'] = values

    @property
    def network_signature(self) -> MessageSignature:
        '''
        Gets the network signature for the service
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        network_signature = self.json_schema['signatures'].get('network')
        if not network_signature:
            raise ValueError('No network signature avaiable')

    @network_signature.setter
    def network_signature(self, value: MessageSignature):
        '''
        Sets the Network signature in the json_schema dict
        '''

        if value and not isinstance(value, MessageSignature):
            raise ValueError(
                'Support email must be an MessageSignature, '
                f'not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self._network_signature = value

        network_signature = self.json_schema['signatures'].get('network')
        if not network_signature:
            self.json_schema['signatures']['network'] = {}

        self.json_schema['signatures']['network'] = value.as_dict()

    @property
    def service_signature(self) -> MessageSignature:
        '''
        Gets the Service signature in the json_schema dict
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        service_signature = self.json_schema['signatures'].get('service')
        if not service_signature:
            raise ValueError('No service signature avaiable')

        return self._service_signature

    @service_signature.setter
    def service_signature(self, value: MessageSignature) -> MessageSignature:
        '''
        Sets the Service signature in the json_schema dict
        '''

        if value and not isinstance(value, MessageSignature):
            raise ValueError(
                f'service_signature must be an MessageSignature, '
                f'not of type {type(value)}'
            )

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        self._service_signature = value

        service_signature = self.json_schema['signatures'].get('service')
        if not service_signature:
            self.json_schema['signatures']['service'] = {}

        self.json_schema['signatures']['service'] = value.as_dict()

        return self._service_signature

    @property
    def signatures(self) -> dict:
        '''
        Gets the network and service signatures for the service
        '''

        if not self.json_schema:
            raise ValueError('No JSON Schema defined')

        return self.json_schema['signatures']

    @property
    def max_query_depth(self) -> int:
        '''
        Gets the maximium depth for a recursive query
        '''

        return self.json_schema.get('max_query_depth', 1)
