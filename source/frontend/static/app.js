const API = "";
const palette = [
  ["#d3b49c", "#b98e74", "#ead4bd"],
  ["#b7b89d", "#707b61", "#d2d1b6"],
  ["#d9b1a5", "#b87668", "#efd2c6"],
  ["#c8b99c", "#877353", "#e5d9c2"],
  ["#b3c0b0", "#728675", "#d5ded1"],
];

const state = { recommendations: [], cart: [], toastTimer: null };
const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatPrice(price) {
  const amount = Number(price);
  if (!Number.isFinite(amount)) return "Giá đang cập nhật";
  return new Intl.NumberFormat("en-US", {
    style: "currency", currency: "USD", maximumFractionDigits: 2,
  }).format(amount);
}

function brandName(item) {
  const brand = item.brand;
  return !brand || brand === "__MISSING__" ? "MUSE BEAUTY EDIT" : brand;
}

function categoryName(item) {
  const category = item.category_code;
  if (!category || category === "__MISSING__") return "BEAUTY ESSENTIAL";
  return category.split(".").filter(Boolean).slice(-1)[0].replaceAll("_", " ").toUpperCase();
}

function artStyle(item, index) {
  const colors = palette[Math.abs(Number(item.item_idx ?? index)) % palette.length];
  const jar = /cream|mask|nail|gel/i.test(`${item.brand} ${item.category_code}`);
  return `--art-dark:${colors[1]};--art-light:${colors[0]};--art-orb:${colors[2]}`;
}

function productCard(item, index, source) {
  const productId = escapeHtml(item.product_id);
  const isInBag = state.cart.some((row) => String(row.product_id) === String(item.product_id));
  const artClass = /cream|mask|nail|gel/i.test(`${item.brand} ${item.category_code}`) ? "jar" : "";
  return `
    <article class="product-card">
      <div class="product-art ${artClass}" style="${artStyle(item, index)}">
        <span class="product-shape"></span>
      </div>
      <div class="product-details">
        <div class="product-meta">${escapeHtml(brandName(item))}</div>
        <h3 class="product-name" title="${productId}">${escapeHtml(categoryName(item))} · ${productId}</h3>
        <div class="product-bottom">
          <span class="product-price">${formatPrice(item.avg_price)}</span>
          <button class="add-button" data-add="${productId}" data-source="${source}" aria-label="Thêm sản phẩm ${productId} vào túi" ${isInBag ? "disabled" : ""}>${isInBag ? "✓" : "+"}</button>
        </div>
      </div>
    </article>`;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 2200);
}

function setApiStatus(online) {
  const status = $("#api-status");
  status.classList.toggle("offline", !online);
  status.lastChild.textContent = online ? " Recommendation engine" : " API không kết nối";
}

async function loadRecommendations() {
  const userId = $("#user-id").value.trim();
  const grid = $("#recommendation-grid");
  const empty = $("#recommendation-empty");
  const loading = $("#recommendation-loading");
  if (!userId) {
    showToast("Nhập mã người dùng để tải gợi ý.");
    return;
  }

  grid.innerHTML = "";
  empty.classList.add("hidden");
  loading.classList.remove("hidden");
  try {
    const response = await fetch(`${API}/api/v1/recommendations/${encodeURIComponent(userId)}?limit=10`);
    if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json();
    state.recommendations = data.items ?? [];
    const strategyText = data.strategy === "cold_start_fallback"
      ? "Gợi ý khám phá dành cho tài khoản mới"
      : "Được xếp hạng từ sở thích và hành vi mua sắm";
    $("#strategy-text").textContent = strategyText;
    grid.innerHTML = state.recommendations.map((item, index) => productCard(item, index, "recommendation")).join("");
    empty.classList.toggle("hidden", state.recommendations.length > 0);
    setApiStatus(true);
  } catch (error) {
    console.error("Recommendation request failed", error);
    state.recommendations = [];
    $("#strategy-text").textContent = "Không thể tải gợi ý — kiểm tra API và dữ liệu MongoDB.";
    empty.classList.remove("hidden");
    setApiStatus(false);
  } finally {
    loading.classList.add("hidden");
  }
}

