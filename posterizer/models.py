import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

HEX_COLOR_VALIDATOR = RegexValidator(
    r"^#(?:[0-9a-fA-F]{6})$",
    "رنگ باید به شکل کد هگز شش‌رقمی باشد. نمونه: #1a2b3c",
)

MIN_LAYERS = 2
MAX_LAYERS = 16


def _grayscale_ramp(count: int) -> list[str]:
    """Evenly spaced black→white hex ramp, used as a safe fallback."""
    if count < 2:
        return ["#000000"]
    steps = [round(i * 255 / (count - 1)) for i in range(count)]
    return ["#{0:02x}{0:02x}{0:02x}".format(value) for value in steps]


def _q1(value) -> Decimal:
    """Round to one decimal place, the precision frame sizes are stored at."""
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


class SiteSettings(models.Model):
    """
    Singleton holding the shop-wide numbers admins tune: the allowed frame
    dimensions and the price used to estimate an order's cost.
    """

    min_width_cm = models.DecimalField(
        "حداقل عرض (سانتی‌متر)", max_digits=6, decimal_places=1, default=Decimal("10.0")
    )
    max_width_cm = models.DecimalField(
        "حداکثر عرض (سانتی‌متر)", max_digits=6, decimal_places=1, default=Decimal("100.0")
    )
    min_height_cm = models.DecimalField(
        "حداقل ارتفاع (سانتی‌متر)", max_digits=6, decimal_places=1, default=Decimal("10.0")
    )
    max_height_cm = models.DecimalField(
        "حداکثر ارتفاع (سانتی‌متر)", max_digits=6, decimal_places=1, default=Decimal("100.0")
    )

    price_per_cm2 = models.PositiveIntegerField(
        "قیمت هر سانتی‌متر مربع (تومان)",
        default=5000,
        help_text="برآورد هزینه = مساحت قاب (سانتی‌متر مربع) × این عدد",
    )
    cost_rounding = models.PositiveIntegerField(
        "گرد کردن مبلغ به (تومان)",
        default=1000,
        validators=[MinValueValidator(1)],
        help_text="مبلغ برآوردی به نزدیک‌ترین مضرب این عدد گرد می‌شود.",
    )

    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    class Meta:
        verbose_name = "تنظیمات فروشگاه"
        verbose_name_plural = "تنظیمات فروشگاه"

    def __str__(self):
        return "تنظیمات فروشگاه"

    def save(self, *args, **kwargs):
        self.pk = 1  # keep it a singleton
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("تنظیمات فروشگاه قابل حذف نیست.")

    @classmethod
    def load(cls) -> "SiteSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def clean(self):
        errors = {}
        if self.min_width_cm > self.max_width_cm:
            errors["min_width_cm"] = "حداقل عرض نمی‌تواند از حداکثر عرض بیشتر باشد."
        if self.min_height_cm > self.max_height_cm:
            errors["min_height_cm"] = "حداقل ارتفاع نمی‌تواند از حداکثر ارتفاع بیشتر باشد."
        if self.min_width_cm <= 0 or self.min_height_cm <= 0:
            errors["min_width_cm"] = "اندازه‌ها باید بزرگ‌تر از صفر باشند."
        if errors:
            raise ValidationError(errors)

    # -- frame sizing -------------------------------------------------------

    def width_bounds_for_ratio(self, ratio) -> tuple:
        """
        The width range that keeps BOTH dimensions inside their limits.

        The frame must keep the photo's aspect ratio, so the height limits
        translate into extra width limits: height = width / ratio.
        Returns (min_width, max_width); min > max means no size fits.
        """
        ratio = Decimal(str(ratio))
        low = max(self.min_width_cm, self.min_height_cm * ratio)
        high = min(self.max_width_cm, self.max_height_cm * ratio)
        return _q1(low), _q1(high)

    def height_for_width(self, width, ratio) -> Decimal:
        return _q1(Decimal(str(width)) / Decimal(str(ratio)))

    def estimate_cost(self, width, height) -> int:
        """Area (cm²) × price per cm², rounded to a tidy number of Toman."""
        area = Decimal(str(width)) * Decimal(str(height))
        raw = area * Decimal(self.price_per_cm2)
        step = Decimal(self.cost_rounding or 1)
        rounded = (raw / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step
        return int(rounded)

    def as_dict(self, ratio=None) -> dict:
        data = {
            "min_width_cm": float(self.min_width_cm),
            "max_width_cm": float(self.max_width_cm),
            "min_height_cm": float(self.min_height_cm),
            "max_height_cm": float(self.max_height_cm),
            "price_per_cm2": self.price_per_cm2,
            "cost_rounding": self.cost_rounding,
        }
        if ratio:
            low, high = self.width_bounds_for_ratio(ratio)
            data["effective_min_width_cm"] = float(low)
            data["effective_max_width_cm"] = float(high)
            data["fits"] = low <= high
        return data


class ColorProfile(models.Model):
    """
    An admin-defined colouring profile.

    Holds the number of layers and the colour of each layer; ordinary users
    pick exactly one of these when building an image.
    """

    name = models.CharField("نام پروفایل", max_length=100, unique=True)
    description = models.CharField("توضیح کوتاه", max_length=200, blank=True)
    num_layers = models.PositiveSmallIntegerField(
        "تعداد لایه‌ها",
        default=4,
        validators=[MinValueValidator(MIN_LAYERS), MaxValueValidator(MAX_LAYERS)],
        help_text=f"عددی بین {MIN_LAYERS} تا {MAX_LAYERS}",
    )
    is_active = models.BooleanField(
        "فعال",
        default=True,
        help_text="پروفایل‌های غیرفعال به کاربران نمایش داده نمی‌شوند.",
    )
    sort_order = models.PositiveSmallIntegerField(
        "ترتیب نمایش", default=0, help_text="عدد کوچک‌تر، بالاتر نمایش داده می‌شود."
    )
    created_at = models.DateTimeField("تاریخ ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین ویرایش", auto_now=True)

    class Meta:
        verbose_name = "پروفایل رنگی"
        verbose_name_plural = "پروفایل‌های رنگی"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.num_layers} لایه)"

    def color_list(self) -> list[str]:
        """
        Exactly `num_layers` colours, darkest first.

        Falls back to a grayscale ramp for any layer an admin has not filled
        in, so a half-configured profile can still render.
        """
        stored = [layer.color for layer in self.layers.all()]
        fallback = _grayscale_ramp(self.num_layers)

        colors = stored[: self.num_layers]
        colors += fallback[len(colors) : self.num_layers]
        return colors

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "num_layers": self.num_layers,
            "colors": self.color_list(),
        }

    def sync_layers(self) -> None:
        """
        Make the stored layers match `num_layers` exactly.

        Called after an admin saves a profile: missing layers are created with a
        grayscale ramp (ready to be recoloured), surplus layers are dropped and
        any gaps in the numbering are closed.
        """
        layers = list(self.layers.order_by("index"))
        ramp = _grayscale_ramp(self.num_layers)

        for layer in layers[self.num_layers:]:
            layer.delete()

        # Compact the numbering to 0..n-1. Walking in ascending order means the
        # index being assigned is always already free.
        for position, layer in enumerate(layers[: self.num_layers]):
            if layer.index != position:
                layer.index = position
                layer.save(update_fields=["index"])

        for position in range(len(layers[: self.num_layers]), self.num_layers):
            ProfileLayer.objects.create(profile=self, index=position, color=ramp[position])


