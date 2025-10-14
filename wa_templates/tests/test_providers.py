from django.test import TestCase
from unittest.mock import patch
from wa_templates.providers.gupshup import GupshupProvider
from wa_templates.models import Tenant, WhatsAppTemplate


class ProviderTest(TestCase):
    @patch('wa_templates.providers.gupshup.requests.post')
    def test_upload_media_and_submit(self, mock_post):
        t = Tenant.objects.create(name='Acme', slug='acme3')
        tpl = WhatsAppTemplate.objects.create(tenant=t, name='img1', templateType='IMAGE', media_url='https://example.com/sample.jpg', content='hi')

        # mock media upload response
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'mediaId': '1234'}

        p = GupshupProvider(api_key='key', app_id='app')
        resp = p.submit_template(tpl)
        assert tpl.provider_metadata.get('media_id') == '1234'
