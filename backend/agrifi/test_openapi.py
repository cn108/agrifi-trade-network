import json
from unittest import skipUnless

from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient

from agrifi.catalog.tests import make_user
from agrifi.accounts.models import UserRole

SCHEMA_URL = '/api/v1/schema/?format=json'


@skipUnless(settings.HAS_SPECTACULAR, 'drf-spectacular is not installed in this environment')
class OpenApiSchemaTests(TestCase):
    """The published contract must be generated from the real routes and cover every API area."""

    def setUp(self):
        self.client = APIClient()
        self.ops = make_user('schema-ops@example.com', UserRole.Role.OPERATIONS_ADMIN)
        self.buyer = make_user('schema-buyer@example.com', UserRole.Role.BUYER)

    def schema(self):
        self.client.force_authenticate(self.ops)
        response = self.client.get(SCHEMA_URL)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def test_schema_documents_every_api_area(self):
        paths = self.schema()['paths']

        for expected in (
            '/api/v1/auth/login/', '/api/v1/harvest-batches/', '/api/v1/orders/',
            '/api/v1/finance/reports/', '/api/v1/audit-events/', '/api/v1/sync/operations/',
            '/api/v1/simulated-payments/',
        ):
            self.assertIn(expected, paths)

    def test_schema_states_that_money_is_simulated(self):
        self.assertIn('SIMULATED', self.schema()['info']['description'])

    def test_schema_is_restricted_to_operations_admins_when_not_debug(self):
        if settings.DEBUG:
            self.skipTest('Schema is intentionally open when DEBUG is on.')
        self.client.force_authenticate(self.buyer)
        self.assertEqual(self.client.get(SCHEMA_URL).status_code, 403)
