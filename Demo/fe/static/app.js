const API = (window.RECSYS_API_BASE_URL || "").replace(/\/$/, "");
const $ = (selector) => document.querySelector(selector);
const state = {
  productPage: 1,
  productPages: 1,
  products: new Map(),
  cart: new Map(),
  favorites: new Set(),
  selectedProduct: null,
  toastTimer: null,
};

const categoryQueries = {
  serum: "Tinh chất", cream: "Kem dưỡng", lipstick: "Son môi",
  palette: "Bảng màu mắt", perfume: "Nước hoa",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
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
  return Number.isFinite(number)
    ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(number)
    : "Liên hệ";
}

function setViewFromHash() {
  const dashboard = window.location.hash === "#view=dashboard";
  const requested = dashboard ? "dashboard" : "web";
  document.querySelectorAll(".app-view").forEach((view) => {
    view.hidden = view.dataset.view !== requested;
  });
  document.querySelectorAll("[data-view-target]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.viewTarget === requested);
  });
  document.body.dataset.activeView = requested;
  if (window.location.hash.startsWith("#view=")) window.scrollTo({ top: 0, behavior: "instant" });
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

function brandLabel(item) {
  return item.display_brand || item.brand || "Muse Studio";
}

function productName(item) {
  return item.display_name || `Sản phẩm ${item.product_id}`;
}

function productVisual(item, extraClass = "") {
  const key = escapeHtml(item.image_key || "serum");
  return `<div class="product-visual visual-${key} ${extraClass}">
    <span class="visual-glow"></span><i class="pack pack-${key}"></i><b>${escapeHtml(brandLabel(item).slice(0, 12))}</b>
  </div>`;
}

function ratingMarkup(item) {
  const value = Number(item.demo_rating || 4.5);
  return `<span class="stars">★★★★★</span><span>${value.toFixed(1)} · ${formatNumber(item.demo_review_count || 0)}</span>`;
}

function productCard(item, compact = false) {
  const id = String(item.product_id);
  state.products.set(id, item);
  const badge = item.demo_badge ? `<span class="product-badge">${escapeHtml(item.demo_badge)}</span>` : "";
  const rank = item.rank ? `<span class="rank-badge">#${item.rank}</span>` : "";
  const favorite = state.favorites.has(id) ? "active" : "";
  return `<article class="product-card ${compact ? "compact-card" : ""}" data-product-card="${escapeHtml(id)}">
    <div class="card-visual" data-detail="${escapeHtml(id)}">${productVisual(item)}${badge}${rank}
      <button class="heart ${favorite}" data-favorite="${escapeHtml(id)}" aria-label="Yêu thích">♡</button>
    </div>
    <div class="product-copy" data-detail="${escapeHtml(id)}">
      <p>${escapeHtml(brandLabel(item))}</p><h3>${escapeHtml(productName(item))}</h3>
      <small>${escapeHtml(item.product_type || item.category_code || `Product ID ${id}`)}</small>
      <div class="card-rating">${ratingMarkup(item)}</div>
      <div class="card-bottom"><strong>${formatPrice(item.price)}</strong><button data-add="${escapeHtml(id)}">+</button></div>
    </div>
  </article>`;
}

function setSystemState(ready) {
  const element = $("#system-state");
  element.classList.toggle("offline", !ready);
  element.querySelector("span").textContent = ready ? "Sẵn sàng" : "Mất kết nối";
}

async function loadFilters() {
  const data = await request("/api/v1/products/filters");
  const select = $("#brand-filter");
  select.innerHTML = '<option value="">Tất cả thương hiệu</option>';
  for (const row of data.brands || []) {
    const option = document.createElement("option");
    option.value = row.value;
    option.textContent = `${row.value} (${formatNumber(row.count)})`;
    select.append(option);
  }
}

async function loadProducts(page = 1) {
  const params = new URLSearchParams({ page: String(page), page_size: "20" });
  const values = {
    q: $("#product-search").value.trim(), brand: $("#brand-filter").value,
    min_price: $("#price-min").value, max_price: $("#price-max").value,
  };
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value);
  $("#product-grid").classList.add("loading-grid");
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
  } finally {
    $("#product-grid").classList.remove("loading-grid");
  }
}

function renderHistory(data) {
  $("#history-total").textContent = `${formatNumber(data.total_products)} sản phẩm đã tương tác`;
  $("#history-list").innerHTML = (data.items || []).slice(0, 12).map((item) => {
    state.products.set(String(item.product_id), item);
    return `<article data-detail="${escapeHtml(item.product_id)}">${productVisual(item, "history-visual")}
      <div><p>${escapeHtml(brandLabel(item))}</p><h3>${escapeHtml(productName(item))}</h3>
      <dl><span>View <b>${formatNumber(item.view_count)}</b></span><span>Cart <b>${formatNumber(item.cart_count)}</b></span><span>Purchase <b>${formatNumber(item.purchase_count)}</b></span></dl></div></article>`;
  }).join("");
  $("#history-empty").classList.toggle("hidden", (data.items || []).length > 0);
}

