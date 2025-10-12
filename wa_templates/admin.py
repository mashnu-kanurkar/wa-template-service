from django.contrib import admin
from .models import WhatsAppTemplate


@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    list_display = ('id', 'org_id', 'template_type', 'status', 'created_at')
