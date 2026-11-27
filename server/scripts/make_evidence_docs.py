"""Draws the 30 evidence documents from workflows/evals/datasets/evidence.json into data/evidence_docs."""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "workflows" / "evals" / "datasets" / "evidence.json"
OUT = ROOT / "server" / "data" / "evidence_docs"
FONTS = Path("C:/Windows/Fonts")
random.seed(9)


def font(name: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size, index=index)


LATIN = font("arial.ttf", 30)
LATIN_BIG = font("arial.ttf", 40)
HINDI = font("Nirmala.ttc", 30)
HINDI_BIG = font("Nirmala.ttc", 40)


def lines_for(doc: dict) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    r = doc["render"]
    date_en = f"{r['day']} {r['month_en']} 2026"
    date_num = f"{r['day']:02d}/{r['month']:02d}/2026"
    kind, company = doc["kind"], doc["company_name"]
    if kind.startswith("order_en") or kind == "noisy_en":
        return [(company, LATIN_BIG), ("Order Confirmation", LATIN), (f"Order ID: {doc['order_id']}", LATIN),
                (f"Order date: {date_en}", LATIN), (f"Item: {r['item']}", LATIN), (f"Order total: {r['amount_text']}", LATIN),
                ("Payment: UPI", LATIN), ("Thank you for shopping with us", LATIN)]
    if kind == "invoice_en":
        return [(f"{company} Retail Pvt Ltd", LATIN_BIG), ("TAX INVOICE", LATIN), (f"Invoice date: {date_num}", LATIN),
                (f"Reference no: {doc['order_id']}", LATIN), (f"Item: {r['item']}", LATIN), (f"Amount paid: {r['amount_text']}", LATIN)]
    if kind == "upi_en":
        return [("Payment successful", LATIN_BIG), (f"Paid to {company}", LATIN), (f"Amount: {r['amount_text']}", LATIN),
                (f"Date: {date_en}", LATIN), (f"Transaction ID: {doc['order_id']}", LATIN)]
    if kind in {"order_hi", "noisy_hi"}:
        return [(company, LATIN_BIG), ("ऑर्डर की पुष्टि", HINDI_BIG), (f"ऑर्डर नंबर: {doc['order_id']}", HINDI),
                (f"ऑर्डर की तारीख: {r['day']} {r['month_hi']} 2026", HINDI), (f"कुल राशि: {r['amount_text']}", HINDI),
                ("आपके ऑर्डर के लिए धन्यवाद", HINDI)]
    return [(company, LATIN_BIG), ("Order summary / ऑर्डर सारांश", HINDI), (f"Order ID: {doc['order_id']}", LATIN),
            (f"तारीख: {date_en}", HINDI), (f"Total / कुल: {r['amount_text']}", HINDI)]


def render(doc: dict) -> Image.Image:
    lines = lines_for(doc)
    img = Image.new("RGB", (1000, 120 + 62 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    y = 40
    for text, fnt in lines:
        draw.text((50, y), text, fill="black", font=fnt)
        y += 62
    if doc["noisy"]:
        img = img.rotate(random.uniform(-2.5, 2.5), expand=True, fillcolor="white").filter(ImageFilter.GaussianBlur(0.9))
        px = img.load()
        for _ in range(img.width * img.height // 40):
            x, yy = random.randrange(img.width), random.randrange(img.height)
            v = random.randint(120, 230)
            px[x, yy] = (v, v, v)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for doc in json.loads(SPEC.read_text(encoding="utf-8")):
        render(doc).save(OUT / f"{doc['id']}.png")
    print("wrote", len(list(OUT.glob("*.png"))), "images to", OUT)


if __name__ == "__main__":
    main()
