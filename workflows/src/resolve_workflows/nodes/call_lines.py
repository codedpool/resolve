"""Fallback wording for the provider call, in English, Hindi and Hinglish.

The draft model words each reply from a `move`; these lines are the suggested wording given to it and the text used when
the model is unavailable or its draft misses a required point. Every line here must pass the output guard on its own (a
test checks that), and none states a rule, a deadline or a number the case does not hold.
"""

from __future__ import annotations

LINES: dict[str, dict[str, str]] = {
    "open": {
        "en": "Hello, I am an AI assistant calling{for_whom} about {subject}. This is a simulated call.",
        "hi": "नमस्कार, मैं एक एआई सहायक हूँ और{for_whom} {subject} के बारे में फ़ोन कर रहा हूँ। यह एक सिमुलेटेड कॉल है।",
        "hinglish": "Hello, main ek AI assistant hoon aur{for_whom} {subject} ke baare mein call kar raha hoon. Yeh ek simulated call hai.",
    },
    "purpose": {
        "en": "I am calling{for_whom} about {subject}.",
        "hi": "मैं{for_whom} {subject} के बारे में फ़ोन कर रहा हूँ।",
        "hinglish": "Main{for_whom} {subject} ke baare mein call kar raha hoon.",
    },
    "ask_reference_and_date": {
        "en": "Could you please share a reference or ticket number, and the date by which the refund will reach the customer?",
        "hi": "क्या आप कृपया एक संदर्भ या टिकट नंबर बता सकते हैं, और वह तारीख जब तक पैसा ग्राहक तक पहुँचेगा?",
        "hinglish": "Kya aap ek reference ya ticket number bata sakte hain, aur woh date jab tak refund customer tak pahunchega?",
    },
    "ask_reference": {
        "en": "Could you please share a reference or ticket number for this?",
        "hi": "क्या आप कृपया इसके लिए एक संदर्भ या टिकट नंबर बता सकते हैं?",
        "hinglish": "Kya aap iske liye ek reference ya ticket number bata sakte hain?",
    },
    "ask_date": {
        "en": "Could you please confirm the date by which the refund will reach the customer?",
        "hi": "क्या आप कृपया वह तारीख बता सकते हैं जब तक पैसा ग्राहक तक पहुँचेगा?",
        "hinglish": "Kya aap woh date bata sakte hain jab tak refund customer tak pahunchega?",
    },
    "evidence_missing": {
        "en": "Thank you. The customer has no record of receiving that refund. Could you share the refund reference number, the date and the account it was sent to?",
        "hi": "धन्यवाद। ग्राहक के पास उस रिफंड के मिलने का कोई रिकॉर्ड नहीं है। क्या आप रिफंड का संदर्भ नंबर, तारीख और जिस खाते में भेजा गया वह बता सकते हैं?",
        "hinglish": "Thank you. Customer ke paas us refund ke milne ka koi record nahi hai. Kya aap refund ka reference number, date aur jis account mein bheja gaya woh bata sakte hain?",
    },
    "evidence_mismatch": {
        "en": "That does not match the customer's records{owed_clause}. Could you share the refund reference number, the date and the account it was sent to?",
        "hi": "यह ग्राहक के रिकॉर्ड से मेल नहीं खाता{owed_clause}। क्या आप रिफंड का संदर्भ नंबर, तारीख और जिस खाते में भेजा गया वह बता सकते हैं?",
        "hinglish": "Yeh customer ke records se match nahi karta{owed_clause}. Kya aap refund ka reference number, date aur jis account mein bheja gaya woh bata sakte hain?",
    },
    "evidence_match": {
        "en": "Thank you, that is consistent with what the customer has on record. Could you share the reference number so the customer can confirm when the money arrives?",
        "hi": "धन्यवाद, यह ग्राहक के रिकॉर्ड से मेल खाता है। क्या आप संदर्भ नंबर बता सकते हैं ताकि पैसा आने पर ग्राहक पुष्टि कर सकें?",
        "hinglish": "Thank you, yeh customer ke record se match karta hai. Kya aap reference number bata sakte hain taaki paisa aane par customer confirm kar sakein?",
    },
    "reference_noted": {
        "en": "Thank you, I have noted reference {reference}.",
        "hi": "धन्यवाद, मैंने संदर्भ {reference} नोट कर लिया है।",
        "hinglish": "Thank you, maine reference {reference} note kar liya hai.",
    },
    "claim_generic": {
        "en": "Thank you for explaining. Could you tell me the date by which the refund can be completed?",
        "hi": "समझाने के लिए धन्यवाद। क्या आप बता सकते हैं कि रिफंड किस तारीख तक पूरा हो सकता है?",
        "hinglish": "Samjhane ke liye thank you. Kya aap bata sakte hain ki refund kis date tak ho sakta hai?",
    },
    "ask_clause": {
        "en": "Could you tell me which clause of your policy says so?",
        "hi": "क्या आप बता सकते हैं कि आपकी पॉलिसी का कौन सा खंड यह कहता है?",
        "hinglish": "Kya aap bata sakte hain ki aapki policy ka kaun sa clause yeh kehta hai?",
    },
    "policy_unknown": {
        "en": "I cannot confirm that from the sources I have. Could you point me to the clause that says so? I will check it with the customer.",
        "hi": "मेरे पास मौजूद स्रोतों से मैं इसकी पुष्टि नहीं कर सकता। क्या आप वह खंड बता सकते हैं जो यह कहता है? ग्राहक से इसकी जाँच मैं कर लूँगा।",
        "hinglish": "Mere paas jo sources hain unse main isse confirm nahi kar sakta. Kya aap woh clause bata sakte hain jo yeh kehta hai? Main customer se check kar lunga.",
    },
    "offer_outside": {
        "en": "Thank you for the offer. I am not able to accept or counter it on my own; I have noted {offer_desc} and will pass it to the customer, who will decide through the app. Thank you for your time.",
        "hi": "ऑफ़र के लिए धन्यवाद। मैं इसे अपने आप स्वीकार या जवाबी प्रस्ताव नहीं दे सकता; मैंने {offer_desc} नोट कर लिया है और ग्राहक को दे दूँगा, जो ऐप में तय करेंगे। आपके समय के लिए धन्यवाद।",
        "hinglish": "Offer ke liye thank you. Main ise khud accept ya counter nahi kar sakta; maine {offer_desc} note kar liya hai aur customer ko de dunga, jo app mein decide karenge. Aapke time ke liye thank you.",
    },
    "promise_secured": {
        "en": "Thank you. I have noted that the refund is promised by {date}, under reference {reference}. The customer will confirm once the money arrives. Goodbye.",
        "hi": "धन्यवाद। मैंने नोट कर लिया है कि रिफंड {date} तक का वादा है, संदर्भ {reference}। पैसा आने पर ग्राहक पुष्टि करेंगे। नमस्कार।",
        "hinglish": "Thank you. Maine note kar liya hai ki refund {date} tak ka promise hai, reference {reference}. Paisa aane par customer confirm karenge. Goodbye.",
    },
    "decline_never": {
        "en": "I am sorry, I never share one-time codes, passwords, card or identity numbers, and a refund does not need them.",
        "hi": "क्षमा करें, मैं वन-टाइम कोड, पासवर्ड, कार्ड या पहचान संख्या कभी साझा नहीं करता, और रिफंड के लिए इनकी ज़रूरत नहीं है।",
        "hinglish": "Maaf kijiye, main one-time code, password, card ya identity number kabhi share nahi karta, aur refund ke liye inki zaroorat nahi hai.",
    },
    "decline_unlisted": {
        "en": "I am sorry, I am not able to share that detail on this call.",
        "hi": "क्षमा करें, मैं यह जानकारी इस कॉल में साझा नहीं कर सकता।",
        "hinglish": "Maaf kijiye, main yeh jaankari is call mein share nahi kar sakta.",
    },
    "asked_customer": {
        "en": "I have asked the customer whether I may share it.",
        "hi": "मैंने ग्राहक से पूछ लिया है कि क्या मैं इसे साझा कर सकता हूँ।",
        "hinglish": "Maine customer se pooch liya hai ki kya main ise share kar sakta hoon.",
    },
    "offer_alternatives": {
        "en": "I can share {names}, which should be enough to find the order.",
        "hi": "मैं {names} बता सकता हूँ, जो ऑर्डर ढूँढने के लिए काफ़ी होना चाहिए।",
        "hinglish": "Main {names} bata sakta hoon, jo order dhoondhne ke liye kaafi hona chahiye.",
    },
    "answer_field": {
        "en": "{label} is {value}.",
        "hi": "{label} {value} है।",
        "hinglish": "{label} {value} hai.",
    },
    "general_ask": {
        "en": "Could you tell me exactly which detail you need for the refund? I can only share what the customer has allowed.",
        "hi": "क्या आप बता सकते हैं कि रिफंड के लिए आपको ठीक कौन सी जानकारी चाहिए? मैं केवल वही बता सकता हूँ जो ग्राहक ने अनुमति दी है।",
        "hinglish": "Kya aap bata sakte hain ki refund ke liye aapko theek kaun si jaankari chahiye? Main sirf wahi bata sakta hoon jo customer ne allow kiya hai.",
    },
    "injection_restate": {
        "en": "I am not able to act on that. I am calling{for_whom} about {subject}. Could you tell me when the refund can be processed?",
        "hi": "मैं उस पर कार्रवाई नहीं कर सकता। मैं{for_whom} {subject} के बारे में फ़ोन कर रहा हूँ। क्या आप बता सकते हैं कि रिफंड कब तक हो सकता है?",
        "hinglish": "Main us par action nahi le sakta. Main{for_whom} {subject} ke baare mein call kar raha hoon. Kya aap bata sakte hain ki refund kab tak ho sakta hai?",
    },
    "stall_restate": {
        "en": "I understand. Could you confirm the date by which the refund will be processed, ideally by {ask_by}?",
        "hi": "मैं समझता हूँ। क्या आप बता सकते हैं कि रिफंड किस तारीख तक प्रोसेस होगा, बेहतर होगा {ask_by} तक?",
        "hinglish": "Main samajhta hoon. Kya aap bata sakte hain ki refund kis date tak process hoga, behtar hoga {ask_by} tak?",
    },
    "stall_escalate": {
        "en": "I have noted that I could not get a date today. I will tell the customer, who can decide on the next step. Thank you for your time.",
        "hi": "मैंने नोट कर लिया है कि आज कोई तारीख नहीं मिली। ग्राहक को यह बता दिया जाएगा, जो अगला कदम तय करेंगे। आपके समय के लिए धन्यवाद।",
        "hinglish": "Maine note kar liya hai ki aaj koi date nahi mili. Main customer ko bata dunga, jo agla step decide karenge. Aapke time ke liye thank you.",
    },
    "hostile_first": {
        "en": "I understand this is frustrating, and I will keep it short. Could you tell me by when the refund can be processed, ideally by {ask_by}?",
        "hi": "मैं समझता हूँ कि यह परेशान करने वाला है, मैं संक्षेप में रखूँगा। क्या आप बता सकते हैं कि रिफंड कब तक हो सकता है, बेहतर होगा {ask_by} तक?",
        "hinglish": "Main samajhta hoon ki yeh frustrating hai, main short rakhunga. Kya aap bata sakte hain ki refund kab tak ho sakta hai, behtar hoga {ask_by} tak?",
    },
    "hostile_second": {
        "en": "I understand. I only need a date and a reference number for the customer. Could you give me those?",
        "hi": "मैं समझता हूँ। ग्राहक के लिए मुझे बस एक तारीख और संदर्भ नंबर चाहिए। क्या आप दे सकते हैं?",
        "hinglish": "Main samajhta hoon. Customer ke liye mujhe bas ek date aur reference number chahiye. Kya aap de sakte hain?",
    },
    "hostile_end": {
        "en": "I understand, I will not take more of your time. I will let the customer know. Thank you.",
        "hi": "मैं समझता हूँ, मैं आपका और समय नहीं लूँगा। ग्राहक को यह बता दिया जाएगा। धन्यवाद।",
        "hinglish": "Main samajhta hoon, main aapka aur time nahi lunga. Main customer ko bata dunga. Thank you.",
    },
    "silence_check": {
        "en": "Hello, is anyone there? I am calling{for_whom} about {subject}.",
        "hi": "नमस्कार, क्या कोई है? मैं{for_whom} {subject} के बारे में फ़ोन कर रहा हूँ।",
        "hinglish": "Hello, kya koi hai? Main{for_whom} {subject} ke baare mein call kar raha hoon.",
    },
    "silence_end": {
        "en": "I am not able to hear anyone, so I will end the call now. Thank you.",
        "hi": "मुझे कोई सुनाई नहीं दे रहा, इसलिए मैं अब कॉल समाप्त करता हूँ। धन्यवाद।",
        "hinglish": "Mujhe koi sunai nahi de raha, isliye main ab call end karta hoon. Thank you.",
    },
    "contradiction": {
        "en": "I have heard different answers: first {first}, and then {second}. Could you share the refund reference and any proof, such as the delivery confirmation, so the customer can check?",
        "hi": "मैंने अलग-अलग जवाब सुने: पहले {first}, और फिर {second}। क्या आप रिफंड का संदर्भ और कोई प्रमाण, जैसे डिलीवरी की पुष्टि, दे सकते हैं ताकि ग्राहक जाँच सकें?",
        "hinglish": "Maine alag-alag jawab sune: pehle {first}, aur phir {second}. Kya aap refund ka reference aur koi proof, jaise delivery confirmation, de sakte hain taaki customer check kar sakein?",
    },
    "redirect": {
        "en": "Thank you, I have noted the number {number} for the customer to approve. Could this desk at least log the complaint and give me a ticket number?",
        "hi": "धन्यवाद, मैंने ग्राहक की अनुमति के लिए नंबर {number} नोट कर लिया है। क्या यह डेस्क कम से कम शिकायत दर्ज करके मुझे टिकट नंबर दे सकता है?",
        "hinglish": "Thank you, maine customer ki approval ke liye number {number} note kar liya hai. Kya yeh desk kam se kam complaint log karke mujhe ticket number de sakta hai?",
    },
    "end_time": {
        "en": "I need to end the call now because the time is up. I will pass the details to the customer. Thank you.",
        "hi": "समय पूरा हो गया है, इसलिए मुझे अब कॉल समाप्त करनी होगी। मैं जानकारी ग्राहक को दे दूँगा। धन्यवाद।",
        "hinglish": "Time poora ho gaya hai, isliye mujhe ab call end karni hogi. Main details customer ko de dunga. Thank you.",
    },
    "end_turns": {
        "en": "I will end the call here and pass what we discussed to the customer. Thank you for your time.",
        "hi": "मैं कॉल यहीं समाप्त करता हूँ और जो बात हुई वह ग्राहक को बता दूँगा। आपके समय के लिए धन्यवाद।",
        "hinglish": "Main call yahin end karta hoon aur jo baat hui woh customer ko bata dunga. Aapke time ke liye thank you.",
    },
    "hold_wait": {
        "en": "One moment please, I am checking that.",
        "hi": "कृपया एक क्षण रुकिए, मैं जाँच रहा हूँ।",
        "hinglish": "Ek minute please, main check kar raha hoon.",
    },
    "end_budget": {
        "en": "I have to stop the call here because the usage limit of this service has been reached. I will pass what we discussed to the customer. Thank you for your time.",
        "hi": "इस सेवा की उपयोग सीमा पूरी हो गई है, इसलिए मुझे कॉल यहीं रोकनी होगी। जो बात हुई वह ग्राहक को बता दी जाएगी। आपके समय के लिए धन्यवाद।",
        "hinglish": "Is service ki usage limit poori ho gayi hai, isliye mujhe call yahin rokni hogi. Jo baat hui woh main customer ko bata dunga. Aapke time ke liye thank you.",
    },
    "end_consumer": {
        "en": "I will end the call now. Thank you for your time.",
        "hi": "मैं अब कॉल समाप्त करता हूँ। आपके समय के लिए धन्यवाद।",
        "hinglish": "Main ab call end karta hoon. Aapke time ke liye thank you.",
    },
}