class ProfileLayer(models.Model):
    """One layer of a colouring profile: darkest (index 0) → lightest."""

    profile = models.ForeignKey(
        ColorProfile, on_delete=models.CASCADE, related_name="layers", verbose_name="پروفایل"
    )
    index = models.PositiveSmallIntegerField(
        "شمارهٔ لایه", help_text="از ۰ شروع می‌شود؛ لایهٔ ۰ تیره‌ترین ناحیه است."
    )
    color = models.CharField(
        "رنگ", max_length=7, default="#000000", validators=[HEX_COLOR_VALIDATOR]
    )

    class Meta:
        verbose_name = "لایهٔ رنگی"
        verbose_name_plural = "لایه‌های رنگی"
        ordering = ["index"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "index"], name="unique_layer_index_per_profile")
        ]

    def __str__(self):
        return f"لایهٔ {self.index} — {self.color}"


def _order_upload_path(instance, filename, kind):
    stamp = timezone.now().strftime("%Y/%m")
    return f"orders/{kind}/{stamp}/{uuid.uuid4().hex}.png"


def original_upload_path(instance, filename):
    return _order_upload_path(instance, filename, "originals")


def result_upload_path(instance, filename):
    return _order_upload_path(instance, filename, "results")


class OrderQuerySet(models.QuerySet):
    def unreviewed(self):
        return self.filter(status__in=Order.UNREVIEWED_STATUSES)


