import _collections_abc
from django.db import models, transaction
from decimal import Decimal
from django.contrib.auth.models import User
# Products Models

class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name

class Supplier(models.Model):
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15)
    address = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Product(models.Model):
    name = models.CharField(max_length=255)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    barcode = models.CharField(max_length=255, unique=True, null=True, blank=True)
    sell_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    low_stock_alert = models.PositiveIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_alert
    @transaction.atomic
    def sell_fifo(self, quantity):
        """Deduct `quantity` from the oldest batches first (FIFO).
        Updates remaining_quantity on each batch and syncs product.stock.
        Returns the total cost of goods sold (COGS) for this sale.
        Raises ValueError if insufficient stock.
        """
        if quantity <= 0:
            raise ValueError('الكمية يجب أن تكون أكبر من صفر')
        if quantity > self.stock:
            raise ValueError(
                f'الكمية المطلوبة ({quantity}) أكبر من المخزون المتاح ({self.stock})'
            )

        remaining_to_sell = quantity
        total_cogs = Decimal('0.00')

        # Oldest first (FIFO) — only batches that still have stock
        batches = self.purchase_batches.filter(
            remaining_quantity__gt=0
        ).order_by('created_at')

        for batch in batches:
            if remaining_to_sell <= 0:
                break

            take = min(batch.remaining_quantity, remaining_to_sell)
            total_cogs += (Decimal(take) * batch.buy_price)
            batch.remaining_quantity -= take
            batch.save(update_fields=['remaining_quantity'])
            remaining_to_sell -= take

        if remaining_to_sell > 0:
            raise ValueError("FIFO inconsistency detected")
        # Sync product stock
        self.stock -= quantity
        self.save(update_fields=['stock'])

        return total_cogs

    def __str__(self):
        return f'#{self.id} - {self.name} - {self.category.name if self.category else "No Category"} - stock {self.stock}'

class PurchaseInvoice(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    invoice_number = models.CharField(max_length=255, blank=True, null=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_amount(self):
        return sum(
            (batch.total_price for batch in self.batches.all()),
            Decimal('0.00')
        )

    def __str__(self):
        return f'#Invoice {self.id} - {self.supplier} - {self.total_amount} EGP'

class PurchaseBatch(models.Model):
    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name='batches',null=True,blank=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='purchase_batches')
    quantity = models.PositiveIntegerField()
    remaining_quantity = models.PositiveIntegerField(editable=False)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_price(self):
        return Decimal(self.quantity) * self.buy_price

    def __str__(self):
        return f'#Batch {self.id} - {self.product.name} - {self.quantity} - {self.buy_price} EGP'

    def save(self, *args, **kwargs):

        if self.pk is None:
            self.remaining_quantity = self.quantity

        super().save(*args, **kwargs)


class SaleInvoice(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    @property
    def total_amount(self):
        return sum(
            (item.total_price for item in self.items.all()),
            Decimal('0.00')
        )

    @property
    def total_profit(self):
        return sum(
            (item.profit for item in self.items.all()),
            Decimal('0.00')
        )

    def __str__(self):
        return f'#Sale {self.id} - {self.total_amount} EGP'


class SaleItem(models.Model):
    invoice = models.ForeignKey(
        SaleInvoice,
        on_delete=models.CASCADE,
        related_name='items'
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='sale_items'
    )

    quantity = models.PositiveIntegerField()

    sell_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    cogs = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total_price(self):
        return Decimal(self.quantity) * self.sell_price
    
    @property
    def profit(self):
        return (Decimal(self.quantity) * self.sell_price) - self.cogs



# Expense Models

class ExpenseCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)
    
    def __str__(self):
        return self.name

class Expense(models.Model):
    category = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.TextField(blank=True)
    expense_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'#Expense {self.id} - {self.amount} EGP'


# Service Models

class ServiceType(models.Model):
    name = models.CharField(max_length=255, unique=True)
    commission_type = models.CharField(max_length=10, choices=[('percentage', 'نسبة'), ('fixed', 'مبلغ ثابت')])
    commission_value = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'#{self.id} - {self.name} - {self.commission_value} {self.commission_type}'
    
class ServiceTransaction(models.Model):
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT, related_name='transactions')
    service_amount = models.DecimalField(max_digits=10, decimal_places=2)
    commission = models.DecimalField(max_digits=10, decimal_places=2) # snapshot
    customer_phone = models.CharField(max_length=15, null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'#{self.id} - {self.service_type.name} - {self.service_amount} EGP'

# Installments Models

class InstallmentSale(models.Model):
    """Header for an installment sale — one per transaction."""
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='installment_sales')
    quantity = models.PositiveIntegerField(default=1)
    installment_sale_price = models.DecimalField(max_digits=10, decimal_places=2)  # Total selling price (تقسيط)
    cogs = models.DecimalField(max_digits=10, decimal_places=2)  # Cost of goods (from FIFO)
    down_payment = models.DecimalField(max_digits=10, decimal_places=2)  # المقدم
    number_of_installments = models.PositiveIntegerField()  # عدد الأقساط

    # Customer info
    customer_name = models.CharField(max_length=255)
    customer_phone = models.CharField(max_length=20)
    customer_address = models.TextField(blank=True, default='')
    customer_id_number = models.CharField(max_length=30, blank=True, default='')  # الرقم القومي

    # Guarantor (ضامن)
    guarantor_name = models.CharField(max_length=255, blank=True, default='')
    guarantor_phone = models.CharField(max_length=20, blank=True, default='')
    guarantor_address = models.TextField(blank=True, default='')
    guarantor_id_number = models.CharField(max_length=30, blank=True, default='')

    note = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Computed Properties ---
    @property
    def total_profit(self):
        """Total profit = installment sale price − COGS."""
        return self.installment_sale_price - self.cogs

    @property
    def installment_amount(self):
        """Per-installment payment = (sale price − down payment) / N."""
        if self.number_of_installments == 0:
            return Decimal('0.00')
        return (self.installment_sale_price - self.down_payment) / self.number_of_installments

    @property
    def total_paid(self):
        """Sum of amounts from paid installments."""
        return self.installments.filter(is_paid=True).aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0.00')

    @property
    def remaining_amount(self):
        """How much is still owed."""
        return self.installment_sale_price - self.total_paid

    @property
    def collected_profit(self):
        """Sum of profit portions from paid installments."""
        return self.installments.filter(is_paid=True).aggregate(
            total=models.Sum('profit_portion')
        )['total'] or Decimal('0.00')

    @property
    def paid_count(self):
        """Number of installments that have been paid."""
        return self.installments.filter(is_paid=True).count()

    @property
    def is_completed(self):
        """True when every installment (including down payment) is paid."""
        return self.installments.filter(is_paid=False).count() == 0

    def __str__(self):
        return f'#قسط {self.id} - {self.product.name} - {self.installment_sale_price} EGP'


class Installment(models.Model):
    """One row per installment (including the down-payment row)."""
    sale = models.ForeignKey(InstallmentSale, on_delete=models.CASCADE, related_name='installments')
    installment_number = models.PositiveIntegerField()  # 0 = down payment, 1..N = installments
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    profit_portion = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['installment_number']
        unique_together = [('sale', 'installment_number')]

    def __str__(self):
        label = 'مقدم' if self.installment_number == 0 else f'قسط {self.installment_number}'
        status = '✅' if self.is_paid else '⬜'
        return f'{status} {label} - {self.amount} EGP'