async function loadUser() {
  const userId = $("#user-id").value.trim();
  if (!userId) return showToast("Hãy nhập hoặc chọn một User ID.");
  $("#strategy-badge").textContent = "Đang tạo beauty edit…";
  try {
    const [recommendations, history] = await Promise.all([
      request(`/api/v1/recommendations/${encodeURIComponent(userId)}?limit=10`),
      request(`/api/v1/users/${encodeURIComponent(userId)}/history?limit=30`),
    ]);
    $("#recommendation-grid").innerHTML = recommendations.items.map((item) => productCard(item, true)).join("");
    $("#recommendation-empty").classList.toggle("hidden", recommendations.items.length > 0);
    const personalized = recommendations.strategy === "als_count_c3";
    $("#strategy-badge").textContent = personalized ? "COUNT_C3 · Cá nhân hóa" : "Popularity · Khách mới";
    $("#strategy-badge").classList.toggle("fallback", !personalized);
    renderHistory(history);
  } catch (error) {
    $("#strategy-badge").textContent = "Không thể tải dữ liệu";
    showToast(error.message);
  }
}

function openProduct(productId) {
  const item = state.products.get(String(productId));
  if (!item) return;
  state.selectedProduct = item;
  $("#modal-visual").innerHTML = productVisual(item, "modal-product-art");
  $("#modal-brand").textContent = brandLabel(item);
  $("#modal-name").textContent = productName(item);
  $("#modal-rating").innerHTML = ratingMarkup(item);
  $("#modal-price").textContent = formatPrice(item.price);
  $("#modal-description").textContent = item.description || "Sản phẩm trong catalog mỹ phẩm.";
  $("#modal-facts").innerHTML = `<div><dt>Product ID gốc</dt><dd>${escapeHtml(item.product_id)}</dd></div>
    <div><dt>Danh mục gốc</dt><dd>${escapeHtml(item.category_code || item.category_id || "Không có")}</dd></div>
    <div><dt>Nguồn giá</dt><dd>Sự kiện gần nhất trong Train</dd></div>`;
  $("#product-modal").classList.add("open");
  $("#product-modal").setAttribute("aria-hidden", "false");
}

function closeProduct() {
  $("#product-modal").classList.remove("open");
  $("#product-modal").setAttribute("aria-hidden", "true");
}

function addToCart(productId) {
  const item = state.products.get(String(productId));
  if (!item) return;
  const current = state.cart.get(String(productId));
  state.cart.set(String(productId), { item, quantity: (current?.quantity || 0) + 1 });
  renderCart();
  showToast(`Đã thêm ${productName(item)} vào giỏ.`);
}

function renderCart() {
  const rows = [...state.cart.values()];
  const count = rows.reduce((sum, row) => sum + row.quantity, 0);
  const total = rows.reduce((sum, row) => sum + Number(row.item.price || 0) * row.quantity, 0);
  $("#cart-count").textContent = count;
  $("#cart-total").textContent = formatPrice(total);
  $("#cart-empty").classList.toggle("hidden", rows.length > 0);
  $("#cart-items").innerHTML = rows.map(({ item, quantity }) => `<article>
    ${productVisual(item, "cart-visual")}<div><p>${escapeHtml(brandLabel(item))}</p><h3>${escapeHtml(productName(item))}</h3><span>${formatPrice(item.price)} · SL ${quantity}</span></div>
    <button data-remove="${escapeHtml(item.product_id)}">×</button></article>`).join("");
}

function openCart() {
  $("#cart-drawer").classList.add("open");
  $("#cart-drawer").setAttribute("aria-hidden", "false");
}

function closeCart() {
  $("#cart-drawer").classList.remove("open");
  $("#cart-drawer").setAttribute("aria-hidden", "true");
}

function metricBar(label, value, max, note = "") {
  const width = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return `<div class="bar-row"><div><span>${escapeHtml(label)}</span><strong>${formatNumber(value, 4)}%</strong></div><div class="bar-track"><i style="width:${width}%"></i></div>${note ? `<small>${escapeHtml(note)}</small>` : ""}</div>`;
}

function findArray(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node) && node.length && node.every((row) => row && typeof row === "object") && predicate(node[0])) return node;
  for (const value of Object.values(node)) { const found = findArray(value, predicate); if (found) return found; }
  return null;
}

function numericCount(row) {
  for (const key of ["count", "event_count", "events", "total", "value"]) if (Number.isFinite(Number(row[key]))) return Number(row[key]);
  return 0;
}

