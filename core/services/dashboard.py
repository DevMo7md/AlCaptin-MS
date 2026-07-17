# ==========================================
# Dashboard & Reports Service Layer
# Handles business logic for statistics,
# KPIs, and financial reports.
# ==========================================

from decimal import Decimal
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum, Count, F, Q, DecimalField
from django.db.models.functions import Coalesce, TruncDate, TruncMonth
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import (
    Product, Category, PurchaseBatch, PurchaseInvoice,
    SaleInvoice, SaleItem, Expense, ExpenseCategory,
    ServiceType, ServiceTransaction,
    InstallmentSale, Installment,
)


# ------------------------------------------
# Dashboard Home — Overview KPIs
# ------------------------------------------

def get_dashboard_overview():
    """
    Returns the main dashboard KPI summary dict.
    All reads are consistent within a single transaction.
    """
    today = timezone.localdate()
    first_of_month = today.replace(day=1)
    first_of_last_month = first_of_month - relativedelta(months=1)
    last_of_last_month = first_of_month - timedelta(days=1)

    # ---- Sales Income (this month) ----
    sales_this_month_qs = SaleItem.objects.filter(
        invoice__created_at__date__gte=first_of_month,
        invoice__created_at__date__lte=today,
    )
    sales_last_month_qs = SaleItem.objects.filter(
        invoice__created_at__date__gte=first_of_last_month,
        invoice__created_at__date__lte=last_of_last_month,
    )

    sales_revenue_this = sales_this_month_qs.aggregate(
        total=Coalesce(Sum(F('quantity') * F('sell_price'), output_field=DecimalField()), Decimal('0.00'))
    )['total']
    sales_revenue_last = sales_last_month_qs.aggregate(
        total=Coalesce(Sum(F('quantity') * F('sell_price'), output_field=DecimalField()), Decimal('0.00'))
    )['total']

    sales_cogs_this = sales_this_month_qs.aggregate(
        total=Coalesce(Sum('cogs'), Decimal('0.00'))
    )['total']
    sales_cogs_last = sales_last_month_qs.aggregate(
        total=Coalesce(Sum('cogs'), Decimal('0.00'))
    )['total']

    sales_profit_this = sales_revenue_this - sales_cogs_this
    sales_profit_last = sales_revenue_last - sales_cogs_last

    # ---- Service Income (this month) ----
    svc_this_month_qs = ServiceTransaction.objects.filter(
        created_at__date__gte=first_of_month,
        created_at__date__lte=today,
    )
    svc_last_month_qs = ServiceTransaction.objects.filter(
        created_at__date__gte=first_of_last_month,
        created_at__date__lte=last_of_last_month,
    )

    service_income_this = svc_this_month_qs.aggregate(
        total=Coalesce(Sum('commission'), Decimal('0.00'))
    )['total']
    service_income_last = svc_last_month_qs.aggregate(
        total=Coalesce(Sum('commission'), Decimal('0.00'))
    )['total']

    # ---- Expenses (this month) ----
    expenses_this = Expense.objects.filter(
        is_active=True,
        expense_date__gte=first_of_month,
        expense_date__lte=today,
    ).aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']
    expenses_last = Expense.objects.filter(
        is_active=True,
        expense_date__gte=first_of_last_month,
        expense_date__lte=last_of_last_month,
    ).aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    # ---- Purchases (this month) ----
    purchases_this = PurchaseBatch.objects.filter(
        created_at__date__gte=first_of_month,
        created_at__date__lte=today,
    ).aggregate(
        total=Coalesce(Sum(F('quantity') * F('buy_price'), output_field=DecimalField()), Decimal('0.00'))
    )['total']
    purchases_last = PurchaseBatch.objects.filter(
        created_at__date__gte=first_of_last_month,
        created_at__date__lte=last_of_last_month,
    ).aggregate(
        total=Coalesce(Sum(F('quantity') * F('buy_price'), output_field=DecimalField()), Decimal('0.00'))
    )['total']

    # ---- Installment Sales (collected profit from paid installments) ----
    inst_paid_this = Installment.objects.filter(
        is_paid=True,
        paid_at__date__gte=first_of_month,
        paid_at__date__lte=today,
    )
    inst_paid_last = Installment.objects.filter(
        is_paid=True,
        paid_at__date__gte=first_of_last_month,
        paid_at__date__lte=last_of_last_month,
    )

    installment_collected_this = inst_paid_this.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']
    installment_collected_last = inst_paid_last.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']

    installment_profit_this = inst_paid_this.aggregate(
        total=Coalesce(Sum('profit_portion'), Decimal('0.00'))
    )['total']
    installment_profit_last = inst_paid_last.aggregate(
        total=Coalesce(Sum('profit_portion'), Decimal('0.00'))
    )['total']

    installment_count_this = InstallmentSale.objects.filter(
        created_at__date__gte=first_of_month,
        created_at__date__lte=today,
    ).count()

    # ---- Total Income = Sales Revenue + Service Commissions + Installment Collections ----
    total_income_this = sales_revenue_this + service_income_this + installment_collected_this
    total_income_last = sales_revenue_last + service_income_last + installment_collected_last

    # ---- Total Outcome = Purchases + Expenses ----
    total_outcome_this = purchases_this + expenses_this
    total_outcome_last = purchases_last + expenses_last

    # ---- Net Profit = Sales Profit + Service Income + Installment Profit - Expenses ----
    net_profit_this = sales_profit_this + service_income_this + installment_profit_this - expenses_this
    net_profit_last = sales_profit_last + service_income_last + installment_profit_last - expenses_last

    # ---- Inventory Stats ----
    total_products = Product.objects.filter(is_active=True).count()
    low_stock_products = Product.objects.filter(
        is_active=True,
        stock__lte=F('low_stock_alert'),
    ).count()
    out_of_stock = Product.objects.filter(is_active=True, stock=0).count()

    # Inventory value (remaining_quantity * buy_price for all batches)
    inventory_value = PurchaseBatch.objects.filter(
        remaining_quantity__gt=0,
        product__is_active=True,
    ).aggregate(
        total=Coalesce(Sum(F('remaining_quantity') * F('buy_price'), output_field=DecimalField()), Decimal('0.00'))
    )['total']

    # ---- Sales count ----
    sales_count_this = SaleInvoice.objects.filter(
        created_at__date__gte=first_of_month,
        created_at__date__lte=today,
    ).count()

    return {
        # Sales
        'sales_revenue_this': sales_revenue_this,
        'sales_revenue_last': sales_revenue_last,
        'sales_revenue_change': _calc_change(sales_revenue_this, sales_revenue_last),
        'sales_profit_this': sales_profit_this,
        'sales_profit_last': sales_profit_last,
        'sales_profit_change': _calc_change(sales_profit_this, sales_profit_last),
        'sales_count_this': sales_count_this,

        # Services
        'service_income_this': service_income_this,
        'service_income_last': service_income_last,
        'service_income_change': _calc_change(service_income_this, service_income_last),

        # Installments
        'installment_collected_this': installment_collected_this,
        'installment_collected_last': installment_collected_last,
        'installment_collected_change': _calc_change(installment_collected_this, installment_collected_last),
        'installment_profit_this': installment_profit_this,
        'installment_profit_last': installment_profit_last,
        'installment_profit_change': _calc_change(installment_profit_this, installment_profit_last),
        'installment_count_this': installment_count_this,

        # Expenses
        'expenses_this': expenses_this,
        'expenses_last': expenses_last,
        'expenses_change': _calc_change(expenses_this, expenses_last),

        # Purchases
        'purchases_this': purchases_this,
        'purchases_last': purchases_last,
        'purchases_change': _calc_change(purchases_this, purchases_last),

        # Aggregates
        'total_income_this': total_income_this,
        'total_income_last': total_income_last,
        'total_income_change': _calc_change(total_income_this, total_income_last),

        'total_outcome_this': total_outcome_this,
        'total_outcome_last': total_outcome_last,
        'total_outcome_change': _calc_change(total_outcome_this, total_outcome_last),

        'net_profit_this': net_profit_this,
        'net_profit_last': net_profit_last,
        'net_profit_change': _calc_change(net_profit_this, net_profit_last),

        # Inventory
        'total_products': total_products,
        'low_stock_products': low_stock_products,
        'out_of_stock': out_of_stock,
        'inventory_value': inventory_value,
    }


