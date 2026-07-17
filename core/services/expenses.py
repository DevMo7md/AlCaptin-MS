# ==========================================
# Expense Service Layer
# Handles business logic for expenses and
# expense categories (CRUD + stats).
# ==========================================

from decimal import Decimal
from datetime import date
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError

from core.models import Expense, ExpenseCategory


# ------------------------------------------
# Expense Stats
# ------------------------------------------

def get_expense_stats():
    """
    Calculate expense statistics for the current month:
    - Total expense this month
    - Per-category totals with comparison % vs last month
    Returns a dict with 'total_this_month' and 'category_stats' list.
    """
    today = date.today()
    first_of_month = today.replace(day=1)
    first_of_last_month = (first_of_month - relativedelta(months=1))
    last_of_last_month = first_of_month - relativedelta(days=1)

    # Current month expenses
    current_qs = Expense.objects.filter(
        is_active=True,
        expense_date__gte=first_of_month,
        expense_date__lte=today,
    )
    # Last month expenses
    last_qs = Expense.objects.filter(
        is_active=True,
        expense_date__gte=first_of_last_month,
        expense_date__lte=last_of_last_month,
    )

    total_this_month = current_qs.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    total_last_month = last_qs.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')

    # Total comparison
    total_comparison = _calc_comparison(total_this_month, total_last_month)

    # Per-category stats
    current_by_cat = dict(
        current_qs.values_list('category__id')
        .annotate(total=Sum('amount'))
        .values_list('category__id', 'total')
    )
    last_by_cat = dict(
        last_qs.values_list('category__id')
        .annotate(total=Sum('amount'))
        .values_list('category__id', 'total')
    )

    # Build category stats list
    categories = ExpenseCategory.objects.all().order_by('name')
    category_stats = []
    for cat in categories:
        this_month = current_by_cat.get(cat.id, Decimal('0.00'))
        last_month_val = last_by_cat.get(cat.id, Decimal('0.00'))
        comparison = _calc_comparison(this_month, last_month_val)
        category_stats.append({
            'id': cat.id,
            'name': cat.name,
            'total': this_month,
            'last_month': last_month_val,
            'comparison': comparison,
        })

    # Sort by total descending so the top spenders appear first in cards
    category_stats.sort(key=lambda x: x['total'], reverse=True)

    return {
        'total_this_month': total_this_month,
        'total_last_month': total_last_month,
        'total_comparison': total_comparison,
        'category_stats': category_stats,
    }


def _calc_comparison(current, previous):
    """
    Returns a dict:
      { 'percent': Decimal, 'direction': 'up'|'down'|'same', 'has_previous': bool }
    """
    if previous == 0 and current == 0:
        return {'percent': Decimal('0'), 'direction': 'same', 'has_previous': False}
    if previous == 0:
        return {'percent': Decimal('100'), 'direction': 'up', 'has_previous': False}

    change = ((current - previous) / previous * 100).quantize(Decimal('0.1'))
    if change > 0:
        direction = 'up'
    elif change < 0:
        direction = 'down'
        change = abs(change)
    else:
        direction = 'same'

    return {'percent': change, 'direction': direction, 'has_previous': True}


# ------------------------------------------
# Expense CRUD
# ------------------------------------------

@transaction.atomic
def create_expense(category_id, amount, note, expense_date, user):
    """
    Create a new expense record.
    Raises ValidationError on invalid data.
    """
    if amount <= 0:
        raise ValidationError('المبلغ يجب أن يكون أكبر من صفر')
    

    if expense_date > date.today():
        raise ValidationError('لا يمكن إضافة مصروفات مستقبلية')
    
    
    if not expense_date:
        raise ValidationError('تاريخ المصروف مطلوب')
    
    

    category = None
    if category_id:
        try:
            category = ExpenseCategory.objects.get(id=category_id)
        except ExpenseCategory.DoesNotExist:
            raise ValidationError('التصنيف غير موجود')

    expense = Expense.objects.create(
        category=category,
        amount=amount,
        note=note,
        expense_date=expense_date,
        created_by=user,
    )
    return expense


def delete_expense(expense_id):
    """Soft-delete an expense (mark is_active=False)."""
    try:
        expense = Expense.objects.get(id=expense_id, is_active=True)
    except Expense.DoesNotExist:
        raise ValidationError('المصروف غير موجود')

    expense.is_active = False
    expense.save(update_fields=['is_active'])
    return expense


# ------------------------------------------
# Expense Category CRUD
# ------------------------------------------

def create_expense_category(name):
    """Create a new expense category. Raises on duplicate."""
    name = name.strip()
    if not name:
        raise ValidationError('اسم التصنيف مطلوب')
    if ExpenseCategory.objects.filter(name=name).exists():
        raise ValidationError(f'التصنيف "{name}" موجود بالفعل')

    return ExpenseCategory.objects.create(name=name)


def update_expense_category(category_id, name):
    """Rename an expense category."""
    name = name.strip()
    if not name:
        raise ValidationError('اسم التصنيف مطلوب')

    try:
        category = ExpenseCategory.objects.get(id=category_id)
    except ExpenseCategory.DoesNotExist:
        raise ValidationError('التصنيف غير موجود')

    if ExpenseCategory.objects.filter(name=name).exclude(id=category_id).exists():
        raise ValidationError(f'التصنيف "{name}" موجود بالفعل')

    category.name = name
    category.save(update_fields=['name'])
    return category


def delete_expense_category(category_id):
    """Delete a category only if no active expenses reference it."""
    try:
        category = ExpenseCategory.objects.get(id=category_id)
    except ExpenseCategory.DoesNotExist:
        raise ValidationError('التصنيف غير موجود')

    if Expense.objects.filter(category=category, is_active=True).exists():
        raise ValidationError(
            f'لا يمكن حذف التصنيف "{category.name}" لأنه مرتبط بمصروفات نشطة. '
            'قم بحذف أو تعديل المصروفات أولاً.'
        )

    category.delete()
