from voice import speak
from listener import listen
from whatsapp_sender import send_message

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

            angel.login()

            # Generate portfolio summary
            summary = angel.create_summary()

            print("\n" + summary)

            speak(summary)

            try:

                send_message(summary)

                speak(
                    "Portfolio update sent to WhatsApp."
                )

            except Exception as e:

                print(
                    f"WhatsApp Error: {e}"
                )

                speak(
                    "Failed to send WhatsApp message."
                )

            # Debug holdings
            try:

                holdings = angel.get_holdings()

                if (
                    holdings
                    and holdings.get("data")
                    and len(holdings["data"]) > 0
                ):

                    print(
                        "\nFIRST HOLDING:\n"
                    )

                    print(
                        holdings["data"][0]
                    )

            except Exception as e:

                print(
                    f"Holding Debug Error: {e}"
                )

        except Exception as e:

            print(
                f"\nPortfolio Error: {e}"
            )

            speak(
                "Portfolio retrieval failed."
            )

    elif "exit" in command:

        speak("Goodbye.")

        break
