from django.db import migrations

TABLE = 'audit_auditevent'


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        f'CREATE TRIGGER {TABLE}_immutable BEFORE UPDATE OR DELETE ON {TABLE} '
        'FOR EACH ROW EXECUTE FUNCTION agrifi_forbid_mutation();'
    )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(f'DROP TRIGGER IF EXISTS {TABLE}_immutable ON {TABLE};')


class Migration(migrations.Migration):
    dependencies = [
        ('audit', '0001_initial'),
        # Defines agrifi_forbid_mutation().
        ('inventory', '0003_immutable_ledger_triggers'),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
