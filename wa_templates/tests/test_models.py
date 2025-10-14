from django.test import TestCase
from wa_templates.models import Tenant, WhatsAppTemplate


class ModelsTest(TestCase):
    def test_create_template(self):
        t = Tenant.objects.create(name='Acme', slug='acme')
        tpl = WhatsAppTemplate.objects.create(tenant=t, name='otp', templateType='TEXT', content='your otp is {{1}}')
        self.assertEqual(tpl.status, 'draft')
