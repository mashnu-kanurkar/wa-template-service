# WhatsApp Template Service

This is a Django REST microservice to manage WhatsApp templates with a pluggable provider (Gupshup) and tenant support.

Features:
- Django + DRF
- Celery + Redis for async submissions
- PostgreSQL database (default name: whatsapp_template_db)
- JWT auth with public key verification
- Provider adapters under `wa_templates/providers/`
- Webhook endpoint for provider callbacks

Quick start (development):

1. Create a virtualenv and install requirements

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Set environment variables for DB, Redis and JWT public key

3. Run migrations and start Django and Celery

```powershell
python manage.py migrate
python manage.py runserver
# in another shell
celery -A whatsapp_template_service worker -l info
```

Run tests:

```powershell
python manage.py test
```

Webhooks:
- Configure your provider to call /api/webhooks/gupshup/ with JSON {"template_id": <id>, "status": "approved"}

Provider configuration:
- Set GUPSHUP_API_KEY and GUPSHUP_APP_ID environment variables

Middleware and demo curl
------------------------

This project includes `wa_templates.middleware.InjectOrgMiddleware` which extracts
the tenant/org identifier from the incoming JWT (Authorization: Bearer <token>)
and places it on `request.org_id` for convenient access in views and other
middleware. By default the middleware is tolerant: if the token is missing or
invalid it leaves `request.org_id` as null. You can enable strict behavior by
setting `JWT_ORG_MIDDLEWARE_STRICT=True` in your environment.

Example curl (development):

```powershell
# Replace <dev-token> with a valid JWT from your identity provider that
# contains the tenant claim configured by JWT_TENANT_CLAIM (default 'tenant').
curl -X POST http://127.0.0.1:8000/api/templates/ \
	-H "Authorization: Bearer <dev-token>" \
	-H "Content-Type: application/json" \
	-d '{"name": "promo-1", "templateType": "TEXT", "payload": {"text": "Hello"}}'
```

In views you can read `request.org_id` (set by the middleware) to filter or
default values when creating new templates. If you rely only on DRF auth and
permissions you can still access `request.user.org_id` after authentication.

