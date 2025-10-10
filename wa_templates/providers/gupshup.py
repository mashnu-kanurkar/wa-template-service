import requests
from .base import BaseProvider
from django.conf import settings
import time


class GupshupProvider(BaseProvider):
    BASE = 'https://partner.gupshup.io'

    def __init__(self, api_key=None, app_id=None):
        self.api_key = api_key or settings.GUPSHUP_API_KEY
        self.app_id = app_id or settings.GUPSHUP_APP_ID

    def headers(self):
        return {
            'Authorization': f'apikey {self.api_key}',
            "Accept": "application/json",
            'Content-Type': 'application/x-www-form-urlencoded'
        }

    def upload_media(self, template):
        if not template.media_url:
            return None
        url = f"{self.BASE}/partner/app/{self.app_id}/media"
        data = {'mediaUrl': template.media_url}
        for attempt in range(3):
            r = requests.post(url, headers=self.headers(), data=data, timeout=10)
            if r.status_code in (200, 201):
                return r.json()
            time.sleep(1 + attempt)
        r.raise_for_status()

    def submit_template(self, template):
        # If there's media, upload first
        provider_resp = {}
        if template.media_url:
            upload = self.upload_media(template)
            if upload:
                provider_resp['media'] = upload
                media_id = upload.get('mediaId') or upload.get('id')
                template.provider_metadata['media_id'] = media_id
                template.save()

        url = f"{self.BASE}/partner/app/{self.app_id}/template/{template.template_type.lower()}"
        payload = {
            'elementName': template.name,
            'languageCode': 'en',
            'content': template.content,
            'category': 'MARKETING',
            'templateType': template.template_type,
        }
        # Handle more fields based on type
        r = requests.post(url, headers=self.headers(), data=payload, timeout=10)
        provider_resp['submit'] = {'status_code': r.status_code, 'body': r.text}
        if r.status_code in (200, 201):
            return {'ok': True, 'response': r.json()}
        return {'ok': False, 'response': r.text}
