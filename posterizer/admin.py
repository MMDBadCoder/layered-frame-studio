from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html, format_html_join

from .jalali import format_cm, format_jalali, format_toman
from .models import ColorProfile, Order, ProfileLayer, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """Singleton: the shop-wide size limits and pricing."""

    fieldsets = (
        (
            "محدودهٔ اندازهٔ قاب",
            {
                "fields": (("min_width_cm", "max_width_cm"), ("min_height_cm", "max_height_cm")),
                "description": (
                    "کاربر فقط می‌تواند اندازه‌ای در این محدوده انتخاب کند. "
                    "نسبت عرض به ارتفاع همیشه برابر نسبت تصویر اصلی است، بنابراین "
                    "محدودیت ارتفاع به‌طور خودکار محدودهٔ عرض را هم تنگ‌تر می‌کند."
                ),
            },
        ),
        (
            "قیمت‌گذاری",
            {
                "fields": ("price_per_cm2", "cost_rounding", "price_examples"),
                "description": "هزینهٔ برآوردی = مساحت قاب × قیمت هر سانتی‌متر مربع",
            },
        ),
        (None, {"fields": ("updated_at",)}),
    )
    readonly_fields = ("updated_at", "price_examples")

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="نمونهٔ قیمت با تنظیمات فعلی")
    def price_examples(self, obj):
        if not obj or not obj.pk:
            return "—"
        samples = [(20, 30), (30, 40), (50, 70)]
        rows = [
            (f"{w}×{h} سانتی‌متر", f"{w * h} سانتی‌متر مربع", format_toman(obj.estimate_cost(w, h)))
            for w, h in samples
        ]
        return format_html(
            '<table style="border-collapse:collapse">{}</table>',
            format_html_join(
                "",
                '<tr><td style="padding:2px 16px 2px 0">{}</td>'
                '<td style="padding:2px 16px 2px 0;color:#666">{}</td>'
                '<td style="padding:2px 0;font-weight:700">{}</td></tr>',
                rows,
            ),
        )


def _swatches(colors, size: int = 20) -> str:
    """A row of colour chips, used all over the admin."""
    if not colors:
        return format_html('<span style="color:#999">—</span>')
    return format_html(
        '<span style="display:inline-flex;gap:3px;vertical-align:middle">{}</span>',
        format_html_join(
            "",
            '<span title="{}" style="width:{}px;height:{}px;border-radius:4px;'
            'border:1px solid rgba(0,0,0,.25);background:{}"></span>',
            ((color, size, size, color) for color in colors),
        ),
    )


# ------------------------------------------------------- colour profiles ----

class ProfileLayerForm(forms.ModelForm):
    class Meta:
        model = ProfileLayer
        fields = "__all__"
        widgets = {
            # A real colour picker beats typing hex codes by hand.
            "color": forms.TextInput(attrs={"type": "color", "style": "width:70px;height:34px;padding:2px"}),
        }


class ProfileLayerInline(admin.TabularInline):
    model = ProfileLayer
    form = ProfileLayerForm
    extra = 0
    ordering = ("index",)
    verbose_name = "لایه"
    verbose_name_plural = "رنگ لایه‌ها (لایهٔ ۰ تیره‌ترین، آخرین لایه روشن‌ترین)"


@admin.register(ColorProfile)
class ColorProfileAdmin(admin.ModelAdmin):
    inlines = [ProfileLayerInline]
    list_display = ("name", "num_layers", "palette", "is_active", "sort_order", "order_count")
    list_editable = ("is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    fieldsets = (
        (None, {"fields": ("name", "description")}),
        (
            "لایه‌ها",
            {
                "fields": ("num_layers",),
                "description": (
                    "پس از ذخیره، به تعداد لایه‌های تعیین‌شده ردیف رنگ ساخته می‌شود؛ "
                    "سپس رنگ هر لایه را در جدول پایین مشخص کنید."
                ),
            },
        ),
        ("نمایش", {"fields": ("is_active", "sort_order")}),
    )

    @admin.display(description="پالت")
    def palette(self, obj):
        return _swatches(obj.color_list())

    @admin.display(description="سفارش‌ها")
    def order_count(self, obj):
        return obj.orders.count()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Keep the layer rows consistent with num_layers: create what is
        # missing, drop the surplus, close any gaps.
        form.instance.sync_layers()


