from django.test import TestCase
from wa_templates.serializers import WhatsAppTemplateSerializer
from wa_templates.models import Tenant


class SerializerTest(TestCase):
    def test_text_requires_content(self):
        t = Tenant.objects.create(name='Acme', slug='acme2')
        data = {'tenant': t.id, 'name': 'no-content', 'templateType': 'TEXT'}
        s = WhatsAppTemplateSerializer(data=data)
        self.assertFalse(s.is_valid())
