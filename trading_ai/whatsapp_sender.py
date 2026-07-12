import os
from dotenv import load_dotenv
import pywhatkit

load_dotenv()

PHONE_NUMBER = os.getenv("DAD_PHONE")

def send_message(message):

    pywhatkit.sendwhatmsg_instantly(
        PHONE_NUMBER,
        message,
        wait_time=15,
        tab_close=True,
        close_time=5
    )

    print(
        f"Message sent to {PHONE_NUMBER}"
    )