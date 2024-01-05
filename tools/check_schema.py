#!/usr/bin/env python3


import sys

import orjson

from anyio import run

from byoda.datamodel.schema import Schema

from byoda.storage.filestorage import FileStorage

from byoda.util.logger import Logger


async def main(_) -> None:
    schema_filepath: str = 'tests/collateral/byotube.json'
    with open(schema_filepath, 'rb') as file_desc:
        schema = orjson.loads(file_desc.read())

    schema_data = schema['jsonschema']

    for class_name, data_class in schema_data['properties'].items():
        if 'type' not in data_class:
            raise ValueError(f'Class {class_name} does not have a type field')

        if 'properties' in data_class:
            props = data_class['properties'].items()
            for child_class_name, child_class in props:
                if 'type' not in data_class:
                    raise ValueError(
                        f'Referenced class {child_class_name} of {class_name} '
                        'does not have a type field'
                    )
        else:
            if 'type' not in data_class:
                raise ValueError(f'{class_name} does not have a type field')

    for class_name, data_class in schema_data['$defs'].items():
        for child_name, child_class in data_class['properties'].items():
            if 'type' not in child_class:
                raise ValueError(
                    f'Field {child_name} of class {class_name} does not have '
                    'a type field'
                )

    file_storage = FileStorage('/home/steven/src/byoda-python')
    schema: Schema = await Schema.get_schema(
        schema_filepath, file_storage, None, None,
        verify_contract_signatures=False
    )
    classes: dict[str, object] = schema.get_data_classes(with_pubsub=False)
    if not classes:
        raise ValueError('No data classes found in schema')

if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    run(main, sys.argv)
