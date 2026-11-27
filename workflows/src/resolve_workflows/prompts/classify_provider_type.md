version: 1
You decide what kind of company a consumer bought from, from their short answer. You receive JSON with `text` and `labels`.

- `marketplace`: a large platform that sells and lists many sellers' goods (for example an online shopping app or site).
- `seller_on_marketplace`: a separate seller who sold through such a platform.
- `direct_seller`: the company's own website, app or shop.
- `payment_intermediary`: a payment app, wallet, bank or card company that moved the money.
- `unknown`: the answer does not say or the consumer does not know.

Return JSON with `label` and `confidence` between 0 and 1. Use `unknown` rather than guessing.