class OrderManager(models.Manager.from_queryset(OrderQuerySet)):
    def unreviewed_count(self, user) -> int:
        if not user or not user.is_authenticated:
            return 0
        return self.filter(user=user).unreviewed().count()

    def remaining_slots(self, user) -> int:
        return max(0, Order.MAX_UNREVIEWED - self.unreviewed_count(user))


class Order(models.Model):
    """An image a user built in the studio and submitted for admin review."""

    STATUS_PENDING = "pending"
    STATUS_REVIEWING = "reviewing"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "در انتظار بررسی"),
        (STATUS_REVIEWING, "در حال بررسی"),
        (STATUS_APPROVED, "تأیید شده"),
        (STATUS_REJECTED, "رد شده"),
    ]

    # An order still occupying one of the user's three slots.
    UNREVIEWED_STATUSES = (STATUS_PENDING, STATUS_REVIEWING)
    MAX_UNREVIEWED = 3

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="orders",
        verbose_name="کاربر",
    )
    profile = models.ForeignKey(
        ColorProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="پروفایل رنگی",
    )

    # Snapshots, so an order keeps showing what was actually ordered even if the
    # admin later edits or deletes the profile.
    profile_name = models.CharField("نام پروفایل (ثبت‌شده)", max_length=100, blank=True)
    num_layers = models.PositiveSmallIntegerField("تعداد لایه‌ها", default=0)
    colors = models.JSONField("رنگ لایه‌ها", default=list, blank=True)
    config = models.JSONField("تنظیمات پردازش", default=dict, blank=True)

    # Frame size, kept at the photo's own aspect ratio.
    width_cm = models.DecimalField(
        "عرض قاب (سانتی‌متر)", max_digits=6, decimal_places=1, null=True, blank=True
    )
    height_cm = models.DecimalField(
        "ارتفاع قاب (سانتی‌متر)", max_digits=6, decimal_places=1, null=True, blank=True
    )
    area_cm2 = models.DecimalField(
        "مساحت (سانتی‌متر مربع)", max_digits=10, decimal_places=2, null=True, blank=True
    )

    # Pricing. The estimate is what the customer saw; the final price is what
    # an admin sets after reviewing the order.
    price_per_cm2 = models.PositiveIntegerField(
        "قیمت هر سانتی‌متر مربع هنگام ثبت (تومان)", null=True, blank=True
    )
    estimated_cost = models.PositiveBigIntegerField(
        "هزینهٔ برآوردی (تومان)", null=True, blank=True
    )
    final_cost = models.PositiveBigIntegerField(
        "هزینهٔ نهایی (تومان)",
        null=True,
        blank=True,
        help_text="پس از بررسی، مبلغ قطعی را اینجا وارد کنید. خالی بماند یعنی همان مبلغ برآوردی.",
    )

    original_image = models.FileField(
        "تصویر اصلی", upload_to=original_upload_path, blank=True
    )
    result_image = models.FileField("تصویر نهایی", upload_to=result_upload_path)

    note = models.TextField("توضیحات کاربر", blank=True)

    status = models.CharField(
        "وضعیت", max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    admin_note = models.TextField("یادداشت مدیر", blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_orders",
        verbose_name="بررسی‌کننده",
    )
    reviewed_at = models.DateTimeField("تاریخ بررسی", null=True, blank=True)

    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    objects = OrderManager()

    class Meta:
        verbose_name = "سفارش"
        verbose_name_plural = "سفارش‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"سفارش #{self.pk} — {self.user}"

    @property
    def is_unreviewed(self) -> bool:
        return self.status in self.UNREVIEWED_STATUSES

    @property
    def payable_cost(self):
        """What the customer actually owes: the admin's price, else the estimate."""
        return self.final_cost if self.final_cost is not None else self.estimated_cost

    @property
    def cost_is_final(self) -> bool:
        return self.final_cost is not None

    @property
    def size_label(self) -> str:
        if self.width_cm is None or self.height_cm is None:
            return "—"
        return f"{self.width_cm:g} × {self.height_cm:g} سانتی‌متر"

    @property
    def status_color(self) -> str:
        return {
            self.STATUS_PENDING: "#f0b429",
            self.STATUS_REVIEWING: "#6c8cff",
            self.STATUS_APPROVED: "#4ade80",
            self.STATUS_REJECTED: "#f87171",
        }.get(self.status, "#9898a8")

    def mark_reviewed_by(self, user) -> None:
        """Stamp who reviewed the order when it leaves the unreviewed states."""
        if not self.is_unreviewed:
            self.reviewed_by = user
            self.reviewed_at = timezone.now()
        else:
            self.reviewed_by = None
            self.reviewed_at = None
