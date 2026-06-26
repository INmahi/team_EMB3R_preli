"""Multilingual keyword maps for case classification (en / bn / banglish).

The judge harness includes English, Bangla, and mixed "Banglish" complaints, so
each case type carries cues in all three. These are intentionally lowercase and
matched against a normalized complaint string. Bangla script terms are matched
as substrings; Banglish/English terms as word-ish substrings.

Keep this list conservative and high-precision: a false phishing classification
is worse than a missed keyword, because routing and safety hinge on it.
"""
from __future__ import annotations

# Per-case_type cue lists. Order does not imply priority; priority is handled in
# reasoning.py (phishing/fraud is checked first).
CASE_KEYWORDS: dict[str, list[str]] = {
    "phishing_or_social_engineering": [
        # English
        "otp", "one time password", "pin", "password", "cvv", "card number",
        "scam", "fraud", "phishing", "suspicious call", "suspicious sms",
        "suspicious message", "fake call", "fake sms", "lottery", "won a prize",
        "you have won", "prize money", "reward", "verify your account",
        "click the link", "click this link", "share your", "asked for my",
        "asked me to", "impersonat", "pretending", "bkash officer", "nagad officer",
        "gift", "bonus offer", "account will be blocked", "account suspended",
        # Banglish
        "প্রতারণা", "প্রতারক", "ভুয়া", "vua", "vuya", "bhua", "fake",
        "otp chaiche", "pin chaiche", "password chaiche", "code chaiche",
        "puroshkar", "lottery jiteche", "lottery peyechi", "uposhar",
        "sandehojonok", "fishing", "fishing call", "link e click",
        "code dite bolse", "code dite bolche", "tothho chaiche",
        "প্রতারণার", "ফাঁদ", "জালিয়াতি", "প্রলোভন",
    ],
    "wrong_transfer": [
        "wrong number", "wrong recipient", "wrong person", "wrong account",
        "sent to wrong", "mistakenly sent", "sent by mistake", "wrong send",
        "vul number", "bhul number", "vul number e", "bhul number e",
        "vul manush", "bhul manushe", "vul jaygay", "wrong e chole gese",
        "ভুল নম্বর", "ভুল মানুষ", "ভুল জায়গায়", "ভুল করে",
        "onno number", "onno manush", "onner kache chole gese",
    ],
    "duplicate_payment": [
        "duplicate", "double charge", "charged twice", "charged two times",
        "paid twice", "deducted twice", "two times", "double payment",
        "double kete", "dui bar", "duibar", "duto", "dui bar kete",
        "duibar kete niyeche", "double cut", "dubar", "ekta payment dui bar",
        "দুইবার", "দুবার", "দুই বার", "ডাবল", "দুইবার কেটে",
    ],
    "payment_failed": [
        "payment failed", "transaction failed", "failed transaction",
        "payment did not", "payment didnt", "did not go through",
        "didnt go through", "money deducted but", "balance deducted but",
        "deducted but failed", "taka kete niyeche kintu", "taka kete nise",
        "payment hoyni", "transaction hoyni", "lenden hoyni", "failed hoyse",
        "taka kete fail", "kete niyeche kintu hoyni", "payment hocche na",
        "ব্যর্থ", "টাকা কেটে নিয়েছে কিন্তু", "পেমেন্ট হয়নি", "লেনদেন ব্যর্থ",
    ],
    "refund_request": [
        "refund", "money back", "return my money", "want my money back",
        "give me refund", "refund chai", "taka ferot", "taka ferot chai",
        "ferot chai", "ferot din", "fete chai", "money return",
        "refund korben", "refund din", "taka ফেরত", "ফেরত", "টাকা ফেরত",
        "ফেরত চাই", "রিফান্ড",
    ],
    "merchant_settlement_delay": [
        "settlement", "settlement delay", "settlement not received",
        "settlement pending", "merchant payment not received", "payout not",
        "payout delay", "shop payment", "dokaner taka", "merchant er taka",
        "settlement asheni", "settlement pai nai", "dokane taka ashe nai",
        "settlement hoyni", "merchant settlement", "store payment pending",
        "সেটেলমেন্ট", "দোকানের টাকা", "মার্চেন্ট",
    ],
    "agent_cash_in_issue": [
        "cash in", "cash-in", "cashin", "agent", "deposit through agent",
        "agent deposit", "agent er kache", "agent ke diyechi", "agent diye",
        "cash in korechi kintu", "balance ashe nai", "balance pai nai",
        "deposit kintu", "taka jma dei", "cash in hoyni", "agent point",
        "ক্যাশ ইন", "এজেন্ট", "জমা দিয়েছি", "ব্যালেন্স আসেনি",
    ],
}

# Words/units that often precede or follow a money amount in a complaint.
AMOUNT_HINTS: list[str] = [
    "taka", "tk", "bdt", "৳", "টাকা", "tk.", "amount", "poisa",
]

# Status words a complaint might use, mapped to canonical transaction statuses.
STATUS_WORDS: dict[str, list[str]] = {
    "failed": ["failed", "fail", "hoyni", "hoy nai", "did not", "didnt",
               "unsuccessful", "ব্যর্থ", "হয়নি"],
    "pending": ["pending", "processing", "atke", "atkay", "hocche na",
                "wait", "অপেক্ষমাণ", "প্রসেসিং"],
    "reversed": ["reversed", "ferot eseche", "back peyechi", "returned",
                 "ফেরত এসেছে"],
    "completed": ["completed", "successful", "hoyeche", "hoye gese", "done",
                  "সম্পন্ন", "হয়েছে"],
}
