from django.db import migrations

# Row-level triggers only: TRUNCATE does not fire them, which keeps test-database
# flushes working while still blocking any UPDATE or DELETE of ledger rows.
CREATE_FUNCTION = """
CREATE OR REPLACE FUNCTION agrifi_forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed: rows are immutable', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""
DROP_FUNCTION = 'DROP FUNCTION IF EXISTS agrifi_forbid_mutation();'

CREATE_TRIGGER = """
CREATE TRIGGER inventory_stockmovement_immutable
BEFORE UPDATE OR DELETE ON inventory_stockmovement
FOR EACH ROW EXECUTE FUNCTION agrifi_forbid_mutation();
"""
DROP_TRIGGER = 'DROP TRIGGER IF EXISTS inventory_stockmovement_immutable ON inventory_stockmovement;'


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        # params=None: the function body contains literal % characters that psycopg
        # would otherwise treat as placeholders.
        schema_editor.execute(CREATE_FUNCTION, params=None)
        schema_editor.execute(CREATE_TRIGGER)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(DROP_TRIGGER)
        # The shared function is dropped by the migration that created it only if no
        # other table still uses it; later apps own their own triggers.
        schema_editor.execute(DROP_FUNCTION)


class Migration(migrations.Migration):
    dependencies = [('inventory', '0002_stock_ledger_and_review')]
    operations = [migrations.RunPython(forwards, backwards)]
