"""Order workflow. The only code that creates orders or changes their status.

Lock order across the whole system: order -> listing -> batch -> reservation.
Checkout locks listings (sorted by id) and only then inserts the new order."""
from datetime import timedelta
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from agrifi.accounts.models import UserRole
from agrifi.accounts.permissions import user_has_role
from agrifi.audit import services as audit
from agrifi.catalog.models import Listing
from agrifi.catalog.permissions import is_ops_admin
from agrifi.inventory import services as stock
from agrifi.inventory.models import Reservation

from .models import Dispute, Order, OrderItem, OrderStatusHistory

S = Order.Status
MAX_ITEMS = 50
MAX_MINOR = 9_223_372_036_854_775_807
BUYER, SELLER, ADMIN = 'buyer', 'seller', 'admin'

# (from, to) -> roles allowed to perform it. Anything not listed is forbidden.
TRANSITIONS = {
    (S.PENDING, S.CONFIRMED): {SELLER},
    (S.PENDING, S.CANCELLED): {BUYER, SELLER, ADMIN},
    (S.CONFIRMED, S.SHIPPED): {SELLER},
    (S.SHIPPED, S.DELIVERED): {SELLER},
    (S.DELIVERED, S.COMPLETED): {BUYER},
}
DISPUTABLE = {S.CONFIRMED, S.SHIPPED, S.DELIVERED, S.COMPLETED}