# ------------------------------------------
# Reports — Date-Filtered Financial Report
# ------------------------------------------

def get_financial_report(date_from, date_to):
    """
    Returns a detailed financial report for the given date range.
    All reads are consistent within a single transaction.
    """
    # ---- Sales ----
    sale_items_qs = SaleItem.objects.filter(
        invoice__created_at__date__gte=date_from,
        invoice__created_at__date__lte=date_to,
    )

    sales_revenue = sale_items_qs.aggregate(
        total=Coalesce(Sum(F('quantity') * F('sell_price'), output_field=DecimalField()), Decimal('0.00'))
    )['total']
    sales_cogs = sale_items_qs.aggregate(
        total=Coalesce(Sum('cogs'), Decimal('0.00'))
    )['total']
    sales_profit = sales_revenue - sales_cogs
    sales_count = SaleInvoice.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).count()

    # ---- Purchases ----
    purchases_total = PurchaseBatch.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).aggregate(
        total=Coalesce(Sum(F('quantity') * F('buy_price'), output_field=DecimalField()), Decimal('0.00'))
    )['total']
    purchases_count = PurchaseInvoice.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).count()

    # ---- Expenses ----
    expenses_qs = Expense.objects.filter(
        is_active=True,
        expense_date__gte=date_from,
        expense_date__lte=date_to,
    )
    expenses_total = expenses_qs.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']
    expenses_count = expenses_qs.count()

    # Expenses by category
    expenses_by_category = list(
        expenses_qs.values('category__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )
    # Replace None category name
    for item in expenses_by_category:
        if item['category__name'] is None:
            item['category__name'] = 'بدون تصنيف'

    # ---- Services ----
    svc_qs = ServiceTransaction.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    )
    service_income = svc_qs.aggregate(
        total=Coalesce(Sum('commission'), Decimal('0.00'))
    )['total']
    service_count = svc_qs.count()

    # Services by type
    services_by_type = list(
        svc_qs.values('service_type__name')
        .annotate(
            total_commission=Sum('commission'),
            count=Count('id'),
        )
        .order_by('-total_commission')
    )

    # ---- Installment Sales ----
    inst_paid_qs = Installment.objects.filter(
        is_paid=True,
        paid_at__date__gte=date_from,
        paid_at__date__lte=date_to,
    )
    installment_collected = inst_paid_qs.aggregate(
        total=Coalesce(Sum('amount'), Decimal('0.00'))
    )['total']
    installment_profit = inst_paid_qs.aggregate(
        total=Coalesce(Sum('profit_portion'), Decimal('0.00'))
    )['total']
    installment_count = InstallmentSale.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).count()
    # Total installment sales value created in the period
    installment_total_value = InstallmentSale.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).aggregate(
        total=Coalesce(Sum('installment_sale_price'), Decimal('0.00'))
    )['total']
    installment_total_cogs = InstallmentSale.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
    ).aggregate(
        total=Coalesce(Sum('cogs'), Decimal('0.00'))
    )['total']
    installment_total_expected_profit = installment_total_value - installment_total_cogs

    # ---- Top selling products ----
    top_products = list(
        sale_items_qs.values('product__name')
        .annotate(
            total_qty=Sum('quantity'),
            total_revenue=Sum(F('quantity') * F('sell_price'), output_field=DecimalField()),
            total_cogs=Sum('cogs'),
        )
        .order_by('-total_qty')[:10]
    )
    for p in top_products:
        p['profit'] = p['total_revenue'] - p['total_cogs']

    # ---- Daily sales trend ----
    daily_sales = list(
        sale_items_qs.annotate(day=TruncDate('invoice__created_at'))
        .values('day')
        .annotate(
            revenue=Sum(F('quantity') * F('sell_price'), output_field=DecimalField()),
            cogs=Sum('cogs'),
        )
        .order_by('day')
    )
    for d in daily_sales:
        d['profit'] = d['revenue'] - d['cogs']
        d['day_str'] = d['day'].strftime('%Y-%m-%d') if d['day'] else ''

    # ---- Aggregates ----
    total_income = sales_revenue + service_income + installment_collected
    total_outcome = purchases_total + expenses_total
    net_profit = sales_profit + service_income + installment_profit - expenses_total

    return {
        # Sales
        'sales_revenue': sales_revenue,
        'sales_cogs': sales_cogs,
        'sales_profit': sales_profit,
        'sales_count': sales_count,

        # Purchases
        'purchases_total': purchases_total,
        'purchases_count': purchases_count,

        # Expenses
        'expenses_total': expenses_total,
        'expenses_count': expenses_count,
        'expenses_by_category': expenses_by_category,

        # Services
        'service_income': service_income,
        'service_count': service_count,
        'services_by_type': services_by_type,

        # Installments
        'installment_collected': installment_collected,
        'installment_profit': installment_profit,
        'installment_count': installment_count,
        'installment_total_value': installment_total_value,
        'installment_total_cogs': installment_total_cogs,
        'installment_total_expected_profit': installment_total_expected_profit,

        # Products
        'top_products': top_products,

        # Daily trend
        'daily_sales': daily_sales,

        # Aggregates
        'total_income': total_income,
        'total_outcome': total_outcome,
        'net_profit': net_profit,

        # Date range
        'date_from': date_from,
        'date_to': date_to,
    }


# ------------------------------------------
# Helpers
# ------------------------------------------

def _calc_change(current, previous):
    """
    Returns a dict with percent change, direction, and whether previous data exists.
    """
    if previous == 0 and current == 0:
        return {'percent': Decimal('0'), 'direction': 'same', 'has_previous': False}
    if previous == 0:
        return {'percent': Decimal('100'), 'direction': 'up', 'has_previous': False}

    change = ((current - previous) / abs(previous) * 100).quantize(Decimal('0.1'))
    if change > 0:
        direction = 'up'
    elif change < 0:
        direction = 'down'
        change = abs(change)
    else:
        direction = 'same'

    return {'percent': change, 'direction': direction, 'has_previous': True}
