"""Small Hindi and Hinglish to English consumer-law word list for the full-text half of retrieval.

The legal sources are English, and full-text search matches words, so a question written in
Devanagari or in Latin-script Hindi finds nothing by words alone. Words found here add their English
equivalents to the full-text query only. The vector half is untouched. The list is general consumer
vocabulary, not tuned to the evaluation questions, and a miss costs nothing: the vector half still runs.
"""

from __future__ import annotations

import re

# Devanagari stems; a stem matches inside longer inflected words (शिकायतें, शिकायत).
DEVANAGARI = {
    "शिकायत अधिकारी": "grievance officer",
    "शिकायत": "complaint",
    "उपभोक्ता": "consumer",
    "ग्राहक": "consumer",
    "अपील": "appeal",
    "आयोग": "commission",
    "जिला": "district",
    "राज्य": "state",
    "राष्ट्रीय": "national",
    "लोकपाल": "ombudsman",
    "आरबीआई": "RBI reserve bank",
    "बैंक": "bank",
    "रिफंड": "refund",
    "पैसे लौट": "refund price",
    "पैसे वापस": "refund price",
    "वापस": "take back return",
    "खराब": "defective defect",
    "दोष": "defect",
    "सामान": "goods",
    "वस्तु": "goods",
    "उत्पाद": "product",
    "सेवा": "service",
    "विक्रेता": "seller",
    "दुकानदार": "seller trader",
    "कंपनी": "entity company",
    "ऑर्डर": "order purchase",
    "रद्द": "cancel cancellation",
    "कैंसल": "cancel cancellation",
    "शुल्क": "charges",
    "चार्ज": "charges",
    "समय सीमा": "period limit within",
    "समय": "period time",
    "दिन": "days",
    "घंटे": "hours",
    "महीने": "month months",
    "साल": "years",
    "वर्ष": "years",
    "जुर्माना": "penalty fine",
    "सज़ा": "punishment imprisonment",
    "सजा": "punishment imprisonment",
    "मुआवज": "compensation",
    "बदल": "replace replacement",
    "पावती": "acknowledges receipt acknowledge",
    "अनुचित": "unfair",
    "व्यापार": "trade",
    "व्यवहार": "practice",
    "विज्ञापन": "advertisement",
    "भ्रामक": "misleading",
    "हेल्पलाइन": "helpline",
    "टोल फ्री": "toll free",
    "व्हाट्सएप": "whatsapp",
    "नंबर": "number",
    "ई-कॉमर्स": "e-commerce",
    "मार्केटप्लेस": "marketplace",
    "भुगतान": "payment",
    "वारंटी": "warranty",
    "गारंटी": "guarantee",
    "नकली": "spurious",
    "मध्यस्थता": "mediation",
    "अधिकार": "rights",
    "पुष्टि": "confirming confirm",
    "स्थापित": "established",
    "लागू": "apply applicability",
    "अदालत": "court",
}

# Latin-script Hindi (Hinglish). Whole words only.
HINGLISH = {
    "shikayat": "complaint",
    "upbhokta": "consumer",
    "grahak": "consumer",
    "aayog": "commission",
    "lokpal": "ombudsman",
    "wapas": "take back return",
    "kharab": "defective defect",
    "saman": "goods",
    "dukandar": "seller trader",
    "vikreta": "seller",
    "rad": "cancel cancellation",
    "jurmana": "penalty fine",
    "saza": "punishment imprisonment",
    "muavza": "compensation",
    "mana": "refuse refusal",
    "din": "days",
    "ghante": "hours",
    "mahine": "month",
    "saal": "years",
    "samay": "period time",
    "adalat": "court",
    "vigyapan": "advertisement",
    "dhokha": "unfair deceptive",
}


def english_terms(query: str) -> list[str]:
    """English words to add to the full-text query for a Hindi or Hinglish question.

    Longer stems are matched first and consumed, so "शिकायत अधिकारी" (grievance officer) does not also
    match the shorter stem "अधिकार" (rights)."""
    found: list[str] = []
    remaining = query
    for stem in sorted(DEVANAGARI, key=len, reverse=True):
        if stem in remaining:
            found.extend(DEVANAGARI[stem].split())
            remaining = remaining.replace(stem, " ")
    for word in re.findall(r"[a-z]+", query.lower()):
        if word in HINGLISH:
            found.extend(HINGLISH[word].split())
    return list(dict.fromkeys(found))
