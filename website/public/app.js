const channels = {
  instagram: {
    theme: "instagram",
    logo: "IG",
    platform: "Instagram",
    name: "Splitzzz",
    handle: "@splitzz.isodope",
    description: "Follow Splitzzz for new Reels, previews, and pack updates.",
    url: "https://www.instagram.com/splitzz.isodope?igsi=ZDNjaWM2bzMxM3Ux",
  },
  youtube: {
    theme: "youtube",
    logo: "YT",
    platform: "YouTube",
    name: "Splitzzz",
    handle: "@splitzz.7",
    description: "Watch the latest Splitzzz Shorts and creator content.",
    url: "https://youtube.com/@splitzz.7?si=xHxr2JUCiZFT4v5Z",
  },
  facebook: {
    theme: "facebook",
    logo: "f",
    platform: "Facebook",
    name: "Splitzz",
    handle: "Facebook Page",
    description: "Follow the Splitzz Page for cross-posted Reels and updates.",
    url: "https://www.facebook.com/share/14m6DMh4Eg8/",
  },
};

const tabs = document.querySelectorAll("[data-channel]");
const logo = document.querySelector("#channel-logo");
const platformName = document.querySelector("#platform-name");
const channelName = document.querySelector("#channel-name");
const channelHandle = document.querySelector("#channel-handle");
const channelDescription = document.querySelector("#channel-description");
const followButton = document.querySelector("#follow-button");
const checkoutDialog = document.querySelector("#checkout-dialog");
const downloadLinks = document.querySelector("#download-links");
const savedPurchases = document.querySelector("#saved-purchases");
const purchaseStorageKey = "splitzzz-paid-orders";

function selectChannel(channelId) {
  const channel = channels[channelId];
  if (!channel) return;

  document.body.dataset.theme = channel.theme;
  logo.textContent = channel.logo;
  platformName.textContent = channel.platform;
  channelName.textContent = channel.name;
  channelHandle.textContent = channel.handle;
  channelDescription.textContent = channel.description;
  followButton.href = channel.url;
  followButton.setAttribute("aria-label", `Follow Splitzzz on ${channel.platform}`);

  tabs.forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.channel === channelId));
  });
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => selectChannel(tab.dataset.channel));
});

function purchases() {
  try {
    const value = JSON.parse(localStorage.getItem(purchaseStorageKey) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function savePurchase(purchase) {
  const saved = purchases().filter((item) => item.orderId !== purchase.orderId);
  saved.push(purchase);
  localStorage.setItem(purchaseStorageKey, JSON.stringify(saved));
  renderPurchases();
}

async function verifyAndShowDownloads(proof) {
  const response = await fetch("/api/verify-payment", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(proof),
  });
  const result = await response.json();
  if (!response.ok || !result.verified) {
    throw new Error(result.error || "Payment verification failed.");
  }

  downloadLinks.replaceChildren();
  result.downloads.forEach((download) => {
    const link = document.createElement("a");
    link.href = download.url;
    const filename = document.createElement("span");
    filename.textContent = download.filename;
    const action = document.createElement("span");
    action.textContent = "Download ZIP";
    link.append(filename, action);
    link.rel = "noopener noreferrer";
    downloadLinks.append(link);
  });
  checkoutDialog.showModal();
}

async function checkoutProduct(product) {
  const orderResponse = await fetch("/api/create-order", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ productId: product.id }),
  });
  const order = await orderResponse.json();
  if (!orderResponse.ok) {
    throw new Error(order.error || "Checkout is unavailable.");
  }
  if (!window.Razorpay) throw new Error("Razorpay checkout could not load.");

  const checkout = new window.Razorpay({
    key: order.keyId,
    order_id: order.orderId,
    amount: order.amount,
    currency: order.currency,
    name: "Splitzzz",
    description: product.name,
    theme: { color: "#7357ff" },
    handler: async (payment) => {
      const proof = {
        razorpay_order_id: payment.razorpay_order_id,
        razorpay_payment_id: payment.razorpay_payment_id,
        razorpay_signature: payment.razorpay_signature,
      };
      savePurchase({
        ...proof,
        orderId: payment.razorpay_order_id,
        productId: product.id,
        productName: product.name,
      });
      try {
        await verifyAndShowDownloads(proof);
      } catch (error) {
        alert(error.message);
      }
    },
  });
  checkout.open();
}

function productCard(product) {
  const card = document.createElement("article");
  card.className = "price-card";

  const label = document.createElement("p");
  label.className = "pack-label";
  label.textContent = product.label || "READY TO UPLOAD";

  const title = document.createElement("h3");
  title.textContent = product.name;

  const detail = document.createElement("p");
  detail.textContent = `${product.reelCount} Reels · ZIP download`;
  detail.className = "channel-handle";

  const price = document.createElement("p");
  price.className = "price";
  price.textContent = `₹${product.price}`;

  const button = document.createElement("button");
  button.type = "button";
  button.disabled = !product.available;
  button.className = product.available ? "buy-button" : "disabled-buy";
  button.textContent = product.available ? "Buy now" : "Coming soon";
  if (product.available) {
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await checkoutProduct(product);
      } catch (error) {
        alert(error.message);
      } finally {
        button.disabled = false;
      }
    });
  }

  card.append(label, title, detail, price, button);
  return card;
}

function renderPurchases() {
  const saved = purchases();
  savedPurchases.replaceChildren();
  if (saved.length === 0) {
    const message = document.createElement("p");
    message.textContent = "No purchases saved on this device yet.";
    savedPurchases.append(message);
    return;
  }
  saved.forEach((purchase) => {
    const row = document.createElement("div");
    row.className = "saved-purchase";
    const name = document.createElement("strong");
    name.textContent = purchase.productName || purchase.productId;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Get download";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await verifyAndShowDownloads(purchase);
      } catch (error) {
        alert(error.message);
      } finally {
        button.disabled = false;
      }
    });
    row.append(name, button);
    savedPurchases.append(row);
  });
}

async function loadCatalog() {
  const catalog = document.querySelector("#catalog");
  const empty = document.querySelector("#catalog-empty");
  try {
    let response = await fetch("/api/products", { cache: "no-store" });
    if (!response.ok) {
      response = await fetch("/products.json", { cache: "no-store" });
    }
    if (!response.ok) throw new Error("Catalog unavailable");
    const products = await response.json();
    if (!Array.isArray(products) || products.length === 0) return;
    empty.hidden = true;
    products.forEach((product) => catalog.append(productCard(product)));
  } catch {
    empty.textContent = "The first verified Splitzzz Reel packs are being prepared.";
  }
}

document.querySelector("#close-dialog").addEventListener("click", () => checkoutDialog.close());
document.querySelector("#year").textContent = new Date().getFullYear();
selectChannel("youtube");
renderPurchases();
loadCatalog();
