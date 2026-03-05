# app.py
# DPIS IVR — localized prompts + MP3 playback (env override -> hardcoded defaults -> final fallback)
import os
import csv
import logging
from datetime import datetime
from functools import wraps
from flask import Flask, request, Response, url_for, redirect
from twilio.twiml.voice_response import VoiceResponse, Gather

app = Flask(__name__)

# --- Logging setup ---
LOG_FILE = os.environ.get("APP_LOG_FILE", "app.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# Config via env vars
COUNSELOR_NUMBER = os.environ.get("COUNSELOR_NUMBER")
TWILIO_PUBLIC_NUMBER = os.environ.get("TWILIO_PUBLIC_NUMBER", None)
CALL_LOG_FILE = os.environ.get("CALL_LOG_FILE", "call_logs.csv")

# Final fallback MP3 (used only if everything else missing)
DEFAULT_GUIDED_MP3 = "https://www.cci.health.wa.gov.au/~/media/CCI/Audio-files/Mindfulnessofthebreath.mp3"

# -------------------------
# Hardcoded per-language / per-activity defaults
# You can change these values directly here later, or override via env vars.
# -------------------------
# English
EN_BREATHING_URL     = "https://voluble-pasca-d2b5e0.netlify.app/breathing_english.mp3"
EN_GROUNDING_URL     = "https://voluble-pasca-d2b5e0.netlify.app/grounding_english.mp3"
EN_AFFIRMATIONS_URL  = "https://voluble-pasca-d2b5e0.netlify.app/affirmations_english.mp3"

# Hindi
HI_BREATHING_URL     = "https://voluble-pasca-d2b5e0.netlify.app/breathing_hindi.mp3"
HI_GROUNDING_URL     = "https://voluble-pasca-d2b5e0.netlify.app/breathing_hindi.mp3"
HI_AFFIRMATIONS_URL  = "https://voluble-pasca-d2b5e0.netlify.app/affirmations_hindi.mp3"

# Marathi
MR_BREATHING_URL     = "https://voluble-pasca-d2b5e0.netlify.app/breathing_marathi.mp3"
MR_GROUNDING_URL     = "https://voluble-pasca-d2b5e0.netlify.app/breathing_marathi.mp3"
MR_AFFIRMATIONS_URL  = "https://voluble-pasca-d2b5e0.netlify.app/affirmations_marathi.mp3"

# PREMIUM vs FALLBACK voices: premium enabled only via ENABLE_PREMIUM_VOICES=1
PREMIUM_VOICE_MAP = {
    "en": "Google.en-US-Chirp3-HD-Aoede",
    "hi": "Google.hi-IN-Chirp3-HD-Despina",
    "mr": "Google.mr-IN-Chirp3-HD-Despina",
}

FALLBACK_VOICE_MAP = {
    "en": "alice",
    "hi": "Polly.Aditi",
    "mr": "Google.mr-IN-Standard-A",
}

def get_voice_for(lang_code: str) -> str:
    if not lang_code:
        key = "en"
    else:
        key = lang_code.lower().split("-")[0]

    use_premium = os.environ.get("ENABLE_PREMIUM_VOICES", "0") == "1"
    if use_premium:
        return PREMIUM_VOICE_MAP.get(key, FALLBACK_VOICE_MAP.get(key, FALLBACK_VOICE_MAP["en"]))
    else:
        return FALLBACK_VOICE_MAP.get(key, FALLBACK_VOICE_MAP["en"])

# ---------- Helpers ----------
def log_choice(call_sid: str, choice: str):
    row = {
        "call_sid": call_sid or "",
        "choice": choice,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    write_header = not os.path.exists(CALL_LOG_FILE)
    with open(CALL_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["call_sid", "choice", "timestamp"])
        if write_header:
            writer.writeheader()
        writer.writerow(row)

def text_for(lang: str, key: str) -> str:
    prompts = {
        "en": {
            "welcome_anonymous": "Welcome to the Student Wellness Line. This call is anonymous and confidential. Please choose an option to continue.",
            "main_menu": "Press 1 for a quick breathing exercise. Press 2 for a grounding technique. Press 3 for positive affirmations. Press 4 to connect with a counselor or helpline. Press 9 to repeat this menu.",
            "no_input": "Sorry, we didn't receive a response. Let's try again.",
            "invalid": "That option is not valid. Please press 9 to hear the menu again.",
            "breathing_start": "Let's begin. Breathe in... two... three... four. Hold... two... three... four. Breathe out... two... three... four. Let's repeat together.",
            "breathing_end": "Well done. Press 1 to repeat, or 9 to return to the main menu.",
            "grounding_start": "This is a grounding exercise. Think of five things you can see. Now four things you can touch. Now three things you can hear. Now two things you can smell. And finally one thing you can taste.",
            "grounding_end": "Great work. Press 1 to repeat, or 9 for the main menu.",
            "affirmations_start": "Repeat after me: I am calm. I am safe. I can handle challenges. I am not alone.",
            "affirmations_end": "Remember, you are stronger than your stress. Press 9 to return to the menu.",
            "connecting": "You have chosen to connect to a counselor. Please hold while we transfer your call.",
            "counselor_busy": "Sorry, the counselor is not available right now. You will be connected to the national helpline."
        },
        "hi": {
            "welcome_anonymous": "छात्र वेलनेस लाइन में आपका स्वागत है। यह कॉल गुप्त रखा जाएगा। जारी रखने के लिए विकल्प चुनें।",
            "main_menu": "श्वास अभ्यास के लिए १ दबाएं। ग्राउंडिंग तकनीक के लिए २ दबाएं। सकारात्मक विचारों के लिये के लिए ३ दबाएं। काउंसलर से जुड़ने के लिए ४ दबाएं। मेन मेनू दोहराने के लिए ९ दबाएं।",
            "no_input": "क्षमा करें, हमें कोई उत्तर नहीं मिला। फिर से प्रयास करते हैं।",
            "invalid": "यह विकल्प मान्य नहीं है। मेनू सुनने के लिए 9 दबाएं।",
            "breathing_start": "शुरू करते हैं। सांस अंदर लें... एक... दो... तीन... चार। रोकें... एक... दो... तीन... चार। सांस बाहर छोड़ें... एक... दो... तीन... चार। फिर से साथ में दोहराएं।",
            "breathing_end": "शाबाश। दोहराने के लिए 1 दबाएं, या मेन मेन्यू के लिए 9 दबाएं।",
            "grounding_start": "यह एक ग्राउंडिंग अभ्यास है। अपने आसपास पाँच चीजें सोचें जो आप देख सकते हैं... चार चीजें जिन्हें आप छू सकते हैं... तीन चीजें जिन्हें आप सुन सकते हैं... दो चीजें जिन्हें आप सूंघ सकते हैं... एक चीज़ जिसे आप चख सकते हैं।",
            "grounding_end": "अच्छा काम। दोहराने के लिए 1 दबाएं, या मेन मेन्यू के लिए 9 दबाएं।",
            "affirmations_start": "मेरे साथ दोहराएं: मैं शांत हूँ। मैं सुरक्षित हूँ। मैं चुनौतियों का सामना कर सकता/सकती हूँ। मैं अकेला नहीं हूँ।",
            "affirmations_end": "याद रखें, आप अपनी चिंता से अधिक मजबूत हैं। मेन्यू पर लौटने के लिए 9 दबाएं।",
            "connecting": "आपने काउंसलर से जुड़ना चुना है। कृपया प्रतीक्षा करें, हम आपकी कॉल स्थानांतरित कर रहे हैं।",
            "counselor_busy": "क्षमा करें, काउंसलर अभी उपलब्ध नहीं है। आपको राष्ट्रीय हेल्पलाइन से जोड़ा जाएगा।"
        },
        "mr": {
            "welcome_anonymous": "विद्यार्थी वेलनेस लाईनमध्ये आपले स्वागत आहे. हा कॉल गुपित ठेवला जाईल. कृपया पुढे जाण्यासाठी एक पर्याय निवडा.",
            "main_menu": "श्वासाचा सराव साठी 1 दाबा. ग्राउंडिंग टेक्निकसाठी 2 दाबा. सकारात्मक विचारांसाठी 3 दाबा. काउन्सलरशी जोडण्यासाठी 4 दाबा. मेनू पुन्हा ऐकण्यासाठी 9 दाबा.",
            "no_input": "क्षमस्व, आम्हाला प्रतिसाद मिळाला नाही. पुन्हा प्रयत्न करूया.",
            "invalid": "हा पर्याय वैध नाही. मेनू ऐकण्यासाठी 9 दाबा.",
            "breathing_start": "सुरू करूया. श्वास आत घ्या... एक... दोन... तीन... चार. थांबा... एक... दोन... तीन... चार. श्वास बाहेर सोडा... एक... दोन... तीन... चार.",
            "breathing_end": "छान. पुन्हा करण्यासाठी 1 दाबा, किंवा मेनूवर परत जाण्यासाठी 9 दाबा.",
            "grounding_start": "हे एक ग्राउंडिंग व्यायाम आहे. आता पाच गोष्टी विचार करा ज्या तुम्हाला दिसतात... चार गोष्टी स्पर्श करता येतात... तीन गोष्टी तुम्हाला ऐकू येतात... दोन गोष्टी तुम्हाला सुंघता येतील... एक चव.",
            "grounding_end": "छान काम. पुन्हा करण्यासाठी 1 दाबा, किंवा मेनू साठी 9 दाबा.",
            "affirmations_start": "माझ्याबरोबर म्हणा: मी शांत आहे. मी सुरक्षित आहे. मी आव्हानांना सामोरे जाऊ शकतो. मी एकटा नाही.",
            "affirmations_end": "लक्षात ठेवा, तुम्ही तुमच्या ताणापेक्षा अधिक मजबूत आहात. मेनूमध्ये परत जाण्यासाठी 9 दाबा.",
            "connecting": "तुम्ही काउंसलरशी कनेक्ट होण्याचा पर्याय निवडला आहे. कृपया धैर्य ठेवा, आम्ही तुमचा कॉल ट्रान्सफर करत आहोत.",
            "counselor_busy": "क्षमस्व, काउंसलर सध्या उपलब्ध नाही. तुम्हाला राष्ट्रीय हेल्पलाइनशी कनेक्ट केले जाईल."
        }
    }
    if not lang:
        lang = "en"
    lk = lang.lower()
    if lk.startswith("hi"):
        return prompts["hi"].get(key, prompts["en"].get(key, ""))
    if lk.startswith("mr"):
        return prompts["mr"].get(key, prompts["en"].get(key, ""))
    return prompts["en"].get(key, "")

def _env_for(kind: str, lang: str) -> str:
    """
    Lookup precedence:
      1) LANG-specific environment variable, e.g. BREATHING_MP3_EN, GROUNDING_MP3_HI
      2) Global environment variable, e.g. BREATHING_MP3
      3) Hard-coded per-language default (EN_BREATHING_URL, HI_GROUNDING_URL, etc.)
      4) DEFAULT_GUIDED_MP3 final fallback
    kind should be one of: 'BREATHING', 'GROUNDING', 'AFFIRMATIONS'
    """
    if not kind:
        return None

    # normalized language key like 'EN', 'HI', 'MR'
    lang_key = (lang or "en").lower().split("-")[0]
    lang_suffix = lang_key.upper()  # 'mr' -> 'MR'

    # 1) lang-specific env var (BREATHING_MP3_EN, GROUNDING_MP3_HI, AFFIRMATIONS_MP3_MR, etc.)
    candidate_lang_env = f"{kind}_MP3_{lang_suffix}"
    lang_env_val = os.environ.get(candidate_lang_env)
    if lang_env_val:
        return lang_env_val

    # 2) global env var (BREATHING_MP3, GROUNDING_MP3, AFFIRMATIONS_MP3)
    global_env_val = os.environ.get(f"{kind}_MP3")
    if global_env_val:
        return global_env_val

    # 3) hard-coded per-language defaults
    kind_upper = kind.upper()
    if lang_key == "en":
        if kind_upper == "BREATHING":
            return EN_BREATHING_URL
        if kind_upper == "GROUNDING":
            return EN_GROUNDING_URL
        if kind_upper == "AFFIRMATIONS":
            return EN_AFFIRMATIONS_URL
    if lang_key == "hi":
        if kind_upper == "BREATHING":
            return HI_BREATHING_URL
        if kind_upper == "GROUNDING":
            return HI_GROUNDING_URL
        if kind_upper == "AFFIRMATIONS":
            return HI_AFFIRMATIONS_URL
    if lang_key == "mr":
        if kind_upper == "BREATHING":
            return MR_BREATHING_URL
        if kind_upper == "GROUNDING":
            return MR_GROUNDING_URL
        if kind_upper == "AFFIRMATIONS":
            return MR_AFFIRMATIONS_URL

    # 4) final fallback
    return DEFAULT_GUIDED_MP3

def make_twiml_response(resp: VoiceResponse) -> Response:
    """Convert VoiceResponse -> Flask Response and log request + TwiML"""
    xml = str(resp)
    try:
        logging.info("Incoming request.form: %s", dict(request.form))
    except Exception:
        logging.info("Incoming request: (could not read form)")
    logging.info("Returned TwiML: %s", xml.replace("\n", " "))
    print("---- Returned TwiML ----")
    print(xml)
    print("---- End TwiML ----")
    return Response(xml, mimetype="application/xml")

def safe_route(f):
    """Decorator to catch exceptions and return valid TwiML apology so Twilio doesn't see an app error."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logging.exception("Unhandled exception in route %s: %s", f.__name__, e)
            resp = VoiceResponse()
            resp.say("Sorry, something went wrong. Please try again later.")
            resp.hangup()
            return make_twiml_response(resp)
    return wrapper

# -------- Language selection entry (localized prompts) --------
@app.route("/ivr", methods=["GET", "POST"])
@safe_route
def ivr():
    lang = request.values.get("lang")
    if lang:
        return menu(lang=lang)

    resp = VoiceResponse()
    gather = Gather(num_digits=1, action=url_for('set_language', _external=False), method="POST", timeout=8)
    # Localized short language prompts: English / Hindi / Marathi
    gather.say("For English, press 1.", voice=get_voice_for("en"), language="en-US")
    gather.say("हिन्दी के लिए २ दबाएँ।", voice=get_voice_for("hi"), language="hi-IN")
    gather.say("मराठी साठी 3 दाबा.", voice=get_voice_for("mr"), language="mr-IN")
    resp.append(gather)
    resp.redirect(url_for('menu', lang="en"))
    return make_twiml_response(resp)

@app.route("/set_language", methods=["POST"])
@safe_route
def set_language():
    digit = request.values.get("Digits", "")
    if digit == "1":
        chosen = "en"
    elif digit == "2":
        chosen = "hi"
    elif digit == "3":
        chosen = "mr"
    else:
        chosen = "en"
    return redirect(url_for('menu', lang=chosen))

@app.route("/menu", methods=["GET", "POST"])
@safe_route
def menu(lang=None):
    lang = lang or request.values.get("lang", "en")
    resp = VoiceResponse()
    voice = get_voice_for(lang)
    locale = "en-US"
    if lang.lower().startswith("hi"):
        locale = "hi-IN"
    elif lang.lower().startswith("mr"):
        locale = "mr-IN"

    gather = Gather(num_digits=1, action=url_for('exercise', _external=False) + f"?lang={lang}", method="POST", timeout=8)
    gather.say(text_for(lang, "welcome_anonymous"), voice=voice, language=locale)
    gather.pause(length=1)
    gather.say(text_for(lang, "main_menu"), voice=voice, language=locale)
    resp.append(gather)

    resp.say(text_for(lang, "no_input"), voice=voice, language=locale)
    resp.redirect(url_for('ivr', lang=lang))
    return make_twiml_response(resp)

@app.route("/exercise", methods=["GET", "POST"])
@safe_route
def exercise():
    lang = request.values.get("lang", "en")
    digit = request.values.get("Digits")
    call_sid = request.values.get("CallSid")
    resp = VoiceResponse()

    if not digit:
        resp.say(text_for(lang, "no_input"), voice=get_voice_for(lang),
                 language=("hi-IN" if lang.lower().startswith("hi") else "mr-IN" if lang.lower().startswith("mr") else "en-US"))
        resp.redirect(url_for('menu', lang=lang))
        return make_twiml_response(resp)

    if digit == "1":
        log_choice(call_sid, "breathing")
        resp.redirect(url_for('breathing', lang=lang))
    elif digit == "2":
        log_choice(call_sid, "grounding")
        resp.redirect(url_for('grounding', lang=lang))
    elif digit == "3":
        log_choice(call_sid, "affirmations")
        resp.redirect(url_for('affirmations', lang=lang))
    elif digit == "4":
        log_choice(call_sid, "connect_counselor")
        resp.redirect(url_for('connect_counselor', lang=lang))
    elif digit == "9":
        resp.redirect(url_for('menu', lang=lang))
    else:
        resp.say(text_for(lang, "invalid"), voice=get_voice_for(lang),
                 language=("hi-IN" if lang.lower().startswith("hi") else "mr-IN" if lang.lower().startswith("mr") else "en-US"))
        resp.redirect(url_for('menu', lang=lang))

    return make_twiml_response(resp)

@app.route("/breathing", methods=["GET", "POST"])
@safe_route
def breathing():
    lang = request.values.get("lang", "en")
    resp = VoiceResponse()
    voice = get_voice_for(lang)
    locale = "en-US" if not lang.lower().startswith("hi") and not lang.lower().startswith("mr") else ("hi-IN" if lang.lower().startswith("hi") else "mr-IN")
    mp3_url = _env_for("BREATHING", lang)

    # Play MP3 (loop twice). Since we now default to DEFAULT_GUIDED_MP3, this will always play
    if mp3_url:
        resp.play(mp3_url, loop=2)
    else:
        for _ in range(2):
            resp.say(text_for(lang, "breathing_start"), voice=voice, language=locale)
            resp.pause(length=2)

    gather = Gather(num_digits=1, action=url_for('after_breathing', _external=False) + f"?lang={lang}", method="POST", timeout=8)
    gather.say(text_for(lang, "breathing_end"), voice=voice, language=locale)
    resp.append(gather)
    resp.say(text_for(lang, "no_input"), voice=voice, language=locale)
    resp.redirect(url_for('menu', lang=lang))
    return make_twiml_response(resp)

@app.route("/after_breathing", methods=["GET", "POST"])
@safe_route
def after_breathing():
    lang = request.values.get("lang", "en")
    digit = request.values.get("Digits")
    resp = VoiceResponse()
    if digit == "1":
        resp.redirect(url_for('breathing', lang=lang))
    else:
        resp.redirect(url_for('menu', lang=lang))
    return make_twiml_response(resp)

@app.route("/grounding", methods=["GET", "POST"])
@safe_route
def grounding():
    lang = request.values.get("lang", "en")
    resp = VoiceResponse()
    voice = get_voice_for(lang)
    locale = "hi-IN" if lang.lower().startswith("hi") else "mr-IN" if lang.lower().startswith("mr") else "en-US"
    mp3_url = _env_for("GROUNDING", lang)

    if mp3_url:
        resp.play(mp3_url, loop=1)
    else:
        resp.say(text_for(lang, "grounding_start"), voice=voice, language=locale)
        resp.pause(length=3)

    gather = Gather(num_digits=1, action=url_for('after_grounding', _external=False) + f"?lang={lang}", method="POST", timeout=8)
    gather.say(text_for(lang, "grounding_end"), voice=voice, language=locale)
    resp.append(gather)
    resp.say(text_for(lang, "no_input"), voice=voice, language=locale)
    resp.redirect(url_for('menu', lang=lang))
    return make_twiml_response(resp)

@app.route("/after_grounding", methods=["GET", "POST"])
@safe_route
def after_grounding():
    lang = request.values.get("lang", "en")
    digit = request.values.get("Digits")
    resp = VoiceResponse()
    if digit == "1":
        resp.redirect(url_for('grounding', lang=lang))
    else:
        resp.redirect(url_for('menu', lang=lang))
    return make_twiml_response(resp)

@app.route("/affirmations", methods=["GET", "POST"])
@safe_route
def affirmations():
    lang = request.values.get("lang", "en")
    resp = VoiceResponse()
    voice = get_voice_for(lang)
    locale = "hi-IN" if lang.lower().startswith("hi") else "mr-IN" if lang.lower().startswith("mr") else "en-US"
    mp3_url = _env_for("AFFIRMATIONS", lang)

    if mp3_url:
        resp.play(mp3_url, loop=2)
    else:
        for _ in range(2):
            resp.say(text_for(lang, "affirmations_start"), voice=voice, language=locale)
            resp.pause(length=1)
        resp.say(text_for(lang, "affirmations_end"), voice=voice, language=locale)

    resp.redirect(url_for('menu', lang=lang))
    return make_twiml_response(resp)

@app.route("/connect_counselor", methods=["GET", "POST"])
@safe_route
def connect_counselor():
    lang = request.values.get("lang", "en")
    resp = VoiceResponse()
    voice = get_voice_for(lang)
    locale = "hi-IN" if lang.lower().startswith("hi") else "mr-IN" if lang.lower().startswith("mr") else "en-US"
    resp.say(text_for(lang, "connecting"), voice=voice, language=locale)
    dial = resp.dial(callerId=TWILIO_PUBLIC_NUMBER) if TWILIO_PUBLIC_NUMBER else resp.dial()
    dial.number(COUNSELOR_NUMBER)
    resp.say(text_for(lang, "counselor_busy"), voice=voice, language=locale)
    resp.hangup()
    return make_twiml_response(resp)

# Simple helper to view TwiML in browser (simulate Twilio)
@app.route("/inspect", methods=["GET"])
def inspect():
    """
    Usage: /inspect?route=/menu&lang=hi
    Will call the internal route and return the TwiML that would be generated (helpful for debugging).
    """
    route = request.args.get("route", "/menu")
    lang = request.args.get("lang", "en")
    if route == "/menu":
        return menu(lang=lang)
    if route == "/breathing":
        return breathing()
    if route == "/grounding":
        return grounding()
    if route == "/affirmations":
        return affirmations()
    return Response("Invalid inspect route", status=400)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
