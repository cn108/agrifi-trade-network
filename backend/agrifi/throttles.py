import hashlib

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class _SettingsRateThrottle(SimpleRateThrottle):
    """Reads the rate from settings.AGRIFI_THROTTLE_RATES on every request, so deployments
    and tests can change it without re-importing DRF. A missing or empty rate disables the
    throttle."""

    scope = None

    def get_rate(self):
        return settings.AGRIFI_THROTTLE_RATES.get(self.scope) or None


class AnonymousAuthThrottle(_SettingsRateThrottle):
    """Per-client-address limit on credential endpoints (login, register, refresh)."""

    scope = 'auth_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginEmailThrottle(_SettingsRateThrottle):
    """Per-account limit on login attempts, so a distributed guesser cannot hammer one
    account. The email is hashed so the cache never stores it."""

    scope = 'login_email'

    def get_cache_key(self, request, view):
        email = str(request.data.get('email', '')).strip().lower() if hasattr(request, 'data') else ''
        if not email:
            return None
        digest = hashlib.sha256(email.encode()).hexdigest()
        return self.cache_format % {'scope': self.scope, 'ident': digest}
