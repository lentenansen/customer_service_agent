// 商品测试页逻辑：商品列表 / 购买 / 我的订单 / 物流弹窗与三个操作
// 登录态与聊天页共用 localStorage（同源），所有接口都带 token
// 关键：token 不做页面级缓存。若在加载时存成常量，之后去聊天页重新登录，
// 本页仍拿着旧 token，点「购买」只会 401 显示一行红字，看起来像按钮没反应。
function currentToken() {
  return localStorage.getItem("cs_token") || "";
}

const notice = document.getElementById("notice");
const productsView = document.getElementById("products-view");
const ordersView = document.getElementById("orders-view");
const productList = document.getElementById("product-list");
const orderList = document.getElementById("order-list");
const logisticsBtn = document.getElementById("logistics-btn");
const modal = document.getElementById("modal");
const timeline = document.getElementById("timeline");

let currentOrderNo = "";
let view = "products"; // products | orders

function showNotice(text, ok = false) {
  notice.textContent = text;
  notice.classList.toggle("ok", ok);
}

async function request(path, { method = "GET", body = null } = {}) {
  const url = new URL(path, location.origin);
  const token = currentToken();           // 每次请求实时读，不用刷新页面
  if (method === "GET") url.searchParams.set("token", token);

  const options = { method, headers: {} };
  if (body) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify({ ...body, token });
  }

  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    showNotice("未登录或登录已过期：请返回聊天页登录后再试（登录后本页无需刷新）");
    throw new Error("未登录或登录已过期：请返回聊天页登录后再试");
  }
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

function switchView(next) {
  view = next;
  productsView.hidden = next !== "products";
  ordersView.hidden = next !== "orders";
  logisticsBtn.textContent = next === "orders" ? "返回商品" : "修改物流";
}

// ---------------- 商品 ----------------

async function loadProducts() {
  const data = await request("/api/test/products");
  productList.innerHTML = "";
  data.products.forEach((p) => {
    const card = document.createElement("div");
    card.className = "card";

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = p.name;

    const price = document.createElement("div");
    price.className = "price";
    price.textContent = "¥" + Number(p.price).toFixed(2);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "购买";
    btn.addEventListener("click", () => buy(p, btn));

    card.append(name, price, btn);
    productList.appendChild(card);
  });
}

async function buy(product, btn) {
  btn.disabled = true;
  try {
    const data = await request("/api/test/buy", {
      method: "POST",
      body: { sku: product.sku },
    });
    showNotice(
      `购买成功：${data.product}，订单号 ${data.order_no}，状态「${data.status}」`,
      true
    );
  } catch (err) {
    showNotice(err.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------------- 订单列表 ----------------

async function loadOrders() {
  const data = await request("/api/test/orders");
  orderList.innerHTML = "";

  if (!data.orders.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "还没有订单，先回商品列表购买一件吧";
    orderList.appendChild(empty);
    return;
  }

  data.orders.forEach((o) => {
    const item = document.createElement("div");
    item.className = "order-item";

    const left = document.createElement("div");
    const no = document.createElement("div");
    no.className = "no";
    no.textContent = o.order_no + " · " + o.product_name;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `¥${Number(o.total_amount).toFixed(2)} ｜ 下单时间 ${o.created_at}`;
    left.append(no, meta);

    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = o.status;

    item.append(left, tag);
    item.addEventListener("click", () => openModal(o.order_no));
    orderList.appendChild(item);
  });
}

// ---------------- 物流弹窗 ----------------

function renderModal(data) {
  const o = data.order;
  document.getElementById("modal-title").textContent = `订单 ${o.order_no} 物流信息`;
  document.getElementById("modal-info").textContent =
    `状态：${o.status} ｜ 金额：¥${Number(o.total_amount).toFixed(2)} ｜ ` +
    `下单：${o.created_at} ｜ 快递：${o.carrier || "未发货"} ${o.tracking_no || ""}`;

  timeline.innerHTML = "";
  if (!data.events.length) {
    const li = document.createElement("li");
    li.textContent = "暂无物流轨迹";
    timeline.appendChild(li);
  } else {
    data.events.forEach((e) => {
      const li = document.createElement("li");
      const time = document.createElement("span");
      time.className = "time";
      time.textContent = e.event_at;
      const desc = document.createElement("span");
      desc.textContent = e.description;
      li.append(time, desc);
      timeline.appendChild(li);
    });
  }
}

async function refreshModal() {
  const data = await request(`/api/test/orders/${encodeURIComponent(currentOrderNo)}`);
  renderModal(data);
}

async function openModal(orderNo) {
  currentOrderNo = orderNo;
  try {
    const data = await request(`/api/test/orders/${encodeURIComponent(orderNo)}`);
    renderModal(data);
    modal.hidden = false;
  } catch (err) {
    showNotice(err.message);
  }
}

async function act(action, btn) {
  if (!currentOrderNo) return;
  btn.disabled = true;
  try {
    const data = await request(
      `/api/test/orders/${encodeURIComponent(currentOrderNo)}/${action}`,
      { method: "POST", body: {} }
    );
    showNotice(`操作成功，当前状态「${data.status}」`, true);
    await refreshModal();
  } catch (err) {
    showNotice(err.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------------- 事件绑定 ----------------

logisticsBtn.addEventListener("click", async () => {
  if (view === "products") {
    try {
      await loadOrders();
      switchView("orders");
    } catch (err) {
      showNotice(err.message);
    }
  } else {
    switchView("products");
  }
});

document.getElementById("modal-close").addEventListener("click", () => {
  modal.hidden = true;
});
modal.addEventListener("click", (e) => {
  if (e.target === modal) modal.hidden = true;
});
document.getElementById("btn-ship").addEventListener("click", (e) => act("ship", e.currentTarget));
document.getElementById("btn-transit").addEventListener("click", (e) => act("transit", e.currentTarget));
document.getElementById("btn-sign").addEventListener("click", (e) => act("sign", e.currentTarget));

(async function init() {
  switchView("products");
  if (!currentToken()) showNotice("未登录：请先返回聊天页登录，再使用测试购买与修改物流");
  try {
    await loadProducts();
  } catch (err) {
    showNotice("商品加载失败：" + err.message);
  }
})();
