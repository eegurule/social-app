"""
Webhook + join form for Circle Planner.

The public /join page is an invitation-request form. Texting is OPTIONAL:
the phone number and the SMS consent checkbox are unticked by default and
not required. Only if the box is ticked do we text the number, with ONE
message containing the full disclosure; the person is enrolled in texts only
after replying YES (double opt-in). STOP and HELP work at any point.

Nothing past the consent gate is wired to the real engine yet -- once
someone has consented, replies go to a stub that will become onboarding
and event logic later.

Deploy target: Render. Needs a real public URL for Twilio to reach.

Optional environment variables (set in the Render dashboard):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_MESSAGING_SERVICE_SID
      -> required for the join form to actually send its confirmation text
  SUPPORT_EMAIL   -> shown on the Privacy and Terms pages if set
  PUBLIC_BASE_URL -> defaults to the Render URL below
"""

import json
import os
import re
import time
from datetime import datetime, timezone

from flask import Flask, render_template, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://social-app-dzp6.onrender.com").rstrip("/")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "").strip()

# In-memory state for now. Resets when the server restarts (Render free tier
# spins down when idle). Fine for proving the flow; not fine for real use.
INCOMING_LOG = []
CONSENT_STATE = {}   # from_number -> "new" | "awaiting_consent" | "consented"
OPT_INS = []         # form submissions (also printed to the Render log)
LAST_FORM_TEXT = {}  # number -> epoch seconds of last confirmation text
IP_HITS = {}         # ip -> list of epoch seconds

NUMBER_COOLDOWN_SECONDS = 60 * 60
IP_LIMIT = 5
IP_WINDOW_SECONDS = 60 * 60

CONSENT_DISCLOSURE = (
    "By replying YES, you consent to receive text messages from Circle "
    "Planner about event planning, availability, and reminders. This is "
    "a private, invite-only group — not a marketing list. Consent is not "
    "a condition of participation. Up to 30 msgs/month. Msg & data rates "
    "may apply. Reply HELP for help or STOP at any time to opt out."
)

ENROLLMENT_CONFIRMATION = (
    "You're in! You'll get texts from Circle Planner about event planning, "
    "availability, and reminders. This is a private group, not marketing. "
    "Up to 30 msgs/month. Msg & data rates may apply. Reply HELP for help, "
    "STOP to opt out anytime."
)

OPT_OUT_CONFIRMATION = (
    "You've been unsubscribed from Circle Planner and won't receive any "
    "more texts. Reply JOIN anytime if you'd like to rejoin the group."
)

HELP_MESSAGE = (
    "Circle Planner helps a small group of friends plan real-world "
    "get-togethers. Reply STOP to opt out. Questions? Just ask here."
)


# ----------------------------------------------------------------- pages

@app.route("/", methods=["GET"])
def health_check():
    return "Server is up. Waiting for texts."


@app.route("/privacy", methods=["GET"])
def privacy():
    return render_template("privacy.html", support_email=SUPPORT_EMAIL)


@app.route("/terms", methods=["GET"])
def terms():
    return render_template("terms.html", support_email=SUPPORT_EMAIL)


