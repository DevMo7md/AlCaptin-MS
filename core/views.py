from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, FileResponse
import json
import os
import shutil
from datetime import datetime, date
from django.utils import timezone
from django.db.models import Q, Sum, F
from decimal import Decimal, InvalidOperation
from django.db.models import Prefetch
from django.core.exceptions import ValidationError
from django.conf import settings as django_settings
import logging

# pyrefly: ignore [missing-import]
from .models import Product, Category, PurchaseBatch, Supplier, PurchaseInvoice, SaleInvoice, SaleItem, Expense, ExpenseCategory, ServiceType, ServiceTransaction, InstallmentSale, Installment
from .services import inventory, sales, expenses
from .services import services as services_svc
from .services import dashboard as dashboard_svc
from .services import installments as installments_svc

logger = logging.getLogger(__name__)


def _to_decimal(value, default=Decimal('0.00')):
    """Safely convert a string to Decimal."""
    try:
        result = Decimal(str(value))
        return result
    except (InvalidOperation, ValueError, TypeError):
        return default


def _to_int(value, default=0):
    """Safely convert a string to int."""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


@login_required
def products_list(request):
    """Display all products with search, filtering and pagination."""
    products_qs = Product.objects.select_related(
        'category'
    ).prefetch_related(
        Prefetch(
            'purchase_batches',
            queryset=PurchaseBatch.objects.order_by('-created_at')
        )
    ).filter(is_active=True).order_by('-created_at')
    
    categories = Category.objects.all().order_by('name')
    suppliers = Supplier.objects.all().order_by('name')

    # --- Search ---
    search_query = request.GET.get('q', '').strip()
    if search_query:
        if search_query.isdigit():
            products_qs = products_qs.filter(
                Q(name__icontains=search_query) | 
                Q(barcode__icontains=search_query) |
                Q(id=int(search_query))
            )
        else:
            products_qs = products_qs.filter(
                Q(name__icontains=search_query) | 
                Q(barcode__icontains=search_query)
            )

    # --- Category Filter ---
    selected_category = request.GET.get('category', '')
    if selected_category:
        products_qs = products_qs.filter(category_id=selected_category)

    # --- Stock Filter ---
    stock_filter = request.GET.get('stock', '')
    if stock_filter == 'low':
        products_qs = [p for p in products_qs if p.is_low_stock and p.stock > 0]
    elif stock_filter == 'out':
        products_qs = products_qs.filter(stock=0)
    elif stock_filter == 'ok':
        products_qs = [p for p in products_qs if not p.is_low_stock]

    # --- Stats (computed from full active set) ---
    all_products_qs = Product.objects.filter(is_active=True)
    total_products = all_products_qs.count()
    total_stock = all_products_qs.aggregate(total=Sum('stock'))['total'] or 0
    total_categories = categories.count()
    from django.db.models import F
    low_stock_count = all_products_qs.filter(stock__lte=F('low_stock_alert'), stock__gt=0).count()

    # --- Compute stats in memory ---
    if isinstance(products_qs, list):
        product_list = products_qs
    else:
        product_list = list(products_qs)

    inventory.hydrate_products(product_list)

    paginator = Paginator(product_list, 15)
    page_number = request.GET.get('page', 1)
    products_page = paginator.get_page(page_number)

    # All products for JS data (edit modals etc.)
    all_products_raw = Product.objects.select_related('category').prefetch_related(
        Prefetch(
            'purchase_batches',
            queryset=PurchaseBatch.objects.order_by('-created_at')
        )
    ).filter(is_active=True)
    
    all_products = list(all_products_raw)
    inventory.hydrate_products(all_products)

    context = {
        'active_nav': 'inventory',
        'products': products_page,
        'all_products': all_products,
        'categories': categories,
        'suppliers': suppliers,
        'total_products': total_products,
        'total_stock': total_stock,
        'total_categories': total_categories,
        'low_stock_count': low_stock_count,
        'search_query': search_query,
        'selected_category': selected_category,
        'stock_filter': stock_filter,
    }
    return render(request, 'core/products_list.html', context)


