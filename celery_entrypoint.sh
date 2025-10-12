#!/bin/sh
set -e

python wait_for_services.py

echo "Starting Celery worker..."
exec celery -A whatsapp_template_service worker -l info