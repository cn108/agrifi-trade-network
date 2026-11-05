import json
import logging
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from config.logging import JsonFormatter


class HealthAndLoggingTests(TestCase):
    def test_liveness_and_readiness(self):
        self.assertEqual(self.client.get(reverse('health-check')).json(), {'status': 'ok'})
        self.assertEqual(self.client.get(reverse('readiness-check')).json(), {'status': 'ready'})

    def test_readiness_failure_returns_503_without_leaking_details(self):
        with mock.patch('config.urls.connection') as connection, self.assertLogs('agrifi.health', 'ERROR'):
            connection.cursor.side_effect = RuntimeError('db password=hunter2 host=internal')
            response = self.client.get(reverse('readiness-check'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})
        self.assertNotIn('hunter2', response.content.decode())

    def test_json_formatter_emits_one_json_object(self):
        record = logging.LogRecord('agrifi.test', logging.INFO, __file__, 1, 'hello %s', ('world',), None)
        parsed = json.loads(JsonFormatter().format(record))
        self.assertEqual(parsed['message'], 'hello world')
        self.assertEqual(parsed['level'], 'INFO')
