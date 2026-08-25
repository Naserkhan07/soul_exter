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
- `SPLITZZZ_SELLABLE_PRODUCTS_JSON` — server-owned product IDs, paise amounts, and private object keys
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`
- `STORE_LIVE=true`

Example product JSON:
`{"pack-001":{"name":"50 Reel Pack 001","reelCount":50,"amount":30000,"objectKeys":["bundles/splitzzz-reels-pack-001-50-reels.zip"]}}`.
The browser never receives Razorpay or R2 secrets. ZIP objects remain private; after the server
verifies a paid Razorpay order, it returns download URLs signed for only 15 minutes. Browser source
and the public product catalog contain no permanent ZIP URL.
