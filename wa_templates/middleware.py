import logging
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
import jwt

logger = logging.getLogger(__name__)


class InjectOrgMiddleware(MiddlewareMixin):
    """
    Decode JWT from Authorization header (Bearer <token>) and attach org id
    to request.org_id and optional request.external_user_id.

    Behavior:
    - Tolerant by default: if token is missing/invalid or claim absent, set
      request.org_id = None and continue. This avoids breaking public endpoints.
    - When setting JWT_ORG_MIDDLEWARE_STRICT = True in settings, the middleware
      will return a 401 response for missing/invalid tokens when an
      Authorization header is present.
    """

    def _decode_token(self, token):
        logger.debug('Decoding token')
        public_key = getattr(settings, "JWT_PUBLIC_KEY", None)
        alg = getattr(settings, 'JWT_ALGORITHM', 'RS256')
        if not public_key:
            logger.debug('No public key configured for JWT verification')
            # Nothing to verify against — treat as no payload.
            return None
        return jwt.decode(token, public_key, algorithms=[alg], options={"verify_aud": False})

    def process_request(self, request):
        # Default attributes
        request.org_id = None
        request.external_user_id = None

        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth:
            logger.debug('No Authorization header present, request.org_id remains None')
            return None

        parts = auth.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            # malformed header — don't block unless strict mode and header is present
            logger.debug('Malformed Authorization header, will fail in strict mode')
            if getattr(settings, 'JWT_ORG_MIDDLEWARE_STRICT', False):
                from django.http import HttpResponse
                return HttpResponse('Invalid Authorization header', status=401)
            return None

        token = parts[1]

        try:
            payload = self._decode_token(token)
        except Exception as exc:
            logger.debug('JWT decode failed in InjectOrgMiddleware: %s', exc)
            if getattr(settings, 'JWT_ORG_MIDDLEWARE_STRICT', False):
                from django.http import HttpResponse
                return HttpResponse('Invalid token', status=401)
            return None

        if not payload:
            logger.debug('No payload extracted from token, request.org_id remains None')
            return None

        org_claim = getattr(settings, 'JWT_ORG_CLAIM', 'org')
        user_claim = getattr(settings, 'JWT_USER_CLAIM', 'sub')

        org_val = payload.get(org_claim) or payload.get('org_id')
        if org_val:
            request.org_id = str(org_val)

        user_val = payload.get(user_claim) or payload.get('sub') or payload.get('user_id')
        if user_val:
            request.external_user_id = str(user_val)
        
        logger.debug('Request org_id set to %s, external_user_id set to %s', request.org_id, request.external_user_id)
        return None
