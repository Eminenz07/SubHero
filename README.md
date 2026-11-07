# SubHero

SubHero is a comprehensive Django-based application designed to manage various financial and marketing services. It includes modules for user accounts, wallet management, payments, virtual top-up (VTU), social media marketing (SMM), transactions, and notifications.

## Table of Contents

- [Project Structure](#project-structure)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Hosting and Deployment](#hosting-and-deployment)
- [Setup and Installation](#setup-and-installation)
- [Contribution Guidelines](#contribution-guidelines)

## Project Structure

The project follows a modular Django architecture with the following key components:

```
subhero/
├── config/
│   ├── settings/
│   │   └── __init__.py
│   ├── wsgi.py
│   └── asgi.py
├── apps/
│   ├── core/
│   ├── accounts/
│   ├── wallet/
│   ├── payments/
│   ├── vtu/
│   ├── smm/
│   ├── transactions/
│   └── notifications/
├── static/
│   └── js/
│       └── pin-input.js
├── requirements/
│   ├── development.txt
│   └── production.txt
├── manage.py
└── package.json
```

## Key Features

1. **User Accounts**: Comprehensive user management with authentication and authorization.
2. **Wallet Management**: Secure handling of user wallets and transactions.
3. **Payments**: Integration with payment gateways for secure transactions.
4. **Virtual Top-Up (VTU)**: Services for airtime and data top-up.
5. **Social Media Marketing (SMM)**: Tools for managing social media accounts and campaigns.
6. **Transactions**: Detailed records of all financial transactions.
7. **Notifications**: Real-time notifications for users.

## Architecture

SubHero is built using Django, a high-level Python web framework, and follows the Model-View-Template (MVT) architectural pattern. The application is structured into multiple Django apps, each handling a specific domain of functionality. This modular approach ensures that the codebase is maintainable and scalable.

## Hosting and Deployment

SubHero is hosted on a Contabo VPS with the domain subhero.com.ng. Cloudflare is used as a proxy to handle the domain and provide additional security features. Cloudflare also manages the POP (Point of Presence) and handles email routing for the application.

### Deployment Details

1. **VPS Configuration**:
   - **Provider**: Contabo
   - **Domain**: subhero.com.ng
   - **Proxy**: Cloudflare

2. **Email Routing**:
   - Cloudflare handles the POP (Point of Presence) and manages email routing for the application.

3. **Deployment Steps**:
   - The application is deployed on a Contabo VPS.
   - Cloudflare is configured as a proxy to handle the domain and provide additional security features.
   - Email routing is managed by Cloudflare.

### Manual Deploy

GitHub Actions does not run reliably for this repo, so the VPS is updated by hand.
On the VPS (`/home/subhero_admin/SubHero`):

```bash
git fetch --prune origin main
git reset --hard origin/main
git clean -fd -e .env -e config/local_settings.py
docker compose up -d --build --remove-orphans web
```

`start.sh` runs the migrations when the container starts. Watch the boot with
`docker logs -f subhero_web`.

### VTU Providers

Outbound data and airtime purchases go through a provider chain, configured with
`VTU_PROVIDER_ORDER`. The first provider that can deliver serves the order; the
rest are fallbacks. A purchase that fails with an unclear outcome is checked
with the provider before the next one is tried, so an order is never delivered
twice.

```env
VTU_PROVIDER_ORDER=gsubz,dancity

GSUBZ_API_KEY=
GSUBZ_BASE_URL=https://api.gsubz.com
GSUBZ_WEBHOOK_SECRET=
GSUBZ_TIMEOUT=60

DANCITY_API_KEY=
DANCITY_BASE_URL=https://api.dancity.app
DANCITY_WEBHOOK_SECRET=
DANCITY_TIMEOUT=30
```

Each provider has its own plan identifiers. `VTUPlan.provider_plan_ids` stores
the id each provider uses for the same bundle, so the same plan can be bought
from either provider.

Provider webhooks:

- GSUBZ: `https://subhero.com.ng/vtu/webhooks/gsubz/` — signed with
  `sha256=` + HMAC-SHA256 of `timestamp + "." + raw body`.
- Dancity: `https://subhero.com.ng/vtu/webhooks/dancity/` — signed with
  HMAC-SHA256 of the raw body.

The plan catalogue is synced by the `sync_vtu_plans` Celery task. To run it by
hand:

```bash
docker compose exec web python manage.py shell -c "from apps.vtu.tasks import sync_vtu_plans; sync_vtu_plans()"
```


## Setup and Installation

### Prerequisites

- Python 3.8 or higher
- Node.js and npm
- Virtual environment (venv)
- PostgreSQL or any other preferred database

### Installation Steps

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-repository/subhero.git
   cd subhero
   ```

2. **Set Up Virtual Environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements/development.txt
   npm install
   ```

4. **Configure Environment Variables**:
   - Create a `.env` file in the root directory and add the necessary environment variables.

5. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Run the Development Server**:
   ```bash
   python manage.py runserver
   ```

## Contribution Guidelines

This project is private and contributions are not required at this time.
