"""
Builds the English and Hindi prompts from one template (prompts/system_prompt.md).

Each language gets ONLY its own phrasing. In testing, a single prompt holding both
languages made the agent read out both versions of the same line.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "prompts" / "system_prompt.md").read_text()

LANG = {
    "en": {
        "header": "# Language\nSpeak English (Indian English).\n\n",
        "<<AMOUNT>>": "{{amount_words_en}}",
        "<<ASK_YEAR>>": "For security, could you please tell me your year of birth?",
        "<<YEAR_EXAMPLE>>": '"nineteen ninety one"',
        "<<CLOSING>>": "Thank you for your time, have a good day. Goodbye!",
        "<<BYE>>": "Bye!",
    },
    "hi": {
        "header": ("# Language\nSpeak natural conversational Hindi (Hinglish is fine), written in Devanagari "
                   "script. Keep brand names, 'UPI', 'SMS', 'link' and 'Razorpay' in English. Translate the "
                   "fixed lines below naturally into Hindi.\n\n"),
        "<<AMOUNT>>": "{{amount_words_hi}}",
        "<<ASK_YEAR>>": "सुरक्षा के लिए, क्या आप अपना जन्म वर्ष बता सकते हैं?",
        "<<YEAR_EXAMPLE>>": '"उन्नीस सौ इक्यानवे" or "nineteen ninety one"',
        "<<CLOSING>>": "आपका समय देने के लिए धन्यवाद, आपका दिन शुभ हो। नमस्ते!",
        "<<BYE>>": "नमस्ते!",
    },
}


def build(lang):
    cfg = LANG[lang]
    text = cfg["header"] + TEMPLATE
    for key, value in cfg.items():
        if key.startswith("<<"):
            text = text.replace(key, value)
    assert "<<" not in text, f"unfilled placeholder in {lang} prompt"
    return text


if __name__ == "__main__":
    for lang in LANG:
        out = ROOT / "prompts" / f"system_prompt_{lang}.md"
        out.write_text(build(lang))
        print("wrote", out.relative_to(ROOT))
