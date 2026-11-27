"""Builds datasets/evidence.json: 30 evidence documents with hand labels (fictional data only).

The images are drawn by server/scripts/make_evidence_docs.py from these specs. Fields to find:
company_name, order_id, amount (digits), order_date (ISO).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(5)
OUT = Path(__file__).parent / "datasets" / "evidence.json"
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
COMPANIES = ["Flipkart", "Amazon", "Myntra", "Swiggy", "Zomato", "Croma", "Nykaa", "BigBasket", "Meesho", "Ajio", "Snapdeal", "Tata CLiQ"]
PREFIX = {"Flipkart": "OD", "Amazon": "", "Myntra": "MY", "Swiggy": "SW", "Zomato": "ZM", "Croma": "CR", "Nykaa": "NY",
          "BigBasket": "BB", "Meesho": "ME", "Ajio": "AJ", "Snapdeal": "SD", "Tata CLiQ": "TC"}


def order_id(company: str) -> str:
    if company == "Amazon":
        return f"{random.randint(100, 999)}-{random.randint(1000000, 9999999)}-{random.randint(1000000, 9999999)}"
    return PREFIX[company] + str(random.randint(10**7, 10**9 - 1))


def amount_text(value: int, style: str) -> str:
    if style == "rupee":
        return f"₹{value:,}"
    if style == "rs":
        return f"Rs. {value:,}.00"
    return f"INR {value}"


DOCS = []
kinds = (["order_en"] * 10 + ["invoice_en"] * 4 + ["upi_en"] * 4 + ["order_hi"] * 5 + ["order_mixed"] * 3 + ["noisy_en"] * 2 + ["noisy_hi"] * 2)
for i, kind in enumerate(kinds, 1):
    company = random.choice(COMPANIES)
    oid = order_id(company)
    value = random.choice([450, 680, 899, 1299, 2100, 2500, 4999, 10900, 14200, 25900])
    day, month = random.randint(1, 28), random.randint(1, 11)
    iso = f"2026-{month:02d}-{day:02d}"
    lang = "hi" if kind.endswith("_hi") else "mixed" if kind == "order_mixed" else "en"
    style = random.choice(["rupee", "rs", "inr"])
    DOCS.append({
        "id": f"ev{i:02d}", "kind": kind, "language": lang, "noisy": kind.startswith("noisy"),
        "company_name": company, "order_id": oid, "amount": str(value), "order_date": iso,
        "render": {"day": day, "month_en": MONTHS_EN[month - 1], "month_hi": MONTHS_HI[month - 1], "month": month,
                   "amount_text": amount_text(value, style), "item": random.choice(["Wireless earbuds", "Cotton kurta", "Mixer grinder", "Phone case", "Running shoes"])},
    })
assert len(DOCS) == 30
OUT.write_text(json.dumps(DOCS, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(DOCS))
