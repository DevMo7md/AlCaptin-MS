from django.db import transaction
from django.core.exceptions import ValidationError

from core.models import Product, SaleInvoice, SaleItem, InstallmentSale

@transaction.atomic
def sell_product(product, quantity):
    """
    Sells a quantity of product using FIFO logic,
    and returns revenue, cogs, and profit.
    """
    total_cogs = product.sell_fifo(quantity)
    total_revenue = quantity * product.sell_price
    profit = total_revenue - total_cogs
    
    return {
        'total_revenue': total_revenue,
        'total_cogs': total_cogs,
        'profit': profit
    }


@transaction.atomic
def create_sale_invoice(cart_items, user):
    """
    Creates a full sale invoice from a list of cart items.
    cart_items structure: [{"product_id": 1, "quantity": 2}, ...]
    Rolls back transaction and raises ValidationError on failure.
    """
    if not cart_items:
        raise ValidationError('سلة المشتريات فارغة')

    invoice = SaleInvoice.objects.create(created_by=user)

    for item_data in cart_items:
        product_id = item_data.get('product_id')
        try:
            quantity = int(item_data.get('quantity', 0))
        except (ValueError, TypeError):
            raise ValidationError('كمية المنتج غير صحيحة')

        if quantity <= 0:
            raise ValidationError('الكمية يجب أن تكون أكبر من صفر')

        try:
            product = Product.objects.get(id=product_id, is_active=True)
        except Product.DoesNotExist:
            raise ValidationError(f'المنتج غير موجود أو غير نشط (ID: {product_id})')

        if product.stock < quantity:
            raise ValidationError(f'الكمية المطلوبة من "{product.name}" غير متوفرة في المخزون (المتاح: {product.stock})')

        try:
            # Execute FIFO deduction which updates stock and returns total COGS
            total_cogs = product.sell_fifo(quantity)
        except ValueError as e:
            raise ValidationError(str(e))

        # Create the SaleItem tracking the product price and cost at this exact moment
        SaleItem.objects.create(
            invoice=invoice,
            product=product,
            quantity=quantity,
            sell_price=product.sell_price,
            cogs=total_cogs
        )

    return invoice

# Installments Sales Service
