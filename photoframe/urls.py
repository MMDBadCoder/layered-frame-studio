from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "پنل مدیریت قاب عکس سه‌بعدی"
admin.site.site_title = "قاب عکس سه‌بعدی"
admin.site.index_title = "مدیریت سفارش‌ها و پروفایل‌های رنگی"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("", include("posterizer.urls")),
]