async function loadCrossSell(product) {
  const grid = $("#cross-sell-grid");
  const empty = $("#cross-sell-empty");
  const context = $("#cross-sell-context");
  grid.innerHTML = "";
  empty.classList.add("hidden");
  lastCrossSellItems = [];
  context.classList.remove("hidden");
  context.textContent = `Gợi ý đi cùng ${product.product_id}`;
  try {
    const response = await fetch(`${API}/api/v1/cross-sell/${encodeURIComponent(product.product_id)}?limit=3`);
    if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json();
    lastCrossSellItems = data.items ?? [];
    const sourceLabel = data.recommendation_source === "FP-Growth"
      ? "Sản phẩm thường xuất hiện cùng nhau"
      : "Khám phá thêm trong cùng nhóm sản phẩm";
    context.textContent = `${sourceLabel} · cho sản phẩm ${product.product_id}`;
    const items = data.items ?? [];
    grid.innerHTML = items.map((item, index) => productCard(item, index, "cross-sell")).join("");
    empty.classList.toggle("hidden", items.length > 0);
    if (!items.length) $("#cross-sell-empty small").textContent = "Chưa có luật mua kèm hoặc sản phẩm fallback cho lựa chọn này.";
    setApiStatus(true);
  } catch (error) {
    console.error("Cross-sell request failed", error);
    context.textContent = "Không thể tải gợi ý mua kèm.";
    empty.classList.remove("hidden");
    setApiStatus(false);
  }
}

function renderCart() {
  $("#bag-count").textContent = String(state.cart.length);
  $("#cart-empty").classList.toggle("hidden", state.cart.length > 0);
  $("#cart-items").innerHTML = state.cart.map((item) => `
    <div class="cart-row">
      <div class="cart-swatch">m.</div>
      <div><strong>${escapeHtml(categoryName(item))} · ${escapeHtml(item.product_id)}</strong><small>${escapeHtml(brandName(item))} · ${formatPrice(item.avg_price)}</small></div>
      <button data-remove="${escapeHtml(item.product_id)}" aria-label="Xóa sản phẩm">×</button>
    </div>`).join("");
  document.querySelectorAll(".add-button").forEach((button) => {
    const exists = state.cart.some((item) => String(item.product_id) === button.dataset.add);
    button.disabled = exists;
    button.textContent = exists ? "✓" : "+";
  });
}

function addToCart(productId, source) {
  const list = source === "cross-sell" ? getLastCrossSellItems() : state.recommendations;
  const item = list.find((row) => String(row.product_id) === String(productId));
  if (!item) return;
  if (state.cart.some((row) => String(row.product_id) === String(productId))) {
    showToast("Món này đã có trong túi rồi.");
    return;
  }
  state.cart.push(item);
  renderCart();
  showToast("Đã thêm vào túi của bạn.");
  if (source !== "cross-sell") loadCrossSell(item);
}

let lastCrossSellItems = [];
function getLastCrossSellItems() { return lastCrossSellItems; }

document.addEventListener("click", (event) => {
  const addButton = event.target.closest("[data-add]");
  if (addButton) addToCart(addButton.dataset.add, addButton.dataset.source);
  const removeButton = event.target.closest("[data-remove]");
  if (removeButton) {
    state.cart = state.cart.filter((item) => String(item.product_id) !== removeButton.dataset.remove);
    renderCart();
  }
});

function openDrawer() {
  $("#cart-drawer").classList.add("open");
  $("#cart-drawer").setAttribute("aria-hidden", "false");
}
function closeDrawer() {
  $("#cart-drawer").classList.remove("open");
  $("#cart-drawer").setAttribute("aria-hidden", "true");
}

$("#load-recs").addEventListener("click", loadRecommendations);
$("#user-id").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadRecommendations();
});
$("#bag-toggle").addEventListener("click", openDrawer);
$("#close-drawer").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);
$("#continue-shopping").addEventListener("click", closeDrawer);

loadRecommendations();
