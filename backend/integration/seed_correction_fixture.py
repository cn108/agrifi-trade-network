"""Seed the isolated manual-test / integration database.

Run ONLY against a throwaway database (set AGRIFI_SQLITE_PATH first), from backend/:
    python manage.py shell -c "exec(open('integration/seed_correction_fixture.py').read())"

Idempotent: re-running resets these two accounts' passwords to the values below.
Used by web/src/app/integration/farmer-correction.integration.spec.ts and for manual browser testing.
"""
from agrifi.accounts.models import BuyerProfile, FarmerProfile, User, UserRole  # noqa: F401
from agrifi.catalog.models import CropCategory

PASSWORD = 'pw-test-2026-strong'

ACCOUNTS = (
    ('it-farmer@example.com', UserRole.Role.FARMER),
    ('it-ops@example.com', UserRole.Role.OPERATIONS_ADMIN),
)

for email, role in ACCOUNTS:
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(email=email, password=PASSWORD)
    else:
        user.set_password(PASSWORD)
        user.save(update_fields=['password'])
    UserRole.objects.get_or_create(user=user, role=role)
    if role == UserRole.Role.FARMER:
        FarmerProfile.objects.get_or_create(user=user, defaults={'display_name': email})

CropCategory.objects.get_or_create(slug='it-maize', defaults={'name': 'IT Maize'})
print('seeded:', ', '.join(email for email, _ in ACCOUNTS), '| password:', PASSWORD)
