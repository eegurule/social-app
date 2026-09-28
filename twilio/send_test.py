"""
First real send test — one message, to the founder's own phone.
Credentials are read from .env, never hardcoded here.
"""

import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

sid = os.environ["TWILIO_ACCOUNT_SID"]
token = os.environ["TWILIO_AUTH_TOKEN"]
messaging_service_sid = os.environ["TWILIO_MESSAGING_SERVICE_SID"]

client = Client(sid, token)

TO_NUMBER = "+17075489502"

message = client.messages.create(
    to=TO_NUMBER,
    messaging_service_sid=messaging_service_sid,
    body="This is your social-coordination app's first real message. If you're reading this, sending works.",
)

print(f"Sent. Message SID: {message.sid}, status: {message.status}")
