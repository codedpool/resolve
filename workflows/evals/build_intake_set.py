"""Builds datasets/intake.json: 20 text intake scenarios with hand labels.

Narration date is 2026-11-26 for every scenario. `expect` covers the six critical fields. Each has a
value (normalised: amount as digits, dates as ISO) and a certainty (stated, inferred, approximate,
not_stated). `flags` marks the trap in the scenario: contradiction, ambiguity, approximate, relative_date,
not_stated, correction.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parent / "datasets" / "intake.json"
REF = "2026-11-26"
S = "stated"
A = "approximate"
N = "not_stated"
I = "inferred"  # noqa: E741


def f(value="", certainty=N):
    return {"value": value, "certainty": certainty}


def sc(id, text, company, order_id, amount, order_date, promised, remedy, flags=(), note=""):
    return {
        "id": id, "narration_date": REF, "text": text, "flags": list(flags), "note": note,
        "expect": {"company_name": company, "order_id": order_id, "amount": amount,
                   "order_date": order_date, "promised_date": promised, "desired_remedy": remedy},
    }


SCENARIOS = [
    sc("in01", "Maine Flipkart se 20 November ko ek phone order kiya, order id OD1234567890. 10900 rupaye kate. Box mein sirf charger tha. Mujhe poora refund chahiye.",
       f("Flipkart", S), f("OD1234567890", S), f("10900", S), f("2026-11-20", S), f(), f("full refund", S)),
    sc("in02", "I ordered a laptop bag on Amazon around 3 weeks ago, order number 302-1112223-4445556. It cost about 5500. The zip was broken, I returned it but no refund yet. They said it would come by 30 November. I want my money back.",
       f("Amazon", S), f("302-1112223-4445556", S), f("5500", A), f("2026-11-05", A), f("2026-11-30", S), f("money back", S), ["approximate", "relative_date"]),
    sc("in03", "Swiggy se khana mangaya tha kal raat, delivered dikha raha hai par aaya nahi. Order id SW44556677 hai, 340 rupaye pay kiye the.",
       f("Swiggy", S), f("SW44556677", S), f("340", S), f("2026-11-25", S), f(), f(), ["relative_date", "not_stated"], "no remedy stated"),
    sc("in04", "Myntra ka order tha, do kurte, total 2500 rupaye. Wrong size the, return kiya, par Myntra bol raha hai item nahi mila. Order number MY9876543 hai. Date yaad nahi hai, shayad 10 November ke aas paas. Paisa wapas chahiye.",
       f("Myntra", S), f("MY9876543", S), f("2500", S), f("2026-11-10", A), f(), f("refund", S), ["approximate"]),
    sc("in05", "Zomato dinner order, I paid 680 rupees on the 22nd. Food was cold and items were missing. Order ID is ZM11223344. They offered 50 rupees credit but I want a full refund.",
       f("Zomato", S), f("ZM11223344", S), f("680", S), f("2026-11-22", S), f(), f("full refund", S)),
    sc("in06", "Paytm se bijli ka bill bhara, payment failed dikha lekin paise kat gaye. 2100 rupaye. Transaction id TXN555666777. 8 tarikh ko hua tha. Paise wapas chahiye.",
       f("Paytm", S), f("TXN555666777", S), f("2100", S), f("2026-11-08", S), f(), f("refund", S)),
    sc("in07", "Croma se washing machine li thi 16 November ko, 25900 ki. Chalu hi nahi hui. Technician teen baar aaya. Bill number CR220011. Replacement ya refund, jo bhi mile.",
       f("Croma", S), f("CR220011", S), f("25900", S), f("2026-11-16", S), f(), f("replacement or refund", S), ["ambiguity"], "two remedies offered by the consumer"),
    sc("in08", "MakeMyTrip pe flight book ki thi 3 November ko, 14200 rupaye. Airline ne cancel kar di. Booking reference MMT9988. Unhone kaha 90 din mein refund aayega, mujhe abhi chahiye.",
       f("MakeMyTrip", S), f("MMT9988", S), f("14200", S), f("2026-11-03", S), f(), f("immediate refund", S)),
    sc("in09", "Nykaa se cream mangayi, seal toota hua tha, fake lag raha hai. Order NY778899, 450 ka tha. Replacement nahi, refund chahiye. Order 20 tarikh ko kiya tha.",
       f("Nykaa", S), f("NY778899", S), f("450", S), f("2026-11-20", S), f(), f("refund", S)),
    sc("in10", "BigBasket grocery 12 tarikh ko order ki, 1300 rupaye. Doodh aur sabzi kharab thi. Customer care ne kaha do din mein refund aayega, ek hafta ho gaya. Order id BB1357924.",
       f("BigBasket", S), f("BB1357924", S), f("1300", S), f("2026-11-12", S), f(), f("refund", S)),
    sc("in11", "Maine kuch din pehle ek phone kharida online, company ka naam yaad nahi, bas itna pata hai ki 15000 ke aas paas tha. Screen kharab nikli.",
       f(), f(), f("15000", A), f(), f(), f(), ["not_stated", "approximate"], "company and order id are not stated"),
    sc("in12", "I bought shoes from Ajio and also a bag from Myntra last week. The shoes never arrived. Order AJ556677, 2999 rupees. I want a refund.",
       f("Ajio", I), f("AJ556677", S), f("2999", S), f("2026-11-19", A), f(), f("refund", S), ["ambiguity", "relative_date"], "two companies named; the shoes were Ajio, ambiguity_note expected"),
    sc("in13", "Order id OD2020202020 from Flipkart, Rs 8,999. Actually no, it was Rs 9,899, sorry. Date was last Tuesday. The TV panel is cracked. Replacement within 10 days was promised.",
       f("Flipkart", S), f("OD2020202020", S), f("9899", S), f("2026-11-24", S), f(), f("replacement", S), ["correction", "relative_date", "not_stated"], "amount corrected in the same narration; a promised period is not a date"),
    sc("in14", "Meri complaint Reliance Digital ke baare mein hai. Order RD123456, amount 4,50,000 nahi... 45,000 rupaye. AC install nahi hua. 2 December tak install karne ka wada kiya tha.",
       f("Reliance Digital", S), f("RD123456", S), f("45000", S), f(), f("2026-12-02", S), f(), ["correction", "not_stated"], "no order date, no remedy said; amount self-corrected"),
    sc("in15", "Meesho se saree mangayi thi parso, 899 rupaye. Dusri aayi, photo se alag. Order number ME44221. Wapas lekar paisa de do.",
       f("Meesho", S), f("ME44221", S), f("899", S), f("2026-11-24", A), f(), f("return and refund", S), ["relative_date"], "parso is ambiguous, approximate"),
    sc("in16", "Ek Samsung phone ka order tha Amazon pe, 22 tarikh ko. Seller ne alag IMEI wala phone bheja. Amount 18000. Mujhe nahi pata order id kya hai, email mein hai.",
       f("Amazon", S), f(), f("18000", S), f("2026-11-22", S), f(), f(), ["not_stated"], "order id and remedy not stated; Samsung is the brand, not the company"),
    sc("in17", "PhonePe se 5000 rupaye bhejne the, kat gaye, receiver ko nahi mile. Transaction id T2611261234567. Kal hua tha. Please reverse karo.",
       f("PhonePe", S), f("T2611261234567", S), f("5000", S), f("2026-11-25", S), f(), f("reversal", S), ["relative_date"]),
    sc("in18", "Hotel booking Goibibo se, 3 nights, 12,600 rupees, 1 December ki. Hotel ne kaha room nahi hai. Booking GB778899. Pura paisa wapas aur compensation chahiye.",
       f("Goibibo", S), f("GB778899", S), f("12600", S), f(), f(), f("full refund and compensation", S), ["not_stated"], "1 December is the stay date, not the order date"),
    sc("in19", "Shaadi ka lehenga order kiya tha Tata CLiQ se, around 30 hazaar ka. Order 10 November ko kiya, TC889900. Late aaya aur size galat. Refund de do ya size badal do.",
       f("Tata CLiQ", S), f("TC889900", S), f("30000", A), f("2026-11-10", S), f(), f("refund or size exchange", S), ["approximate", "ambiguity"]),
    sc("in20", "I paid 1,299 for a mixer grinder on Snapdeal on 18 November. Order SD90909. It stopped working after 2 days. They promised a technician visit by 28 November but nobody came. I want a replacement.",
       f("Snapdeal", S), f("SD90909", S), f("1299", S), f("2026-11-18", S), f("2026-11-28", S), f("replacement", S)),
]
assert len(SCENARIOS) == 20
OUT.write_text(json.dumps(SCENARIOS, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(SCENARIOS))
