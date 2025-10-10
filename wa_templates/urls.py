from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WhatsAppTemplateViewSet, gupshup_webhook, template_types

router = DefaultRouter()
router.register('templates', WhatsAppTemplateViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('webhooks/gupshup/', gupshup_webhook, name='gupshup_webhook'),
    path('template-types/', template_types, name='template_types'),
]