function renderDashboard(data) {
  const source = data.data_source || {};
  $("#data-source-status").textContent = source.hdfs_synced ? `HDFS đã đồng bộ · ${source.hdfs_path}` : "Đang dùng SQLite cache local";
  $("#data-source-status").classList.toggle("local", !source.hdfs_synced);
  const report = data.evaluation_report || {};
  const winner = report.test_evaluation?.winner || {};
  const baseline = report.test_evaluation?.baseline || {};
  const validation = report.ground_truth_coverage?.validation || {};
  const test = report.ground_truth_coverage?.test || {};
  const metrics = [["Test Recall@10", winner.macro_recall_at_10, "COUNT_C3"], ["Test Precision@10", winner.macro_precision_at_10, "COUNT_C3"], ["Validation coverage", validation.pair_coverage, `${formatNumber(validation.known_purchase_pairs)} cặp warm-start`], ["Test coverage", test.pair_coverage, `${formatNumber(test.known_purchase_pairs)} cặp warm-start`]];
  if (metrics.every((row) => Number.isFinite(Number(row[1])))) $("#metric-grid").innerHTML = metrics.map(([label, value, note]) => `<article><span>${label}</span><strong>${formatNumber(Number(value) * 100, 4)}%</strong><small>${note}</small></article>`).join("");
  const comparison = [["COUNT_C3 Recall@10", Number(winner.macro_recall_at_10 || 0) * 100], ["Popularity Recall@10", Number(baseline.macro_recall_at_10 || 0) * 100], ["COUNT_C3 Precision@10", Number(winner.macro_precision_at_10 || 0) * 100], ["Popularity Precision@10", Number(baseline.macro_precision_at_10 || 0) * 100]];
  const maxMetric = Math.max(...comparison.map((row) => row[1]), 1);
  $("#model-chart").innerHTML = comparison.map(([label, value]) => metricBar(label, value, maxMetric)).join("");
  const eventRows = findArray(data.dashboard_stats, (row) => "event_type" in row);
  if (eventRows) {
    const totals = new Map();
    for (const row of eventRows) totals.set(row.event_type, (totals.get(row.event_type) || 0) + numericCount(row));
    const rows = [...totals.entries()].filter((row) => row[1] > 0);
    const maxEvent = Math.max(...rows.map((row) => row[1]), 1);
    $("#event-chart").innerHTML = rows.map(([label, value]) => metricBar(label, value, maxEvent, `${formatNumber(value)} sự kiện`)).join("");
  } else $("#event-chart").innerHTML = '<p class="muted">Thống kê phân loại hành vi chưa có trong export.</p>';
}

document.addEventListener("click", (event) => {
  const add = event.target.closest("[data-add]");
  if (add) { event.stopPropagation(); addToCart(add.dataset.add); return; }
  const favorite = event.target.closest("[data-favorite]");
  if (favorite) {
    event.stopPropagation();
    const id = favorite.dataset.favorite;
    state.favorites.has(id) ? state.favorites.delete(id) : state.favorites.add(id);
    favorite.classList.toggle("active");
    showToast(state.favorites.has(id) ? "Đã lưu vào danh sách yêu thích." : "Đã bỏ khỏi yêu thích.");
    return;
  }
  const detail = event.target.closest("[data-detail]");
  if (detail) { openProduct(detail.dataset.detail); return; }
  const remove = event.target.closest("[data-remove]");
  if (remove) { state.cart.delete(remove.dataset.remove); renderCart(); return; }
  if (event.target.closest("[data-close-cart]")) closeCart();
  if (event.target.closest("[data-close-modal]")) closeProduct();
});

async function initialize() {
  try {
    const health = await request("/health");
    if (!health.data_ready) throw new Error("Chưa nạp serving_export vào cơ sở dữ liệu.");
    setSystemState(true);
    const [users, dashboard] = await Promise.all([request("/api/v1/demo-users?limit=20"), request("/api/v1/dashboard"), loadFilters(), loadProducts()]);
    const list = users.users || [];
    $("#demo-user-list").innerHTML = list.map((id) => `<option value="${escapeHtml(id)}"></option>`).join("");
    if (list.length) { $("#user-id").value = list[0]; await loadUser(); }
    renderDashboard(dashboard);
  } catch (error) { setSystemState(false); showToast(error.message); }
}

$("#product-filters").addEventListener("submit", (event) => { event.preventDefault(); loadProducts(1); });
$("#previous-products").addEventListener("click", () => loadProducts(state.productPage - 1));
$("#next-products").addEventListener("click", () => loadProducts(state.productPage + 1));
$("#load-user").addEventListener("click", loadUser);
$("#user-id").addEventListener("keydown", (event) => { if (event.key === "Enter") loadUser(); });
$("#header-search-input").addEventListener("keydown", (event) => { if (event.key === "Enter") { $("#product-search").value = event.target.value; window.location.hash = "#shop"; loadProducts(1); } });
$("#category-grid").addEventListener("click", (event) => { const button = event.target.closest("[data-category]"); if (!button) return; $("#product-search").value = categoryQueries[button.dataset.category] || ""; window.location.hash = "#shop"; loadProducts(1); });
$("#cart-toggle").addEventListener("click", openCart);
$("#modal-add").addEventListener("click", () => { if (state.selectedProduct) addToCart(state.selectedProduct.product_id); });
$("#checkout-demo").addEventListener("click", () => showToast("Thanh toán chỉ là luồng minh họa trong đồ án."));
window.addEventListener("hashchange", setViewFromHash);

setViewFromHash();
renderCart();
initialize();
