from django.db import migrations


IMMUTABLE_TABLES = (
    'finance_ledgeraccount',
    'finance_journal',
    'finance_journalline',
    'finance_simulatedpayment',
    'finance_refund',
    'finance_settlement',
)

CREATE_BALANCE_FUNCTION = """
CREATE OR REPLACE FUNCTION agrifi_validate_finance_journal() RETURNS trigger AS $$
DECLARE
    target_id uuid;
    line_count bigint;
    debits numeric;
    credits numeric;
    stored_debits bigint;
    stored_credits bigint;
    journal_currency char(3);
    mismatched_accounts bigint;
BEGIN
    IF TG_TABLE_NAME = 'finance_journal' THEN
        target_id := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        target_id := OLD.journal_id;
    ELSE
        target_id := NEW.journal_id;
    END IF;

    SELECT debit_total_minor, credit_total_minor, currency
      INTO stored_debits, stored_credits, journal_currency
      FROM finance_journal WHERE id = target_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT COUNT(*), COALESCE(SUM(debit_minor), 0), COALESCE(SUM(credit_minor), 0)
      INTO line_count, debits, credits
      FROM finance_journalline WHERE journal_id = target_id;
    SELECT COUNT(*)
      INTO mismatched_accounts
      FROM finance_journalline l
      JOIN finance_ledgeraccount a ON a.id = l.account_id
     WHERE l.journal_id = target_id AND a.currency <> journal_currency;

    IF line_count < 2 OR debits <= 0 OR debits <> credits
       OR debits <> stored_debits OR credits <> stored_credits
       OR mismatched_accounts > 0 THEN
        RAISE EXCEPTION 'journal % is not balanced or has inconsistent currency', target_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

DROP_BALANCE_FUNCTION = 'DROP FUNCTION IF EXISTS agrifi_validate_finance_journal();'


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for table in IMMUTABLE_TABLES:
        schema_editor.execute(
            f'CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} '
            'FOR EACH ROW EXECUTE FUNCTION agrifi_forbid_mutation();'
        )
    # params=None: the function body contains a literal % that psycopg would treat as a placeholder.
    schema_editor.execute(CREATE_BALANCE_FUNCTION, params=None)
    schema_editor.execute(
        'CREATE CONSTRAINT TRIGGER finance_journal_balance_check '
        'AFTER INSERT OR UPDATE ON finance_journal '
        'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW '
        'EXECUTE FUNCTION agrifi_validate_finance_journal();'
    )
    schema_editor.execute(
        'CREATE CONSTRAINT TRIGGER finance_journal_line_balance_check '
        'AFTER INSERT OR UPDATE OR DELETE ON finance_journalline '
        'DEFERRABLE INITIALLY DEFERRED FOR EACH ROW '
        'EXECUTE FUNCTION agrifi_validate_finance_journal();'
    )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    schema_editor.execute(
        'DROP TRIGGER IF EXISTS finance_journal_line_balance_check ON finance_journalline;'
    )
    schema_editor.execute(
        'DROP TRIGGER IF EXISTS finance_journal_balance_check ON finance_journal;'
    )
    for table in IMMUTABLE_TABLES:
        schema_editor.execute(f'DROP TRIGGER IF EXISTS {table}_immutable ON {table};')
    schema_editor.execute(DROP_BALANCE_FUNCTION)


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0001_initial'),
        ('inventory', '0003_immutable_ledger_triggers'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
