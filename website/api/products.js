function products() {
  try {
    const value = JSON.parse(process.env.SPLITZZZ_SELLABLE_PRODUCTS_JSON || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

module.exports = async function listProducts(request, response) {
  response.setHeader("Cache-Control", "public, max-age=60, s-maxage=300");
  if (request.method !== "GET") {
    response.setHeader("Allow", "GET");
    return response.status(405).json({ error: "Method not allowed" });
  }

  const publicProducts = Object.entries(products())
    .filter(([, product]) => product && Array.isArray(product.objectKeys))
    .map(([id, product]) => ({
      id,
      name: String(product.name || `Splitzzz Reel Pack ${id}`),
      label: String(product.label || "READY TO UPLOAD"),
      reelCount: Number(product.reelCount || product.objectKeys.length * 50),
      price: Number(product.amount || 0) / 100,
      available: true,
    }))
    .filter((product) => [50, 100].includes(product.reelCount) && product.price > 0);

  return response.status(200).json(publicProducts);
};
