import logging

from django.http import JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .request_context import get_request_id

logger = logging.getLogger('agrifi.api')

DEFAULT_CODES = {
    status.HTTP_401_UNAUTHORIZED: 'not_authenticated',
    status.HTTP_403_FORBIDDEN: 'permission_denied',
    status.HTTP_404_NOT_FOUND: 'not_found',
    status.HTTP_405_METHOD_NOT_ALLOWED: 'method_not_allowed',
    status.HTTP_429_TOO_MANY_REQUESTS: 'throttled',
}


def _flatten(detail):
    if isinstance(detail, (list, tuple)):
        return ' '.join(_flatten(item) for item in detail)
    if isinstance(detail, dict):
        return ' '.join(_flatten(item) for item in detail.values())
    return str(detail)


def build_error(code, message, request_id, fields=None):
    body = {
        'code': code,
        'message': message,
        # Kept for clients written before the standard envelope existed.
        'detail': message,
        'request_id': request_id,
    }
    if fields:
        body['fields'] = fields
    return body


def server_error(request, *args, **kwargs):
    """handler500: JSON envelope for unexpected failures. Exception text is never returned."""
    return JsonResponse(
        build_error('server_error', 'An unexpected error occurred.', get_request_id()),
        status=500,
    )


def exception_handler(exc, context):
    """Single error envelope: {code, message, detail, fields?, request_id}."""
    request_id = get_request_id()
    response = drf_exception_handler(exc, context)
    if response is None:
        # Unexpected exception: let Django log it and call handler500 (server_error below).
        return None

    data = response.data
    code = DEFAULT_CODES.get(response.status_code, 'error')
    fields = None
    if isinstance(exc, exceptions.ValidationError):
        code = 'validation_error'
        if isinstance(data, dict):
            fields = {key: value for key, value in data.items()}
            message = 'The request was not valid.'
        else:
            message = _flatten(data)
    elif isinstance(data, dict) and 'code' in data and 'detail' in data:
        # Business-rule errors raised by the app services.
        code, message = str(data['code']), _flatten(data['detail'])
    else:
        message = _flatten(data.get('detail', data) if isinstance(data, dict) else data)
        if isinstance(exc, exceptions.APIException) and not isinstance(
            exc, (exceptions.NotAuthenticated, exceptions.PermissionDenied, exceptions.NotFound),
        ):
            codes = exc.get_codes()
            if isinstance(codes, str) and codes not in ('error', 'invalid'):
                code = codes
    response.data = build_error(code, message, request_id, fields)
    return response
