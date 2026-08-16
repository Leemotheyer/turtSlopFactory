(function () {
  "use strict";

  const LIMITS = { title: 200, body: 2000 };

  const els = {
    appName: document.getElementById("app-name"),
    appDescription: document.getElementById("app-description"),
    healthStatus: document.getElementById("health-status"),
    form: document.getElementById("item-form"),
    titleInput: document.getElementById("item-title"),
    bodyInput: document.getElementById("item-body"),
    titleError: document.getElementById("title-error"),
    bodyError: document.getElementById("body-error"),
    submitBtn: document.getElementById("submit-btn"),
    refreshBtn: document.getElementById("refresh-btn"),
    retryBtn: document.getElementById("retry-btn"),
    itemCount: document.getElementById("item-count"),
    listLoading: document.getElementById("list-loading"),
    listError: document.getElementById("list-error"),
    listErrorMessage: document.getElementById("list-error-message"),
    itemsList: document.getElementById("items-list"),
    listEmpty: document.getElementById("list-empty"),
    toastContainer: document.getElementById("toast-container"),
  };

  /** @param {string} path */
  async function apiFetch(path, options) {
    const res = await fetch(path, options);
    let data = null;
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      data = await res.json();
    } else if (!res.ok) {
      data = { detail: await res.text() };
    }
    if (!res.ok) {
      const message =
        (data && (data.detail || data.message)) ||
        `Request failed (${res.status})`;
      throw new Error(typeof message === "string" ? message : JSON.stringify(message));
    }
    return data;
  }

  function setHealthStatus(state, label) {
    const dot = els.healthStatus.querySelector(".status-dot");
    const text = els.healthStatus.querySelector(".status-label");
    dot.className = "status-dot status-dot--" + state;
    text.textContent = label;
  }

  async function loadHealth() {
    try {
      const data = await apiFetch("health");
      setHealthStatus("ok", data.status === "ok" ? "Online" : String(data.status));
    } catch {
      setHealthStatus("error", "Offline");
    }
  }

  async function loadInfo() {
    try {
      const info = await apiFetch("api/info");
      if (info.name) els.appName.textContent = info.name;
      if (info.description) els.appDescription.textContent = info.description;
    } catch {
      /* keep defaults */
    }
  }

  function showListState(state) {
    els.listLoading.hidden = state !== "loading";
    els.listError.hidden = state !== "error";
    els.itemsList.hidden = state !== "items";
    els.listEmpty.hidden = state !== "empty";
  }

  function renderItems(items) {
    els.itemsList.innerHTML = items
      .map(function (item) {
        const body = item.body
          ? '<p class="item-card__body">' + escapeHtml(item.body) + "</p>"
          : "";
        return (
          '<li class="item-card">' +
          '<div class="item-card__header">' +
          '<h3 class="item-card__title">' +
          escapeHtml(item.title) +
          "</h3>" +
          '<span class="item-card__id">#' +
          item.id +
          "</span>" +
          "</div>" +
          body +
          "</li>"
        );
      })
      .join("");

    const count = items.length;
    els.itemCount.textContent =
      count === 0
        ? "No items in queue"
        : count === 1
          ? "1 item in queue"
          : count + " items in queue";
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  async function loadItems() {
    showListState("loading");
    els.refreshBtn.disabled = true;

    try {
      const items = await apiFetch("api/items");
      if (!Array.isArray(items) || items.length === 0) {
        showListState("empty");
        els.itemCount.textContent = "No items in queue";
      } else {
        renderItems(items);
        showListState("items");
      }
    } catch (err) {
      els.listErrorMessage.textContent = err.message || "Something went wrong.";
      showListState("error");
      els.itemCount.textContent = "Could not load items";
    } finally {
      els.refreshBtn.disabled = false;
      els.refreshBtn.classList.remove("is-spinning");
    }
  }

  function clearFieldError(input, errorEl) {
    input.classList.remove("field__input--invalid");
    errorEl.hidden = true;
    errorEl.textContent = "";
  }

  function setFieldError(input, errorEl, message) {
    input.classList.add("field__input--invalid");
    errorEl.hidden = false;
    errorEl.textContent = message;
  }

  function validateForm() {
    let valid = true;
    clearFieldError(els.titleInput, els.titleError);
    clearFieldError(els.bodyInput, els.bodyError);

    const title = els.titleInput.value.trim();
    const body = els.bodyInput.value.trim();

    if (!title) {
      setFieldError(els.titleInput, els.titleError, "Title is required.");
      valid = false;
    } else if (title.length > LIMITS.title) {
      setFieldError(
        els.titleInput,
        els.titleError,
        "Title must be " + LIMITS.title + " characters or fewer."
      );
      valid = false;
    }

    if (body.length > LIMITS.body) {
      setFieldError(
        els.bodyInput,
        els.bodyError,
        "Details must be " + LIMITS.body + " characters or fewer."
      );
      valid = false;
    }

    return valid;
  }

  function setSubmitLoading(loading) {
    els.submitBtn.disabled = loading;
    els.submitBtn.classList.toggle("btn--loading", loading);
    els.submitBtn.querySelector(".btn__spinner").hidden = !loading;
  }

  function showToast(message, type) {
    type = type || "info";
    const toast = document.createElement("div");
    toast.className = "toast toast--" + type;
    toast.textContent = message;
    els.toastContainer.appendChild(toast);
    setTimeout(function () {
      toast.remove();
    }, 4000);
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!validateForm()) return;

    setSubmitLoading(true);

    try {
      await apiFetch("api/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: els.titleInput.value.trim(),
          body: els.bodyInput.value.trim(),
        }),
      });
      els.form.reset();
      clearFieldError(els.titleInput, els.titleError);
      clearFieldError(els.bodyInput, els.bodyError);
      showToast("Work item added to queue", "success");
      await loadItems();
    } catch (err) {
      showToast(err.message || "Failed to add item", "error");
    } finally {
      setSubmitLoading(false);
    }
  }

  function handleRefresh() {
    els.refreshBtn.classList.add("is-spinning");
    loadItems();
  }

  els.form.addEventListener("submit", handleSubmit);
  els.refreshBtn.addEventListener("click", handleRefresh);
  els.retryBtn.addEventListener("click", loadItems);

  els.titleInput.addEventListener("input", function () {
    if (els.titleInput.classList.contains("field__input--invalid")) {
      validateForm();
    }
  });

  els.bodyInput.addEventListener("input", function () {
    if (els.bodyInput.classList.contains("field__input--invalid")) {
      validateForm();
    }
  });

  loadHealth();
  loadInfo();
  loadItems();
})();
