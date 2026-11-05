"""Stock services: the only code that writes StockMovement or Reservation rows.

Every operation runs in a transaction. Stock-changing lock order is listing, batch,
reservation; acceptance locks only the batch and never waits on another lock."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, DecimalField, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from agrifi.audit import services as audit
from agrifi.catalog.models import Listing
from agrifi.catalog.permissions import is_ops_admin

from .models import HarvestBatch, Reservation, StockMovement

ZERO = Decimal('0')
DEFAULT_RESERVATION_TTL = timedelta(minutes=15)
T = StockMovement.Type


class InventoryError(Exception):
    """Business-rule violation. `code` is machine-readable."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class InsufficientStock(InventoryError):
    def __init__(self, message='Insufficient stock.'):
        super().__init__('insufficient_stock', message)


def _signed(plus, minus):
    return Case(
        *[When(movement_type=t, then=F('quantity')) for t in plus],
        *[When(movement_type=t, then=-F('quantity')) for t in minus],
        default=Value(ZERO), output_field=DecimalField(max_digits=14, decimal_places=3),
    )


def _sum(queryset, *, plus=(), minus=()):
    return queryset.aggregate(total=Sum(_signed(plus, minus)))['total'] or ZERO


def annotate_listing_stock(queryset, now=None):
    """Annotate listings with `stock_on_hand` and `stock_reserved` in one query, using
    exactly the rules of listing_on_hand / listing_reserved (same ledger, same expiry
    test). Replaces two per-row queries when listing many offers."""
    now = now or timezone.now()
    decimal = DecimalField(max_digits=14, decimal_places=3)
    on_hand = StockMovement.objects.filter(listing=OuterRef('pk')).order_by().values('listing').annotate(
        total=Sum(_signed((T.ALLOCATION,), (T.DEALLOCATION, T.SALE))),
    ).values('total')
    reserved = Reservation.objects.filter(
        listing=OuterRef('pk'), status=Reservation.Status.ACTIVE,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).order_by().values('listing').annotate(
        total=Sum('quantity'),
    ).values('total')
    return queryset.annotate(
        stock_on_hand=Coalesce(Subquery(on_hand, output_field=decimal), Value(ZERO), output_field=decimal),
        stock_reserved=Coalesce(Subquery(reserved, output_field=decimal), Value(ZERO), output_field=decimal),
    )


def batch_free(batch):
    return _sum(
        StockMovement.objects.filter(batch=batch),
        plus=(T.RECEIPT, T.DEALLOCATION), minus=(T.ALLOCATION,),
    )


def listing_on_hand(listing):
    return _sum(
        StockMovement.objects.filter(listing=listing),
        plus=(T.ALLOCATION,), minus=(T.DEALLOCATION, T.SALE),
    )


def listing_batch_net(listing, batch):
    return _sum(
        StockMovement.objects.filter(listing=listing, batch=batch),
        plus=(T.ALLOCATION,), minus=(T.DEALLOCATION, T.SALE),
    )


def listing_reserved(listing, now=None):
    now = now or timezone.now()
    total = Reservation.objects.filter(
        listing=listing, status=Reservation.Status.ACTIVE,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now),
    ).aggregate(total=Sum('quantity'))['total']
    return total or ZERO


def listing_stock(listing, now=None):
    on_hand = listing_on_hand(listing)
    reserved = listing_reserved(listing, now)
    return {'on_hand': on_hand, 'reserved': reserved, 'available': on_hand - reserved}


def _positive(quantity):
    quantity = Decimal(quantity)
    if quantity <= 0 or quantity != quantity.quantize(Decimal('0.001')):
        raise InventoryError('invalid_quantity', 'Quantity must be positive with at most 3 decimals.')
    return quantity


def accept_batch(batch_id, reviewer):
    if not is_ops_admin(reviewer):
        raise InventoryError('forbidden', 'Only operations administrators can accept batches.')
    with transaction.atomic():
        batch = HarvestBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != HarvestBatch.Status.SUBMITTED:
            raise InventoryError('invalid_state', f'Batch is already {batch.status}.')
        if not batch.category.is_active:
            raise InventoryError('inactive_category', 'The batch category is not active.')
        batch.status = HarvestBatch.Status.ACCEPTED
        batch.reviewed_by = reviewer
        batch.reviewed_at = timezone.now()
        batch.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
        StockMovement.objects.create(
            batch=batch, movement_type=T.RECEIPT, quantity=batch.quantity, created_by=reviewer,
        )
        audit.record('harvest_batch.accepted', reviewer, batch, {'quantity': batch.quantity})
    return batch


