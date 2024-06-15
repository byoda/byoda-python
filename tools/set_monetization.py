#!/usr/bin/env python3

'''
Add monetization to existing byoda-hosted assets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from typing import Any, Dict, Tuple

from psycopg import Cursor, connect
from psycopg import Connection
from psycopg.rows import dict_row

from byoda.datamodel.monetization import Monetizations
from byoda.datamodel.monetization import BurstMonetization

monetizations: Monetizations = Monetizations.from_monetization_instance(
    BurstMonetization()
)
monetizations_data: bytes = monetizations.as_json()

conn: Connection[Tuple] = connect(
    'postgresql://postgres:byoda@postgres/byoda', autocommit=True,
)
cur: Cursor[Dict[str, Any]] = conn.cursor(row_factory=dict_row)

rows: list[dict_row] = cur.execute(
    '''
        SELECT _asset_id
        FROM _public_assets_16384
        WHERE _ingest_status='published' AND _creator='Dathes';
    '''
).fetchall()

for row in rows:
    conn.execute(
        '''
            UPDATE _public_assets_16384
            SET _monetizations=%(mon)s
            WHERE _asset_id=%(asset_id)s;
        ''',
        {
            'mon': monetizations_data,
            'asset_id': row['_asset_id']
        }
    )
    print(row)
    print(f'Updated monetization for asset {row["_asset_id"]}')

conn.close()

print(f'Updated {len(rows)} rows with monetization {monetizations.as_dict()} ')
