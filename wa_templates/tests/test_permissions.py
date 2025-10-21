from django.test import TestCase, Client
from wa_templates.models import Tenant, TenantUser, WhatsAppTemplate
from django.urls import reverse
import jwt
from django.conf import settings


class PermissionTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Acme', slug='acme-1')
        self.other = Tenant.objects.create(name='Other', slug='other')
        self.user = TenantUser.objects.create(tenant=self.tenant, username='joe', user_id='user-1')
        self.client = Client()

    def make_token(self, payload):
        # create unsigned token for tests or sign with a dummy key
        private_key = getattr(settings, 'TEST_JWT_PRIVATE_KEY', None)
        if private_key:
            return jwt.encode(payload, private_key, algorithm='RS256')
        return jwt.encode(payload, 'secret', algorithm='HS256')

    def test_cannot_access_other_tenant(self):
        token = self.make_token({'tenant': self.tenant.slug, 'sub': self.user.user_id})
        headers = {'HTTP_AUTHORIZATION': f'Bearer {token}', 'CONTENT_TYPE': 'application/json'}
        # try to create a template for other tenant
        import json
        data = {'tenant': self.other.id, 'name': 't1', 'templateType': 'TEXT', 'content': 'hi'}
        resp = self.client.post('/api/templates/', json.dumps(data), **headers)
        # should be forbidden (403)
        self.assertEqual(resp.status_code, 403)
