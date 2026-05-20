"""
Accounts — Authentication Backend
===================================
PRD Section 6.1.2: Login via phone_number + password.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class PhoneAuthBackend(ModelBackend):
    """
    Authenticate users by phone number instead of username.
    PRD Section 6.1.2: Login via phone number + password.
    """

    def authenticate(self, request, phone_number=None, password=None, **kwargs):
        if phone_number is None or password is None:
            return None

        try:
            user = User.objects.get(phone_number=phone_number)
        except User.DoesNotExist:
            # Run the password hasher to prevent timing attacks
            # (PRD: identical error messages regardless of existence)
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
