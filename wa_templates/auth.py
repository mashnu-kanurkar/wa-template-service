import jwt
from rest_framework import authentication, exceptions, permissions
from django.conf import settings
from types import SimpleNamespace


class JWTAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        auth = authentication.get_authorization_header(request).split()
        if not auth or auth[0].lower() != b'bearer':
            return None
        if len(auth) == 1:
            raise exceptions.AuthenticationFailed('Invalid token header. No credentials provided.')
        token = auth[1]
        try:
            public_key = settings.JWT_PUBLIC_KEY
            alg = getattr(settings, 'JWT_ALGORITHM', 'RS256')
            payload = jwt.decode(token, public_key, algorithms=[alg], options={'verify_aud': False})
        except Exception as e:
            raise exceptions.AuthenticationFailed('Invalid token') from e
        # Resolve claim names from settings to support different identity providers
        tenant_claim = getattr(settings, 'JWT_TENANT_CLAIM', 'tenant')
        user_claim = getattr(settings, 'JWT_USER_CLAIM', 'sub')
        # Backwards-compatible fallback alternatives
        tenant_key = payload.get(tenant_claim) or payload.get('tenant') or payload.get('tenant_id') or payload.get('org')
        external_user_id = payload.get(user_claim) or payload.get('sub') or payload.get('user_id') or payload.get('uid')
        if not tenant_key or not external_user_id:
            # still return payload but no authenticated user
            return (None, payload)

        # Return a lightweight user-like object containing org_id and external id
        user = SimpleNamespace()
        user.org_id = str(tenant_key)
        user.external_id = str(external_user_id)
        user.is_authenticated = True
        return (user, payload)


class IsTenantMember(permissions.BasePermission):
    """Allow access only to users belonging to the requested tenant."""

    def has_permission(self, request, view):
        # Determine org requested by the caller. For unsafe methods prefer body, otherwise query param.
        org_param = None
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            org_param = request.data.get('org_id') if hasattr(request, 'data') else None
        if not org_param:
            org_param = request.query_params.get('org_id') or request.query_params.get('tenant')

        # If no org provided, allow (endpoint may be global)
        if not org_param:
            return True

        user = getattr(request, 'user', None)
        # Deny if unauthenticated
        if not user:
            return False

        try:
            return str(user.org_id) == str(org_param)
        except Exception:
            return False

