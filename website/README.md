# Splitzzz storefront

Static, mobile-first storefront prepared for Vercel. The platform themes switch immediately; there are intentionally no color transitions or theme animations.

## Local preview

```powershell
cd website
npm run build
python -m http.server 8080 --directory dist
```

Open `http://localhost:8080`.

## Vercel

Import the GitHub repository and set **Root Directory** to `website`. Vercel uses `vercel.json` and publishes `dist`.

## Product delivery status

The public catalog is empty until private ZIP storage is connected. Do not commit Reel ZIP files to Git and do not place them in `website/public`. The bot creates verified local 50-Reel packs in `store-bundles/`; the website-storage copy and Razorpay delivery flow will be enabled after storage credentials are configured.

Prices are fixed in the storefront requirements:

- 50 Reels: ₹300
- 100 Reels (two 50-Reel ZIPs): ₹500

Public social links are configured in `public/app.js`.

## Razorpay safety gate

The serverless order and signature-verification endpoints are scaffolded under `api/`, but checkout
stays disabled until products have private downloadable storage. When that is ready, configure these
Vercel secrets (never commit them):

- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `SPLITZZZ_SELLABLE_PRODUCTS_JSON` — server-owned product IDs and paise amounts
- `STORE_LIVE=true`

Example product JSON: `{"pack-001":{"amount":30000}}`. The browser must never receive the Razorpay
secret. Payment verification does not yet release a file; private storage fulfilment is deliberately
left disabled until the selected storage phase begins.