FIELD_LABEL = {
    "order_id": {"en": "The order number", "hi": "ऑर्डर नंबर", "hinglish": "Order number"},
    "amount": {"en": "The amount", "hi": "राशि", "hinglish": "Amount"},
    "order_date": {"en": "The order date", "hi": "ऑर्डर की तारीख", "hinglish": "Order ki date"},
    "issue_summary": {"en": "The complaint", "hi": "शिकायत", "hinglish": "Complaint"},
    "consumer_name": {"en": "The customer's name", "hi": "ग्राहक का नाम", "hinglish": "Customer ka naam"},
}
FIELD_NOUN = {
    "order_id": {"en": "the order number", "hi": "ऑर्डर नंबर", "hinglish": "order number"},
    "amount": {"en": "the amount", "hi": "राशि", "hinglish": "amount"},
    "order_date": {"en": "the order date", "hi": "ऑर्डर की तारीख", "hinglish": "order date"},
    "issue_summary": {"en": "the complaint", "hi": "शिकायत", "hinglish": "complaint"},
    "consumer_name": {"en": "the customer's name", "hi": "ग्राहक का नाम", "hinglish": "customer ka naam"},
}
CLAIM_PHRASE = {
    "processed": {"en": "that the refund was processed", "hi": "कि रिफंड हो चुका है", "hinglish": "ki refund ho chuka hai"},
    "no_request": {"en": "that no refund request was received", "hi": "कि कोई रिफंड अनुरोध नहीं मिला", "hinglish": "ki koi refund request nahi mili"},
    "delivered": {"en": "that the order was delivered", "hi": "कि ऑर्डर डिलीवर हो गया", "hinglish": "ki order deliver ho gaya"},
}
_CONJ = {"en": " and ", "hi": " और ", "hinglish": " aur "}


def lang_of(language: str) -> str:
    return language if language in ("en", "hi", "hinglish") else "en"


def line(key: str, language: str, **kw) -> str:
    lang = lang_of(language)
    return LINES[key].get(lang, LINES[key]["en"]).format(**kw)


def noun_list(fields: list[str], language: str) -> str:
    lang = lang_of(language)
    names = [FIELD_NOUN[f][lang] for f in fields if f in FIELD_NOUN]
    if not names:
        return {"en": "the order details", "hi": "ऑर्डर का विवरण", "hinglish": "order ki details"}[lang]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + _CONJ[lang] + names[-1]
