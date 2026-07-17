# AlCaptinMS - Business Management System

## The Problem
Many small to medium-sized businesses struggle with tracking their daily operations effectively. Managing inventory with accurate costing (like FIFO), keeping up with supplier purchases, recording customer sales, tracking daily expenses, and handling service transactions can quickly become overwhelming. More importantly, managing complex installment sales—including down payments, monthly collections, and guarantor tracking—often leads to data loss, inaccurate profit calculations, and difficulties in collecting payments on time when relying on manual paper records or disjointed spreadsheets.

## The Solution
AlCaptinMS is a comprehensive, local Business Management System designed to solve these exact problems. Built as a local web application, it provides an intuitive interface to handle everything from basic inventory and stock alerts to sophisticated FIFO (First-In, First-Out) cost calculations. It centralizes sales, purchases, services, expenses, and installment sales into one unified, secure, and easy-to-use platform, ensuring you always know the exact financial health of your business.

## Features
- **Inventory & Stock Management**: Track products, categories, and stock levels. Includes automatic low-stock alerts to ensure you never run out of critical items.
- **Advanced Costing (FIFO)**: Accurately calculates the Cost of Goods Sold (COGS) and net profit using the First-In, First-Out method for purchase batches.
- **Purchase & Sales Invoices**: Easily create and manage purchases from suppliers and sales to customers, with automatic total and profit calculations per invoice.
- **Installment Sales Management**: A dedicated, robust module for handling installment sales. Track down payments, calculate equal monthly installments, record detailed customer and guarantor information (including national ID numbers), and easily monitor paid vs. remaining amounts.
- **Service Transactions**: Manage various business services with customizable employee/agent commission structures (fixed amount or percentage).
- **Expense Tracking**: Categorize and record daily business expenses to maintain an accurate ledger.
- **Local & Secure**: A locally hosted application ensuring your business data remains entirely private, accessible only on your local machine or network.

## Tech Stack
- **Backend Framework**: Django (Python)
- **Database**: SQLite (Local database, easy to back up, requires zero configuration)
- **Architecture**: MVT (Model-View-Template)

## Getting Started

### Prerequisites
- Python 3.8 or higher installed on your system.

### Installation & Setup

1. **Clone the repository or extract the project files into your desired directory.**

2. **Open a terminal (Command Prompt or PowerShell) and navigate into the project root directory:**
   ```bash
   cd path/to/AlCaptinMS
   ```

3. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   ```

4. **Activate the virtual environment:**
   - On Windows:
     ```bash
     venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source venv/bin/activate
     ```

5. **Install the required dependencies:**
   ```bash
   pip install django
   # If a requirements.txt is provided, run: pip install -r requirements.txt
   ```

6. **Navigate to the inner project directory where `manage.py` is located:**
   ```bash
   cd AlCaptinMS
   ```

7. **Apply database migrations to set up the SQLite database:**
   ```bash
   python manage.py migrate
   ```

8. **Create a superuser to access the admin panel and the main system:**
   ```bash
   python manage.py createsuperuser
   ```
   Follow the prompts to enter a username, email (optional), and password.

9. **Run the local development server:**
   ```bash
   python manage.py runserver
   ```

10. **Access the application:**
    Open your web browser and navigate to `http://127.0.0.1:8000/`. You can log in using the superuser credentials you just created.

---
