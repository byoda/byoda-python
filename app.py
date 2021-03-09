#!/usr/bin/env python3

import os
import sys
PATH = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, PATH)

server = os.environ.get('BYODA_APP', 'dirserver')

if server == 'dirserver':
    from dirserver import create_app        # noqa: E402
elif server == 'podserver':
    from podserver import create_app        # noqa: E402

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
