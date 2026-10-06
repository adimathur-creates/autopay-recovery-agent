"""
Turns rupee amounts into spoken words, in English and Hindi.

Why this exists: in testing, the AI said "1,499 rupees" in Hindi when the real amount was 2,499.
Language models are unreliable at converting numbers into words, and a wrong amount on a payment
call is unacceptable. So the server converts the number once, deterministically, and the agent
only reads the words out.
"""

ONES_EN = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
           "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
           "eighteen", "nineteen"]
TENS_EN = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

# Hindi numbers 0-99 are irregular, so they need a full table.
HI_0_99 = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह "
           "उन्नीस बीस इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस "
           "तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस "
           "पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास इक्यावन बावन तिरेपन चौवन पचपन छप्पन सत्तावन "
           "अट्ठावन उनसठ साठ इकसठ बासठ तिरेसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर "
           "बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी बयासी तिरासी "
           "चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पंचानवे "
           "छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()
assert len(HI_0_99) == 100


def _en_below_100(n):
    if n < 20:
        return ONES_EN[n]
    return TENS_EN[n // 10] + ("-" + ONES_EN[n % 10] if n % 10 else "")


def to_words_en(n):
    """Indian-English words for 1 to 99,99,999 (e.g. 2499 -> two thousand four hundred ninety-nine)."""
    if n <= 0 or n > 9_999_999:
        raise ValueError(f"amount out of range: {n}")
    parts = []
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    hundred, rest = divmod(n, 100)
    if lakh:
        parts.append(_en_below_100(lakh) + " lakh")
    if thousand:
        parts.append(_en_below_100(thousand) + " thousand")
    if hundred:
        parts.append(ONES_EN[hundred] + " hundred")
    if rest:
        parts.append(_en_below_100(rest))
    return " ".join(parts) + " rupees"


def to_words_hi(n):
    """Hindi words in Devanagari (e.g. 2499 -> दो हज़ार चार सौ निन्यानवे रुपये)."""
    if n <= 0 or n > 9_999_999:
        raise ValueError(f"amount out of range: {n}")
    parts = []
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    hundred, rest = divmod(n, 100)
    if lakh:
        parts.append(HI_0_99[lakh] + " लाख")
    if thousand:
        parts.append(HI_0_99[thousand] + " हज़ार")
    if hundred:
        parts.append(HI_0_99[hundred] + " सौ")
    if rest:
        parts.append(HI_0_99[rest])
    return " ".join(parts) + " रुपये"


if __name__ == "__main__":
    for amt in (499, 799, 999, 1499, 2499, 2999, 100000, 125050):
        print(amt, "|", to_words_en(amt), "|", to_words_hi(amt))
