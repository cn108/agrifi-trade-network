from django.db import migrations

TABLES = ('orders_orderitem', 'orders_orderstatushistory')


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in TABLES:
        schema_editor.execute(
            f'CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} '
            'FOR EACH ROW EXECUTE FUNCTION agrifi_forbid_mutation();'
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in TABLES:
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {table}_immutable ON {table};')


class Migration(migrations.Migration):
    dependencies = [
        ('orders', '0001_initial'),
        ('inventory', '0003_immutable_ledger_triggers'),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
