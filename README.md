# AutoFlow Backend

Production-ready Django backend for the AutoFlow Chrome extension.
Handles user accounts, email-verified auth, free/pro plan logic, daily usage limits,
reward credits, and future Whop integration.

## Tech Stack

- **Python 3.12+** / **Django 5.1** / **Django REST Framework**
- **PostgreSQL** (production) / **SQLite** (local dev)
- **Simple JWT** for authentication
- **Docker + docker-compose**

## Quick Start (Local Development)

```bash
cd backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate         # Windows
# source venv/bin/activate    # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Copy environment file
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux

# Run migrations (uses SQLite locally)
python manage.py migrate

# Create superuser for admin
python manage.py createsuperuser

# Run the dev server
python manage.py runserver
```

Server runs at `http://localhost:8000`.
Admin panel at `http://localhost:8000/admin/`.

## Docker Usage

```bash
cd backend
copy .env.example .env        # Edit .env with your production values

docker-compose up --build
```

This starts PostgreSQL + Django on port 8000.

## Environment Variables

| Variable                          | Description                     | Default                              |
| --------------------------------- | ------------------------------- | ------------------------------------ |
| `SECRET_KEY`                      | Django secret key               | `insecure-dev-key`                   |
| `DEBUG`                           | Debug mode                      | `False`                              |
| `ALLOWED_HOSTS`                   | Comma-separated hosts           | `localhost,127.0.0.1`                |
| `DB_NAME/USER/PASSWORD/HOST/PORT` | PostgreSQL config               | `autoflow`                           |
| `CORS_ALLOWED_ORIGINS`            | Allowed CORS origins            | `http://localhost:3000`              |
| `VERIFY_EMAIL_BASE_URL`           | Base URL for email verify links | `http://localhost:3000/verify-email` |
| `VERIFICATION_TOKEN_EXPIRY_HOURS` | Token expiry                    | `24`                                 |
| `FREE_DAILY_PROMPT_LIMIT`         | Free tier daily limit           | `30`                                 |
| `WHOP_WEBHOOK_SECRET`             | Whop webhook verification       | ``                                   |
| `EMAIL_BACKEND`                   | Django email backend            | `console` (dev)                      |

## Run Tests

```bash
python manage.py test apps.api --verbosity=2
```

Tests cover: registration, email verification, login, entitlements,
usage consumption (free/reward/pro), reward idempotency, API endpoints, webhooks.

## How Email Verification Works

1. User calls `POST /api/auth/register` with email + password
2. Backend creates inactive user + profile + verification token
3. Backend sends email with link: `{VERIFY_EMAIL_BASE_URL}?token=XYZ`
4. User clicks link → frontend calls `GET /api/auth/verify-email?token=XYZ`
5. Backend activates user, marks token used
6. User can now login via `POST /api/auth/login`

In local dev, verification emails print to the console.

## Chrome Extension Authentication

The extension should:

1. **Register**: `POST /api/auth/register` → user verifies email
2. **Login**: `POST /api/auth/login` → receive `access` + `refresh` tokens
3. **Store tokens** in `chrome.storage.local`
4. **Attach token** to all API calls: `Authorization: Bearer <access_token>`
5. **Refresh** when access token expires: `POST /api/auth/refresh`

## How Extension Should Call Entitlements + Consume

**Before running a queue:**

```
GET /api/entitlements
→ Check can_run_prompt === true
→ Display free_remaining_today to user
```

**For each prompt consumed:**

```
POST /api/usage/consume
→ If allowed === true → proceed
→ If allowed === false → show limit message to user
```

**Log telemetry events:**

```
POST /api/usage/events
{ "event_type": "queue_started", "prompt_count": 5 }
```

## API Endpoints

| Method | URL                             | Auth   | Description           |
| ------ | ------------------------------- | ------ | --------------------- |
| POST   | `/api/auth/register`            | Public | Create account        |
| POST   | `/api/auth/login`               | Public | Get JWT tokens        |
| POST   | `/api/auth/refresh`             | Public | Refresh JWT           |
| GET    | `/api/auth/me`                  | JWT    | Current user info     |
| GET    | `/api/auth/verify-email?token=` | Public | Verify email          |
| POST   | `/api/auth/resend-verification` | Public | Resend verification   |
| GET    | `/api/entitlements`             | JWT    | Plan + usage snapshot |
| POST   | `/api/usage/consume`            | JWT    | Consume 1 prompt      |
| POST   | `/api/usage/events`             | JWT    | Log telemetry         |
| POST   | `/api/rewards/grant`            | Admin  | Grant reward credits  |
| POST   | `/api/webhooks/whop`            | Public | Whop webhook          |
| GET    | `/api/health`                   | Public | Health check          |

## Whop Webhook Integration (Future)

1. In Whop dashboard, set webhook URL to `https://yourdomain.com/api/webhooks/whop`
2. Set `WHOP_WEBHOOK_SECRET` in .env
3. Backend handles `membership.went_valid` → activates Pro
4. Backend handles `membership.went_invalid` / `membership.cancelled` → deactivates Pro
5. All raw events are stored in `WebhookEvent` for audit

## What's Implemented vs Future

| Feature                                | Status                         |
| -------------------------------------- | ------------------------------ |
| User registration + email verification | ✅ Done                        |
| JWT auth (access + refresh)            | ✅ Done                        |
| Free/Pro plan logic                    | ✅ Done                        |
| Daily usage limits (30/day free)       | ✅ Done                        |
| Atomic prompt consumption              | ✅ Done                        |
| Reward credit ledger                   | ✅ Done (schema + services)    |
| Reward credit granting (idempotent)    | ✅ Done                        |
| Entitlement snapshot API               | ✅ Done                        |
| Usage event logging                    | ✅ Done                        |
| Django admin (full support panel)      | ✅ Done                        |
| Whop webhook handler                   | ✅ Starter (extend as needed)  |
| Whop signature verification            | 🔜 Placeholder                 |
| Rewarded ad integration                | 🔜 Schema ready                |
| Account dashboard frontend             | 🔜 API ready                   |
| Rate limiting                          | ✅ Configured (DRF throttling) |
