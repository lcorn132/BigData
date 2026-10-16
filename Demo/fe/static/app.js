const API = (window.RECSYS_API_BASE_URL || "").replace(/\/$/, "");
const $ = (selector) => document.querySelector(selector);
const state = { productPage: 1, productPages: 1, toastTimer: null };

function setViewFromHash() {
  const requested = window.location.hash === "#view=dashboard" ? "dashboard" : "web";
  document.querySelectorAll(".app-view").forEach((view) => {
    view.hidden = view.dataset.view !== requested;
  });
  document.querySelectorAll("[data-view-target]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.viewTarget === requested);
  });
  document.body.dataset.activeView = requested;
  window.scrollTo({ top: 0, behavior: "instant" });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatNumber(value, digits = 0) {
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("vi-VN", { maximumFractionDigits: digits }).format(number)
    : "—";
}

function formatPrice(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "Chưa có giá";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(number);
}

function brandLabel(item) {
  return item.brand || "Không rõ thương hiệu";
}

function categoryLabel(item) {
  if (item.category_code) return item.category_code.split(".").filter(Boolean).join(" / ");
  return item.category_id ? `Category ${item.category_id}` : "Chưa phân loại";
}

function colorIndex(id) {
  return String(id).split("").reduce((sum, char) => sum + char.charCodeAt(0), 0) % 6;
}

function productCard(item, detail = "") {
  const score = item.als_score == null ? "" : `<span>ALS ${Number(item.als_score).toFixed(4)}</span>`;
  const rank = item.rank == null ? "" : `<b class="rank">#${item.rank}</b>`;
  return `
    <article class="product-card tone-${colorIndex(item.product_id)}">
      <div class="product-art"><span></span>${rank}</div>
      <div class="product-copy">
        <p>${escapeHtml(brandLabel(item))}</p>
        <h3>Product ${escapeHtml(item.product_id)}</h3>
        <small>${escapeHtml(categoryLabel(item))}</small>
        <div><strong>${formatPrice(item.price)}</strong>${score}</div>
        ${detail}
      </div>
    </article>`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
}

async function request(path) {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `API ${response.status}`);
  }
  return response.json();
}

function setSystemState(ready) {
  const element = $("#system-state");
  element.classList.toggle("offline", !ready);
  element.lastChild.textContent = ready ? " Hệ thống sẵn sàng" : " Chưa nạp dữ liệu";
}

async function loadFilters() {
  const data = await request("/api/v1/products/filters");
  const select = $("#brand-filter");
  for (const row of data.brands || []) {
    const option = document.createElement("option");
    option.value = row.value;
    option.textContent = `${row.value} (${formatNumber(row.count)})`;
    select.append(option);
  }
}

async function loadProducts(page = 1) {
  const params = new URLSearchParams({ page: String(page), page_size: "24" });
  const values = {
    q: $("#product-search").value.trim(),
    brand: $("#brand-filter").value,
    min_price: $("#price-min").value,
    max_price: $("#price-max").value,
  };
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value);
  try {
    const data = await request(`/api/v1/products?${params}`);
    state.productPage = data.page;
    state.productPages = data.pages;
    $("#product-grid").innerHTML = data.items.map((item) => productCard(item)).join("");
    $("#product-count").textContent = `${formatNumber(data.total)} sản phẩm`;
    $("#product-page-label").textContent = `Trang ${data.page}/${data.pages}`;
    $("#product-empty").classList.toggle("hidden", data.items.length > 0);
    $("#previous-products").disabled = data.page <= 1;
    $("#next-products").disabled = data.page >= data.pages;
  } catch (error) {
    $("#product-count").textContent = "Không thể tải catalog";
    $("#product-empty").classList.remove("hidden");
    showToast(error.message);
  }
}

function renderHistory(data) {
  $("#history-total").textContent = `${formatNumber(data.total_products)} sản phẩm đã tương tác`;
  $("#history-list").innerHTML = (data.items || []).map((item) => `
    <article>
      <div><strong>Product ${escapeHtml(item.product_id)}</strong><span>${escapeHtml(brandLabel(item))}</span></div>
      <dl><div><dt>View</dt><dd>${formatNumber(item.view_count)}</dd></div><div><dt>Cart</dt><dd>${formatNumber(item.cart_count)}</dd></div><div><dt>Purchase</dt><dd>${formatNumber(item.purchase_count)}</dd></div></dl>
    </article>`).join("");
  $("#history-empty").classList.toggle("hidden", (data.items || []).length > 0);
}

async function loadUser() {
  const userId = $("#user-id").value.trim();
  if (!userId) return showToast("Hãy nhập hoặc chọn một User ID.");
  $("#strategy-badge").textContent = "Đang tải…";
  try {
    const [recommendations, history] = await Promise.all([
      request(`/api/v1/recommendations/${encodeURIComponent(userId)}?limit=10`),
      request(`/api/v1/users/${encodeURIComponent(userId)}/history?limit=30`),
    ]);
    $("#recommendation-grid").innerHTML = recommendations.items.map((item) => productCard(item)).join("");
    $("#recommendation-empty").classList.toggle("hidden", recommendations.items.length > 0);
    const personalized = recommendations.strategy === "als_count_c3";
    $("#strategy-badge").textContent = personalized ? "COUNT_C3 · Cá nhân hóa" : "Popularity · User mới";
    $("#strategy-badge").classList.toggle("fallback", !personalized);
    renderHistory(history);
  } catch (error) {
    $("#strategy-badge").textContent = "Lỗi dữ liệu";
    $("#recommendation-empty").classList.remove("hidden");
    $("#history-empty").classList.remove("hidden");
    showToast(error.message);
  }
}

