"""
Minimal webhook server: receives incoming SMS from Twilio, logs it,
and sends a reply. This is the real receiving half of the loop —
where a friend's text actually lands.

Deploy target: Render (or similar always-on host). Do NOT run this
in the sandboxed workspace — it needs a real public URL for Twilio
to reach.
"""

import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

# Very simple in-memory log for now — swap for the real database later.
INCOMING_LOG = []


@app.route("/sms", methods=["POST"])
def incoming_sms():
    from_number = request.form.get("From")
    body = request.form.get("Body", "").strip()

    INCOMING_LOG.append({"from": from_number, "body": body})
    print(f"[INCOMING] {from_number}: {body}")

    # --- This is where real engine logic plugs in later ---
    # For now: a placeholder reply so the round trip is provable end to end.
    reply_text = _placeholder_reply(body)

    resp = MessagingResponse()
    resp.message(reply_text)
    return str(resp)


def _placeholder_reply(body: str) -> str:
    """
    Stand-in for real reasoning. Once this works end to end, this
    function gets replaced by an actual call into the engine
    (evaluate_event_possibility, receive_confirmation, etc.)
    """
    if not body:
        return "Got an empty message — try again?"
    return f"Got it: \"{body}\". (This is a test reply — real logic isn't wired in yet.)"


@app.route("/", methods=["GET"])
def health_check():
    return "Server is up. Waiting for texts."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
