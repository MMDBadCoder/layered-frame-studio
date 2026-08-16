/*
 * Shared front-end helpers: CSRF, toasts, the account menu and the
 * sign-in / sign-up modal.
 *
 * Everything here is AJAX-only on purpose: the studio page must never reload
 * while someone signs in, otherwise the image they just built would be gone.
 */
window.PF = (() => {
  const PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹";

  const state = {
    account: { is_authenticated: false },
    authResolver: null,
  };

  // ---------------------------------------------------------------- utils --

  function faDigits(value) {
    return String(value).replace(/\d/g, (d) => PERSIAN_DIGITS[d]);
  }

  function esc(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function getCookie(name) {
    const match = document.cookie.match(new RegExp("(^|;\\s*)" + name + "=([^;]*)"));
    return match ? decodeURIComponent(match[2]) : null;
  }

  /* Always read the cookie fresh: signing in rotates the CSRF token. */
  function csrfToken() {
    return getCookie("csrftoken") || "";
  }

  async function post(url, formData) {
    const response = await fetch(url, {
      method: "POST",
      body: formData,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
    });

    let data = {};
    try {
      data = await response.json();
    } catch (err) {
      data = { error: "پاسخ نامعتبر از سرور دریافت شد." };
    }
    return { response, data };
  }

  // --------------------------------------------------------------- toasts --

  function toast(message, kind = "info", timeout = 4500) {
    const stack = document.getElementById("toastStack");
    if (!stack) {
      return;
    }

    const el = document.createElement("div");
    el.className = `toast toast--${kind}`;
    el.innerHTML = `<span>${esc(message)}</span>`;
    stack.appendChild(el);

    setTimeout(() => {
      el.classList.add("is-leaving");
      setTimeout(() => el.remove(), 200);
    }, timeout);
  }

  // -------------------------------------------------------- account panel --

  function renderAccount() {
    document.querySelectorAll("#accountArea").forEach((area) => {
      const account = state.account;

      if (!account.is_authenticated) {
        area.innerHTML = `
          <button type="button" class="account-trigger" data-auth-open>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
            </svg>
            ورود / ثبت‌نام
          </button>`;
        return;
      }

      const initial = esc((account.display_name || "؟").trim().charAt(0));
      const quota = `${faDigits(account.unreviewed_orders)} از ${faDigits(account.max_unreviewed_orders)}`;

      area.innerHTML = `
        <button type="button" class="account-trigger" data-account-toggle>
          <span class="account-avatar">${initial}</span>
          <span>${esc(account.display_name)}</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        <div class="account-menu hidden" data-account-menu>
          <div class="account-menu-head">
            <strong>${esc(account.display_name)}</strong>
            <span>${esc(account.phone)}</span>
          </div>
          <div class="account-quota">سفارش‌های بررسی‌نشده: ${quota}</div>
          <a href="/orders/">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            سفارش‌های من
          </a>
          ${account.is_staff ? `
          <a href="/admin/">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l7 4v6c0 5-3 8-7 10-4-2-7-5-7-10V6z"/></svg>
            پنل مدیریت
          </a>` : ""}
          <button type="button" data-logout>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            خروج از حساب
          </button>
        </div>`;
    });
  }

  function setAccount(account) {
    state.account = account || { is_authenticated: false };
    renderAccount();
    document.dispatchEvent(new CustomEvent("pf:account", { detail: state.account }));
  }

  async function logout() {
    const { data } = await post("/api/auth/logout", new FormData());
    setAccount(data.user || { is_authenticated: false });
    toast(data.message || "از حساب کاربری خارج شدید.", "success");
  }

  // ----------------------------------------------------------- auth modal --

  const modal = document.getElementById("authModal");
  const alertBox = document.getElementById("authAlert");
  const introText = document.getElementById("authIntro");
  const titleText = document.getElementById("authTitle");
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");

  const DEFAULT_INTRO = "برای ادامه وارد شوید یا یک حساب کاربری بسازید.";

  function clearErrors() {
    if (!modal) return;
    alertBox.classList.add("hidden");
    alertBox.textContent = "";
    modal.querySelectorAll(".field").forEach((field) => {
      field.classList.remove("has-error");
      const err = field.querySelector(".field-error");
      if (err) err.remove();
    });
  }

  function showFormErrors(form, errors, fallback) {
    const entries = Object.entries(errors || {});
    const unattached = [];

    entries.forEach(([name, issues]) => {
      const message = issues.map((issue) => issue.message).join(" ");
      const field = form.querySelector(`.field[data-field="${name}"]`);

      if (!field) {
        // Non-field errors (__all__) have nowhere to sit, so they go on top.
        unattached.push(message);
        return;
      }

      field.classList.add("has-error");
      const span = document.createElement("span");
      span.className = "field-error";
      span.textContent = message;
      field.appendChild(span);
    });

    if (unattached.length) {
      showAlert(unattached.join(" "));
    } else if (!entries.length && fallback) {
      showAlert(fallback);
    }
  }

  function showAlert(message) {
    if (!alertBox) return;
    alertBox.textContent = message;
    alertBox.classList.remove("hidden");
  }

  function switchTab(tab) {
    if (!modal) return;
    modal.querySelectorAll("[data-auth-tab]").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.authTab === tab);
    });
    loginForm.classList.toggle("hidden", tab !== "login");
    registerForm.classList.toggle("hidden", tab !== "register");
    titleText.textContent = tab === "login" ? "ورود به حساب کاربری" : "ساخت حساب کاربری";
    clearErrors();
  }

  function openAuth(intro, tab = "login") {
    if (!modal) return Promise.resolve(null);

    introText.textContent = intro || DEFAULT_INTRO;
    switchTab(tab);
    modal.classList.remove("hidden");
    setTimeout(() => {
      const target = modal.querySelector("form:not(.hidden) input");
      if (target) target.focus();
    }, 60);

    return new Promise((resolve) => {
      state.authResolver = resolve;
    });
  }

  function closeAuth(account = null) {
    if (!modal) return;
    modal.classList.add("hidden");
    clearErrors();
    loginForm.reset();
    registerForm.reset();

    const resolve = state.authResolver;
    state.authResolver = null;
    if (resolve) resolve(account);
  }

  async function submitAuth(form, url) {
    clearErrors();

    const button = form.querySelector("[data-submit]");
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "لطفاً صبر کنید…";

    try {
      const { response, data } = await post(url, new FormData(form));

      if (!response.ok || !data.ok) {
        showFormErrors(form, data.errors, data.error);
        if (!data.errors && !data.error) {
          showAlert("خطایی رخ داد. دوباره تلاش کنید.");
        }
        return;
      }

      setAccount(data.user);
      toast(data.message || "خوش آمدید!", "success");
      closeAuth(data.user);
    } catch (err) {
      showAlert("ارتباط با سرور برقرار نشد. اتصال اینترنت خود را بررسی کنید.");
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }

  // ----------------------------------------------------------- wiring up --

  if (modal) {
    modal.querySelectorAll("[data-auth-tab]").forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.authTab));
    });

    document.getElementById("authClose").addEventListener("click", () => closeAuth(null));

    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeAuth(null);
    });

    loginForm.addEventListener("submit", (event) => {
      event.preventDefault();
      submitAuth(loginForm, "/api/auth/login");
    });

    registerForm.addEventListener("submit", (event) => {
      event.preventDefault();
      submitAuth(registerForm, "/api/auth/register");
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (modal && !modal.classList.contains("hidden")) closeAuth(null);
  });

  /* Delegated so the account markup can be re-rendered freely. */
  document.addEventListener("click", (event) => {
    const openBtn = event.target.closest("[data-auth-open]");
    if (openBtn) {
      openAuth();
      return;
    }

    const toggle = event.target.closest("[data-account-toggle]");
    if (toggle) {
      const menu = toggle.parentElement.querySelector("[data-account-menu]");
      if (menu) menu.classList.toggle("hidden");
      return;
    }

    if (event.target.closest("[data-logout]")) {
      logout();
      return;
    }

    // Any click elsewhere closes an open account menu.
    document.querySelectorAll("[data-account-menu]").forEach((menu) => {
      if (!menu.contains(event.target)) menu.classList.add("hidden");
    });
  });

  const bootstrap = document.getElementById("account-data");
  if (bootstrap) {
    try {
      state.account = JSON.parse(bootstrap.textContent) || state.account;
    } catch (err) {
      /* keep the anonymous default */
    }
  }
  renderAccount();

  return {
    get account() {
      return state.account;
    },
    isAuthenticated: () => Boolean(state.account.is_authenticated),
    setAccount,
    openAuth,
    closeAuth,
    logout,
    post,
    csrfToken,
    toast,
    faDigits,
    esc,
  };
})();