class OrderError(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def reservation_ttl():
    return timedelta(hours=getattr(settings, 'ORDER_RESERVATION_TTL_HOURS', 48))


def line_total_minor(unit_price_minor, quantity):
    """Integer kobo, rounded half up, computed only from server-side values."""
    result = int(
        (Decimal(unit_price_minor) * Decimal(quantity)).quantize(Decimal('1'), ROUND_HALF_UP)
    )
    if result <= 0 or result > MAX_MINOR:
        raise OrderError('invalid_line_total', 'The calculated line total is outside the supported range.', 400)
    return result


def roles_for(order, user):
    roles = set()
    if user is None:
        return roles
    if order.buyer_id == user.pk:
        roles.add(BUYER)
    if order.seller_id == user.pk:
        roles.add(SELLER)
    if is_ops_admin(user):
        roles.add(ADMIN)
    return roles


def _record(order, from_status, to_status, actor, reason=''):
    OrderStatusHistory.objects.create(
        order=order, from_status=from_status, to_status=to_status, actor=actor, reason=reason,
    )


def create_order(buyer, items, delivery_address, notes='', order_id=None):
    """Single-seller checkout. `items` is a list of {'listing': uuid, 'quantity': Decimal}.
    Prices, names and totals come from the locked listing rows, never from the client."""
    if not user_has_role(buyer, UserRole.Role.BUYER):
        raise OrderError('forbidden', 'Only buyers can place orders.', 403)
    if not items or len(items) > MAX_ITEMS:
        raise OrderError('invalid_items', f'An order needs 1 to {MAX_ITEMS} items.', 400)
    listing_ids = [item['listing'] for item in items]
    if len(set(listing_ids)) != len(listing_ids):
        raise OrderError('duplicate_items', 'Each listing may appear only once.', 400)
    quantities = {item['listing']: stock._positive(item['quantity']) for item in items}

    with transaction.atomic():
        locked = list(Listing.objects.select_for_update().filter(pk__in=listing_ids).order_by('pk'))
        if len(locked) != len(listing_ids):
            raise OrderError('listing_not_found', 'One or more listings do not exist.', 400)
        listings = {
            listing.pk: listing
            for listing in Listing.objects.select_related('category', 'seller').filter(pk__in=listing_ids)
        }
        sellers = {listing.seller_id for listing in listings.values()}
        if len(sellers) != 1:
            raise OrderError('multiple_sellers', 'All items must come from one seller.', 400)
        seller_id = sellers.pop()
        if seller_id == buyer.pk:
            raise OrderError('own_listing', 'You cannot buy your own listing.', 400)
        for listing in listings.values():
            if listing.status != Listing.Status.ACTIVE:
                raise OrderError('listing_not_active', f'"{listing.name}" is not available.', 409)

        lines = []
        for listing in (listings[pk] for pk in sorted(listings)):
            quantity = quantities[listing.pk]
            lines.append((listing, quantity, line_total_minor(listing.unit_price_minor, quantity)))
        total = sum(line[2] for line in lines)
        if total > MAX_MINOR:
            raise OrderError('invalid_order_total', 'The calculated order total is too large.', 400)

        order = Order.objects.create(
            id=order_id or uuid.uuid4(), buyer=buyer, seller_id=seller_id, total_minor=total,
            delivery_address=delivery_address, notes=notes,
        )
        for listing, quantity, line_total in lines:
            reservation = stock.reserve(
                listing.pk, quantity, reference=f'order:{order.pk}', ttl=reservation_ttl(),
            )
            profile = getattr(listing.seller, 'farmer_profile', None)
            OrderItem.objects.create(
                order=order, listing=listing, reservation=reservation,
                listing_name=listing.name, category_name=listing.category.name,
                seller_name=profile.display_name if profile else '',
                unit_code=listing.unit_code, unit_price_minor=listing.unit_price_minor,
                quantity=quantity, line_total_minor=line_total,
            )
        _record(order, '', S.PENDING, buyer, 'Order placed')
        audit.record('order.created', buyer, order, {
            'total_minor': total, 'currency': order.currency, 'item_count': len(lines),
        })
    return order


def transition(order_id, to_status, actor, reason='', system=False):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        allowed = TRANSITIONS.get((order.status, to_status))
        if allowed is None:
            raise OrderError(
                'invalid_transition', f'Cannot change an order from {order.status} to {to_status}.',
            )
        if not system and not (roles_for(order, actor) & allowed):
            raise OrderError('forbidden', 'You may not perform this action on this order.', 403)

        items = list(order.items.order_by('listing_id'))
        if to_status == S.CONFIRMED:
            for item in items:
                stock.commit_reservation(item.reservation_id)
        elif to_status == S.SHIPPED:
            from agrifi.finance.models import SimulatedPayment

            if not SimulatedPayment.objects.filter(
                order=order, status=SimulatedPayment.Status.SUCCEEDED,
            ).exists():
                raise OrderError(
                    'payment_required',
                    'A simulated successful payment is required before shipping.',
                )
            for item in items:
                stock.consume(item.reservation_id, actor)
        elif to_status == S.CANCELLED:
            for item in items:
                stock.release_if_active(item.reservation_id)

        from_status = order.status
        order.status = to_status
        order.save(update_fields=['status', 'updated_at'])
        _record(order, from_status, to_status, None if system else actor, reason)
        audit.record('order.status_changed', None if system else actor, order, {
            'from_status': from_status, 'to_status': to_status, 'system': system, 'reason': reason,
        })
    return order


def open_dispute(order_id, actor, reason):
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if BUYER not in roles_for(order, actor):
            raise OrderError('forbidden', 'Only the buyer can open a dispute.', 403)
        if order.status not in DISPUTABLE:
            raise OrderError('invalid_transition', f'An order that is {order.status} cannot be disputed.')
        if order.disputes.filter(status=Dispute.Status.OPEN).exists():
            raise OrderError('dispute_open', 'This order already has an open dispute.')
        dispute = Dispute.objects.create(
            order=order, opened_by=actor, reason=reason, previous_order_status=order.status,
        )
        from_status = order.status
        order.status = S.DISPUTED
        order.save(update_fields=['status', 'updated_at'])
        _record(order, from_status, S.DISPUTED, actor, reason)
        audit.record('dispute.opened', actor, dispute, {'order_id': order.pk, 'reason': reason})
    return dispute


def resolve_dispute(dispute_id, actor, outcome, notes=''):
    """Operations administrators close a dispute; the order is then completed.
    Any refund is a later, simulated financial step keyed on `outcome`."""
    if not is_ops_admin(actor):
        raise OrderError('forbidden', 'Only operations administrators can resolve disputes.', 403)
    if outcome not in Dispute.Outcome.values:
        raise OrderError('invalid_outcome', 'Unknown outcome.', 400)
    order_id = Dispute.objects.values_list('order_id', flat=True).get(pk=dispute_id)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        dispute = Dispute.objects.select_for_update().get(pk=dispute_id)
        if dispute.status != Dispute.Status.OPEN:
            raise OrderError('invalid_state', 'Dispute is already resolved.')
        previous_status = dispute.previous_order_status
        dispute.status = Dispute.Status.RESOLVED
        dispute.outcome = outcome
        dispute.resolution_notes = notes
        dispute.resolved_by = actor
        dispute.resolved_at = timezone.now()
        dispute.save()
        if outcome == Dispute.Outcome.SELLER_FAVOURED:
            order.status = previous_status
        elif previous_status == S.CONFIRMED:
            for item in order.items.order_by('listing_id'):
                stock.release_if_active(item.reservation_id)
            order.status = S.CANCELLED
        else:
            order.status = S.DISPUTE_RESOLVED
        order.save(update_fields=['status', 'updated_at'])
        _record(order, S.DISPUTED, order.status, actor, f'Dispute resolved: {outcome}')
        audit.record('dispute.resolved', actor, dispute, {
            'order_id': order.pk, 'outcome': outcome, 'to_status': order.status,
        })
    return dispute


def cancel_expired_orders(now=None):
    """Cancel pending orders whose stock reservation has lapsed. Returns the count."""
    now = now or timezone.now()
    due = (
        Order.objects.filter(
            status=S.PENDING, items__reservation__expires_at__lte=now,
            items__reservation__status=Reservation.Status.ACTIVE,
        ) | Order.objects.filter(
            status=S.PENDING, items__reservation__status=Reservation.Status.EXPIRED,
        )
    ).distinct().values_list('pk', flat=True)
    count = 0
    for order_id in list(due):
        try:
            transition(order_id, S.CANCELLED, None, 'Reservation expired', system=True)
            count += 1
        except OrderError:
            continue
    return count
