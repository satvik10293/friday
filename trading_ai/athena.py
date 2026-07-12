"""Athena — the voice-driven portfolio assistant loop.

Say "portfolio" / "today" for a spoken + WhatsApp portfolio summary from the
Angel One account; say "exit" to quit.

Run it explicitly (`python athena.py`) — importing this module used to log
in to the broker, speak, and enter an infinite microphone loop at import.
Everything now lives behind main().
"""

from listener import listen
from voice import speak
from whatsapp_sender import send_message


def _handle_portfolio(angel) -> None:
    angel.login()
    summary = angel.create_summary()
    print("\n" + summary)
    speak(summary)

    try:
        send_message(summary)
        speak("Portfolio update sent to WhatsApp.")
    except Exception as e:
        print(f"WhatsApp Error: {e}")
        speak("Failed to send WhatsApp message.")

    # Debug: show the first raw holding
    try:
        holdings = angel.get_holdings()
        if holdings and holdings.get("data"):
            print("\nFIRST HOLDING:\n")
            print(holdings["data"][0])
    except Exception as e:
        print(f"Holding Debug Error: {e}")


def main() -> int:
    from angel_connector import AngelConnector

    angel = AngelConnector()
    speak("Athena portfolio assistant online.")

    while True:
        command = listen()
        if not command:
            continue
        command = command.lower()

        if "today" in command or "portfolio" in command:
            try:
                _handle_portfolio(angel)
            except Exception as e:
                print(f"\nPortfolio Error: {e}")
                speak("Portfolio retrieval failed.")
        elif "exit" in command:
            speak("Goodbye.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
