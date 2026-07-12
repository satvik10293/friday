"""WhatsApp notifications via pywhatkit (opens WhatsApp Web).

The recipient comes from the DAD_PHONE variable in a local .env — with no
number configured, send_message raises a clear error instead of letting
pywhatkit fail cryptically (or worse, message the wrong chat).
"""

import os


def send_message(message):
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # fine if DAD_PHONE is already in the environment
    phone_number = os.getenv("DAD_PHONE")
    if not phone_number:
        raise RuntimeError(
            "DAD_PHONE is not set — add it to trading_ai/.env "
            "(e.g. DAD_PHONE=+91XXXXXXXXXX) to enable WhatsApp alerts."
        )

    import pywhatkit

    pywhatkit.sendwhatmsg_instantly(
        phone_number,
        message,
        wait_time=15,
        tab_close=True,
        close_time=5,
    )
    print(f"Message sent to {phone_number}")