def reject_batch(batch_id, reviewer, reason=''):
    if not is_ops_admin(reviewer):
        raise InventoryError('forbidden', 'Only operations administrators can reject batches.')
    with transaction.atomic():
        batch = HarvestBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != HarvestBatch.Status.SUBMITTED:
            raise InventoryError('invalid_state', f'Batch is already {batch.status}.')
        batch.status = HarvestBatch.Status.REJECTED
        batch.reviewed_by = reviewer
        batch.reviewed_at = timezone.now()
        batch.rejection_reason = reason
        batch.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'rejection_reason', 'updated_at',
        ])
        audit.record('harvest_batch.rejected', reviewer, batch, {'reason': reason})
    return batch


def allocate(listing_id, batch_id, quantity, user):
    quantity = _positive(quantity)
    with transaction.atomic():
        listing = Listing.objects.select_for_update().get(pk=listing_id)
        batch = HarvestBatch.objects.select_for_update().get(pk=batch_id)
        if batch.status != HarvestBatch.Status.ACCEPTED:
            raise InventoryError('batch_not_accepted', 'Only accepted batches can be allocated.')
        if batch.farmer_id != listing.seller_id:
            raise InventoryError('owner_mismatch', 'Batch and listing belong to different sellers.')
        if user.pk != listing.seller_id:
            raise InventoryError('forbidden', 'Only the listing seller can allocate stock.')
        if batch.category_id != listing.category_id or batch.unit_code != listing.unit_code:
            raise InventoryError('mismatch', 'Batch and listing must share category and unit.')
        if quantity > batch_free(batch):
            raise InsufficientStock('Quantity exceeds unallocated stock in the batch.')
        movement = StockMovement.objects.create(
            batch=batch, listing=listing, movement_type=T.ALLOCATION,
            quantity=quantity, created_by=user,
        )
        audit.record('listing.stock_allocated', user, listing, {'batch_id': batch.pk, 'quantity': quantity})
        return movement


def deallocate(listing_id, batch_id, quantity, user):
    quantity = _positive(quantity)
    with transaction.atomic():
        listing = Listing.objects.select_for_update().get(pk=listing_id)
        batch = HarvestBatch.objects.select_for_update().get(pk=batch_id)
        if batch.farmer_id != listing.seller_id or user.pk != listing.seller_id:
            raise InventoryError('forbidden', 'Only the listing seller can deallocate stock.')
        if batch.status != HarvestBatch.Status.ACCEPTED:
            raise InventoryError('batch_not_accepted', 'Only accepted batches can be deallocated.')
        if quantity > listing_batch_net(listing, batch):
            raise InsufficientStock('Quantity exceeds what this listing holds from the batch.')
        if quantity > listing_stock(listing)['available']:
            raise InsufficientStock('Quantity is committed to active reservations.')
        movement = StockMovement.objects.create(
            batch=batch, listing=listing, movement_type=T.DEALLOCATION,
            quantity=quantity, created_by=user,
        )
        audit.record('listing.stock_deallocated', user, listing, {'batch_id': batch.pk, 'quantity': quantity})
        return movement


def reserve(listing_id, quantity, reference='', ttl=DEFAULT_RESERVATION_TTL):
    quantity = _positive(quantity)
    with transaction.atomic():
        listing = Listing.objects.select_for_update().get(pk=listing_id)
        if listing.status != Listing.Status.ACTIVE:
            raise InventoryError('listing_not_active', 'Listing is not active.')
        if quantity > listing_stock(listing)['available']:
            raise InsufficientStock()
        return Reservation.objects.create(
            listing=listing, quantity=quantity, reference=reference,
            expires_at=timezone.now() + ttl,
        )


def _lock_active_reservation(reservation_id, lock_listing=False):
    """Lock a reservation after its listing when stock is affected."""
    if lock_listing:
        listing_id = Reservation.objects.values_list('listing_id', flat=True).get(pk=reservation_id)
        Listing.objects.select_for_update().get(pk=listing_id)
    reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
    if reservation.status != Reservation.Status.ACTIVE:
        raise InventoryError('invalid_state', f'Reservation is {reservation.status}.')
    return reservation