function metricBar(label, value, max, note = "") {
  const width = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return `<div class="bar-row"><div><span>${escapeHtml(label)}</span><strong>${formatNumber(value, 4)}%</strong></div><div class="bar-track"><i style="width:${width}%"></i></div>${note ? `<small>${escapeHtml(note)}</small>` : ""}</div>`;
}

function findArray(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node) && node.length && node.every((row) => row && typeof row === "object") && predicate(node[0])) return node;
  for (const value of Object.values(node)) {
    const found = findArray(value, predicate);
    if (found) return found;
  }
  return null;
}

function numericCount(row) {
  for (const key of ["count", "event_count", "events", "total", "value"]) {
    if (Number.isFinite(Number(row[key]))) return Number(row[key]);
  }
  return 0;
}

function renderDashboard(data) {
  const source = data.data_source || {};
  const sourceStatus = $("#data-source-status");
  if (sourceStatus) {
    sourceStatus.textContent = source.hdfs_synced
      ? `HDFS đã đồng bộ · ${source.hdfs_path || "serving_export"}`
      : "Đang dùng SQLite cache local";
    sourceStatus.classList.toggle("local", !source.hdfs_synced);
  }
  const report = data.evaluation_report || {};
  const winner = report.test_evaluation?.winner || {};
  const baseline = report.test_evaluation?.baseline || {};
  const validationCoverage = report.ground_truth_coverage?.validation || {};
  const testCoverage = report.ground_truth_coverage?.test || {};
  const metrics = [
    ["Test Recall@10", winner.macro_recall_at_10, "COUNT_C3"],
    ["Test Precision@10", winner.macro_precision_at_10, "COUNT_C3"],
    ["Validation coverage", validationCoverage.pair_coverage, `${formatNumber(validationCoverage.known_purchase_pairs)} cặp warm-start`],
    ["Test coverage", testCoverage.pair_coverage, `${formatNumber(testCoverage.known_purchase_pairs)} cặp warm-start`],
  ];
  if (metrics.every((row) => Number.isFinite(Number(row[1])))) {
    $("#metric-grid").innerHTML = metrics.map(([label, value, note]) => `<article><span>${label}</span><strong>${formatNumber(Number(value) * 100, 4)}%</strong><small>${note}</small></article>`).join("");
  }
  const comparison = [
    ["COUNT_C3 Recall@10", Number(winner.macro_recall_at_10 || 0) * 100],
    ["Popularity Recall@10", Number(baseline.macro_recall_at_10 || 0) * 100],
    ["COUNT_C3 Precision@10", Number(winner.macro_precision_at_10 || 0) * 100],
    ["Popularity Precision@10", Number(baseline.macro_precision_at_10 || 0) * 100],
  ];
  const maxMetric = Math.max(...comparison.map((row) => row[1]), 1);
  $("#model-chart").innerHTML = comparison.map(([label, value]) => metricBar(label, value, maxMetric)).join("");

  const eventRows = findArray(data.dashboard_stats, (row) => "event_type" in row);
  if (eventRows) {
    const totals = new Map();
    for (const row of eventRows) {
      totals.set(row.event_type, (totals.get(row.event_type) || 0) + numericCount(row));
    }
    const rows = [...totals.entries()].filter((row) => row[1] > 0);
    const maxEvent = Math.max(...rows.map((row) => row[1]), 1);
    $("#event-chart").innerHTML = rows.map(([label, value]) => metricBar(label, value, maxEvent, `${formatNumber(value)} sự kiện`)).join("");
  } else {
    $("#event-chart").innerHTML = '<p class="muted">Thống kê sự kiện chưa có trong dữ liệu phục vụ.</p>';
  }
}

async function initialize() {
  try {
    const health = await request("/health");
    if (!health.data_ready) throw new Error("Chưa nạp serving_export vào cơ sở dữ liệu.");
    setSystemState(true);
    const [users, dashboard] = await Promise.all([
      request("/api/v1/demo-users?limit=20"),
      request("/api/v1/dashboard"),
      loadFilters(),
      loadProducts(),
    ]);
    const list = users.users || [];
    $("#demo-user-list").innerHTML = list.map((id) => `<option value="${escapeHtml(id)}"></option>`).join("");
    if (list.length) {
      $("#user-id").value = list[0];
      await loadUser();
    }
    renderDashboard(dashboard);
  } catch (error) {
    setSystemState(false);
    showToast(error.message);
  }
}

$("#product-filters").addEventListener("submit", (event) => { event.preventDefault(); loadProducts(1); });
$("#previous-products").addEventListener("click", () => loadProducts(state.productPage - 1));
$("#next-products").addEventListener("click", () => loadProducts(state.productPage + 1));
$("#load-user").addEventListener("click", loadUser);
$("#user-id").addEventListener("keydown", (event) => { if (event.key === "Enter") loadUser(); });
window.addEventListener("hashchange", setViewFromHash);

setViewFromHash();
initialize();
