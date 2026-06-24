# Groq (cloud LLM)

Hosted API, first link in FRIDAY's cloud fallback chain (`local → Groq → Gemini →
OpenAI`). No weights — only an API config. The API key is read from `GROQ_API_KEY`
in the gitignored `.env`; **never** store it here. **Milestone:** 3.0.