# ---------------------------------------------------------------- orders ----

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "thumbnail",
        "customer",
        "profile_name",
        "layers",
        "frame_size",
        "cost_column",
        "status",
        "submitted_at",
    )
    list_display_links = ("id", "thumbnail")
    list_editable = ("status",)
    list_filter = ("status", "profile", "created_at")
    search_fields = (
        "id",
        "user__phone",
        "user__email",
        "user__full_name",
        "profile_name",
        "note",
    )
    date_hierarchy = "created_at"
    list_per_page = 25
    actions = ("mark_reviewing", "mark_approved", "mark_rejected")

    readonly_fields = (
        "customer",
        "contact",
        "profile_name",
        "num_layers",
        "palette",
        "result_preview",
        "original_preview",
        "settings_table",
        "note",
        "submitted_at",
        "reviewed_by",
        "reviewed_at",
        "frame_size",
        "area_display",
        "price_breakdown",
    )

    fieldsets = (
        (
            "سفارش",
            {"fields": ("customer", "contact", "submitted_at", "note")},
        ),
        (
            "تصویر",
            {"fields": ("result_preview", "original_preview")},
        ),
        (
            "اندازه و قیمت",
            {
                "fields": ("frame_size", "area_display", "price_breakdown", "final_cost"),
                "description": (
                    "مبلغ برآوردی همان چیزی است که کاربر هنگام ثبت سفارش دیده است. "
                    "برای اعلام مبلغ قطعی، «هزینهٔ نهایی» را پر کنید."
                ),
            },
        ),
        (
            "مشخصات ساخت",
            {"fields": ("profile_name", "num_layers", "palette", "settings_table")},
        ),
        (
            "بررسی",
            {
                "fields": ("status", "admin_note", "reviewed_by", "reviewed_at"),
                "description": "وضعیت سفارش را تغییر دهید و در صورت نیاز یادداشت بگذارید.",
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "profile", "reviewed_by")

    def has_add_permission(self, request):
        # Orders are created from the studio page, never by hand.
        return False

    # --- display helpers ---

    @admin.display(description="تصویر")
    def thumbnail(self, obj):
        if not obj.result_image:
            return "—"
        return format_html(
            '<img src="{}" style="height:56px;width:56px;object-fit:cover;'
            'border-radius:8px;border:1px solid rgba(0,0,0,.2)" />',
            reverse("order_image", args=[obj.pk, "result"]),
        )

    @admin.display(description="کاربر", ordering="user__phone")
    def customer(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:accounts_user_change", args=[obj.user_id]),
            obj.user.display_name,
        )

    @admin.display(description="راه ارتباطی")
    def contact(self, obj):
        return format_html("{}<br><span dir=\"ltr\">{}</span>", obj.user.phone, obj.user.email)

    @admin.display(description="لایه‌ها", ordering="num_layers")
    def layers(self, obj):
        return format_html("{} {}", obj.num_layers, _swatches(obj.colors, size=14))

    @admin.display(description="پالت")
    def palette(self, obj):
        return _swatches(obj.colors, size=28)

    @admin.display(description="اندازهٔ قاب", ordering="area_cm2")
    def frame_size(self, obj):
        if obj.width_cm is None:
            return "—"
        return format_html(
            "{} × {} سانتی‌متر",
            format_cm(obj.width_cm),
            format_cm(obj.height_cm),
        )

    @admin.display(description="مساحت")
    def area_display(self, obj):
        if obj.area_cm2 is None:
            return "—"
        return format_html("{} سانتی‌متر مربع", format_cm(obj.area_cm2))

    @admin.display(description="هزینه", ordering="estimated_cost")
    def cost_column(self, obj):
        if obj.final_cost is not None:
            return format_html(
                '<span style="color:#2e7d32;font-weight:700">{}</span><br>'
                '<span style="color:#999;text-decoration:line-through;font-size:.85em">{}</span>',
                format_toman(obj.final_cost),
                format_toman(obj.estimated_cost),
            )
        return format_html('<span title="برآوردی">{} (برآوردی)</span>', format_toman(obj.estimated_cost))

    @admin.display(description="محاسبهٔ هزینه")
    def price_breakdown(self, obj):
        if obj.estimated_cost is None:
            return "—"
        return format_html(
            "{} × {} = <b>{}</b><br><span style=\"color:#666\">مبلغ برآوردی اعلام‌شده به کاربر</span>",
            format_html("{} سانتی‌متر مربع", format_cm(obj.area_cm2)),
            format_toman(obj.price_per_cm2).replace(" تومان", " تومان بر سانتی‌متر مربع"),
            format_toman(obj.estimated_cost),
        )

    @admin.display(description="تاریخ ثبت", ordering="created_at")
    def submitted_at(self, obj):
        return format_jalali(obj.created_at)

    @admin.display(description="تصویر نهایی")
    def result_preview(self, obj):
        return self._preview(obj, "result", "دانلود تصویر نهایی")

    @admin.display(description="تصویر اصلی")
    def original_preview(self, obj):
        return self._preview(obj, "original", "دانلود تصویر اصلی")

    def _preview(self, obj, kind, label):
        field = obj.result_image if kind == "result" else obj.original_image
        if not obj.pk or not field:
            return "—"
        url = reverse("order_image", args=[obj.pk, kind])
        return format_html(
            '<div><img src="{}" style="max-width:340px;max-height:340px;border-radius:10px;'
            'border:1px solid rgba(0,0,0,.2)" /><br>'
            '<a href="{}" download style="display:inline-block;margin-top:6px">{}</a></div>',
            url,
            url,
            label,
        )

    @admin.display(description="تنظیمات پردازش")
    def settings_table(self, obj):
        labels = {
            "num_levels": "تعداد لایه‌ها",
            "preprocess_method": "روش هموارسازی",
            "gaussian_kernel_size": "اندازه کرنل گاوسی",
            "median_kernel_size": "اندازه کرنل میانه",
            "bilateral_d": "قطر فیلتر دوطرفه",
            "bilateral_sigma_color": "سیگما رنگ",
            "bilateral_sigma_space": "سیگما مکان",
            "postprocess_method": "روش پاک‌سازی",
            "morph_kernel_size": "اندازه کرنل مورفولوژی",
            "min_region_size": "حداقل اندازه ناحیه",
            "preserve_edges": "حفظ لبه‌ها",
            "use_superpixels": "سوپرپیکسل",
            "superpixel_region_size": "اندازه ناحیه سوپرپیکسل",
            "majority_window_size": "اندازه پنجره اکثریت",
        }
        config = obj.config or {}
        if not config:
            return "—"

        rows = []
        for key, label in labels.items():
            if key not in config:
                continue
            value = config[key]
            if isinstance(value, bool):
                value = "بله" if value else "خیر"
            rows.append((label, value))

        return format_html(
            '<table style="border-collapse:collapse">{}</table>',
            format_html_join(
                "",
                '<tr><th style="text-align:right;padding:2px 12px 2px 0;font-weight:600">{}</th>'
                '<td style="padding:2px 0">{}</td></tr>',
                rows,
            ),
        )

    # --- review bookkeeping ---

    def save_model(self, request, obj, form, change):
        if "status" in getattr(form, "changed_data", []):
            obj.mark_reviewed_by(request.user)
        super().save_model(request, obj, form, change)

    def _bulk_status(self, request, queryset, status, label):
        stamped = 0
        for order in queryset:
            order.status = status
            order.mark_reviewed_by(request.user)
            order.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
            stamped += 1
        self.message_user(
            request, f"{stamped} سفارش به «{label}» تغییر کرد.", level=messages.SUCCESS
        )

    @admin.action(description="تغییر وضعیت به «در حال بررسی»")
    def mark_reviewing(self, request, queryset):
        self._bulk_status(request, queryset, Order.STATUS_REVIEWING, "در حال بررسی")

    @admin.action(description="تأیید سفارش‌های انتخاب‌شده")
    def mark_approved(self, request, queryset):
        self._bulk_status(request, queryset, Order.STATUS_APPROVED, "تأیید شده")

    @admin.action(description="رد کردن سفارش‌های انتخاب‌شده")
    def mark_rejected(self, request, queryset):
        self._bulk_status(request, queryset, Order.STATUS_REJECTED, "رد شده")
