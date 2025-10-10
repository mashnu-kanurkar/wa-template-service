from django.test import TestCase
from wa_templates.template_schemas import validate_payload, PayloadValidationError


class TemplateValidationTests(TestCase):
    def test_invalid_button_missing_fields(self):
        payload = {
            'elementName': 'btn_test',
            'content': 'hi',
            'category': 'MARKETING',
            'vertical': 'Internal',
            'example': 'example',
            'buttons': [
                {'type': 'URL'}  # missing text, url, buttonValue
            ]
        }
        with self.assertRaises(PayloadValidationError) as cm:
            validate_payload('TEXT', payload)
        errs = cm.exception.errors
        self.assertIn('buttons[0]', errs)

    def test_carousel_card_missing_media(self):
        payload = {
            'elementName': 'ca',
            'content': 'hey',
            'category': 'MARKETING',
            'vertical': 'products',
            'example': 'ex',
            'appId': 'app',
            'cards': [
                {'body': 'card without media'}
            ]
        }
        with self.assertRaises(PayloadValidationError) as cm:
            validate_payload('CAROUSEL', payload)
        errs = cm.exception.errors
        self.assertIn('cards[0]', errs)
