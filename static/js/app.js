/*
 * Studio page: upload an image, render it with the chosen colour profile and
 * submit the result as an order.
 */
(() => {
  const byId = (id) => document.getElementById(id);

  const uploadZone = byId("uploadZone");
  const fileInput = byId("fileInput");
  const browseBtn = byId("browseBtn");
  const previewGrid = byId("previewGrid");
  const originalPreview = byId("originalPreview");
  const resultPreview = byId("resultPreview");
  const loadingOverlay = byId("loadingOverlay");
  const loadingText = byId("loadingText");
  const configForm = byId("configForm");
  const applyBtn = byId("applyBtn");
  const applyHint = byId("applyHint");
  const downloadBtn = byId("downloadBtn");
  const orderBtn = byId("orderBtn");
  const profileSelect = byId("profile_id");
  const palettePreview = byId("palettePreview");
  const paletteLayers = byId("paletteLayers");
  const paletteDescription = byId("paletteDescription");

  const modeSwitch = byId("modeSwitch");
  const segmentedThumb = byId("segmentedThumb");
  const readyIntro = byId("readyIntro");
  const readyZone = byId("readyZone");
  const readyInput = byId("readyInput");
  const readyBrowseBtn = byId("readyBrowseBtn");
  const readySection = byId("readySection");
  const readyPending = byId("readyPending");
  const readyResult = byId("readyResult");
  const readyVerdict = byId("readyVerdict");
  const readyPalette = byId("readyPalette");
  const readyLayers = byId("readyLayers");
  const readyCoverage = byId("readyCoverage");
  const readyReplace = byId("readyReplace");
  const copyPromptBtn = byId("copyPromptBtn");

  const sizeControls = byId("sizeControls");
  const sizeUnavailable = byId("sizeUnavailable");
  const sizeImpossible = byId("sizeImpossible");
  const sizeBounds = byId("sizeBounds");
  const sizeError = byId("sizeError");
  const widthInput = byId("width_cm");
  const heightInput = byId("height_cm");
  const widthRange = byId("width_range");
  const costValue = byId("costValue");

  const confirmModal = byId("confirmModal");
  const confirmThumb = byId("confirmThumb");
  const confirmProfile = byId("confirmProfile");
  const confirmLayers = byId("confirmLayers");
  const confirmSize = byId("confirmSize");
  const confirmCost = byId("confirmCost");
  const confirmQuota = byId("confirmQuota");
  const confirmMax = byId("confirmMax");
  const orderNote = byId("orderNote");

  function readJson(id, fallback) {
    const node = byId(id);
    if (!node) return fallback;
    try {
      return JSON.parse(node.textContent);
    } catch (err) {
      return fallback;
    }
  }

  const profiles = readJson("profiles-data", []);
  const settings = readJson("studio-settings", { maxUnreviewed: 3, openLogin: false });

  let hasImage = false;
  let isProcessing = false;
  let currentFile = null;
  let appliedConfig = null;      // JSON string of the config behind the preview
  let appliedConfigObj = null;   // …and the same thing as an object
  let sizing = readJson("sizing-data", null);  // frame limits + pricing
  let sizeValid = false;
  let mode = "studio";          // "studio" | "ready"
  let readyPaletteColors = null; // detected palette of a verified ready image

  // ----------------------------------------------------------- frame size --

  const round1 = (value) => Math.round(value * 10) / 10;

  function formatToman(value) {
    if (value == null || Number.isNaN(value)) return "—";
    const grouped = Math.round(value).toLocaleString("en-US").replace(/,/g, "٬");
    return `${PF.faDigits(grouped)} تومان`;
  }

  function computeCost(width, height) {
    const step = sizing.cost_rounding || 1;
    return Math.round((width * height * sizing.price_per_cm2) / step) * step;
  }

  function currentSize() {
    const width = parseFloat(widthInput.value);
    const height = parseFloat(heightInput.value);
    return { width, height };
  }

  /* Keep both boxes consistent: the frame always matches the photo's ratio. */
  function setWidth(width, { updateWidthBox = true } = {}) {
    const height = round1(width / sizing.ratio);
    if (updateWidthBox) widthInput.value = round1(width);
    heightInput.value = height;
    widthRange.value = round1(width);
    validateSize();
  }

  function setHeight(height) {
    const width = round1(height * sizing.ratio);
    widthInput.value = width;
    widthRange.value = width;
    validateSize();
  }

  function validateSize() {
    if (!sizing || !sizing.fits) {
      sizeValid = false;
      updateOrderState();
      return false;
    }

    const { width, height } = currentSize();
    const min = sizing.effective_min_width_cm;
    const max = sizing.effective_max_width_cm;

    let message = "";
    if (!Number.isFinite(width) || width <= 0) {
      message = "لطفاً اندازهٔ قاب را وارد کنید.";
    } else if (width < min || width > max) {
      message = `عرض قاب باید بین ${PF.faDigits(round1(min))} تا ${PF.faDigits(round1(max))} سانتی‌متر باشد.`;
    }

    sizeValid = message === "";
    sizeError.textContent = message;
    sizeError.classList.toggle("hidden", sizeValid);

    costValue.textContent = sizeValid ? formatToman(computeCost(width, height)) : "—";
    updateOrderState();
    return sizeValid;
  }

  function applySizing(next) {
    if (!next) return;

    // A different aspect ratio means a different photo, so start fresh;
    // otherwise keep whatever size the visitor already dialled in.
    const isNewImage = !sizing || !sizing.ratio || Math.abs(sizing.ratio - next.ratio) > 1e-9;
    const previousWidth = parseFloat(widthInput.value);
    sizing = next;

    sizeUnavailable.classList.add("hidden");

    if (!next.fits) {
      sizeControls.classList.add("hidden");
      sizeImpossible.classList.remove("hidden");
      sizeValid = false;
      updateOrderState();
      return;
    }

    sizeImpossible.classList.add("hidden");
    sizeControls.classList.remove("hidden");

    const min = next.effective_min_width_cm;
    const max = next.effective_max_width_cm;

    widthRange.min = min;
    widthRange.max = max;
    widthInput.min = min;
    widthInput.max = max;
    heightInput.min = round1(min / next.ratio);
    heightInput.max = round1(max / next.ratio);

    sizeBounds.textContent =
      `عرض مجاز: ${PF.faDigits(round1(min))} تا ${PF.faDigits(round1(max))} سانتی‌متر` +
      ` — ارتفاع متناظر: ${PF.faDigits(round1(min / next.ratio))} تا ${PF.faDigits(round1(max / next.ratio))} سانتی‌متر`;

    const startWidth =
      isNewImage || !Number.isFinite(previousWidth)
        ? next.default_width_cm
        : Math.min(Math.max(previousWidth, min), max);

    setWidth(startWidth);
  }

  // ------------------------------------------------------------- profiles --

  function profileById(id) {
    return profiles.find((profile) => String(profile.id) === String(id)) || null;
  }

  function selectedProfile() {
    return profileSelect ? profileById(profileSelect.value) : null;
  }

  function renderPalette() {
    const profile = selectedProfile();
    if (!profile || !palettePreview) return;

    palettePreview.innerHTML = profile.colors
      .map((color) => `<span class="palette-chip" style="background:${color}" title="${color}"></span>`)
      .join("");
    paletteLayers.textContent = PF.faDigits(profile.num_layers);
    paletteDescription.textContent = profile.description || "";
  }

  // --------------------------------------------------------------- config --

  function getFormConfig() {
    const config = {};
    new FormData(configForm).forEach((value, key) => {
      config[key] = value;
    });

    config.preserve_edges = byId("preserve_edges").checked ? "true" : "false";
    config.use_superpixels = byId("use_superpixels").checked ? "true" : "false";

    const postMedian = byId("median_kernel_size_post");
    if (postMedian && !postMedian.disabled) {
      config.median_kernel_size = postMedian.value;
    }

    return config;
  }

  function configToString(config) {
    return JSON.stringify(config, Object.keys(config).sort());
  }

  function configToFormData(config) {
    const formData = new FormData();
    Object.entries(config).forEach(([key, value]) => formData.append(key, value));
    return formData;
  }

  function updateConditionalFields() {
    const preprocess = byId("preprocess_method").value;
    const postprocess = byId("postprocess_method").value;
    const useSuperpixels = byId("use_superpixels").checked;

    document.querySelectorAll("[data-show-when]").forEach((el) => {
      const [field, expected] = el.dataset.showWhen.split(":");
      let visible = false;

      if (field === "preprocess_method") {
        visible = preprocess === expected;
      } else if (field === "postprocess_method") {
        visible = postprocess === expected;
      } else if (field === "use_superpixels") {
        visible = useSuperpixels;
      }

      el.classList.toggle("is-hidden", !visible);
      el.querySelectorAll("input, select, textarea").forEach((input) => {
        input.disabled = !visible;
      });
    });
  }

  function updateApplyState() {
    if (isReady()) {
      // Nothing to re-render: the artwork is the customer's own.
      applyBtn.classList.add("hidden");
      applyHint.textContent = hasImage
        ? "تصویر آمادهٔ شما تأیید شد — اندازه را انتخاب و سفارش را ثبت کنید"
        : "تصویر لایه‌ای آمادهٔ خود را بارگذاری کنید";
      return;
    }
    applyBtn.classList.remove("hidden");

    if (!hasImage || isProcessing) {
      applyBtn.disabled = true;
      applyBtn.classList.remove("is-ready");
      if (!hasImage) applyHint.textContent = "برای شروع یک تصویر بارگذاری کنید";
      return;
    }

    const dirty = appliedConfig === null || configToString(getFormConfig()) !== appliedConfig;

    applyBtn.disabled = !dirty;
    applyBtn.classList.toggle("is-ready", dirty);

    if (appliedConfig === null) {
      applyHint.textContent = "در حال پردازش تصویر…";
    } else if (dirty) {
      applyHint.textContent = "تنظیمات تغییر کرده — برای بازسازی «اعمال تغییرات» را بزنید";
    } else {
      applyHint.textContent = "تنظیمات با تصویر فعلی هماهنگ است";
    }
  }

  function updateOrderState() {
    if (!orderBtn) return;
    const ready = !isReady() || Boolean(readyPaletteColors);
    orderBtn.disabled = !hasImage || isProcessing || !appliedConfigObj || !sizeValid || !ready;
  }

  function setLoading(active, message) {
    isProcessing = active;
    if (message && loadingText) loadingText.textContent = message;
    loadingOverlay.classList.toggle("hidden", !active);
    updateApplyState();
    updateOrderState();
  }

  // ------------------------------------------------------------ rendering --

  function showPreview(originalUrl, resultUrl) {
    uploadZone.classList.add("hidden");
    if (readyIntro) readyIntro.classList.add("hidden");
    previewGrid.classList.remove("hidden");

    originalPreview.src = originalUrl;
    resultPreview.src = resultUrl;
    downloadBtn.disabled = false;
  }

  async function processImage(includeFile = false) {
    if (!profileSelect) {
      PF.toast("هیچ پروفایل رنگی فعالی وجود ندارد.", "error");
      return;
    }

    const snapshot = getFormConfig();
    const formData = configToFormData(snapshot);

    if (includeFile && currentFile) {
      formData.append("image", currentFile);
    }

    setLoading(true, "در حال پردازش تصویر…");

    try {
      const { response, data } = await PF.post("/api/process", formData);

      if (!response.ok) {
        throw new Error(data.error || "پردازش تصویر ناموفق بود.");
      }

      showPreview(data.original_url, data.result_url);
      // Remember the settings that produced this preview, so "Apply" knows when
      // something really changed and an order always matches what is on screen.
      appliedConfigObj = snapshot;
      appliedConfig = configToString(snapshot);
      hasImage = true;
      applySizing(data.sizing);
    } catch (err) {
      PF.toast(err.message || "پردازش تصویر ناموفق بود.", "error", 6000);
    } finally {
      setLoading(false);
    }
  }

  function handleFile(file) {
    if (!file || !file.type.startsWith("image/")) {
      PF.toast("لطفاً یک فایل تصویر معتبر انتخاب کنید.", "error");
      return;
    }

    currentFile = file;
    hasImage = true;
    appliedConfig = null;
    appliedConfigObj = null;
    processImage(true);
  }

  // ---------------------------------------------------------- ready images --

  function isReady() {
    return mode === "ready";
  }

  /*
   * Slide the highlight onto the active option. Measured rather than hard-coded
   * because the two labels differ in width, and Vazirmatn loads asynchronously
   * so the widths change once the font arrives.
   */
  function positionThumb() {
    if (!modeSwitch || !segmentedThumb) return;

    const active = modeSwitch.querySelector(".segmented-option.is-active");
    if (!active) return;

    const track = modeSwitch.getBoundingClientRect();
    const option = active.getBoundingClientRect();

    segmentedThumb.style.width = `${option.width}px`;
    segmentedThumb.style.transform =
      `translateX(${option.left - track.left - modeSwitch.clientLeft}px)`;
  }

  function setMode(next) {
    if (mode === next) return;
    mode = next;

    document.querySelectorAll("[data-mode]").forEach((btn) => {
      const on = btn.dataset.mode === next;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    positionThumb();
    document.querySelectorAll(".studio-only").forEach((el) => el.classList.toggle("hidden", isReady()));
    document.querySelectorAll(".ready-only").forEach((el) => el.classList.toggle("hidden", !isReady()));

    // Each mode starts from a blank slate so the two paths never mix.
    resetWorkspace();
  }

  function resetWorkspace() {
    hasImage = false;
    currentFile = null;
    appliedConfig = null;
    appliedConfigObj = null;
    readyPaletteColors = null;
    sizeValid = false;

    previewGrid.classList.add("hidden");
    uploadZone.classList.toggle("hidden", isReady());
    if (readyIntro) readyIntro.classList.toggle("hidden", !isReady());

    if (readyResult) readyResult.classList.add("hidden");
    if (readyPending) readyPending.classList.remove("hidden");

    sizeControls.classList.add("hidden");
    sizeImpossible.classList.add("hidden");
    sizeUnavailable.classList.remove("hidden");
    downloadBtn.disabled = true;
    resultPreview.removeAttribute("src");
    originalPreview.removeAttribute("src");

    updateApplyState();
    updateOrderState();
  }

  function showReadyReport(data) {
    readyPaletteColors = data.colors;

    readyPending.classList.add("hidden");
    readyResult.classList.remove("hidden");
    readyVerdict.textContent = data.message;
    readyPalette.innerHTML = data.colors
      .map((color) => `<span class="palette-chip" style="background:${color}" title="${color}"></span>`)
      .join("");
    readyLayers.textContent = PF.faDigits(data.color_count);
    readyCoverage.textContent = `پوشش رنگ‌ها: ${PF.faDigits(data.coverage)}٪`;
  }

  async function verifyReadyImage(file) {
    if (!file || !file.type.startsWith("image/")) {
      PF.toast("لطفاً یک فایل تصویر معتبر انتخاب کنید.", "error");
      return;
    }

    const formData = new FormData();
    formData.append("image", file);

    setLoading(true, "در حال بررسی تصویر…");

    try {
      const { response, data } = await PF.post("/api/ready/verify", formData);

      if (!response.ok || !data.ok) {
        readyPaletteColors = null;
        readyResult.classList.add("hidden");
        readyPending.classList.remove("hidden");
        hasImage = false;
        PF.toast(data.error || "بررسی تصویر ناموفق بود.", "error", 8000);
        return;
      }

      showPreview(data.original_url, data.result_url);
      showReadyReport(data);
      hasImage = true;
      // A verified ready image needs no processing config; the order path
      // keys off the mode instead.
      appliedConfigObj = { source: "ready" };
      appliedConfig = configToString(appliedConfigObj);
      applySizing(data.sizing);
    } catch (err) {
      PF.toast("ارتباط با سرور برقرار نشد.", "error");
    } finally {
      setLoading(false);
    }
  }

  // --------------------------------------------------------------- orders --

  function openConfirm() {
    const account = PF.account;
    const { width, height } = currentSize();

    confirmThumb.src = resultPreview.src;

    if (isReady()) {
      confirmProfile.textContent = "تصویر آمادهٔ شما";
      confirmLayers.textContent = PF.faDigits(readyPaletteColors ? readyPaletteColors.length : 0);
    } else {
      const profile = profileById(appliedConfigObj.profile_id) || selectedProfile();
      confirmProfile.textContent = profile ? profile.name : "—";
      confirmLayers.textContent = profile ? PF.faDigits(profile.num_layers) : "—";
    }
    confirmSize.textContent = `${PF.faDigits(round1(width))} × ${PF.faDigits(round1(height))} سانتی‌متر`;
    confirmCost.textContent = formatToman(computeCost(width, height));
    confirmQuota.textContent = `${PF.faDigits(account.unreviewed_orders || 0)} از ${PF.faDigits(
      account.max_unreviewed_orders || settings.maxUnreviewed
    )}`;
    confirmMax.textContent = PF.faDigits(account.max_unreviewed_orders || settings.maxUnreviewed);

    confirmModal.classList.remove("hidden");
  }

  function closeConfirm() {
    confirmModal.classList.add("hidden");
  }

  async function startOrder() {
    if (!hasImage || !appliedConfigObj) {
      PF.toast("ابتدا یک تصویر بسازید.", "error");
      return;
    }

    if (!validateSize()) {
      PF.toast(sizeError.textContent || "اندازهٔ قاب معتبر نیست.", "error");
      return;
    }

    if (!PF.isAuthenticated()) {
      const account = await PF.openAuth(
        "برای ثبت سفارش ابتدا وارد حساب کاربری خود شوید. تصویری که ساخته‌اید حفظ می‌شود."
      );
      if (!account) return; // cancelled — the render stays exactly as it was
    }

    const account = PF.account;
    if (account.unreviewed_orders >= account.max_unreviewed_orders) {
      PF.toast(
        `شما ${PF.faDigits(account.max_unreviewed_orders)} سفارش بررسی‌نشده دارید. تا بررسی آن‌ها امکان ثبت سفارش جدید نیست.`,
        "error",
        6000
      );
      return;
    }

    openConfirm();
  }

  async function confirmOrder() {
    const button = byId("confirmSubmit");
    button.disabled = true;
    button.textContent = "در حال ثبت…";

    const formData = isReady() ? new FormData() : configToFormData(appliedConfigObj);
    if (isReady()) formData.append("source", "ready");
    formData.append("note", orderNote.value || "");
    // The server re-derives the height and recomputes the price from this.
    formData.append("width_cm", round1(currentSize().width));

    try {
      const { response, data } = await PF.post("/api/orders/create", formData);

      if (!response.ok || !data.ok) {
        if (data.auth_required) {
          closeConfirm();
          const account = await PF.openAuth("نشست شما منقضی شده است. دوباره وارد شوید.");
          if (account) openConfirm();
          return;
        }
        throw new Error(data.error || "ثبت سفارش ناموفق بود.");
      }

      PF.setAccount(data.user);
      closeConfirm();
      orderNote.value = "";
      PF.toast(data.message, "success", 6000);
    } catch (err) {
      PF.toast(err.message || "ثبت سفارش ناموفق بود.", "error", 6000);
    } finally {
      button.disabled = false;
      button.textContent = "بله، سفارش را ثبت کن";
    }
  }

  // ---------------------------------------------------------------- wiring --

  browseBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  uploadZone.addEventListener("click", () => fileInput.click());

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) {
      handleFile(fileInput.files[0]);
    }
  });

  uploadZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadZone.classList.add("dragover");
  });

  uploadZone.addEventListener("dragleave", () => {
    uploadZone.classList.remove("dragover");
  });

  uploadZone.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadZone.classList.remove("dragover");
    if (e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  applyBtn.addEventListener("click", () => processImage(false));

  downloadBtn.addEventListener("click", () => {
    if (!resultPreview.src) return;
    const link = document.createElement("a");
    link.href = resultPreview.src;
    link.download = "photo-frame-3d.png";
    link.click();
  });

  if (orderBtn) {
    orderBtn.addEventListener("click", startOrder);
  }

  if (confirmModal) {
    byId("confirmSubmit").addEventListener("click", confirmOrder);
    byId("confirmCancel").addEventListener("click", closeConfirm);
    byId("confirmClose").addEventListener("click", closeConfirm);
    confirmModal.addEventListener("click", (event) => {
      if (event.target === confirmModal) closeConfirm();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeConfirm();
    });
  }

  if (profileSelect) {
    profileSelect.addEventListener("change", renderPalette);
  }

  document.querySelectorAll("[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => setMode(btn.dataset.mode));
  });

  if (readyZone) {
    readyBrowseBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      readyInput.click();
    });
    readyZone.addEventListener("click", () => readyInput.click());
    readyInput.addEventListener("change", () => {
      if (readyInput.files[0]) verifyReadyImage(readyInput.files[0]);
    });
    readyZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      readyZone.classList.add("dragover");
    });
    readyZone.addEventListener("dragleave", () => readyZone.classList.remove("dragover"));
    readyZone.addEventListener("drop", (e) => {
      e.preventDefault();
      readyZone.classList.remove("dragover");
      if (e.dataTransfer.files[0]) verifyReadyImage(e.dataTransfer.files[0]);
    });
  }

  if (readyReplace) {
    readyReplace.addEventListener("click", () => readyInput.click());
  }

  if (copyPromptBtn) {
    copyPromptBtn.addEventListener("click", async () => {
      const text = byId("aiPrompt").textContent;
      try {
        await navigator.clipboard.writeText(text);
      } catch (err) {
        // Clipboard API needs a secure context; fall back to a selection.
        const range = document.createRange();
        range.selectNodeContents(byId("aiPrompt"));
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        document.execCommand("copy");
        selection.removeAllRanges();
      }
      PF.toast("متن پرامپت کپی شد.", "success");
    });
  }

  // Frame size: the two boxes and the slider all drive each other through the
  // image's aspect ratio. Clamping happens on blur so typing is never fought.
  widthRange.addEventListener("input", () => setWidth(parseFloat(widthRange.value)));

  widthInput.addEventListener("input", () => {
    const value = parseFloat(widthInput.value);
    if (Number.isFinite(value)) setWidth(value, { updateWidthBox: false });
    else validateSize();
  });

  heightInput.addEventListener("input", () => {
    const value = parseFloat(heightInput.value);
    if (Number.isFinite(value)) setHeight(value);
    else validateSize();
  });

  [widthInput, heightInput].forEach((input) => {
    input.addEventListener("blur", () => {
      if (!sizing || !sizing.fits) return;
      const value = parseFloat(widthInput.value);
      const clamped = Math.min(
        Math.max(Number.isFinite(value) ? value : sizing.default_width_cm, sizing.effective_min_width_cm),
        sizing.effective_max_width_cm
      );
      setWidth(clamped);
    });
  });

  configForm.addEventListener("input", () => {
    updateConditionalFields();
    updateApplyState();
  });

  configForm.addEventListener("change", () => {
    updateConditionalFields();
    updateApplyState();
  });

  document.addEventListener("pf:account", updateOrderState);

  positionThumb();
  window.addEventListener("resize", positionThumb);
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(positionThumb);
  }

  renderPalette();
  updateConditionalFields();
  updateApplyState();
  updateOrderState();

  if (settings.openLogin && !PF.isAuthenticated()) {
    PF.openAuth("برای مشاهدهٔ این بخش ابتدا وارد حساب کاربری خود شوید.");
  }
})();