@login_required
def category_add(request):
    """Add a new category."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            Category.objects.get_or_create(name=name)
            messages.success(request, f"تمت إضافة القسم '{name}' بنجاح.")
        else:
            messages.error(request, "اسم القسم مطلوب.")
    return redirect('products_list')

@login_required
def supplier_add(request):
    """Add a new supplier."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            Supplier.objects.get_or_create(name=name)
            messages.success(request, f"تمت إضافة المورد '{name}' بنجاح.")
        else:
            messages.error(request, "اسم المورد مطلوب.")
    return redirect('products_list')

@login_required
def product_add(request):
    """Add a new product without initial stock."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        barcode = request.POST.get('barcode', '').strip()
        category_id = request.POST.get('category', '')
        sell_price = _to_decimal(request.POST.get('sell_price', '0'))
        low_stock_alert = _to_int(request.POST.get('low_stock_alert', '5'))

        # --- Validation ---
        if not name or not category_id or not barcode:
            messages.error(request, 'يرجى ملء جميع الحقول المطلوبة بما في ذلك الباركود')
            return redirect('products_list')

        if sell_price <= 0:
            messages.error(request, 'سعر البيع يجب أن يكون أكبر من صفر')
            return redirect('products_list')
        if low_stock_alert < 0:
            messages.error(request, 'حد تنبيه المخزون يجب أن يكون صفر أو أكبر')
            return redirect('products_list')

        try:
            inventory.add_new_product(
                name=name,
                barcode=barcode,
                category_id=category_id,
                sell_price=sell_price,
                low_stock_alert=low_stock_alert,
            )
            messages.success(request, f'تمت إضافة المنتج "{name}" بنجاح.')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception("Error in product_add")
            messages.error(request, f'حدث خطأ أثناء إضافة المنتج: {e}')

    return redirect('products_list')


@login_required
def product_edit(request):
    """Edit product info (name, category, sell_price, low_stock_alert).
    Buy price and stock are managed through purchase batches."""
    if request.method == 'POST':
        product_id = request.POST.get('product_id', '')
        product = get_object_or_404(Product, id=product_id, is_active=True)

        name = request.POST.get('name', '').strip()
        barcode = request.POST.get('barcode', '').strip()
        category_id = request.POST.get('category', '')
        sell_price = _to_decimal(request.POST.get('sell_price', '0'))
        low_stock_alert = _to_int(request.POST.get('low_stock_alert', '5'))

        # --- Validation ---
        if not name or not category_id or not barcode:
            messages.error(request, 'يرجى ملء جميع الحقول المطلوبة بما في ذلك الباركود')
            return redirect('products_list')

        if sell_price <= 0:
            messages.error(request, 'سعر البيع يجب أن يكون أكبر من صفر')
            return redirect('products_list')
        if low_stock_alert < 0:
            messages.error(request, 'حد تنبيه المخزون يجب أن يكون صفر أو أكبر')
            return redirect('products_list')

        try:
            inventory.update_product_info(
                product=product,
                name=name,
                barcode=barcode,
                category_id=category_id,
                sell_price=sell_price,
                low_stock_alert=low_stock_alert
            )
            messages.success(request, f'تم تحديث المنتج "{name}" بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception("Error in product_edit")
            messages.error(request, f'حدث خطأ أثناء تحديث المنتج: {e}')

    return redirect('products_list')


# ==========================================
# Purchases Views
# ==========================================

@login_required
def purchases_page(request):
    """Dashboard and POS interface for purchases."""
    invoices = PurchaseInvoice.objects.select_related('supplier').order_by('-created_at')
    
    total_purchases = sum((inv.total_amount for inv in invoices), Decimal('0.00'))
    invoices_count = invoices.count()
    items_bought = PurchaseBatch.objects.aggregate(total=Sum('quantity'))['total'] or 0

    products = list(Product.objects.filter(is_active=True).order_by('name'))
    suppliers = list(Supplier.objects.all().order_by('name'))
    categories = list(Category.objects.all().order_by('name'))
    
    context = {
        'active_nav': 'purchases',
        'invoices': invoices,
        'total_purchases': total_purchases,
        'invoices_count': invoices_count,
        'items_bought': items_bought,
        'products': products,
        'suppliers': suppliers,
        'categories': categories,
    }
    return render(request, 'core/purchases_page.html', context)


@login_required
def purchase_create(request):
    """AJAX POST endpoint to create a purchase invoice."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cart_items = data.get('cart', [])
            supplier_id = data.get('supplier_id')
            invoice_number = data.get('invoice_number', '').strip()
            invoice_note = data.get('invoice_note', '').strip()

            invoice = inventory.create_purchase_transaction(
                supplier_id=supplier_id,
                invoice_number=invoice_number,
                invoice_note=invoice_note,
                cart_items=cart_items
            )
            return JsonResponse({'success': True, 'invoice_id': invoice.id})
        except ValidationError as e:
            return JsonResponse({'success': False, 'error': str(e.message) if hasattr(e, 'message') else str(e)}, status=400)
        except Exception as e:
            logger.exception("Error creating purchase")
            return JsonResponse({'success': False, 'error': 'حدث خطأ غير متوقع'}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)


