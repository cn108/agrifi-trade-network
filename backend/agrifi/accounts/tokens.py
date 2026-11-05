from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken, Token
from rest_framework_simplejwt.utils import datetime_from_epoch

from .models import RevokedRefreshToken


class RevocableRefreshToken(RefreshToken):
    @classmethod
    def for_user(cls, user):
        return Token.for_user.__func__(cls, user)

    def verify(self):
        super().verify()
        self.check_blacklist()

    def check_blacklist(self):
        jti = self.payload[api_settings.JTI_CLAIM]
        if RevokedRefreshToken.objects.filter(jti=jti).exists():
            raise TokenError('Token is revoked.')

    def blacklist(self):
        user_id = self.payload.get(api_settings.USER_ID_CLAIM)
        user = get_user_model().objects.filter(
            **{api_settings.USER_ID_FIELD: user_id},
        ).first()
        if user is None:
            raise TokenError('Token user no longer exists.')
        revoked, created = RevokedRefreshToken.objects.get_or_create(
            jti=self.payload[api_settings.JTI_CLAIM],
            defaults={
                'user': user,
                'expires_at': datetime_from_epoch(self.payload['exp']),
            },
        )
        if not created:
            raise TokenError('Token has already been used or revoked.')
        return revoked

    def outstand(self):
        return None
