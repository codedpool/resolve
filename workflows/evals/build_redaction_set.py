"""Builds datasets/redaction.json: 150 labelled strings for the redaction engine.

Each item has: class, text, redact (substrings that must not survive), keep (substrings that must
survive), reversible (order-id tokens must round-trip). Deterministic; run it to regenerate.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(11)
OUT = Path(__file__).parent / "datasets" / "redaction.json"
ITEMS: list[dict] = []

SPOKEN = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}
HINDI = {"0": "shunya", "1": "ek", "2": "do", "3": "teen", "4": "chaar", "5": "paanch", "6": "chhe", "7": "saat", "8": "aath", "9": "nau"}


def luhn_ok(num: str) -> bool:
    total, alt = 0, False
    for ch in reversed(num):
        d = int(ch)
        if alt:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
        alt = not alt
    return total % 10 == 0


def luhn_complete(prefix: str, length: int) -> str:
    body = prefix + "".join(random.choice("0123456789") for _ in range(length - len(prefix) - 1))
    for d in "0123456789":
        if luhn_ok(body + d):
            return body + d
    raise AssertionError


def luhn_break(num: str) -> str:
    for d in "0123456789":
        cand = num[:-1] + d
        if not luhn_ok(cand):
            return cand
    raise AssertionError


def add(cls: str, text: str, redact=(), keep=(), reversible=False) -> None:
    ITEMS.append({"id": "", "class": cls, "text": text, "redact": list(redact), "keep": list(keep), "reversible": reversible})


def digits(n: int, first: str = "") -> str:
    return first + "".join(random.choice("0123456789") for _ in range(n - len(first)))


def spoken(ds: str, table: dict) -> str:
    return " ".join(table[c] for c in ds)


def groups4(n: str, sep: str = " ") -> str:
    return sep.join(n[j:j + 4] for j in range(0, len(n), 4))


# OTP (25)
for i in range(8):
    d = digits(random.choice([4, 6]))
    add("otp", random.choice(["mera OTP {d} hai", "OTP is {d}", "code {d} aaya hai verification ke liye", "the verification code is {d} please check"]).format(d=d), [d])
for i in range(6):
    d = digits(random.choice([4, 6]))
    add("otp", random.choice(["OTP hai {s}", "my OTP is {s}", "verification code {s}"]).format(s=spoken(d, SPOKEN if i % 2 else HINDI)), [d, spoken(d, SPOKEN), spoken(d, HINDI)])
for i in range(5):
    d = digits(6)
    add("otp", f"jo code aaya wo {d[:3]} {d[3:]} hai", [d, d[:3] + " " + d[3:]])
for i in range(3):
    d = digits(8)
    add("otp", f"OTP number {d} bataya tha", [d])
for i in range(3):
    d = digits(4)
    add("otp", f"CVV code {d} hai card ka", [d])

# Card (25)
VALID_PREFIX = ["4", "51", "37", "6011", "35"]
for i in range(8):
    n = luhn_complete(random.choice(VALID_PREFIX), random.choice([15, 16]))
    form = [n, groups4(n), groups4(n, "-")][i % 3]
    add("card", random.choice(["card number {n} hai", "debit card {n} se pay kiya", "my credit card is {n}"]).format(n=form), [n, form])
for i in range(7):
    n = luhn_break(luhn_complete(random.choice(VALID_PREFIX), 16))
    form = groups4(n)
    add("card", random.choice(["card number {n}", "debit card {n} tha", "credit card {n} ka expiry bhi hai"]).format(n=form), [n, form])
for i in range(5):
    n = luhn_break(luhn_complete("4", 16))
    add("card", f"card number {spoken(n, SPOKEN)}", [n, spoken(n, SPOKEN)])
for i in range(3):
    n = luhn_break(luhn_complete("5", 16))
    add("card", f"maine card se {n} se payment kiya", [n])
for i in range(2):
    n = luhn_complete("4", 16)
    add("card", f"{n} yeh number hai", [n])

# Identity (10)
for i in range(4):
    d = digits(12, random.choice("23456789"))
    form = f"{d[:4]} {d[4:8]} {d[8:]}"
    add("identity", random.choice(["aadhaar number {n} hai", "my Aadhaar is {n}", "UID {n}"]).format(n=form), [d, form])
for i in range(3):
    pan = "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5)) + digits(4) + random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ")
    add("identity", random.choice(["PAN number {p} hai", "my PAN is {p}", "tax id {p}"]).format(p=pan), [pan])
for i in range(3):
    d = digits(12, random.choice("23456789"))
    add("identity", f"aadhar card number {spoken(d, HINDI)}", [d, spoken(d, HINDI)])

# Phone (8) and email (5)
for i in range(5):
    d = digits(10, random.choice("6789"))
    add("phone", random.choice(["mera number {n} hai", "call me on +91 {n}", "phone {n}"]).format(n=d), [d])
for i in range(3):
    d = digits(10, random.choice("6789"))
    add("phone", f"mera mobile number {spoken(d, HINDI)} hai", [d, spoken(d, HINDI)])
for e in ["rahul.sharma92@gmail.com", "priya_k@yahoo.in", "amit.verma@outlook.com", "neha123@rediffmail.com", "sanjay.k@example.org"]:
    add("email", random.choice(["mera email {e} hai", "email id {e}", "send it to {e} please"]).format(e=e), [e])

# Address (12)
for street, pin in [("flat 4B, Rose Apartments, MG Road", "560001"), ("house no 22, Gandhi Nagar", "110031"),
                    ("plot 15, Sector 21", "122001"), ("room 305, Shanti Colony", "400012"), ("door no 7, Lake View Layout", "600042"),
                    ("flat 12, Green Enclave, Civil Lines", "226001")]:
    add("address", f"mera address {street}, pin code {pin} hai", [street, pin])
for pin in ["560034", "700091", "380015", "411045"]:
    add("address", f"pincode {pin} pe deliver hona tha", [pin])
add("address", "main Shanti Colony, Andheri East rehta hoon", ["Shanti Colony"])
add("address", "deliver to H.No 45, Rajiv Vihar", ["H.No 45", "Rajiv Vihar"])

# Order ids (15), reversible
for i in range(5):
    oid = f"OD{digits(10)}"
    add("order_id", random.choice(["order id {o} hai", "Order ID: {o}", "mera order number {o} tha"]).format(o=oid) + " aur refund nahi aaya", [oid], reversible=True)
for i in range(3):
    oid = f"{digits(3)}-{digits(7)}-{digits(7)}"
    add("order_id", f"order number {oid} dekhiye", [oid], reversible=True)
for oid, label in [("MMT9988", "booking reference"), ("TXN555666777", "transaction id"), ("CR220011", "bill number"), ("NY778899", "order number")]:
    add("order_id", f"{label} {oid} hai", [oid], reversible=True)
oid = luhn_complete("1", 17)
add("order_id", f"order id {oid} hai", [oid], reversible=True)  # 17 digits that pass Luhn, under an order label
d = digits(6)
add("order_id", f"order id OD {spoken(d, SPOKEN)}", [d, spoken(d, SPOKEN)], reversible=True)
ref = digits(9)
add("order_id", f"ticket reference {ref} ka status", [ref], reversible=True)

# Other long digit runs (10): dropped
for i in range(10):
    d = digits(random.choice([14, 15, 16, 17, 18]))
    d = d if not luhn_ok(d) else luhn_break(d)
    add("other_long", random.choice(["woh number {n} tha", "yeh likha hai {n}", "slip par {n} aaya"]).format(n=d), [d])

# Keep: amounts, dates, years and ordinary small numbers (40): must survive
for a, k in [("₹12,000", "12,000"), ("Rs 450", "450"), ("1200 rupaye", "1200"), ("Rs.5500", "5500"), ("₹ 2,100", "2,100"),
             ("680 rupees", "680"), ("INR 14200", "14200"), ("₹1,00,000", "1,00,000")]:
    add("keep", random.choice(["{a} kat gaye mere account se", "refund of {a} chahiye", "total {a} ka order tha"]).format(a=a), keep=[k])
for t, k in [("barah sau rupaye kat gaye", "1200"), ("do hazaar paanch sau rupaye kat gaye", "2500"), ("teen sau chaalis rupaye kat gaye", "340"),
             ("twelve hundred rupees kat gaye", "1200"), ("paanch hazaar rupaye kat gaye", "5000")]:
    add("keep", t, keep=[k])
for t, k in [("20/11/2026 ko order kiya", "20/11/2026"), ("20 November 2026 ko mila", "20 November 2026"), ("order March 2025 mein kiya tha", "2025"),
             ("2024 mein kharida tha", "2024"), ("year 2023 ki baat hai", "2023"), ("15th ko delivery thi", "15th")]:
    add("keep", t, keep=[k])
for t, k in [("5500 rupaye ka phone order OD1234567890", "5500"), ("order OD1234567890 ke 450 rupaye", "450"), ("1 phone aur 2 charger mangaye", "2 charger"),
             ("refund 7 din mein aana tha", "7 din"), ("3 baar call kiya", "3 baar"), ("warranty 12 mahine ki thi", "12 mahine"), ("size 42 mangaya tha", "42"),
             ("1500 ka offer tha", "1500"), ("bas 25 percent discount tha", "25 percent"), ("delivery 10 baje thi", "10 baje"),
             ("2 hafte se wait kar raha hoon", "2 hafte"), ("rating 4 star di thi", "4 star"), ("amount Rs 99 tha", "99"), ("seat 14 booked tha", "14"),
             ("flight 6E 204 thi", "204"), ("2500 rupaye wapas chahiye", "2500"), ("refund 30 din mein", "30 din"), ("5 din pehle order kiya", "5 din"), ("quantity 3 thi", "quantity 3"), ("Rs 750 ka coupon tha", "750"), ("9 tarikh ko call kiya", "9 tarikh")]:
    add("keep", t, keep=[k])

random.shuffle(ITEMS)
for i, item in enumerate(ITEMS, 1):
    item["id"] = f"rd{i:03d}"
assert len(ITEMS) == 150, len(ITEMS)
OUT.write_text(json.dumps(ITEMS, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(ITEMS), {c: sum(1 for x in ITEMS if x["class"] == c) for c in sorted({x["class"] for x in ITEMS})})
