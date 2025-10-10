from django.db import models
try:
    # Django 3.1+
    from django.db.models import JSONField
except Exception:
    from django.contrib.postgres.fields import JSONField



class WhatsAppTemplate(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    TEMPLATE_TYPES = [
        ('TEXT', 'Text'),
        ('IMAGE', 'Image'),
        ('VIDEO', 'Video'),
        ('DOCUMENT', 'Document'),
        ('CAROUSEL', 'Carousel'),
        ('CATALOG', 'Catalog'),
    ]
    # No tenant FK — we rely on external org_id (multi-tenant managed elsewhere)
    name = models.CharField(max_length=200)
    template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPES)
    content = models.TextField(blank=True)
    media_url = models.URLField(blank=True, null=True)
    provider_metadata = JSONField(default=dict, blank=True)
    # structured payload containing template-type-specific fields (buttons, cards, exampleMedia, etc.)
    payload = JSONField(default=dict, blank=True)
    # External tenant/org identifier from upstream identity provider (do not duplicate tenant DB)
    org_id = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.org_id})"
    
