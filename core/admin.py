from django.contrib import admin
from .models import (
    Category, Product, PurchaseBatch, PurchaseInvoice,
    SaleInvoice, SaleItem, ServiceType, ServiceTransaction,
    InstallmentSale, Installment,
)


class PurchaseBatchInline(admin.TabularInline):
    model = PurchaseBatch
    extra = 0
    readonly_fields = ('created_at',)


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0
    readonly_fields = ('installment_number', 'amount', 'profit_portion', 'paid_at', 'created_at')


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'created_at')
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'sell_price', 'stock', 'low_stock_alert', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    inlines = [PurchaseBatchInline]


@admin.register(PurchaseBatch)
class PurchaseBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'quantity', 'remaining_quantity', 'buy_price', 'created_at')
    list_filter = ('product',)
    search_fields = ('product__name',)

@admin.register(PurchaseInvoice)
class PurchaseInvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'supplier', 'total_amount', 'created_at')
    list_filter = ('supplier', 'created_at')
    search_fields = ('id',)

@admin.register(SaleInvoice)
class SaleInvoiceAdmin(admin.ModelAdmin):
    list_display = ('id', 'total_amount', 'total_profit', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('id',)

@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'quantity', 'sell_price', 'cogs', 'total_price', 'profit', 'created_at')
    list_filter = ('product', 'created_at')
    search_fields = ('product__name',)


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'commission_type', 'commission_value', 'is_active', 'created_at')
    list_filter = ('commission_type', 'is_active')
    search_fields = ('name',)


@admin.register(ServiceTransaction)
class ServiceTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'service_type', 'service_amount', 'commission', 'customer_phone', 'created_by', 'created_at')
    list_filter = ('service_type', 'created_at')
    search_fields = ('customer_phone', 'note')


@admin.register(InstallmentSale)
class InstallmentSaleAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'customer_name', 'installment_sale_price', 'down_payment', 'number_of_installments', 'is_completed', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('customer_name', 'customer_phone', 'product__name')
    inlines = [InstallmentInline]


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'sale', 'installment_number', 'amount', 'profit_portion', 'is_paid', 'paid_at')
    list_filter = ('is_paid',)
    search_fields = ('sale__customer_name',)