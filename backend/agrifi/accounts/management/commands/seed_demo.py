"""Populate a local database with demo accounts, crop categories and stock-backed listings.

Local/demo use only: every account shares a well-known password, so the command refuses to run
unless DJANGO_DEBUG is on. Safe to re-run; existing rows are reused and stock is not duplicated.
"""
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agrifi.accounts.models import BuyerProfile, FarmerProfile, User, UserRole
from agrifi.catalog.models import CropCategory, Listing
from agrifi.inventory import services as inventory
from agrifi.inventory.models import HarvestBatch

PASSWORD = 'AgriFi-Demo-2026!'
Role = UserRole.Role

CATEGORIES = (
    ('Maize', 'maize', 'Dry yellow and white maize grain.'),
    ('Cassava', 'cassava', 'Fresh cassava tubers and chips.'),
    ('Yam', 'yam', 'Tubers from the Benue and Kwara belts.'),
    ('Cocoa', 'cocoa', 'Fermented and dried cocoa beans.'),
    ('Rice', 'rice', 'Locally milled paddy and parboiled rice.'),
    ('Tomatoes', 'tomatoes', 'Fresh tomatoes from Kano and Plateau.'),
)

STAFF = (
    ('ops@agrifi.demo', Role.OPERATIONS_ADMIN),
    ('finance@agrifi.demo', Role.FINANCE_OPERATOR),
)

FARMERS = (
    ('farmer@agrifi.demo', 'Adaeze Okafor Farms', 'South East', 'Enugu'),
    ('farmer2@agrifi.demo', 'Musa Ibrahim Agro', 'North West', 'Kano'),
)

BUYERS = (
    ('buyer@agrifi.demo', 'Lagos Fresh Foods Ltd', 'South West', 'Lagos'),
)

# (farmer email, category slug, name, unit, kobo per unit, batch qty, listed qty)
LISTINGS = (
    ('farmer@agrifi.demo', 'maize', 'Premium white maize', 'kg', 35_000, '5000.000', '3000.000'),
    ('farmer@agrifi.demo', 'cassava', 'Fresh cassava tubers', 'tonne', 9_500_000, '40.000', '25.000'),
    ('farmer@agrifi.demo', 'yam', 'Benue yam (large)', 'piece', 120_000, '800.000', '500.000'),
    ('farmer2@agrifi.demo', 'rice', 'Parboiled local rice', 'bag', 4_800_000, '300.000', '200.000'),
    ('farmer2@agrifi.demo', 'tomatoes', 'Roma tomatoes', 'crate', 1_800_000, '120.000', '80.000'),
    ('farmer2@agrifi.demo', 'cocoa', 'Dried cocoa beans', 'kg', 280_000, '2000.000', '1500.000'),
)


def _user(email, role, first_name=''):
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(email=email, password=PASSWORD, first_name=first_name)
    else:
        user.set_password(PASSWORD)
        user.save(update_fields=['password'])
    UserRole.objects.get_or_create(user=user, role=role)
    return user


class Command(BaseCommand):
    help = 'Create demo users, categories and listings for local development (DEBUG only).'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_demo only runs when DJANGO_DEBUG is true.')

        for name, slug, description in CATEGORIES:
            CropCategory.objects.get_or_create(
                slug=slug, defaults={'name': name, 'description': description}
            )

        users = {}
        for email, role in STAFF:
            users[email] = _user(email, role, first_name=role.label)
        for email, display_name, region, location in FARMERS:
            users[email] = _user(email, Role.FARMER, first_name=display_name.split()[0])
            FarmerProfile.objects.get_or_create(
                user=users[email],
                defaults={'display_name': display_name, 'region': region, 'location': location},
            )
        for email, business_name, region, location in BUYERS:
            users[email] = _user(email, Role.BUYER, first_name='Buyer')
            BuyerProfile.objects.get_or_create(
                user=users[email],
                defaults={'business_name': business_name, 'region': region, 'location': location},
            )

        ops = users['ops@agrifi.demo']
        created = 0
        for farmer_email, slug, name, unit, price, batch_qty, listed_qty in LISTINGS:
            farmer = users[farmer_email]
            category = CropCategory.objects.get(slug=slug)
            listing, was_created = Listing.objects.get_or_create(
                seller=farmer, category=category, name=name,
                defaults={
                    'description': f'{name} supplied directly by the farmer.',
                    'unit_code': unit,
                    'unit_price_minor': price,
                    'status': Listing.Status.ACTIVE,
                },
            )
            if not was_created:
                continue
            batch = HarvestBatch.objects.create(
                farmer=farmer, category=category, quantity=Decimal(batch_qty),
                unit_code=unit, harvested_on=date.today(), notes='Demo harvest batch.',
            )
            inventory.accept_batch(batch.pk, ops)
            inventory.allocate(listing.pk, batch.pk, Decimal(listed_qty), farmer)
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Demo data ready ({created} new listings). Password for all demo accounts: {PASSWORD}'
        ))
        for email in users:
            self.stdout.write(f'  {email}')
