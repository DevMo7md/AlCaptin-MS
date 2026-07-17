from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError

from core.models import Product, Category, PurchaseBatch, Supplier, PurchaseInvoice


def sync_product_stock(product):
    """
    Recalculate product.stock from its PurchaseBatch remaining_quantity totals.
    This ensures that PurchaseBatch.remaining_quantity is the single source of truth.
    """
    total = product.purchase_batches.aggregate(
        total=Coalesce(Sum('remaining_quantity'), 0)
    )['total']
    product.stock = total
    product.save(update_fields=['stock'])


def create_purchase_invoice(supplier_id, invoice_number, note):
    """Create and return a PurchaseInvoice."""
    supplier = None
    if supplier_id:
        supplier = Supplier.objects.filter(id=supplier_id).first()
    
    return PurchaseInvoice.objects.create(
        supplier=supplier,
        invoice_number=invoice_number,
        note=note
    )


@transaction.atomic
def add_new_product(name, barcode, category_id, sell_price, low_stock_alert):
    """
    Creates a new product without initial stock.
    Raises ValidationError if the barcode is already in use.
    """
    if Product.objects.filter(barcode=barcode).exists():
        raise ValidationError('هذا الباركود مستخدم بالفعل لمنتج آخر')
    
    category = Category.objects.get(id=category_id)

    product = Product.objects.create(
        name=name,
        barcode=barcode,
        category=category,
        sell_price=sell_price,
        stock=0,
        low_stock_alert=low_stock_alert,
    )
    
    return product


@transaction.atomic
def update_product_info(product, name, barcode, category_id, sell_price, low_stock_alert):
    """
    Updates the core information of a product atomically.
    Raises ValidationError if the barcode is taken by another product.
    """
    if Product.objects.filter(barcode=barcode).exclude(id=product.id).exists():
        raise ValidationError('هذا الباركود مستخدم بالفعل لمنتج آخر')

    category = Category.objects.get(id=category_id)
    
    product.name = name
    product.barcode = barcode
    product.category = category
    product.sell_price = sell_price
    product.low_stock_alert = low_stock_alert
    product.save()
    
    return product


@transaction.atomic
def create_purchase_transaction(supplier_id, invoice_number, invoice_note, cart_items):
    """
    Creates a purchase invoice and associated purchase batches.
    cart_items structure: [{"product_id": 1, "quantity": 10, "buy_price": 50.00}, ...]
    Syncs the stock of all affected products.
    """
    if not cart_items:
        raise ValidationError('لا توجد منتجات في الفاتورة')

    invoice = create_purchase_invoice(supplier_id, invoice_number, invoice_note)
    
    affected_products = set()

    for item in cart_items:
        try:
            quantity = int(item.get('quantity', 0))
        except (ValueError, TypeError):
            raise ValidationError('الكمية غير صحيحة')
            
        if quantity <= 0:
            raise ValidationError('الكمية يجب أن تكون أكبر من صفر')

        try:
            buy_price = Decimal(str(item.get('buy_price', '0')))
        except Exception:
            raise ValidationError('سعر الشراء غير صحيح')
            
        if buy_price <= 0:
            raise ValidationError('سعر الشراء يجب أن يكون أكبر من صفر')

        is_new = item.get('is_new', False)
        
        if is_new:
            new_data = item.get('new_data', {})
            try:
                product = add_new_product(
                    name=new_data.get('name'),
                    barcode=new_data.get('barcode'),
                    category_id=new_data.get('category_id'),
                    sell_price=Decimal(str(new_data.get('sell_price', '0'))),
                    low_stock_alert=int(new_data.get('low_stock_alert', 0))
                )
            except ValidationError as e:
                raise ValidationError(f"المنتج '{new_data.get('name')}': {str(e.message) if hasattr(e, 'message') else str(e)}")
            except Exception as e:
                raise ValidationError(f"فشل إنشاء المنتج '{new_data.get('name')}': {str(e)}")
        else:
            product_id = item.get('product_id')
            try:
                product = Product.objects.get(id=product_id, is_active=True)
            except Product.DoesNotExist:
                raise ValidationError(f'المنتج غير موجود أو غير نشط (ID: {product_id})')

        PurchaseBatch.objects.create(
            invoice=invoice,
            product=product,
            quantity=quantity,
            buy_price=buy_price
        )
        
        affected_products.add(product)
        
    for product in affected_products:
        sync_product_stock(product)
        
    return invoice


def calculate_product_stats_in_memory(product):
    """
    Calculates product stats (max_stock, avg_buy_price) and generates batch history 
    using prefetched `purchase_batches` to avoid N+1 queries.
    Returns a dictionary of statistics to be assigned back to the product.
    """
    # Assuming `purchase_batches` is prefetched, .all() avoids hitting DB
    batches = list(product.purchase_batches.all())
    
    # max stock (total purchased over time)
    max_stock = sum(b.quantity for b in batches)
    
    # avg buy price
    remaining_batches = [b for b in batches if b.remaining_quantity > 0]
    total_qty = sum(b.remaining_quantity for b in remaining_batches)
    
    if total_qty == 0:
        # Fallback to latest batch price (batches are ordered by -created_at in prefetch)
        avg_buy_price = batches[0].buy_price if batches else Decimal('0.00')
    else:
        weighted_sum = sum(b.remaining_quantity * b.buy_price for b in remaining_batches)
        avg_buy_price = (weighted_sum / total_qty).quantize(Decimal('0.01'))
        
    profit = product.sell_price - avg_buy_price
    
    batches_list = [
        {
            'id': b.id,
            'quantity': b.quantity,
            'remaining_quantity': b.remaining_quantity,
            'buy_price': str(b.buy_price),  # Convert to string for JSON serialization
            'created_at': b.created_at
        } for b in batches
    ]
    
    return {
        'max_stock': max_stock,
        'avg_buy_price': avg_buy_price,
        'profit': profit,
        'batches_list': batches_list
    }


def hydrate_products(products_list):
    """
    Hydrates a list of products with in-memory calculated stats 
    (avg_buy_price, profit, max_stock, batches_list).
    This centralizes the hydration loop so it isn't duplicated in views.
    """
    for p in products_list:
        stats = calculate_product_stats_in_memory(p)
        p.avg_buy_price = stats['avg_buy_price']
        p.profit = stats['profit']
        p.max_stock = stats['max_stock']
        p.batches_list = stats['batches_list']
    return products_list
