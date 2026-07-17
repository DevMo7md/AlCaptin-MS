# ==========================================
# Installment Sales Service Layer
# Handles creation, payment tracking, and
# profit distribution for installment sales.
# ==========================================

from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import Product, InstallmentSale, Installment


@transaction.atomic
def create_installment_sale(
    product_id,
    quantity,
    installment_sale_price,
    down_payment,
    number_of_installments,
    customer_name,
    customer_phone,
    customer_address='',
    customer_id_number='',
    guarantor_name='',
    guarantor_phone='',
    guarantor_address='',
    guarantor_id_number='',
    note='',
    user=None,
):
    """
    Create an installment sale:
    1. Validate inputs
    2. Deduct stock via FIFO → get COGS
    3. Create InstallmentSale header
    4. Create Installment rows (0=down payment, 1..N=installments)
    5. Distribute profit evenly across N+1 slices
    """
    # --- Validation ---
    try:
        quantity = int(quantity)
    except (ValueError, TypeError):
        raise ValidationError('الكمية يجب أن تكون رقم صحيح')

    if quantity <= 0:
        raise ValidationError('الكمية يجب أن تكون أكبر من صفر')

    installment_sale_price = Decimal(str(installment_sale_price))
    down_payment = Decimal(str(down_payment))

    try:
        number_of_installments = int(number_of_installments)
    except (ValueError, TypeError):
        raise ValidationError('عدد الأقساط يجب أن يكون رقم صحيح')

    if number_of_installments <= 0:
        raise ValidationError('عدد الأقساط يجب أن يكون أكبر من صفر')

    if installment_sale_price <= 0:
        raise ValidationError('سعر البيع بالتقسيط يجب أن يكون أكبر من صفر')

    if down_payment < 0:
        raise ValidationError('المقدم لا يمكن أن يكون سالب')

    if down_payment >= installment_sale_price:
        raise ValidationError('المقدم يجب أن يكون أقل من سعر البيع بالتقسيط')

    if not customer_name or not customer_name.strip():
        raise ValidationError('اسم العميل مطلوب')

    if not customer_phone or not customer_phone.strip():
        raise ValidationError('رقم هاتف العميل مطلوب')

    # --- Get product & deduct stock ---
    try:
        product = Product.objects.get(id=product_id, is_active=True)
    except Product.DoesNotExist:
        raise ValidationError(f'المنتج غير موجود أو غير نشط (ID: {product_id})')

    if product.stock < quantity:
        raise ValidationError(
            f'الكمية المطلوبة من "{product.name}" غير متوفرة في المخزون (المتاح: {product.stock})'
        )

    try:
        total_cogs = product.sell_fifo(quantity)
    except ValueError as e:
        raise ValidationError(str(e))

    # --- Create sale header ---
    sale = InstallmentSale.objects.create(
        product=product,
        quantity=quantity,
        installment_sale_price=installment_sale_price,
        cogs=total_cogs,
        down_payment=down_payment,
        number_of_installments=number_of_installments,
        customer_name=customer_name.strip(),
        customer_phone=customer_phone.strip(),
        customer_address=customer_address.strip() if customer_address else '',
        customer_id_number=customer_id_number.strip() if customer_id_number else '',
        guarantor_name=guarantor_name.strip() if guarantor_name else '',
        guarantor_phone=guarantor_phone.strip() if guarantor_phone else '',
        guarantor_address=guarantor_address.strip() if guarantor_address else '',
        guarantor_id_number=guarantor_id_number.strip() if guarantor_id_number else '',
        note=note.strip() if note else '',
        created_by=user,
    )

    # --- Profit distribution ---
    total_profit = installment_sale_price - total_cogs
    total_slices = number_of_installments + 1  # +1 for down payment
    base_profit = (total_profit / total_slices).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    # --- Installment amount ---
    remaining_after_down = installment_sale_price - down_payment
    base_installment = (remaining_after_down / number_of_installments).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )

    # --- Create installment rows ---
    installments_to_create = []

    # Row 0: Down payment
    installments_to_create.append(Installment(
        sale=sale,
        installment_number=0,
        amount=down_payment,
        profit_portion=base_profit,
    ))

    # Rows 1..N: Regular installments
    profit_distributed = base_profit  # already used for down payment
    amount_distributed = Decimal('0.00')

    for i in range(1, number_of_installments + 1):
        if i == number_of_installments:
            # Last installment gets the remainder to avoid rounding drift
            inst_amount = remaining_after_down - amount_distributed
            inst_profit = total_profit - profit_distributed
        else:
            inst_amount = base_installment
            inst_profit = base_profit

        installments_to_create.append(Installment(
            sale=sale,
            installment_number=i,
            amount=inst_amount,
            profit_portion=inst_profit,
        ))
        amount_distributed += inst_amount
        profit_distributed += inst_profit

    Installment.objects.bulk_create(installments_to_create)

    return sale


@transaction.atomic
def toggle_installment_paid(installment_id):
    """Toggle the paid status of an installment. Returns the updated installment."""
    try:
        installment = Installment.objects.select_related('sale').get(id=installment_id)
    except Installment.DoesNotExist:
        raise ValidationError('القسط غير موجود')

    if installment.is_paid:
        # Un-pay
        installment.is_paid = False
        installment.paid_at = None
    else:
        # Pay
        installment.is_paid = True
        installment.paid_at = timezone.now()

    installment.save(update_fields=['is_paid', 'paid_at'])
    return installment


def get_installment_sale_detail(sale_id):
    """Return the installment sale with all its installments."""
    try:
        sale = InstallmentSale.objects.select_related(
            'product', 'created_by'
        ).prefetch_related('installments').get(id=sale_id)
    except InstallmentSale.DoesNotExist:
        raise ValidationError('عملية البيع بالتقسيط غير موجودة')
    return sale


def get_installment_sales_list():
    """Return all installment sales ordered by newest first."""
    return InstallmentSale.objects.select_related(
        'product', 'created_by'
    ).prefetch_related('installments').order_by('-created_at')


def update_installment_sale(sale_id, **kwargs):
    """Update editable fields on an installment sale (customer/guarantor info, note)."""
    try:
        sale = InstallmentSale.objects.get(id=sale_id)
    except InstallmentSale.DoesNotExist:
        raise ValidationError('عملية البيع بالتقسيط غير موجودة')

    editable_fields = [
        'customer_name', 'customer_phone', 'customer_address', 'customer_id_number',
        'guarantor_name', 'guarantor_phone', 'guarantor_address', 'guarantor_id_number',
        'note',
    ]
    updated = []
    for field in editable_fields:
        if field in kwargs:
            value = kwargs[field]
            if isinstance(value, str):
                value = value.strip()
            setattr(sale, field, value)
            updated.append(field)

    if updated:
        sale.save(update_fields=updated + ['updated_at'])

    return sale
