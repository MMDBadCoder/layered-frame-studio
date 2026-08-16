from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.db.models import Count, Q
from django.utils.html import format_html

from posterizer.models import Order

from .models import User

try:  # Django >= 5.1 ships an admin-specific creation form.
    from django.contrib.auth.forms import AdminUserCreationForm as _BaseCreationForm
except ImportError:  # pragma: no cover - older Django
    from django.contrib.auth.forms import UserCreationForm as _BaseCreationForm


class UserCreationForm(_BaseCreationForm):
    class Meta:
        model = User
        fields = ("phone", "email", "full_name")


class UserUpdateForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserUpdateForm
    model = User

    list_display = ("phone", "email", "full_name", "role_badge", "order_count", "is_active", "date_joined")
    list_filter = ("is_staff", "is_active", "date_joined")
    search_fields = ("phone", "email", "full_name")
    ordering = ("-date_joined",)
    readonly_fields = ("last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("phone", "email", "password")}),
        ("اطلاعات شخصی", {"fields": ("full_name",)}),
        (
            "دسترسی‌ها",
            {
                "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
                "description": "«مدیر» یعنی کاربر می‌تواند وارد پنل مدیریت شود.",
            },
        ),
        ("تاریخ‌های مهم", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "email", "full_name", "password1", "password2"),
            },
        ),
        ("دسترسی‌ها", {"classes": ("wide",), "fields": ("is_active", "is_staff")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _order_count=Count("orders", distinct=True),
            _unreviewed_count=Count(
                "orders",
                filter=Q(orders__status__in=Order.UNREVIEWED_STATUSES),
                distinct=True,
            ),
        )

    @admin.display(description="نقش", ordering="is_staff")
    def role_badge(self, obj):
        color = "#6c8cff" if obj.is_staff else "#9898a8"
        return format_html(
            '<span style="color:{};font-weight:700">{}</span>', color, obj.role_label
        )

    @admin.display(description="سفارش‌ها", ordering="_order_count")
    def order_count(self, obj):
        return format_html(
            "{} (بررسی‌نشده: {})", obj._order_count, obj._unreviewed_count
        )