@login_required
def purchase_invoice_detail(request, invoice_id):
    invoice = get_object_or_404(PurchaseInvoice, id=invoice_id)
    batches = invoice.batches.select_related('product').all()
    context = {
        'invoice': invoice,
        'batches': batches,
    }
    return render(request, 'core/purchase_invoice_detail.html', context)


@login_required
def product_delete(request):
    """Soft-delete a product (mark as inactive)."""
    if request.method == 'POST':
        product_id = request.POST.get('product_id', '')
        product = get_object_or_404(Product, id=product_id)
        name = product.name
        try:
            product.is_active = False
            product.save(update_fields=['is_active'])
            messages.success(request, f'تم حذف المنتج "{name}" بنجاح')
        except Exception as e:
            logger.exception("Error in product_delete")
            messages.error(request, f'حدث خطأ أثناء حذف المنتج: {e}')

    return redirect('products_list')


@login_required
def product_sell(request):
    """Sell a product (deduct stock using FIFO and create an invoice)."""
    if request.method == 'POST':
        product_id = request.POST.get('product_id', '')
        product = get_object_or_404(Product, id=product_id, is_active=True)
        quantity = _to_int(request.POST.get('quantity', '0'))

        try:
            invoice = sales.create_sale_invoice(
                cart_items=[{'product_id': product_id, 'quantity': quantity}],
                user=request.user
            )
            
            messages.success(
                request,
                f'تم بيع {quantity} قطعة من "{product.name}" بنجاح. '
                f'(فاتورة رقم: {invoice.id} | الإجمالي: {invoice.total_amount} ج.م | الربح: {invoice.total_profit} ج.م)'
            )
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception("Error in product_sell")
            messages.error(request, f'حدث خطأ أثناء عملية البيع: {e}')

    return redirect('products_list')


# ==========================================
# Sales Views
# ==========================================

@login_required
def sales_page(request):
    """Dashboard and POS interface for sales."""
    invoices = SaleInvoice.objects.select_related('created_by').order_by('-created_at')
    
    # Calculate stats
    # For a real large-scale app we might aggregate in DB, but with properties this is required
    total_sales = sum((inv.total_amount for inv in invoices), Decimal('0.00'))
    total_profit = sum((inv.total_profit for inv in invoices), Decimal('0.00'))
    invoices_count = invoices.count()
    items_sold = SaleItem.objects.aggregate(total=Sum('quantity'))['total'] or 0

    # Products for POS dropdown - only active with stock
    products = list(Product.objects.filter(is_active=True, stock__gt=0).order_by('name'))
    
    context = {
        'active_nav': 'sales',
        'invoices': invoices,
        'total_sales': total_sales,
        'total_profit': total_profit,
        'invoices_count': invoices_count,
        'items_sold': items_sold,
        'products': products,
    }
    return render(request, 'core/sales_page.html', context)


