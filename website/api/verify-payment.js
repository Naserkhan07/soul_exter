const crypto = require("node:crypto");
const { GetObjectCommand, S3Client } = require("@aws-sdk/client-s3");
const { getSignedUrl } = require("@aws-sdk/s3-request-presigner");

function safeEqual(left, right) {
  const leftBuffer = Buffer.from(left, "utf8");
  const rightBuffer = Buffer.from(right, "utf8");
  return leftBuffer.length === rightBuffer.length && crypto.timingSafeEqual(leftBuffer, rightBuffer);
}

function products() {
  try {
    const value = JSON.parse(process.env.SPLITZZZ_SELLABLE_PRODUCTS_JSON || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

module.exports = async function verifyPayment(request, response) {
  if (request.method !== "POST") {
    response.setHeader("Allow", "POST");
    return response.status(405).json({ error: "Method not allowed" });
  }

  const orderId = String(request.body?.razorpay_order_id || "");
  const paymentId = String(request.body?.razorpay_payment_id || "");
  const signature = String(request.body?.razorpay_signature || "");
  const razorpaySecret = process.env.RAZORPAY_KEY_SECRET;
  const razorpayKey = process.env.RAZORPAY_KEY_ID;
  if (!razorpaySecret || !razorpayKey || !orderId || !paymentId || !signature) {
    return response.status(400).json({ error: "Payment verification data is incomplete." });
  }

  const expected = crypto
    .createHmac("sha256", razorpaySecret)
    .update(`${orderId}|${paymentId}`)
    .digest("hex");
  if (!safeEqual(expected, signature)) {
    return response.status(400).json({ error: "Payment signature is invalid." });
  }

  const authorization = Buffer.from(`${razorpayKey}:${razorpaySecret}`).toString("base64");
  const orderResponse = await fetch(`https://api.razorpay.com/v1/orders/${orderId}`, {
    headers: { Authorization: `Basic ${authorization}` },
  });
  const order = await orderResponse.json();
  if (!orderResponse.ok || order.status !== "paid") {
    return response.status(400).json({ error: "Razorpay has not marked this order as paid." });
  }

  const productId = String(order.notes?.product_id || "");
  const product = products()[productId];
  const objectKeys = Array.isArray(product?.objectKeys) ? product.objectKeys : [];
  if (!product || order.amount !== product.amount || objectKeys.length === 0) {
    return response.status(400).json({ error: "Paid product delivery is not configured." });
  }

  const accountId = process.env.R2_ACCOUNT_ID;
  const accessKeyId = process.env.R2_ACCESS_KEY_ID;
  const secretAccessKey = process.env.R2_SECRET_ACCESS_KEY;
  const bucket = process.env.R2_BUCKET_NAME;
  if (!accountId || !accessKeyId || !secretAccessKey || !bucket) {
    return response.status(503).json({ error: "Private download storage is unavailable." });
  }

  const client = new S3Client({
    region: "auto",
    endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
    credentials: { accessKeyId, secretAccessKey },
  });
  const downloads = await Promise.all(
    objectKeys.map(async (key) => ({
      filename: key.split("/").pop(),
      url: await getSignedUrl(client, new GetObjectCommand({ Bucket: bucket, Key: key }), {
        expiresIn: 15 * 60,
      }),
    })),
  );

  response.setHeader("Cache-Control", "no-store");
  return response.status(200).json({
    verified: true,
    orderId,
    paymentId,
    productId,
    downloads,
    expiresInSeconds: 15 * 60,
  });
};
