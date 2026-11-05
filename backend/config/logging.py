import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Exception tracebacks are included; message args are not
    inspected, so callers must never log credentials or request bodies."""

    def format(self, record):
        payload = {
            'ts': datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        for key, value in getattr(record, '__dict__', {}).items():
            if key in ('status_code', 'request_id', 'user_id', 'duration_ms'):
                payload[key] = value
        if 'request_id' not in payload:
            from agrifi.request_context import get_request_id
            request_id = get_request_id()
            if request_id:
                payload['request_id'] = request_id
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
