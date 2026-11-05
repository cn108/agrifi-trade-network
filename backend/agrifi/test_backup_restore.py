import os
import sqlite3
import tempfile

from django.db import connection
from django.test import TransactionTestCase, skipUnlessDBFeature

from agrifi.accounts.models import User
from agrifi.audit.models import AuditEvent


@skipUnlessDBFeature('supports_transactions')
class SqliteBackupRestoreTests(TransactionTestCase):
    """Proves the documented SQLite backup/restore procedure on a real copy.
    SQLite only: says nothing about the PostgreSQL pg_dump/pg_restore procedure.
    Uses TransactionTestCase because the online backup needs no open transaction."""

    def setUp(self):
        if connection.vendor != 'sqlite':
            self.skipTest('SQLite-only restore test')

    def test_backup_copy_restores_identical_data_and_passes_integrity_check(self):
        for index in range(3):
            User.objects.create_user(email=f'backup{index}@example.com', password='pw-test-2026-strong')
        expected_users = User.objects.count()
        expected_events = AuditEvent.objects.count()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'backup.sqlite3')
            destination = sqlite3.connect(path)
            try:
                connection.connection.backup(destination)
            finally:
                destination.close()

            restored = sqlite3.connect(path)
            try:
                self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM accounts_user').fetchone()[0], expected_users)
                self.assertEqual(restored.execute('SELECT COUNT(*) FROM audit_auditevent').fetchone()[0], expected_events)
                self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(), [])
            finally:
                restored.close()
