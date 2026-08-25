const PRODUCTS_ENV = "SPLITZZZ_SELLABLE_PRODUCTS_JSON";

function products() {
  try {
    const value = JSON.parse(process.env[PRODUCTS_ENV] || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

module.exports = async function createOrder(request, response) {
  response.setHeader("Cache-Control", "no-store");
  if (request.method !== "POST") {
    response.setHeader("Allow", "POST");
    return response.status(405).json({ error: "Method not allowed" });
  }
  if (process.env.STORE_LIVE !== "true") {
    return response.status(503).json({ error: "Splitzzz checkout is not live yet." });
  }

  const productId = String(request.body?.productId || "");
  const product = products()[productId];
  if (!product || !Number.isInteger(product.amount) || product.amount < 100) {
    return response.status(400).json({ error: "This Reel pack is not available." });
  }

  const keyId = process.env.RAZORPAY_KEY_ID;
  const keySecret = process.env.RAZORPAY_KEY_SECRET;
  if (!keyId || !keySecret) {
    return response.status(503).json({ error: "Checkout configuration is incomplete." });
  }

  const authorization = Buffer.from(`${keyId}:${keySecret}`).toString("base64");
  const razorpayResponse = await fetch("https://api.razorpay.com/v1/orders", {
    method: "POST",
    headers: {
      Authorization: `Basic ${authorization}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      amount: product.amount,
      currency: "INR",
      receipt: `splitzzz-${productId}`.slice(0, 40),
      notes: { product_id: productId },
    }),
  });
  const order = await razorpayResponse.json();
  if (!razorpayResponse.ok) {
    return response.status(502).json({ error: "Razorpay could not create the order." });
  }
  return response.status(200).json({
    keyId,
    orderId: order.id,
    amount: order.amount,
    currency: order.currency,
    productId,
  });
};
