'''
API manager for BYODA

:maintainer: Steven Hessing <stevenhessing@live.com>
:copyright: Copyright 2021
:license: GPLv3
'''

from flask_restx import Api
from flask import url_for

from .status import api as status       # noqa: F401
from .server import api as server       # noqa: F401


class Swagger_Api(Api):
    '''
    This is a modification of the base Flask Restplus Api class due to
    the issue described here:
    https://github.com/noirbizarre/flask-restplus/issues/223
    '''

    @property
    def specs_url(self):
        """
        The Swagger specifications absolute url (ie. `swagger.json`)
        :rtype: str
        """
        return url_for(self.endpoint("specs"), _external=False)


api = Swagger_Api(
    title='Byoda',
    version='0.1',
    description='Byoda APIs',
    prefix='/api',
    doc='/swagger/'
)

api.add_namespace(status)
api.add_namespace(server)
