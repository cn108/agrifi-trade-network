import logging
import re
import time
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = 'X-Request-ID'
VALID_REQUEST_ID = re.compile(r'^[A-Za-z0-9._-]{8,64}$')

_request_id = ContextVar('agrifi_request_id', default=None)
logger = logging.getLogger('agrifi.request')


def get_request_id():
    return _request_id.get()


class RequestIdMiddleware:
    """Attach a correlation ID to every request, log line and response.

    A caller-supplied X-Request-ID is reused only when it is short and made of safe
    characters; anything else is replaced so it cannot inject into logs or headers.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.META.get('HTTP_X_REQUEST_ID', '')
        request_id = supplied if VALID_REQUEST_ID.match(supplied) else uuid.uuid4().hex
        request.request_id = request_id
        token = _request_id.set(request_id)
        started = time.monotonic()
        try:
            response = self.get_response(request)
        finally:
            _request_id.reset(token)
        response[REQUEST_ID_HEADER] = request_id
        # Path only: query strings and bodies may carry personal data.
        logger.info(
            '%s %s', request.method, request.path,
            extra={
                'status_code': response.status_code,
                'request_id': request_id,
                'duration_ms': round((time.monotonic() - started) * 1000, 1),
            },
        )
        return response
