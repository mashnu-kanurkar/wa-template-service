#!/bin/sh
set -e

python wait_for_services.py

echo "Creating and running migrations..."
# 💡 Add this line to create the initial migration file for wa_templates
python manage.py makemigrations wa_templates --noinput
python manage.py migrate --noinput

echo "Starting Django server..."
exec python manage.py runserver 0.0.0.0:8000