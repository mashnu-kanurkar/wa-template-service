from django.test import RequestFactory, override_settings, SimpleTestCase
from wa_templates.middleware import InjectOrgMiddleware
from unittest.mock import patch


class InjectOrgMiddlewareTests(SimpleTestCase):
    def test_middleware_tolerant_no_auth_header(self):
        rf = RequestFactory()
        request = rf.get('/api/templates/')
        mw = InjectOrgMiddleware(get_response=lambda r: None)
        resp = mw.process_request(request)
        self.assertIsNone(resp)
        self.assertIsNone(getattr(request, 'org_id', None))

    def test_middleware_tolerant_invalid_token(self):
        rf = RequestFactory()
        request = rf.get('/api/templates/', HTTP_AUTHORIZATION='Bearer bad.token.here')
        mw = InjectOrgMiddleware(get_response=lambda r: None)

        # Patch _decode_token to raise to simulate invalid token
        with patch.object(InjectOrgMiddleware, '_decode_token', side_effect=Exception('invalid')):
            resp = mw.process_request(request)
        self.assertIsNone(resp)
        self.assertIsNone(getattr(request, 'org_id', None))

    @override_settings(JWT_ORG_MIDDLEWARE_STRICT=True)
    def test_middleware_strict_invalid_token(self):
        rf = RequestFactory()
        request = rf.get('/api/templates/', HTTP_AUTHORIZATION='Bearer bad.token.here')
        mw = InjectOrgMiddleware(get_response=lambda r: None)
        with patch.object(InjectOrgMiddleware, '_decode_token', side_effect=Exception('invalid')):
            resp = mw.process_request(request)
        self.assertIsNotNone(resp)
        self.assertEqual(getattr(resp, 'status_code', None), 401)
