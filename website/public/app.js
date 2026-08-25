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
  button.className = "disabled-buy";
  button.disabled = true;
  button.textContent = product.available ? "Buy now" : "Coming soon";

  card.append(label, title, detail, price, button);
  return card;
}

async function loadCatalog() {
  const catalog = document.querySelector("#catalog");
  const empty = document.querySelector("#catalog-empty");
  try {
    const response = await fetch("/products.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Catalog unavailable");
    const products = await response.json();
    if (!Array.isArray(products) || products.length === 0) return;
    empty.hidden = true;
    products.forEach((product) => catalog.append(productCard(product)));
  } catch {
    empty.textContent = "The first verified Splitzzz Reel packs are being prepared.";
  }
}

document.querySelector("#year").textContent = new Date().getFullYear();
selectChannel("youtube");
loadCatalog();
