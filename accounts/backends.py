from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.db.models import Q

from .validators import normalize_digits, normalize_phone

UserModel = get_user_model()


class PhoneOrEmailBackend(ModelBackend):
    """
    Authenticate against either the phone number or the email address.

    People remember one or the other, so the sign-in form accepts a single
    "identifier" field and this backend works out which one it is.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = username or kwargs.get("phone") or kwargs.get("email")
        if identifier is None or password is None:
            return None

        identifier = normalize_digits(str(identifier)).strip()

        lookup = Q(email__iexact=identifier)
        try:
            lookup |= Q(phone=normalize_phone(identifier))
        except ValidationError:
            # Not phone-shaped, so email is the only possibility.
            pass

        try:
            user = UserModel.objects.get(lookup)
        except UserModel.DoesNotExist:
            # Run the default hasher once anyway so that a missing account and a
            # wrong password take the same amount of time.
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            user = UserModel.objects.filter(lookup).order_by("id").first()

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