def release(reservation_id):
    with transaction.atomic():
        reservation = _lock_active_reservation(reservation_id)
        reservation.status = Reservation.Status.RELEASED
        reservation.resolved_at = timezone.now()
        reservation.save(update_fields=['status', 'resolved_at'])
    return reservation


def release_if_active(reservation_id):
    """Release a reservation unless it already ended (expired/consumed/released)."""
    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
        if reservation.status == Reservation.Status.ACTIVE:
            reservation.status = Reservation.Status.RELEASED
            reservation.resolved_at = timezone.now()
            reservation.save(update_fields=['status', 'resolved_at'])
    return reservation


def commit_reservation(reservation_id):
    """Make an active reservation non-expiring after an order is confirmed."""
    with transaction.atomic():
        reservation = _lock_active_reservation(reservation_id, lock_listing=True)
        if reservation.expires_at is not None and reservation.expires_at <= timezone.now():
            raise InventoryError('reservation_expired', 'Reservation has expired.')
        reservation.expires_at = None
        reservation.save(update_fields=['expires_at'])
    return reservation


def consume(reservation_id, user=None):
    """Turn an active, unexpired reservation into SALE movements drawn FIFO
    from the batches allocated to the listing."""
    with transaction.atomic():
        reservation = _lock_active_reservation(reservation_id, lock_listing=True)
        listing = Listing.objects.get(pk=reservation.listing_id)
        if user is not None and user.pk != listing.seller_id:
            raise InventoryError('forbidden', 'Only the listing seller can fulfil stock.')
        if reservation.expires_at is not None and reservation.expires_at <= timezone.now():
            raise InventoryError('reservation_expired', 'Reservation has expired.')
        remaining = reservation.quantity
        batch_ids = (
            StockMovement.objects.filter(listing=listing, movement_type=T.ALLOCATION)
            .order_by('created_at', 'id').values_list('batch_id', flat=True)
        )
        seen = []
        for batch_id in batch_ids:
            if batch_id in seen:
                continue
            seen.append(batch_id)
            net = listing_batch_net(listing, batch_id)
            take = min(net, remaining)
            if take > 0:
                StockMovement.objects.create(
                    batch_id=batch_id, listing=listing, movement_type=T.SALE, quantity=take,
                    reference=f'reservation:{reservation.pk}', created_by=user,
                )
                remaining -= take
            if remaining == 0:
                break
        if remaining > 0:
            raise InsufficientStock('Allocated stock no longer covers the reservation.')
        reservation.status = Reservation.Status.CONSUMED
        reservation.resolved_at = timezone.now()
        reservation.save(update_fields=['status', 'resolved_at'])
    return reservation


def expire_reservations(now=None):
    """Mark overdue active reservations as expired (audit only; availability already
    ignores them). Returns the number expired."""
    now = now or timezone.now()
    count = 0
    with transaction.atomic():
        due = Reservation.objects.select_for_update().filter(
            status=Reservation.Status.ACTIVE, expires_at__isnull=False, expires_at__lte=now,
        )
        for reservation in due:
            reservation.status = Reservation.Status.EXPIRED
            reservation.resolved_at = now
            reservation.save(update_fields=['status', 'resolved_at'])
            count += 1
    return count
def audit_stock(now=None):
    """Recompute every balance from the ledger and return human-readable problems.
    An empty list means: no batch, listing or listing/batch pair is negative and no
    listing has more unexpired reservations than on-hand stock."""
    problems = []
    for batch in HarvestBatch.objects.all():
        if batch_free(batch) < 0:
            problems.append(f'batch {batch.pk}: negative free stock')
    pairs = StockMovement.objects.exclude(listing=None).values_list('listing_id', 'batch_id').distinct()
    for listing_id, batch_id in pairs:
        if listing_batch_net(listing_id, batch_id) < 0:
            problems.append(f'listing {listing_id}/batch {batch_id}: negative allocation')
    for listing in Listing.objects.filter(stock_movements__isnull=False).distinct():
        values = listing_stock(listing, now)
        if values['on_hand'] < 0 or values['available'] < 0:
            problems.append(f'listing {listing.pk}: on_hand/available negative {values}')
    return problems
