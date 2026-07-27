from langchain.chat_models import init_chat_model
from dotenv import load_dotenv

load_dotenv()

# Flat, low-nesting extraction (JD analysis) — cheap tier is reliable here.
openai_nano = init_chat_model(
    model="gpt-5-nano"
)

# Deeply-nested structured output (CV analysis) and multi-step reasoning
# (resume tailoring) — nano was unreliable on these (missing required
# fields, wrong nested types); use the stronger tier.
openai_mini = init_chat_model(
    model="gpt-5-mini"
)

