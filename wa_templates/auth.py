import jwt
from rest_framework import authentication, exceptions
from django.conf import settings
from types import SimpleNamespace
import logging

logger = logging.getLogger(__name__)

class JWTAuthentication(authentication.BaseAuthentication):
    """
    Decode JWT from Authorization header and attach a lightweight user object
    containing org_id and external_id.
    """
    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()
        if not auth or auth[0].lower() != b'bearer':
            logger.debug("No Bearer token in Authorization header")
            return None
        if len(auth) == 1:
            raise exceptions.AuthenticationFailed('Invalid token header. No credentials provided.')

        token = auth[1]
        try:
            public_key = settings.JWT_PUBLIC_KEY
            alg = getattr(settings, 'JWT_ALGORITHM', 'RS256')
            payload = jwt.decode(token, public_key, algorithms=[alg], options={'verify_aud': False})
            logger.debug("JWT decoded successfully: %s", payload)
        except Exception as e:
            logger.error("JWT decode failed: %s", e)
            raise exceptions.AuthenticationFailed('Invalid token') from e

        # Extract claims
        org_claim = getattr(settings, 'JWT_ORG_CLAIM', 'org')
        user_claim = getattr(settings, 'JWT_USER_CLAIM', 'sub')

        org_id = payload.get(org_claim) or payload.get('org_id')
        external_id = payload.get(user_claim) or payload.get('sub') or payload.get('user_id')

        if not org_id or not external_id:
            logger.debug("JWT missing org_id or user claim, returning payload without user object")
            return (None, payload)

        # Lightweight user object
        user = SimpleNamespace()
        user.org_id = str(org_id)
        user.external_id = str(external_id)
        user.is_authenticated = True

        logger.debug("Authenticated user set with org_id: %s, external_id: %s", user.org_id, user.external_id)
        return (user, payload)
