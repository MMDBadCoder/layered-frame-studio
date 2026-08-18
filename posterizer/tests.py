import io
import shutil
import struct
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

import numpy as np
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image

from .models import ColorProfile, Order, SiteSettings
from .stl import build_mesh, layer_index_map, mesh_is_closed, resolve_saddles

User = get_user_model()

TEMP_MEDIA = tempfile.mkdtemp(prefix="pf-test-media-")


def make_image_bytes(size=(120, 90)) -> bytes:
    """A small gradient image, enough to exercise the whole pipeline."""
    width, height = size
    gradient = np.tile(np.linspace(0, 255, width, dtype=np.uint8), (height, 1))
    out = io.BytesIO()
    Image.fromarray(gradient, mode="L").convert("RGB").save(out, format="PNG")
    return out.getvalue()


def upload(name="test.png"):
    return SimpleUploadedFile(name, make_image_bytes(), content_type="image/png")


def decode_data_url(url: str) -> Image.Image:
    import base64

    payload = url.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(payload)))


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class StudioTestCase(TestCase):
    """Base class that keeps uploads and media out of the real project dirs."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.uploads = Path(tempfile.mkdtemp(prefix="pf-test-uploads-"))
        patcher = mock.patch("posterizer.views.UPLOAD_DIR", self.uploads)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.uploads, ignore_errors=True)

        self.profile = ColorProfile.objects.filter(is_active=True).first()

    def make_user(self, phone="09121112233", email="user@example.com", password="TestPass!234"):
        return User.objects.create_user(phone=phone, email=email, password=password)

    def render_image(self, client=None):
        """Upload + process, returning the JSON payload."""
        client = client or self.client
        response = client.post(
            "/api/process",
            {"profile_id": self.profile.id, "image": upload(), "postprocess_method": "none"},
        )
        self.assertEqual(response.status_code, 200, response.content[:400])
        return response.json()


class PublicStudioTests(StudioTestCase):
    def test_home_page_is_open_to_anonymous_visitors(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('lang="fa"', html)
        self.assertIn('dir="rtl"', html)
        self.assertIn("ثبت سفارش", html)
        self.assertIn(self.profile.name, html)

        # The auth modal ships with the page but stays closed: an anonymous
        # visitor is never blocked from uploading and rendering.
        self.assertIn('id="authModal"', html)
        self.assertIn('class="modal-backdrop hidden" id="authModal"', html)
        self.assertIn('"openLogin": false', html)

        # Template comments must not leak into the response.
        self.assertNotIn("{#", html)
        self.assertNotIn("{%", html)

    def test_seed_profiles_exist(self):
        self.assertGreaterEqual(ColorProfile.objects.filter(is_active=True).count(), 3)
        for profile in ColorProfile.objects.all():
            self.assertEqual(len(profile.color_list()), profile.num_layers)

    def test_anonymous_can_render_an_image(self):
        data = self.render_image()
        self.assertIn("result_url", data)
        self.assertEqual(data["profile"]["id"], self.profile.id)
        self.assertEqual(data["config"]["num_levels"], self.profile.num_layers)

    def test_render_uses_the_profile_colours(self):
        data = self.render_image()
        image = decode_data_url(data["result_url"]).convert("RGB")
        used = {tuple(c) for c in np.array(image).reshape(-1, 3)}

        expected = {
            tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            for color in self.profile.color_list()
        }
        self.assertTrue(used.issubset(expected), f"unexpected colours: {used - expected}")

    def test_layer_count_comes_from_the_profile_not_the_client(self):
        five_layer = ColorProfile.objects.filter(num_layers=5, is_active=True).first()
        self.assertIsNotNone(five_layer, "expected a seeded 5-layer profile")

        response = self.client.post(
            "/api/process",
            {
                "profile_id": five_layer.id,
                "image": upload(),
                "postprocess_method": "none",
                "num_levels": 2,  # a tampered client value must be ignored
            },
        )
        data = response.json()
        self.assertEqual(data["config"]["num_levels"], 5)

    def test_invalid_profile_is_rejected(self):
        response = self.client.post("/api/process", {"profile_id": 99999, "image": upload()})
        self.assertEqual(response.status_code, 400)
        self.assertIn("پروفایل", response.json()["error"])

    def test_invalid_image_is_rejected(self):
        bad = SimpleUploadedFile("x.png", b"definitely-not-an-image", content_type="image/png")
        response = self.client.post("/api/process", {"profile_id": self.profile.id, "image": bad})
        self.assertEqual(response.status_code, 400)
        self.assertIn("معتبر", response.json()["error"])


class AuthTests(StudioTestCase):
    def test_register_creates_a_user_and_signs_them_in(self):
        response = self.client.post(
            "/api/auth/register",
            {
                "full_name": "علی رضایی",
                "phone": "۰۹۱۲۳۴۵۶۷۸۹",  # Persian digits must be accepted
                "email": "Ali@Example.com",
                "password1": "StrongPass!234",
                "password2": "StrongPass!234",
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:400])
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["user"]["is_authenticated"])

        user = User.objects.get(phone="09123456789")
        self.assertEqual(user.email, "ali@example.com")
        self.assertFalse(user.is_staff)

    def test_register_rejects_mismatched_passwords_and_duplicates(self):
        self.make_user(phone="09120000001", email="dupe@example.com")

        response = self.client.post(
            "/api/auth/register",
            {
                "phone": "09120000001",
                "email": "dupe@example.com",
                "password1": "StrongPass!234",
                "password2": "different",
            },
        )
        self.assertEqual(response.status_code, 400)
        errors = response.json()["errors"]
        self.assertIn("phone", errors)
        self.assertIn("email", errors)
        self.assertIn("password2", errors)

    def test_login_works_with_phone_or_email(self):
        self.make_user(phone="09120000002", email="both@example.com", password="TestPass!234")

        for identifier in ("09120000002", "both@example.com", "۰۹۱۲۰۰۰۰۰۰۲"):
            client = Client()
            response = client.post(
                "/api/auth/login", {"identifier": identifier, "password": "TestPass!234"}
            )
            self.assertEqual(response.status_code, 200, f"failed for {identifier}")
            self.assertTrue(response.json()["user"]["is_authenticated"])

    def test_login_with_a_wrong_password_fails(self):
        self.make_user(phone="09120000003", email="wrong@example.com")
        response = self.client.post(
            "/api/auth/login", {"identifier": "09120000003", "password": "nope"}
        )
        self.assertEqual(response.status_code, 401)

    def test_signing_in_keeps_the_image_that_was_already_built(self):
        """The whole point of the modal: the render must survive the login."""
        data = self.render_image()
        image_id = self.client.session["image_id"]
        self.assertTrue(image_id)

        self.make_user(phone="09120000004", email="keep@example.com", password="TestPass!234")
        response = self.client.post(
            "/api/auth/login", {"identifier": "09120000004", "password": "TestPass!234"}
        )
        self.assertEqual(response.status_code, 200)

        # Same uploaded image still attached to the (rotated) session…
        self.assertEqual(self.client.session["image_id"], image_id)
        # …and an order can be placed straight away, without re-uploading.
        response = self.client.post(
            "/api/orders/create",
            {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"},
        )
        self.assertEqual(response.status_code, 200, response.content[:400])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(data["profile"]["id"], self.profile.id)


class OrderTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    def test_anonymous_order_is_refused_with_an_auth_flag(self):
        client = Client()
        client.post("/api/process", {"profile_id": self.profile.id, "image": upload()})
        response = client.post("/api/orders/create", {"profile_id": self.profile.id})

        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.json()["auth_required"])
        self.assertEqual(Order.objects.count(), 0)

    def test_order_stores_a_snapshot_of_the_render(self):
        self.render_image()
        response = self.client.post(
            "/api/orders/create",
            {
                "profile_id": self.profile.id,
                "postprocess_method": "none",
                "note": "قاب چوبی",
                "width_cm": "40",
            },
        )
        self.assertEqual(response.status_code, 200, response.content[:400])

        order = Order.objects.get()
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(order.note, "قاب چوبی")
        self.assertEqual(order.profile_name, self.profile.name)
        self.assertEqual(order.num_layers, self.profile.num_layers)
        self.assertEqual(order.colors, self.profile.color_list())
        self.assertTrue(order.result_image.name.endswith(".png"))
        self.assertTrue(order.original_image.name.endswith(".png"))
        self.assertGreater(order.result_image.size, 0)

    def test_order_without_an_image_is_refused(self):
        response = self.client.post("/api/orders/create", {"profile_id": self.profile.id})
        self.assertEqual(response.status_code, 400)
        self.assertIn("تصویری", response.json()["error"])

    def test_at_most_three_unreviewed_orders(self):
        self.render_image()
        payload = {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"}

        for index in range(Order.MAX_UNREVIEWED):
            response = self.client.post("/api/orders/create", payload)
            self.assertEqual(response.status_code, 200, f"order {index + 1} failed")

        response = self.client.post("/api/orders/create", payload)
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertTrue(body["limit_reached"])
        self.assertEqual(Order.objects.count(), Order.MAX_UNREVIEWED)

        # Reviewing one frees a slot again.
        order = Order.objects.first()
        order.status = Order.STATUS_APPROVED
        order.save(update_fields=["status"])

        response = self.client.post("/api/orders/create", payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.count(), Order.MAX_UNREVIEWED + 1)

    def test_reviewed_statuses_do_not_count_towards_the_limit(self):
        self.render_image()
        for status in (Order.STATUS_APPROVED, Order.STATUS_REJECTED):
            Order.objects.create(user=self.user, status=status, num_layers=4)

        self.assertEqual(Order.objects.unreviewed_count(self.user), 0)
        response = self.client.post(
            "/api/orders/create",
            {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"},
        )
        self.assertEqual(response.status_code, 200)

    def test_my_orders_page_requires_login_and_lists_orders(self):
        anonymous = Client()
        response = anonymous.get("/orders/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login=1", response["Location"])

        self.render_image()
        self.client.post(
            "/api/orders/create",
            {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"},
        )

        response = self.client.get("/orders/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "سفارش‌های من")
        self.assertContains(response, "در انتظار بررسی")

    def test_order_images_are_private(self):
        self.render_image()
        self.client.post(
            "/api/orders/create",
            {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"},
        )
        order = Order.objects.get()

        response = self.client.get(f"/orders/{order.pk}/image/result/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

        other = Client()
        other.force_login(self.make_user(phone="09129998877", email="other@example.com"))
        self.assertEqual(other.get(f"/orders/{order.pk}/image/result/").status_code, 404)

        staff = Client()
        staff.force_login(
            User.objects.create_user(
                phone="09127776655", email="staff@example.com", password="x", is_staff=True
            )
        )
        self.assertEqual(staff.get(f"/orders/{order.pk}/image/result/").status_code, 200)


class FrameSizeAndCostTests(StudioTestCase):
    """Frame sizing keeps the photo's ratio; pricing is computed server-side."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)
        self.site = SiteSettings.load()
        # The fixture image is 120x90 -> ratio 4:3.
        self.ratio = Decimal("120") / Decimal("90")

    def order_payload(self, **extra):
        payload = {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"}
        payload.update(extra)
        return payload

    def test_process_reports_the_sizing_envelope(self):
        data = self.render_image()
        sizing = data["sizing"]

        self.assertEqual(sizing["image_width_px"], 120)
        self.assertEqual(sizing["image_height_px"], 90)
        self.assertAlmostEqual(sizing["ratio"], 120 / 90)
        self.assertTrue(sizing["fits"])

        # A 4:3 photo cannot be wider than max_height * ratio.
        expected_min = max(float(self.site.min_width_cm), float(self.site.min_height_cm) * (120 / 90))
        self.assertAlmostEqual(sizing["effective_min_width_cm"], round(expected_min, 1))
        self.assertLessEqual(sizing["effective_max_width_cm"], float(self.site.max_width_cm))

    def test_height_is_derived_from_the_ratio_and_priced(self):
        self.render_image()
        response = self.client.post("/api/orders/create", self.order_payload(width_cm="40"))
        self.assertEqual(response.status_code, 200, response.content[:400])

        order = Order.objects.get()
        self.assertEqual(order.width_cm, Decimal("40.0"))
        self.assertEqual(order.height_cm, Decimal("30.0"))  # 40 / (4/3)
        self.assertEqual(order.area_cm2, Decimal("1200.00"))
        self.assertEqual(order.price_per_cm2, self.site.price_per_cm2)
        self.assertEqual(order.estimated_cost, self.site.estimate_cost(40, 30))
        self.assertEqual(order.estimated_cost, 1200 * self.site.price_per_cm2)

    def test_client_cannot_dictate_the_height_or_the_price(self):
        """A tampered height/cost must be ignored: both are recomputed."""
        self.render_image()
        response = self.client.post(
            "/api/orders/create",
            self.order_payload(
                width_cm="40", height_cm="5", estimated_cost="1", final_cost="1", area_cm2="1"
            ),
        )
        self.assertEqual(response.status_code, 200)

        order = Order.objects.get()
        self.assertEqual(order.height_cm, Decimal("30.0"))
        self.assertEqual(order.estimated_cost, 1200 * self.site.price_per_cm2)
        self.assertIsNone(order.final_cost)

    def test_width_outside_the_allowed_range_is_refused(self):
        self.render_image()

        for bad in ("5", "500", "0", "-10"):
            response = self.client.post("/api/orders/create", self.order_payload(width_cm=bad))
            self.assertEqual(response.status_code, 400, f"width {bad} should be refused")
            self.assertIn("عرض قاب", response.json()["error"])

        self.assertEqual(Order.objects.count(), 0)

    def test_width_is_required_and_must_be_numeric(self):
        self.render_image()

        response = self.client.post("/api/orders/create", self.order_payload(width_cm=""))
        self.assertEqual(response.status_code, 400)
        self.assertIn("اندازهٔ قاب", response.json()["error"])

        response = self.client.post("/api/orders/create", self.order_payload(width_cm="abc"))
        self.assertEqual(response.status_code, 400)

    def test_persian_digits_are_accepted_for_the_width(self):
        self.render_image()
        response = self.client.post("/api/orders/create", self.order_payload(width_cm="۴۰"))
        self.assertEqual(response.status_code, 200, response.content[:400])
        self.assertEqual(Order.objects.get().width_cm, Decimal("40.0"))

    def test_admin_limits_are_respected_after_being_changed(self):
        self.site.min_width_cm = Decimal("50.0")
        self.site.max_width_cm = Decimal("60.0")
        self.site.save()
        self.render_image()

        response = self.client.post("/api/orders/create", self.order_payload(width_cm="40"))
        self.assertEqual(response.status_code, 400)

        response = self.client.post("/api/orders/create", self.order_payload(width_cm="55"))
        self.assertEqual(response.status_code, 200, response.content[:400])
        self.assertEqual(Order.objects.get().width_cm, Decimal("55.0"))

    def test_price_change_is_reflected_in_new_estimates(self):
        self.render_image()
        self.site.price_per_cm2 = 12000
        self.site.save()

        response = self.client.post("/api/orders/create", self.order_payload(width_cm="40"))
        self.assertEqual(response.status_code, 200)

        order = Order.objects.get()
        self.assertEqual(order.price_per_cm2, 12000)
        self.assertEqual(order.estimated_cost, 1200 * 12000)

    def test_impossible_ratio_is_reported_and_refused(self):
        """A very wide photo cannot fit limits that cap width tightly."""
        self.site.max_width_cm = Decimal("40.0")
        self.site.min_height_cm = Decimal("30.0")
        self.site.save()

        wide = SimpleUploadedFile("wide.png", make_image_bytes((1200, 100)), content_type="image/png")
        response = self.client.post(
            "/api/process", {"profile_id": self.profile.id, "image": wide, "postprocess_method": "none"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["sizing"]["fits"])

        response = self.client.post("/api/orders/create", self.order_payload(width_cm="40"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("هیچ اندازه‌ای", response.json()["error"])

    def test_cost_rounding(self):
        self.site.price_per_cm2 = 1234
        self.site.cost_rounding = 10000
        self.site.save()

        cost = self.site.estimate_cost(Decimal("40"), Decimal("30"))
        self.assertEqual(cost % 10000, 0)
        self.assertEqual(cost, round(1200 * 1234 / 10000) * 10000)

    def test_final_cost_overrides_the_estimate_for_the_customer(self):
        self.render_image()
        self.client.post("/api/orders/create", self.order_payload(width_cm="40"))
        order = Order.objects.get()

        self.assertFalse(order.cost_is_final)
        self.assertEqual(order.payable_cost, order.estimated_cost)

        order.final_cost = 9_000_000
        order.save(update_fields=["final_cost"])
        order.refresh_from_db()

        self.assertTrue(order.cost_is_final)
        self.assertEqual(order.payable_cost, 9_000_000)

        response = self.client.get("/orders/")
        self.assertContains(response, "هزینهٔ نهایی")
        self.assertContains(response, "تأییدشده توسط مدیر")

    def test_customer_sees_the_estimate_on_the_orders_page(self):
        self.render_image()
        self.client.post("/api/orders/create", self.order_payload(width_cm="40"))

        response = self.client.get("/orders/")
        self.assertContains(response, "هزینهٔ تقریبی")
        self.assertContains(response, "تقریبی — پس از بررسی نهایی می‌شود")
        self.assertContains(response, "۴۰ × ۳۰ سانتی‌متر")

    def test_site_settings_is_a_singleton(self):
        second = SiteSettings(min_width_cm=Decimal("1.0"))
        second.save()
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(second.pk, 1)

    def test_site_settings_validates_its_ranges(self):
        site = SiteSettings.load()
        site.min_width_cm = Decimal("90.0")
        site.max_width_cm = Decimal("20.0")
        with self.assertRaises(ValidationError):
            site.full_clean()


class ColorProfileTests(StudioTestCase):
    def test_sync_layers_creates_trims_and_renumbers(self):
        profile = ColorProfile.objects.create(name="آزمایشی", num_layers=3)
        profile.sync_layers()
        self.assertEqual(profile.layers.count(), 3)
        self.assertEqual([layer.index for layer in profile.layers.all()], [0, 1, 2])

        profile.num_layers = 5
        profile.save()
        profile.sync_layers()
        self.assertEqual(profile.layers.count(), 5)

        profile.num_layers = 2
        profile.save()
        profile.sync_layers()
        self.assertEqual(profile.layers.count(), 2)
        self.assertEqual([layer.index for layer in profile.layers.all()], [0, 1])

    def test_inactive_profiles_are_hidden_from_users(self):
        profile = ColorProfile.objects.create(name="غیرفعال", num_layers=3, is_active=False)
        profile.sync_layers()

        response = self.client.get("/")
        self.assertNotContains(response, "غیرفعال")

        response = self.client.post(
            "/api/process", {"profile_id": profile.id, "image": upload()}
        )
        self.assertEqual(response.status_code, 400)


class RenderDefaultsTests(StudioTestCase):
    """The settings the studio opens with are admin-configurable."""

    def test_home_page_uses_the_admin_configured_defaults(self):
        site = SiteSettings.load()
        site.default_preprocess_method = "gaussian"
        site.default_postprocess_method = "majority_filter"
        site.default_gaussian_kernel_size = 9
        site.default_min_region_size = 123
        site.default_preserve_edges = False
        site.save()

        html = self.client.get("/").content.decode()
        self.assertIn('<option value="gaussian" selected>', html)
        self.assertIn('<option value="majority_filter" selected>', html)
        self.assertIn('value="9"', html)
        self.assertIn('value="123"', html)
        self.assertNotIn('id="preserve_edges" name="preserve_edges" checked', html)

    def test_defaults_apply_when_the_client_sends_nothing(self):
        site = SiteSettings.load()
        site.default_postprocess_method = "median"
        site.default_median_kernel_size = 7
        site.default_bilateral_d = 11
        site.save()

        response = self.client.post(
            "/api/process", {"profile_id": self.profile.id, "image": upload()}
        )
        config = response.json()["config"]
        self.assertEqual(config["postprocess_method"], "median")
        self.assertEqual(config["median_kernel_size"], 7)
        self.assertEqual(config["bilateral_d"], 11)

    def test_user_choice_still_overrides_the_defaults(self):
        site = SiteSettings.load()
        site.default_preprocess_method = "gaussian"
        site.save()

        response = self.client.post(
            "/api/process",
            {"profile_id": self.profile.id, "image": upload(), "preprocess_method": "none"},
        )
        self.assertEqual(response.json()["config"]["preprocess_method"], "none")

    def test_default_profile_is_preselected(self):
        chosen = ColorProfile.objects.filter(is_active=True).order_by("-sort_order").first()
        site = SiteSettings.load()
        site.default_profile = chosen
        site.save()

        html = self.client.get("/").content.decode()
        self.assertIn(f'<option value="{chosen.id}" selected>', html)

        # …and it is what an upload without an explicit profile uses.
        response = self.client.post("/api/process", {"image": upload()})
        self.assertEqual(response.json()["profile"]["id"], chosen.id)

    def test_inactive_default_profile_falls_back(self):
        chosen = ColorProfile.objects.filter(is_active=True).first()
        site = SiteSettings.load()
        site.default_profile = chosen
        site.save()

        chosen.is_active = False
        chosen.save()

        response = self.client.post("/api/process", {"image": upload()})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["profile"]["id"], chosen.id)

    def test_config_api_reports_the_configured_defaults(self):
        site = SiteSettings.load()
        site.default_min_region_size = 321
        site.save()

        data = self.client.get("/api/config").json()
        self.assertEqual(data["defaults"]["min_region_size"], 321)
        self.assertIn("sizing", data)


class StlExportTests(StudioTestCase):
    """3D export: one terrace per colour, at admin-configured heights."""

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            phone="09120000009", email="admin@example.com", password="AdminPass!234"
        )
        self.user = self.make_user()

        client = Client()
        client.force_login(self.user)
        client.post(
            "/api/process",
            {"profile_id": self.profile.id, "image": upload(), "postprocess_method": "none"},
        )
        client.post(
            "/api/orders/create",
            {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"},
        )
        self.order = Order.objects.get()

    def test_the_darkest_layer_is_the_tallest_by_default(self):
        """Dark areas are the deep ones on a layered frame."""
        site = SiteSettings.load()
        site.stl_layer_height_mm = Decimal("2.50")
        site.save()

        # Palette order is darkest first, so the first entry gets the full stack.
        self.assertTrue(site.stl_dark_is_tallest)
        self.assertEqual(site.layer_heights_mm(4), [10.0, 7.5, 5.0, 2.5])
        self.assertEqual(site.layer_heights_mm(3), [7.5, 5.0, 2.5])

    def test_height_direction_can_be_flipped(self):
        site = SiteSettings.load()
        site.stl_layer_height_mm = Decimal("2.00")
        site.stl_dark_is_tallest = False
        site.save()

        self.assertEqual(site.layer_heights_mm(4), [2.0, 4.0, 6.0, 8.0])

    def test_exported_geometry_puts_the_dark_colour_on_top(self):
        """
        End-to-end check on the mesh itself, not just the height table:
        the region painted with the darkest colour must be the tallest.
        """
        from .stl import order_to_stl

        site = SiteSettings.load()
        site.stl_layer_height_mm = Decimal("2.00")
        site.save()

        colors = ["#101010", "#606060", "#b0b0b0", "#f0f0f0"]  # darkest first
        rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in colors]
        array = np.zeros((40, 80, 3), dtype=np.uint8)
        for index, colour in enumerate(rgb):
            array[:, index * 20:(index + 1) * 20] = colour
        image = Image.fromarray(array, "RGB")

        heights = site.layer_heights_mm(4)
        payload, _ = order_to_stl(image, colors, heights, 80.0, 40.0, max_resolution=80)

        count = struct.unpack("<I", payload[80:84])[0]
        dtype = np.dtype([("n", "<3f4"), ("v", "<3,3f4"), ("a", "<u2")])
        verts = np.frombuffer(payload[84:], dtype=dtype, count=count)["v"].astype(np.float64)

        # Tallest z strictly inside each colour band. The margin matters: the
        # wall between two bands lies exactly on their shared x plane, so it
        # belongs to both and would report the taller neighbour's height.
        peaks = []
        for index in range(4):
            x_low, x_high = index * 20.0 + 1.0, (index + 1) * 20.0 - 1.0
            inside = (verts[:, :, 0] >= x_low).all(axis=1) & (verts[:, :, 0] <= x_high).all(axis=1)
            peaks.append(round(float(verts[inside][:, :, 2].max()), 3))

        self.assertEqual(peaks, [8.0, 6.0, 4.0, 2.0], f"band peaks were {peaks}")
        self.assertGreater(peaks[0], peaks[-1], "the darkest band must be the tallest")

    def test_admin_can_download_an_stl(self):
        self.client.force_login(self.admin)
        response = self.client.get(f"/orders/{self.order.pk}/stl/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "model/stl")
        self.assertIn(f"order-{self.order.pk}.stl", response["Content-Disposition"])

        payload = b"".join(response.streaming_content) if response.streaming else response.content
        count = struct.unpack("<I", payload[80:84])[0]
        self.assertGreater(count, 0)
        # Binary STL: 80-byte header + 4-byte count + 50 bytes per triangle.
        self.assertEqual(len(payload), 84 + count * 50)

    def test_stl_is_a_closed_manifold_solid(self):
        site = SiteSettings.load()
        with Image.open(self.order.result_image.path) as image:
            indices = layer_index_map(image, self.order.colors, 120)

        indices, _ = resolve_saddles(indices)
        heights = np.array(site.layer_heights_mm(len(self.order.colors)))[indices]
        builder = build_mesh(heights, 400.0, 300.0, levels=site.layer_heights_mm(len(self.order.colors)))

        self.assertTrue(mesh_is_closed(builder), "exported mesh must be watertight")

    def test_model_dimensions_follow_the_ordered_frame_size(self):
        site = SiteSettings.load()
        site.stl_layer_height_mm = Decimal("3.00")
        site.save()

        self.client.force_login(self.admin)
        response = self.client.get(f"/orders/{self.order.pk}/stl/")

        # Order is 40 x 30 cm -> 400 x 300 mm; 4 layers x 3 mm -> 12 mm tallest
        # (the tallest step is the same whichever end of the palette gets it).
        self.assertEqual(response["X-Model-Size-Mm"], "400.0x300.0x12.0")

    def test_every_column_is_solid_from_the_base_to_its_top(self):
        """
        The plate must be a filled solid, not a stack of floating slabs.

        Casts a vertical ray through every cell and checks the surface is
        crossed exactly twice: entering at z=0 and leaving at that cell's
        height. Any gap under a terrace would show up as extra crossings.
        """
        from .stl import order_to_stl

        colors = ["#1a1a1a", "#6b4a24", "#b08750", "#f2e0c9"]
        rgb = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in colors]

        # Blobs over noise: islands, saddles and isolated cells all present.
        rng = np.random.default_rng(4)
        indices = rng.integers(0, 4, (32, 40))
        rows_grid, cols_grid = np.mgrid[0:32, 0:40]
        for radius, value in ((13, 0), (8, 3), (4, 1)):
            indices[(cols_grid - 20) ** 2 // 2 + (rows_grid - 16) ** 2 < radius ** 2] = value
        image = Image.fromarray(np.array(rgb, "uint8")[indices], "RGB")

        heights = [2.0, 4.0, 6.0, 8.0]
        width_mm, height_mm = 40.0, 32.0
        payload, _ = order_to_stl(image, colors, heights, width_mm, height_mm, max_resolution=40)

        count = struct.unpack("<I", payload[80:84])[0]
        dtype = np.dtype([("n", "<3f4"), ("v", "<3,3f4"), ("a", "<u2")])
        verts = np.frombuffer(payload[84:], dtype=dtype, count=count)["v"].astype(np.float64)

        first, second, third = verts[:, 0, :], verts[:, 1, :], verts[:, 2, :]
        edge_a = second[:, :2] - first[:, :2]
        edge_b = third[:, :2] - first[:, :2]
        det = edge_a[:, 0] * edge_b[:, 1] - edge_b[:, 0] * edge_a[:, 1]
        usable = np.abs(det) > 1e-12
        safe_det = np.where(usable, det, 1.0)

        def crossings(px, py):
            rel = np.array([px, py]) - first[:, :2]
            u = (rel[:, 0] * edge_b[:, 1] - edge_b[:, 0] * rel[:, 1]) / safe_det
            w = (edge_a[:, 0] * rel[:, 1] - rel[:, 0] * edge_a[:, 1]) / safe_det
            inside = usable & (u > 1e-9) & (w > 1e-9) & (u + w < 1 - 1e-9)
            z = (
                first[inside, 2]
                + u[inside] * (second[inside, 2] - first[inside, 2])
                + w[inside] * (third[inside, 2] - first[inside, 2])
            )
            return np.sort(z)

        repaired, _ = resolve_saddles(layer_index_map(image, colors, 40))
        heightmap = np.array(heights)[repaired]
        rows, cols = heightmap.shape
        dx, dy = width_mm / cols, height_mm / rows

        # Probe off-centre and asymmetrically: the cell centre and the 45°
        # diagonal both lie on the split between the cell's two triangles.
        gaps = []
        for row in range(rows):
            for col in range(cols):
                z = crossings((col + 0.3) * dx, height_mm - (row + 0.6) * dy)
                expected = heightmap[row, col]
                if len(z) != 2 or abs(z[0]) > 1e-6 or abs(z[1] - expected) > 1e-6:
                    gaps.append((row, col, np.round(z, 3).tolist(), float(expected)))

        self.assertEqual(gaps[:5], [], f"{len(gaps)} column(s) are not solid to the base")

    def test_saddle_repair_keeps_the_picture_recognisable(self):
        """Repairs must be rare on a real posterized image, not wholesale."""
        with Image.open(self.order.result_image.path) as image:
            indices = layer_index_map(image, self.order.colors, 200)

        repaired_indices, changed = resolve_saddles(indices)
        self.assertLess(changed / indices.size, 0.05)
        self.assertEqual(indices.shape, repaired_indices.shape)

    def test_ordinary_users_cannot_download_stl(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f"/orders/{self.order.pk}/stl/").status_code, 404)

    def test_anonymous_cannot_download_stl(self):
        response = Client().get(f"/orders/{self.order.pk}/stl/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login=1", response["Location"])

    def test_stl_works_for_orders_placed_before_sizing_existed(self):
        self.order.width_cm = None
        self.order.height_cm = None
        self.order.save()

        self.client.force_login(self.admin)
        response = self.client.get(f"/orders/{self.order.pk}/stl/")
        self.assertEqual(response.status_code, 200)

    def test_admin_pages_expose_the_download_link(self):
        self.client.force_login(self.admin)

        listing = self.client.get("/admin/posterizer/order/")
        self.assertContains(listing, f"/orders/{self.order.pk}/stl/")

        detail = self.client.get(f"/admin/posterizer/order/{self.order.pk}/change/")
        self.assertContains(detail, "دانلود فایل STL")


class PageTitleTests(StudioTestCase):
    def test_titles_are_short_enough_for_a_browser_tab(self):
        html = self.client.get("/").content.decode()
        title = html.split("<title>")[1].split("</title>")[0]
        self.assertEqual(title, "قاب عکس سه‌بعدی")
        self.assertLess(len(title), 25)


class AdminPanelTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            phone="09120000009", email="admin@example.com", password="AdminPass!234"
        )
        self.user = self.make_user()

        client = Client()
        client.force_login(self.user)
        client.post(
            "/api/process",
            {"profile_id": self.profile.id, "image": upload(), "postprocess_method": "none"},
        )
        client.post(
            "/api/orders/create",
            {"profile_id": self.profile.id, "postprocess_method": "none", "width_cm": "40"},
        )
        self.order = Order.objects.get()

        self.client.force_login(self.admin)

    def test_ordinary_users_cannot_reach_the_admin_panel(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/admin/", follow=True)
        self.assertNotContains(response, "مدیریت سفارش‌ها", status_code=200)

    def test_admin_can_list_and_open_orders_and_profiles(self):
        for url in (
            "/admin/",
            "/admin/posterizer/order/",
            f"/admin/posterizer/order/{self.order.pk}/change/",
            "/admin/posterizer/colorprofile/",
            "/admin/accounts/user/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f"{url} -> {response.status_code}")

    def test_admin_status_change_is_stamped(self):
        response = self.client.post(
            f"/admin/posterizer/order/{self.order.pk}/change/",
            {"status": Order.STATUS_APPROVED, "admin_note": "تأیید شد", "_save": "ذخیره"},
        )
        self.assertEqual(response.status_code, 302, response.content[:400])

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_APPROVED)
        self.assertEqual(self.order.reviewed_by, self.admin)
        self.assertIsNotNone(self.order.reviewed_at)

    def test_admin_bulk_action_approves_orders(self):
        response = self.client.post(
            "/admin/posterizer/order/",
            {"action": "mark_approved", "_selected_action": [str(self.order.pk)]},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.STATUS_APPROVED)
        self.assertEqual(self.order.reviewed_by, self.admin)


class ReadyImageTests(StudioTestCase):
    """The second order path: images the customer built elsewhere."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    # --- helpers ---

    @staticmethod
    def flat_image(colors=((26, 26, 26), (107, 74, 36), (176, 135, 80), (242, 224, 201)),
                   size=(400, 300), fmt="PNG", quality=90) -> bytes:
        width, height = size
        array = np.zeros((height, width, 3), dtype=np.uint8)
        band = width // len(colors)
        for index, color in enumerate(colors):
            array[:, index * band:(index + 1) * band] = color
        out = io.BytesIO()
        Image.fromarray(array, "RGB").save(out, format=fmt, quality=quality)
        return out.getvalue()

    @staticmethod
    def gradient_image() -> bytes:
        ramp = np.linspace(0, 255, 400, dtype=np.uint8)
        array = np.repeat(np.repeat(ramp[None, :, None], 300, 0), 3, 2)
        out = io.BytesIO()
        Image.fromarray(array, "RGB").save(out, format="PNG")
        return out.getvalue()

    def upload_ready(self, payload=None, name="ready.png", content_type="image/png"):
        payload = payload if payload is not None else self.flat_image()
        return self.client.post(
            "/api/ready/verify",
            {"image": SimpleUploadedFile(name, payload, content_type=content_type)},
        )

    # --- verification ---

    def test_flat_image_is_accepted_and_its_palette_detected(self):
        response = self.upload_ready()
        self.assertEqual(response.status_code, 200, response.content[:400])

        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["color_count"], 4)
        self.assertEqual(len(data["colors"]), 4)
        self.assertTrue(all(c.startswith("#") for c in data["colors"]))
        self.assertIn("sizing", data)

        # Darkest first, matching how colour profiles number their layers.
        def luminance(hex_color):
            r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        values = [luminance(c) for c in data["colors"]]
        self.assertEqual(values, sorted(values))

    def test_jpeg_compression_noise_is_tolerated(self):
        """The same artwork saved as JPEG must still read as four layers."""
        response = self.upload_ready(self.flat_image(fmt="JPEG", quality=40),
                                     name="ready.jpg", content_type="image/jpeg")
        self.assertEqual(response.status_code, 200, response.content[:400])
        self.assertEqual(response.json()["color_count"], 4)

    def test_gradient_is_rejected_with_an_explanation(self):
        response = self.upload_ready(self.gradient_image())
        self.assertEqual(response.status_code, 400)

        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("یکدست", data["error"])
        self.assertIn(data["reason"], ("too_many_colors", "low_coverage"))

    def test_photo_is_rejected(self):
        noise = np.random.default_rng(5).integers(0, 255, (300, 400, 3), dtype=np.uint8)
        out = io.BytesIO()
        Image.fromarray(noise, "RGB").save(out, format="PNG")
        self.assertEqual(self.upload_ready(out.getvalue()).status_code, 400)

    def test_layer_limit_is_enforced_from_settings(self):
        site = SiteSettings.load()
        site.ready_max_colors = 3
        site.save()

        response = self.upload_ready()  # four bands
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "too_many_colors")

    def test_feature_can_be_switched_off(self):
        site = SiteSettings.load()
        site.ready_images_enabled = False
        site.save()

        self.assertEqual(self.upload_ready().status_code, 400)
        self.assertNotContains(self.client.get("/"), 'data-mode="ready"')

    def test_invalid_file_is_rejected(self):
        response = self.upload_ready(b"not-an-image")
        self.assertEqual(response.status_code, 400)
        self.assertIn("معتبر", response.json()["error"])

    # --- ordering ---

    def test_ready_image_can_be_ordered_without_a_profile(self):
        verify = self.upload_ready().json()

        response = self.client.post(
            "/api/orders/create",
            {"source": "ready", "width_cm": "40", "note": "تصویر آماده"},
        )
        self.assertEqual(response.status_code, 200, response.content[:400])

        order = Order.objects.get()
        self.assertEqual(order.source, Order.SOURCE_READY)
        self.assertTrue(order.is_ready_image)
        self.assertIsNone(order.profile)
        self.assertEqual(order.profile_name, "")
        self.assertEqual(order.colors, verify["colors"])
        self.assertEqual(order.num_layers, 4)
        self.assertEqual(order.width_cm, Decimal("40.0"))
        self.assertGreater(order.estimated_cost, 0)
        self.assertEqual(order.palette_label, "پالت تصویر آماده")

    def test_stored_image_contains_only_the_detected_palette(self):
        """Compression noise must be snapped away, or the STL would be wrong."""
        self.upload_ready(self.flat_image(fmt="JPEG", quality=40),
                          name="ready.jpg", content_type="image/jpeg")
        self.client.post("/api/orders/create", {"source": "ready", "width_cm": "40"})

        order = Order.objects.get()
        with Image.open(order.result_image.path) as image:
            used = {tuple(c) for c in np.array(image.convert("RGB")).reshape(-1, 3)}

        expected = {
            tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in order.colors
        }
        self.assertEqual(used, expected)

    def test_ready_order_exports_an_stl(self):
        self.upload_ready()
        self.client.post("/api/orders/create", {"source": "ready", "width_cm": "40"})
        order = Order.objects.get()

        admin = User.objects.create_superuser(
            phone="09120000009", email="admin@example.com", password="AdminPass!234"
        )
        staff = Client()
        staff.force_login(admin)

        response = staff.get(f"/orders/{order.pk}/stl/")
        self.assertEqual(response.status_code, 200)
        payload = b"".join(response.streaming_content) if response.streaming else response.content
        count = struct.unpack("<I", payload[80:84])[0]
        self.assertEqual(len(payload), 84 + count * 50)

    def test_cannot_order_ready_without_verifying_first(self):
        response = self.client.post("/api/orders/create", {"source": "ready", "width_cm": "40"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_switching_back_to_the_studio_clears_the_ready_state(self):
        self.upload_ready()
        self.assertIn("ready_palette", self.client.session)

        self.client.post(
            "/api/process",
            {"profile_id": self.profile.id, "image": upload(), "postprocess_method": "none"},
        )
        self.assertNotIn("ready_palette", self.client.session)

        # A subsequent "ready" order must not silently reuse the studio render.
        response = self.client.post("/api/orders/create", {"source": "ready", "width_cm": "40"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Order.objects.get().source, Order.SOURCE_STUDIO)

    def test_ready_orders_count_towards_the_same_quota(self):
        self.upload_ready()
        for _ in range(Order.MAX_UNREVIEWED):
            self.assertEqual(
                self.client.post("/api/orders/create", {"source": "ready", "width_cm": "40"}).status_code,
                200,
            )
        response = self.client.post("/api/orders/create", {"source": "ready", "width_cm": "40"})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["limit_reached"])

    # --- UI ---

    def test_studio_page_offers_both_paths_and_the_ai_prompt(self):
        html = self.client.get("/").content.decode()
        self.assertIn('data-mode="studio"', html)
        self.assertIn('data-mode="ready"', html)
        self.assertIn("ساخت با ابزار ما", html)
        self.assertIn("تصویر آماده دارم", html)
        self.assertIn("Nano Banana Pro", html)
        self.assertIn('id="aiPrompt"', html)

        # The switch is a compact segmented control, and the AI guide lives in
        # the canvas (where it has room), not squeezed into the sidebar.
        self.assertIn('class="segmented"', html)
        self.assertIn('id="segmentedThumb"', html)
        self.assertEqual(html.count('id="aiPrompt"'), 1)
        self.assertIn('class="ai-guide"', html)

    def test_the_shipped_prompt_is_the_real_one(self):
        """Guards against the placeholder creeping back in."""
        from .prompts import DEFAULT_AI_PROMPT

        site = SiteSettings.load()
        self.assertEqual(site.ai_helper_prompt, DEFAULT_AI_PROMPT)
        self.assertIn("Extreme posterization", DEFAULT_AI_PROMPT)
        self.assertIn("NO gradients", DEFAULT_AI_PROMPT)
        self.assertNotIn("Convert this photo into a flat, poster-style", DEFAULT_AI_PROMPT)

        # …and it reaches the page the customer reads.
        self.assertContains(self.client.get("/"), "Extreme posterization")

    def test_ai_helper_can_be_hidden(self):
        site = SiteSettings.load()
        site.ai_helper_enabled = False
        site.save()
        self.assertNotContains(self.client.get("/"), 'id="aiPrompt"')

    def test_orders_page_marks_ready_images(self):
        self.upload_ready()
        self.client.post("/api/orders/create", {"source": "ready", "width_cm": "40"})
        self.assertContains(self.client.get("/orders/"), "تصویر آماده")