@login_required
def sale_create(request):
    """AJAX POST endpoint to create a sale invoice."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cart_items = data.get('cart', [])
            
            invoice = sales.create_sale_invoice(cart_items, request.user)
            
            return JsonResponse({
                'success': True,
                'message': f'تم إنشاء فاتورة المبيعات بنجاح (رقم {invoice.id})',
                'invoice_id': invoice.id
            })
            
        except ValidationError as e:
            return JsonResponse({
                'success': False, 
                'message': str(e.message) if hasattr(e, 'message') else str(e)
            }, status=400)
        except Exception as e:
            logger.exception("Error in sale_create")
            return JsonResponse({'success': False, 'message': 'حدث خطأ غير متوقع'}, status=500)
    
    return JsonResponse({'success': False, 'message': 'طلب غير صالح'}, status=400)


@login_required
def sale_invoice_detail(request, invoice_id):
    """View details of a specific sale invoice."""
    invoice = get_object_or_404(SaleInvoice, id=invoice_id)
    items = invoice.items.select_related('product').all()
    
    context = {
        'active_nav': 'sales',
        'invoice': invoice,
        'items': items
    }
    return render(request, 'core/sale_invoice_detail.html', context)


# ==========================================
# Expenses Views
# ==========================================

@login_required
def expenses_page(request):
    """Main expenses dashboard — stats cards, expense list."""
    expenses_qs = Expense.objects.filter(is_active=True).select_related(
        'category', 'created_by'
    ).order_by('-expense_date', '-created_at')

    categories = ExpenseCategory.objects.all().order_by('name')

    # Stats
    stats = expenses.get_expense_stats()

    # Pagination
    paginator = Paginator(expenses_qs, 15)
    page_number = request.GET.get('page', 1)
    expenses_page_obj = paginator.get_page(page_number)

    context = {
        'active_nav': 'expenses',
        'expenses': expenses_page_obj,
        'categories': categories,
        'stats': stats,
    }
    return render(request, 'core/expenses_page.html', context)


@login_required
def expense_add(request):
    """Create a new expense (form POST)."""
    if request.method == 'POST':
        category_id = request.POST.get('category', '').strip()
        amount = _to_decimal(request.POST.get('amount', '0'))
        note = request.POST.get('note', '').strip()
        expense_date = request.POST.get('expense_date', '').strip()

        if not expense_date:
            messages.error(request, 'تاريخ المصروف مطلوب')
            return redirect('expenses_page')

        if amount <= 0:
            messages.error(request, 'المبلغ يجب أن يكون أكبر من صفر')
            return redirect('expenses_page')

        try:
            from datetime import date as _date
            parsed_date = _date.fromisoformat(expense_date)
        except (ValueError, TypeError):
            messages.error(request, 'تاريخ غير صحيح')
            return redirect('expenses_page')

        try:
            expenses.create_expense(
                category_id=category_id if category_id else None,
                amount=amount,
                note=note,
                expense_date=parsed_date,
                user=request.user,
            )
            messages.success(request, 'تمت إضافة المصروف بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in expense_add')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('expenses_page')


@login_required
def expense_delete(request):
    """Soft-delete an expense."""
    if request.method == 'POST':
        expense_id = request.POST.get('expense_id', '')
        try:
            expenses.delete_expense(expense_id)
            messages.success(request, 'تم حذف المصروف بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in expense_delete')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('expenses_page')


@login_required
def expense_categories_page(request):
    """Dedicated page to view and edit expense categories."""
    categories = ExpenseCategory.objects.all().order_by('name')

    # Count expenses per category for display
    from django.db.models import Count
    categories = categories.annotate(
        expense_count=Count('expense', filter=Q(expense__is_active=True))
    )

    context = {
        'active_nav': 'expenses',
        'categories': categories,
    }
    return render(request, 'core/expense_categories_page.html', context)


@login_required
def expense_category_add(request):
    """Add expense category — supports both AJAX (JSON) and regular POST."""
    if request.method == 'POST':
        # Check if AJAX JSON request (from popup modal)
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body)
                name = data.get('name', '').strip()
                cat = expenses.create_expense_category(name)
                return JsonResponse({
                    'success': True,
                    'id': cat.id,
                    'name': cat.name,
                    'message': f'تمت إضافة التصنيف "{cat.name}" بنجاح'
                })
            except ValidationError as e:
                return JsonResponse({
                    'success': False,
                    'message': str(e.message) if hasattr(e, 'message') else str(e)
                }, status=400)
            except Exception as e:
                logger.exception('Error in expense_category_add (AJAX)')
                return JsonResponse({'success': False, 'message': 'حدث خطأ غير متوقع'}, status=500)
        else:
            # Regular form POST (from categories page)
            name = request.POST.get('name', '').strip()
            try:
                expenses.create_expense_category(name)
                messages.success(request, f'تمت إضافة التصنيف "{name}" بنجاح')
            except ValidationError as e:
                messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
            except Exception as e:
                logger.exception('Error in expense_category_add')
                messages.error(request, f'حدث خطأ: {e}')
            return redirect('expense_categories_page')

    return JsonResponse({'success': False, 'message': 'طلب غير صالح'}, status=400)


@login_required
def expense_category_edit(request):
    """Rename an expense category."""
    if request.method == 'POST':
        category_id = request.POST.get('category_id', '')
        name = request.POST.get('name', '').strip()
        try:
            expenses.update_expense_category(category_id, name)
            messages.success(request, f'تم تحديث التصنيف إلى "{name}" بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in expense_category_edit')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('expense_categories_page')


@login_required
def expense_category_delete(request):
    """Delete an expense category."""
    if request.method == 'POST':
        category_id = request.POST.get('category_id', '')
        try:
            expenses.delete_expense_category(category_id)
            messages.success(request, 'تم حذف التصنيف بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in expense_category_delete')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('expense_categories_page')


# ==========================================
# Services Views
# ==========================================

@login_required
def services_page(request):
    """Main services dashboard — stats cards, filters, paginated transaction list."""
    # Stats
    stats = services_svc.get_service_stats()

    # Filter options
    filter_opts = services_svc.get_transaction_filter_options()

    # Read filter params
    selected_type = request.GET.get('service_type', '')
    selected_user = request.GET.get('created_by', '')
    page_number = request.GET.get('page', 1)

    # Filtered & paginated transactions
    transactions_page = services_svc.get_filtered_transactions(
        service_type_id=selected_type if selected_type else None,
        created_by_id=selected_user if selected_user else None,
        page=page_number,
    )

    # All active service types for the add-transaction modal dropdown
    service_types = ServiceType.objects.filter(is_active=True).order_by('name')

    context = {
        'active_nav': 'services',
        'stats': stats,
        'transactions': transactions_page,
        'service_types': service_types,
        'filter_types': filter_opts['service_types'],
        'filter_users': filter_opts['users'],
        'selected_type': selected_type,
        'selected_user': selected_user,
    }
    return render(request, 'core/services_page.html', context)


@login_required
def service_transaction_add(request):
    """Create a new service transaction (form POST from modal)."""
    if request.method == 'POST':
        service_type_id = request.POST.get('service_type', '').strip()
        service_amount = _to_decimal(request.POST.get('service_amount', '0'))
        customer_phone = request.POST.get('customer_phone', '').strip()
        note = request.POST.get('note', '').strip()

        try:
            services_svc.create_service_transaction(
                service_type_id=service_type_id if service_type_id else None,
                service_amount=service_amount,
                customer_phone=customer_phone,
                note=note,
                user=request.user,
            )
            messages.success(request, 'تمت إضافة المعاملة بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in service_transaction_add')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('services_page')


@login_required
def service_type_add(request):
    """Add service type — supports both AJAX (JSON) and regular POST."""
    if request.method == 'POST':
        # Check if AJAX JSON request (from popup modal)
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body)
                name = data.get('name', '').strip()
                commission_type = data.get('commission_type', '').strip()
                commission_value = _to_decimal(data.get('commission_value', '0'))
                stype = services_svc.create_service_type(name, commission_type, commission_value)
                return JsonResponse({
                    'success': True,
                    'id': stype.id,
                    'name': stype.name,
                    'message': f'تمت إضافة نوع الخدمة "{stype.name}" بنجاح'
                })
            except ValidationError as e:
                return JsonResponse({
                    'success': False,
                    'message': str(e.message) if hasattr(e, 'message') else str(e)
                }, status=400)
            except Exception as e:
                logger.exception('Error in service_type_add (AJAX)')
                return JsonResponse({'success': False, 'message': 'حدث خطأ غير متوقع'}, status=500)
        else:
            # Regular form POST (from types page)
            name = request.POST.get('name', '').strip()
            commission_type = request.POST.get('commission_type', '').strip()
            commission_value = _to_decimal(request.POST.get('commission_value', '0'))
            try:
                services_svc.create_service_type(name, commission_type, commission_value)
                messages.success(request, f'تمت إضافة نوع الخدمة "{name}" بنجاح')
            except ValidationError as e:
                messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
            except Exception as e:
                logger.exception('Error in service_type_add')
                messages.error(request, f'حدث خطأ: {e}')
            return redirect('service_types_page')

    return JsonResponse({'success': False, 'message': 'طلب غير صالح'}, status=400)


@login_required
def service_types_page(request):
    """Dedicated page to view and edit service types."""
    from django.db.models import Count

    service_types = ServiceType.objects.filter(is_active=True).order_by('name')
    service_types = service_types.annotate(
        txn_count=Count('transactions')
    )

    context = {
        'active_nav': 'services',
        'service_types': service_types,
    }
    return render(request, 'core/service_types_page.html', context)


@login_required
def service_type_edit(request):
    """Rename / update commission of a service type."""
    if request.method == 'POST':
        type_id = request.POST.get('type_id', '')
        name = request.POST.get('name', '').strip()
        commission_type = request.POST.get('commission_type', '').strip()
        commission_value = _to_decimal(request.POST.get('commission_value', '0'))
        try:
            services_svc.update_service_type(type_id, name, commission_type, commission_value)
            messages.success(request, f'تم تحديث نوع الخدمة "{name}" بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in service_type_edit')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('service_types_page')


@login_required
def service_type_delete(request):
    """Soft-delete a service type."""
    if request.method == 'POST':
        type_id = request.POST.get('type_id', '')
        try:
            services_svc.delete_service_type(type_id)
            messages.success(request, 'تم حذف نوع الخدمة بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in service_type_delete')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('service_types_page')


# ==========================================
# Installment Sales Views
# ==========================================

@login_required
def installment_sales_page(request):
    """Main installment sales page — stats cards, create form, and list."""
    sales_qs = installments_svc.get_installment_sales_list()

    # Stats
    total_sales_count = sales_qs.count()
    total_sales_value = sum((s.installment_sale_price for s in sales_qs), Decimal('0.00'))
    total_collected = sum((s.total_paid for s in sales_qs), Decimal('0.00'))
    total_profit_collected = sum((s.collected_profit for s in sales_qs), Decimal('0.00'))
    active_count = sum(1 for s in sales_qs if not s.is_completed)
    completed_count = sum(1 for s in sales_qs if s.is_completed)

    # Products for the create form
    products = list(Product.objects.filter(is_active=True, stock__gt=0).order_by('name'))

    context = {
        'active_nav': 'installments',
        'sales': sales_qs,
        'products': products,
        'total_sales_count': total_sales_count,
        'total_sales_value': total_sales_value,
        'total_collected': total_collected,
        'total_profit_collected': total_profit_collected,
        'active_count': active_count,
        'completed_count': completed_count,
    }
    return render(request, 'core/installment_sales_page.html', context)


@login_required
def installment_sale_create(request):
    """AJAX POST endpoint to create an installment sale."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            sale = installments_svc.create_installment_sale(
                product_id=data.get('product_id'),
                quantity=data.get('quantity', 1),
                installment_sale_price=_to_decimal(data.get('installment_sale_price', '0')),
                down_payment=_to_decimal(data.get('down_payment', '0')),
                number_of_installments=data.get('number_of_installments', 0),
                customer_name=data.get('customer_name', ''),
                customer_phone=data.get('customer_phone', ''),
                customer_address=data.get('customer_address', ''),
                customer_id_number=data.get('customer_id_number', ''),
                guarantor_name=data.get('guarantor_name', ''),
                guarantor_phone=data.get('guarantor_phone', ''),
                guarantor_address=data.get('guarantor_address', ''),
                guarantor_id_number=data.get('guarantor_id_number', ''),
                note=data.get('note', ''),
                user=request.user,
            )

            return JsonResponse({
                'success': True,
                'message': f'تم تسجيل البيع بالتقسيط بنجاح (رقم {sale.id})',
                'sale_id': sale.id,
            })

        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'message': str(e.message) if hasattr(e, 'message') else str(e)
            }, status=400)
        except Exception as e:
            logger.exception('Error in installment_sale_create')
            return JsonResponse({'success': False, 'message': 'حدث خطأ غير متوقع'}, status=500)

    return JsonResponse({'success': False, 'message': 'طلب غير صالح'}, status=400)


