"""
Webhook server: receives incoming SMS from Twilio and replies.

This version implements the real consent gate (spec-required, not
placeholder): JOIN -> disclosure -> YES, before anything else happens.
Nothing past that gate is wired to the real engine yet — once someone
has consented, we hand off to a stub that will become real onboarding
and event logic later.

Deploy target: Render (or similar always-on host). Do NOT run this
in the sandboxed workspace — it needs a real public URL for Twilio
to reach.
"""

import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# Very simple in-memory log and state for now — swap for real storage later.
# State is per-phone-number and resets if the server restarts (Render free
# tier can spin down). Fine for a proof-of-flow test; not fine for real use.
INCOMING_LOG = []

# from_number -> one of: "new", "awaiting_consent", "consented"
CONSENT_STATE = {}

CONSENT_DISCLOSURE = (
    "By replying YES, you consent to receive text messages from Circle "
    "Planner about event planning, availability, and reminders. This is "
    "a private, invite-only group — not a marketing list. Consent is not "
    "a condition of participation. Msg & data rates may apply. Message "
    "frequency varies. Reply STOP at any time to opt out."
)

ENROLLMENT_CONFIRMATION = (
    "You're in! You'll get texts from Circle Planner about event planning, "
    "availability, and reminders. This is a private group, not marketing. "
    "Msg & data rates may apply, frequency varies. Reply STOP to opt out "
    "anytime."
)

OPT_OUT_CONFIRMATION = (
    "You've been unsubscribed from Circle Planner and won't receive any "
    "more texts. Reply JOIN anytime if you'd like to rejoin the group."
)

HELP_MESSAGE = (
    "Circle Planner helps a small group of friends plan real-world "
    "get-togethers. Reply STOP to opt out. Questions? Just ask here."
)


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
    """
    The real consent gate. This is the part that was previously a
    placeholder echo — it now actually enforces JOIN -> disclosure -> YES
    before anything else happens, per the Terms/Privacy pages and
    onboarding_script.md.
    """
    normalized = body.strip().upper()
    state = CONSENT_STATE.get(from_number, "new")

    # STOP and HELP are honored at any point, regardless of state.
    if normalized in ("STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"):
        CONSENT_STATE[from_number] = "new"
        return OPT_OUT_CONFIRMATION

    if normalized in ("HELP", "INFO", "SUPPORT"):
        return HELP_MESSAGE

    if state == "new":
        if normalized == "JOIN":
            CONSENT_STATE[from_number] = "awaiting_consent"
            return CONSENT_DISCLOSURE
        # Anything else from an unknown number is not onboarded yet —
        # don't start collecting data, just point them at the real entry.
        return "Hi! To join Circle Planner, text JOIN to get started."

    if state == "awaiting_consent":
        if normalized == "YES":
            CONSENT_STATE[from_number] = "consented"
            return ENROLLMENT_CONFIRMATION
        # Per onboarding_script.md: a hedge, a question, or silence does
        # not count as YES. Re-send the disclosure once rather than guess.
        return CONSENT_DISCLOSURE

    if state == "consented":
        # --- Real onboarding/event logic plugs in here next. ---
        # This is the boundary: everything before this point is the
        # consent gate (done, for real). Everything after it is
        # onboarding_script.md's six questions and, eventually, the
        # engine (evaluate_event_possibility, receive_confirmation,
        # handle_fast_event) — not yet wired in.
        return (
            f"Got it: \"{body}\". (Consent is confirmed — real onboarding "
            f"questions aren't wired in yet.)"
        )

    return "Something went wrong — text JOIN to start over."


@app.route("/", methods=["GET"])
def health_check():
    return "Server is up. Waiting for texts."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
