from groq import Groq
# NOTE: The API key string below is an inactive, revoked placeholder 
# included for demonstration purposes. To run and test the AI chatbot locally, 
# replace this string with your own active Groq API key.
API_KEY = "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"
MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are a friendly, sharp stock investment consultant. "
    "Your job is to help the user decide what to invest in. "
    "Ask about their goals, time horizon, and risk tolerance when useful. "
    "Explain your reasoning in plain language, suggest specific sectors, "
    "tickers, and strategies, and always remind them this is general "
    "information, not licensed financial advice. Keep replies focused and practical."
)


class AIChatService:
    def __init__(self, api_key=API_KEY, model=MODEL, system_prompt=SYSTEM_PROMPT):
        self.client = Groq(api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt

    def _build(self, history):
        return [{"role": "system", "content": self.system_prompt}] + list(history)

    def reply(self, history):
        """history: list of {"role": "user"|"assistant", "content": str}.
        Returns the assistant's full reply as a string."""
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=self._build(history),
        )
        return completion.choices[0].message.content

    def stream(self, history):
        """Yields the assistant's reply in chunks as they arrive."""
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=self._build(history),
            stream=True,
        )
        for chunk in completion:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


def main():
    service = AIChatService()
    history = []

    print("Stock Consultant AI. Type your question. ('quit' or 'exit' to leave.)\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye. Invest wisely.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit"):
            print("Goodbye. Invest wisely.")
            break

        history.append({"role": "user", "content": user_input})

        print("Consultant: ", end="", flush=True)
        reply = ""
        for delta in service.stream(history):
            print(delta, end="", flush=True)
            reply += delta
        print("\n")

        history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