@app.route("/join", methods=["GET", "POST"])
def join():
    """
    Invitation-request form. Name, inviting member and email are required;
    the phone number and the SMS consent checkbox are OPTIONAL and unchecked
    by default. Texts are sent only if the person ticks the box, and even
    then enrollment needs a YES reply (double opt-in).
    """
    if request.method == "GET":
        return render_template("join.html")

    name = request.form.get("name", "").strip()
    invited_by = request.form.get("invited_by", "").strip()
    email = request.form.get("email", "").strip()
    raw_phone = request.form.get("phone", "")
    wants_texts = request.form.get("consent") == "yes"

    def again(error):
        return render_template(
            "join.html", error=error, name=name, invited_by=invited_by,
            email=email, phone=raw_phone, wants_texts=wants_texts,
        ), 400

    if not name or len(name) > 120:
        return again("Please enter your name.")
    if not invited_by or len(invited_by) > 120:
        return again("Please tell us which member invited you.")
    if not EMAIL_RE.match(email) or len(email) > 254:
        return again("Please enter a valid email address.")

    number = None
    if wants_texts:
        number = _normalize_us_number(raw_phone)
        if not number:
            return again("To get texts, please enter a valid US mobile number. "
                         "Or untick the box to request an invitation without texts.")

    ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
          or request.remote_addr or "unknown")
    if _ip_limited(ip):
        return again("Too many requests from this connection. Please try again later.")

    record = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": name,
        "invited_by": invited_by,
        "email": email,
        "texts_requested": wants_texts,
    }

    if not wants_texts:
        # No phone number is read, stored, or texted when the box is unticked.
        record["action"] = "invitation_request_no_texts"
        _log_opt_in(record)
        return render_template("thanks.html", mode="no_texts")

    record["number"] = number
    masked = "\u2022\u2022\u2022 \u2022\u2022\u2022 " + number[-4:]
    now = time.time()
    already = CONSENT_STATE.get(number) in ("awaiting_consent", "consented")
    recent = now - LAST_FORM_TEXT.get(number, 0) < NUMBER_COOLDOWN_SECONDS

    if already or recent:
        # Don't re-text (prevents using the form to spam one number) and
        # don't reveal whether this number is already in the system.
        record["action"] = "skipped_duplicate_or_cooldown"
        _log_opt_in(record)
        return render_template("thanks.html", mode="texted", masked=masked)

    sent, err = _send_sms(number, CONSENT_DISCLOSURE)
    record["action"] = "disclosure_text_sent" if sent else f"send_failed: {err}"
    _log_opt_in(record)

    if sent:
        CONSENT_STATE[number] = "awaiting_consent"
        LAST_FORM_TEXT[number] = now
        return render_template("thanks.html", mode="texted", masked=masked)
    return render_template("thanks.html", mode="text_failed", masked=masked)


# -------------------------------------------------------------- webhook

@app.route("/sms", methods=["POST"])
def incoming_sms():
    from_number = request.form.get("From")
    body = request.form.get("Body", "").strip()

    INCOMING_LOG.append({"from": from_number, "body": body})
    print(f"[INCOMING] {from_number}: {body}")

    reply_text = _route_message(from_number, body)

    resp = MessagingResponse()
    resp.message(reply_text)
    return str(resp)


def _route_message(from_number: str, body: str) -> str:
    normalized = body.strip().upper()
    state = CONSENT_STATE.get(from_number, "new")

    # STOP and HELP are honored at any point, regardless of state.
    if normalized in ("STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"):
        CONSENT_STATE[from_number] = "new"
        return OPT_OUT_CONFIRMATION

    if normalized in ("HELP", "INFO", "SUPPORT"):
        return HELP_MESSAGE

    if state == "new":
        # Texting in is not consent. The only way in is the join form.
        return f"To join Circle Planner, sign up here: {PUBLIC_BASE_URL}/join"

    if state == "awaiting_consent":
        if normalized == "YES":
            CONSENT_STATE[from_number] = "consented"
            return ENROLLMENT_CONFIRMATION
        # A hedge, a question, or silence does not count as YES.
        return CONSENT_DISCLOSURE

    if state == "consented":
        # Real onboarding/event logic plugs in here next.
        return (
            f"Got it: \"{body}\". (Consent is confirmed — real onboarding "
            f"questions aren't wired in yet.)"
        )

    return f"Something went wrong — sign up again at {PUBLIC_BASE_URL}/join"


# -------------------------------------------------------------- helpers

def _normalize_us_number(raw: str):
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] in "01" or digits[3] in "01":
        return None
    return "+1" + digits


def _ip_limited(ip: str) -> bool:
    now = time.time()
    hits = [t for t in IP_HITS.get(ip, []) if now - t < IP_WINDOW_SECONDS]
    hits.append(now)
    IP_HITS[ip] = hits
    return len(hits) > IP_LIMIT


def _log_opt_in(record: dict):
    OPT_INS.append(record)
    print("[OPT_IN] " + json.dumps(record))


def _send_sms(to: str, body: str):
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    service = os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
    if not (sid and token and service):
        return False, "twilio credentials not configured on this server"
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(to=to, messaging_service_sid=service, body=body)
        return True, None
    except Exception as exc:  # report, never crash the form
        return False, str(exc)[:200]


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