@login_required
def installment_sale_detail(request, sale_id):
    """Detail/edit page for a specific installment sale."""
    try:
        sale = installments_svc.get_installment_sale_detail(sale_id)
    except ValidationError:
        messages.error(request, 'عملية البيع بالتقسيط غير موجودة')
        return redirect('installment_sales_page')

    installments = sale.installments.all()

    context = {
        'active_nav': 'installments',
        'sale': sale,
        'installments': installments,
    }
    return render(request, 'core/installment_sale_detail.html', context)


@login_required
def installment_sale_update(request, sale_id):
    """POST to update customer/guarantor info on an installment sale."""
    if request.method == 'POST':
        try:
            installments_svc.update_installment_sale(
                sale_id=sale_id,
                customer_name=request.POST.get('customer_name', ''),
                customer_phone=request.POST.get('customer_phone', ''),
                customer_address=request.POST.get('customer_address', ''),
                customer_id_number=request.POST.get('customer_id_number', ''),
                guarantor_name=request.POST.get('guarantor_name', ''),
                guarantor_phone=request.POST.get('guarantor_phone', ''),
                guarantor_address=request.POST.get('guarantor_address', ''),
                guarantor_id_number=request.POST.get('guarantor_id_number', ''),
                note=request.POST.get('note', ''),
            )
            messages.success(request, 'تم تحديث البيانات بنجاح')
        except ValidationError as e:
            messages.error(request, str(e.message) if hasattr(e, 'message') else str(e))
        except Exception as e:
            logger.exception('Error in installment_sale_update')
            messages.error(request, f'حدث خطأ: {e}')

    return redirect('installment_sale_detail', sale_id=sale_id)


