# ==========================================
# Service Transaction Service Layer
# Handles business logic for service types
# and service transactions (CRUD + stats).
# ==========================================

from decimal import Decimal
from datetime import date
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from core.models import ServiceType, ServiceTransaction


# ------------------------------------------
# Service Stats
# ------------------------------------------

def get_service_stats():
    """
    Calculate service statistics:
    - Total profit (all-time sum of commissions)
    - Total transaction count
    - This month's profit
    - This month's transaction count
    Returns a dict with all four values.
    """
    today = date.today()
    first_of_month = today.replace(day=1)

    all_qs = ServiceTransaction.objects.all()
    month_qs = ServiceTransaction.objects.filter(
        created_at__date__gte=first_of_month,
        created_at__date__lte=today,
    )

    total_profit = all_qs.aggregate(
        total=Sum('commission')
    )['total'] or Decimal('0.00')

    total_count = all_qs.count()

    month_profit = month_qs.aggregate(
        total=Sum('commission')
    )['total'] or Decimal('0.00')

    month_count = month_qs.count()

    return {
        'total_profit': total_profit,
        'total_count': total_count,
        'month_profit': month_profit,
        'month_count': month_count,
    }


# ------------------------------------------
# Filtered & Paginated Transactions
# ------------------------------------------

def get_filtered_transactions(service_type_id=None, created_by_id=None, page=1, per_page=15):
    """
    Return a paginated Page object of ServiceTransactions,
    optionally filtered by service_type and/or created_by.
    Also returns the base queryset for stat purposes.
    """
    qs = ServiceTransaction.objects.select_related(
        'service_type', 'created_by'
    ).order_by('-created_at')

    if service_type_id:
        qs = qs.filter(service_type_id=service_type_id)

    if created_by_id:
        qs = qs.filter(created_by_id=created_by_id)

    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(page)

    return page_obj


def get_transaction_filter_options():
    """
    Return the data needed to populate filter dropdowns:
    - Active service types
    - Users who have at least one service transaction
    """
    service_types = ServiceType.objects.filter(is_active=True).order_by('name')

    # Only users who actually created service transactions
    user_ids = ServiceTransaction.objects.values_list(
        'created_by', flat=True
    ).distinct()
    users = User.objects.filter(id__in=user_ids).order_by('username')

    return {
        'service_types': service_types,
        'users': users,
    }


# ------------------------------------------
# Service Transaction CRUD
# ------------------------------------------

@transaction.atomic
def create_service_transaction(service_type_id, service_amount, customer_phone, note, user):
    """
    Create a new service transaction.
    Commission is snapshot from the ServiceType at creation time.
    Raises ValidationError on invalid data.
    """
    if not service_type_id:
        raise ValidationError('نوع الخدمة مطلوب')

    try:
        service_type = ServiceType.objects.get(id=service_type_id, is_active=True)
    except ServiceType.DoesNotExist:
        raise ValidationError('نوع الخدمة غير موجود أو غير نشط')

    if service_amount is None or service_amount <= 0:
        raise ValidationError('مبلغ الخدمة يجب أن يكون أكبر من صفر')

    # --- Snapshot commission ---
    if service_type.commission_type == 'percentage':
        commission = (service_amount * service_type.commission_value / Decimal('100')).quantize(Decimal('0.01'))
    else:  # fixed
        commission = service_type.commission_value

    txn = ServiceTransaction.objects.create(
        service_type=service_type,
        service_amount=service_amount,
        commission=commission,
        customer_phone=customer_phone or '',
        note=note or '',
        created_by=user,
    )
    return txn


# ------------------------------------------
# Service Type CRUD
# ------------------------------------------

def create_service_type(name, commission_type, commission_value):
    """Create a new service type. Raises on duplicate or invalid data."""
    name = name.strip()
    if not name:
        raise ValidationError('اسم نوع الخدمة مطلوب')

    if commission_type not in ('percentage', 'fixed'):
        raise ValidationError('نوع العمولة غير صحيح')

    if commission_value is None or commission_value < 0:
        raise ValidationError('قيمة العمولة يجب أن تكون صفر أو أكبر')

    if ServiceType.objects.filter(name=name).exists():
        raise ValidationError(f'نوع الخدمة "{name}" موجود بالفعل')

    return ServiceType.objects.create(
        name=name,
        commission_type=commission_type,
        commission_value=commission_value,
    )


def update_service_type(type_id, name, commission_type, commission_value):
    """Update an existing service type."""
    name = name.strip()
    if not name:
        raise ValidationError('اسم نوع الخدمة مطلوب')

    if commission_type not in ('percentage', 'fixed'):
        raise ValidationError('نوع العمولة غير صحيح')

    if commission_value is None or commission_value < 0:
        raise ValidationError('قيمة العمولة يجب أن تكون صفر أو أكبر')

    try:
        stype = ServiceType.objects.get(id=type_id)
    except ServiceType.DoesNotExist:
        raise ValidationError('نوع الخدمة غير موجود')

    if ServiceType.objects.filter(name=name).exclude(id=type_id).exists():
        raise ValidationError(f'نوع الخدمة "{name}" موجود بالفعل')

    stype.name = name
    stype.commission_type = commission_type
    stype.commission_value = commission_value
    stype.save(update_fields=['name', 'commission_type', 'commission_value'])
    return stype


def delete_service_type(type_id):
    """Soft-delete a service type (set is_active=False).
    Prevents deletion if active transactions reference it.
    """
    try:
        stype = ServiceType.objects.get(id=type_id, is_active=True)
    except ServiceType.DoesNotExist:
        raise ValidationError('نوع الخدمة غير موجود')

    if ServiceTransaction.objects.filter(service_type=stype).exists():
        raise ValidationError(
            f'لا يمكن حذف نوع الخدمة "{stype.name}" لأنه مرتبط بمعاملات. '
            'يمكنك تعديله بدلاً من ذلك.'
        )

    stype.is_active = False
    stype.save(update_fields=['is_active'])
    return stype
