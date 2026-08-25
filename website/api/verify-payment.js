const crypto = require("node:crypto");

function safeEqual(left, right) {
  const leftBuffer = Buffer.from(left, "utf8");
  const rightBuffer = Buffer.from(right, "utf8");
  return leftBuffer.length === rightBuffer.length && crypto.timingSafeEqual(leftBuffer, rightBuffer);
}

module.exports = async function verifyPayment(request, response) {
  if (request.method !== "POST") {
    response.setHeader("Allow", "POST");
    return response.status(405).json({ error: "Method not allowed" });
  }

  const orderId = String(request.body?.razorpay_order_id || "");
  const paymentId = String(request.body?.razorpay_payment_id || "");
  const signature = String(request.body?.razorpay_signature || "");
  const secret = process.env.RAZORPAY_KEY_SECRET;
  if (!secret || !orderId || !paymentId || !signature) {
    return response.status(400).json({ error: "Payment verification data is incomplete." });
  }

  const expected = crypto
    .createHmac("sha256", secret)
    .update(`${orderId}|${paymentId}`)
    .digest("hex");
  if (!safeEqual(expected, signature)) {
    return response.status(400).json({ error: "Payment signature is invalid." });
  }

  // Private storage delivery will be attached here after a storage provider is selected.
  return response.status(200).json({ verified: true, orderId, paymentId });
};
