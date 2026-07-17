from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Dashboard
    path('', RedirectView.as_view(pattern_name='dashboard_home'), name='dashboard'),
    path('home/', views.dashboard_home, name='dashboard_home'),

    # Products CRUD
    path('products/', views.products_list, name='products_list'),
    path('products/add/', views.product_add, name='product_add'),
    path('products/edit/', views.product_edit, name='product_edit'),
    path('products/delete/', views.product_delete, name='product_delete'),
    
    # Categories
    path('categories/add/', views.category_add, name='category_add'),
    path('suppliers/add/', views.supplier_add, name='supplier_add'),

    # Purchases
    path('purchases/', views.purchases_page, name='purchases_page'),
    path('purchases/create/', views.purchase_create, name='purchase_create'),
    path('purchases/<int:invoice_id>/', views.purchase_invoice_detail, name='purchase_invoice_detail'),
    
    # Sales
    path('products/sell/', views.product_sell, name='product_sell'),
    path('sales/', views.sales_page, name='sales_page'),
    path('sales/create/', views.sale_create, name='sale_create'),
    path('sales/<int:invoice_id>/', views.sale_invoice_detail, name='sale_invoice_detail'),

    # Expenses
    path('expenses/', views.expenses_page, name='expenses_page'),
    path('expenses/add/', views.expense_add, name='expense_add'),
    path('expenses/delete/', views.expense_delete, name='expense_delete'),
    path('expenses/categories/', views.expense_categories_page, name='expense_categories_page'),
    path('expenses/categories/add/', views.expense_category_add, name='expense_category_add'),
    path('expenses/categories/edit/', views.expense_category_edit, name='expense_category_edit'),
    path('expenses/categories/delete/', views.expense_category_delete, name='expense_category_delete'),

    # Services
    path('services/', views.services_page, name='services_page'),
    path('services/transaction/add/', views.service_transaction_add, name='service_transaction_add'),
    path('services/types/', views.service_types_page, name='service_types_page'),
    path('services/types/add/', views.service_type_add, name='service_type_add'),
    path('services/types/edit/', views.service_type_edit, name='service_type_edit'),
    path('services/types/delete/', views.service_type_delete, name='service_type_delete'),

    # Installments
    path('installments/', views.installment_sales_page, name='installment_sales_page'),
    path('installments/create/', views.installment_sale_create, name='installment_sale_create'),
    path('installments/<int:sale_id>/', views.installment_sale_detail, name='installment_sale_detail'),
    path('installments/<int:sale_id>/update/', views.installment_sale_update, name='installment_sale_update'),
    path('installments/toggle-paid/', views.installment_toggle_paid, name='installment_toggle_paid'),

    # Settings & Backup
    path('settings/', views.settings_page, name='settings_page'),
    path('settings/backup/create/', views.backup_create, name='backup_create'),
    path('settings/backup/restore/', views.backup_restore, name='backup_restore'),

    # Reports
    path('reports/', views.reports_page, name='reports_page'),
]
