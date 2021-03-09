'''
Status API

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging

from flask_restx import Namespace, Resource, fields

from byoda.util.logger import flask_log_fields

import byoda.config as config


_LOGGER = logging.getLogger(__name__)


api = Namespace(
    'v1/status',
    description='Get the status of the application server'
)

model = api.model('status', {'message': fields.String})


@api.route('/')
@api.doc('Get the status of the application server')
class StatusApi(Resource):
    @flask_log_fields
    @api.doc('Get the status of the application server')
    @api.response('200', 'Success')
    @api.response('400', 'Invalid request')
    @api.response('500', 'Server error')
    @api.response('503', 'Network communication failure, try again')
    def get(self):
        '''
        '''

        _LOGGER.debug('Status API called')
        try:
            # TODO: implement real health check
            return {'status': 'healthy'}
        except Exception as exc:
            _LOGGER.exception('Health check failed: %s', exc)
            return {'message': 'unexpected failure'}, 500