@login_required
def installment_toggle_paid(request):
    """AJAX POST to toggle an installment's paid status."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            installment_id = data.get('installment_id')

            installment = installments_svc.toggle_installment_paid(installment_id)
            sale = installment.sale

            return JsonResponse({
                'success': True,
                'is_paid': installment.is_paid,
                'paid_at': installment.paid_at.strftime('%Y-%m-%d %H:%M') if installment.paid_at else None,
                'total_paid': str(sale.total_paid),
                'remaining_amount': str(sale.remaining_amount),
                'collected_profit': str(sale.collected_profit),
                'paid_count': sale.paid_count,
                'is_completed': sale.is_completed,
            })

        except ValidationError as e:
            return JsonResponse({
                'success': False,
                'message': str(e.message) if hasattr(e, 'message') else str(e)
            }, status=400)
        except Exception as e:
            logger.exception('Error in installment_toggle_paid')
            return JsonResponse({'success': False, 'message': 'حدث خطأ غير متوقع'}, status=500)

    return JsonResponse({'success': False, 'message': 'طلب غير صالح'}, status=400)


# ===================================================================
#  Settings & Backup
# ===================================================================

@login_required
def settings_page(request):
    """Display the settings page."""
    return render(request, 'core/settings_page.html', {
        'active_nav': 'settings',
    })


@login_required
def backup_create(request):
    """Create a backup of the current SQLite database."""
    if request.method != 'POST':
        return redirect('settings_page')

    try:
        db_path = django_settings.DATABASES['default']['NAME']
        backup_dir = os.path.join(django_settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        # Use datetime with milliseconds to guarantee unique filenames
        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d_%H-%M-%S') + f'_{now.microsecond // 1000:03d}ms'
        backup_filename = f'backup_{timestamp}.sqlite3'
        backup_path = os.path.join(backup_dir, backup_filename)

        shutil.copy2(str(db_path), backup_path)

        messages.success(request, f'تم إنشاء النسخة الاحتياطية بنجاح: {backup_filename}')
    except Exception as e:
        logger.exception('Error creating backup')
        messages.error(request, f'فشل إنشاء النسخة الاحتياطية: {e}')

    return redirect('settings_page')


@login_required
def backup_restore(request):
    """Restore the SQLite database from an uploaded backup file."""
    if request.method != 'POST':
        return redirect('settings_page')

    uploaded_file = request.FILES.get('backup_file')
    if not uploaded_file:
        messages.error(request, 'لم يتم اختيار ملف للاستعادة.')
        return redirect('settings_page')

    # Validate file extension
    valid_extensions = ('.sqlite3', '.sqlite', '.db')
    if not uploaded_file.name.lower().endswith(valid_extensions):
        messages.error(request, 'صيغة الملف غير صالحة. يرجى رفع ملف SQLite (.sqlite3, .sqlite, .db).')
        return redirect('settings_page')

    try:
        db_path = str(django_settings.DATABASES['default']['NAME'])

        # Auto-create a safety backup before restoring
        backup_dir = os.path.join(django_settings.BASE_DIR, 'backups/pre_restore')
        os.makedirs(backup_dir, exist_ok=True)
        now = datetime.now()
        timestamp = now.strftime('%Y-%m-%d_%H-%M-%S') + f'_{now.microsecond // 1000:03d}ms'
        safety_filename = f'pre_restore_{timestamp}.sqlite3'
        safety_path = os.path.join(backup_dir, safety_filename)
        shutil.copy2(db_path, safety_path)

        # Write the uploaded file to a temp location then replace the DB
        temp_path = db_path + '.tmp_restore'
        with open(temp_path, 'wb') as dest:
            for chunk in uploaded_file.chunks():
                dest.write(chunk)

        # Replace current database
        shutil.move(temp_path, db_path)

        messages.success(
            request,
            f'تم استعادة النسخة الاحتياطية بنجاح من: {uploaded_file.name}. '
            f'تم حفظ نسخة أمان: {safety_filename}'
        )
    except Exception as e:
        logger.exception('Error restoring backup')
        # Clean up temp file if it exists
        temp_path = str(django_settings.DATABASES['default']['NAME']) + '.tmp_restore'
        if os.path.exists(temp_path):
            os.remove(temp_path)
        messages.error(request, f'فشل استعادة النسخة الاحتياطية: {e}')

    return redirect('settings_page')


# ===================================================================
#  Dashboard Home & Reports
# ===================================================================

@login_required
def dashboard_home(request):
    """Display the main dashboard with KPI overview."""
    try:
        stats = dashboard_svc.get_dashboard_overview()
    except Exception as e:
        logger.exception('Error loading dashboard stats')
        messages.error(request, f'حدث خطأ أثناء تحميل الإحصائيات: {e}')
        stats = {}

    # Low stock products list (up to 15)
    low_stock_list = list(
        Product.objects.select_related('category')
        .filter(is_active=True, stock__lte=F('low_stock_alert'))
        .order_by('stock')[:15]
    )

    # Current month label
    today = date.today()
    months_ar = [
        '', 'يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو',
        'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'
    ]
    current_month = f'{months_ar[today.month]} {today.year}'

    return render(request, 'core/dashboard_home.html', {
        'active_nav': 'home',
        'stats': stats,
        'low_stock_list': low_stock_list,
        'current_month': current_month,
    })


@login_required
def reports_page(request):
    """Display the financial reports page with date filtering."""
    report = None
    max_daily_revenue = Decimal('0')

    # Default date range: current month
    today = timezone.localdate()
    default_from = today.replace(day=1)
    default_to = today

    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')

    # Parse dates
    try:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date() if date_from_str else default_from
    except ValueError:
        date_from = default_from
        messages.error(request, 'تنسيق تاريخ البداية غير صحيح')

    try:
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date() if date_to_str else default_to
    except ValueError:
        date_to = default_to
        messages.error(request, 'تنسيق تاريخ النهاية غير صحيح')

    # Ensure date_from <= date_to
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    # Only generate report if dates were explicitly submitted
    if date_from_str or date_to_str:
        try:
            report = dashboard_svc.get_financial_report(date_from, date_to)
            # Calculate max daily revenue for bar chart width
            if report.get('daily_sales'):
                max_daily_revenue = max(
                    (d['revenue'] for d in report['daily_sales']),
                    default=Decimal('0')
                ) or Decimal('1')  # avoid division by zero
        except Exception as e:
            logger.exception('Error generating report')
            messages.error(request, f'حدث خطأ أثناء إنشاء التقرير: {e}')

    return render(request, 'core/reports_page.html', {
        'active_nav': 'reports',
        'report': report,
        'date_from': date_from,
        'date_to': date_to,
        'max_daily_revenue': max_daily_revenue,
    })
