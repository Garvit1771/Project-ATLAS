"""
ATLAS — IBM Granite AI client.

Wraps the ibm-watsonx-ai SDK (ModelInference) to provide a clean interface for
the three AI reasoning call types: anomaly explanation, decision narrative, and
copilot Q&A.

Design rules (docs/methodology.md Section 7 / docs/architecture.md Section 3.2):
- Granite explains deterministic results only — never calculates, ranks, or decides.
- Temperature <= 0.3 for all calls.
- Token limits: 300 anomaly, 400 decision, 250 copilot.
- Fallback: returns an explicit "AI explanation unavailable" message on any error.
- Constructor injection: credentials/model_id can be injected for testing (no
  env-var read in __init__ so tests can pass None/mock without environment setup).
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Token-limit constants (methodology.md Section 7) ─────────────────────────
MAX_TOKENS_ANOMALY   = 300
MAX_TOKENS_DECISION  = 400
MAX_TOKENS_COPILOT   = 250

# ── Temperature ceiling ───────────────────────────────────────────────────────
TEMPERATURE = 0.2   # <= 0.3 per methodology

# ── Fallback sentinel text ────────────────────────────────────────────────────
_UNAVAILABLE = "AI explanation unavailable. Please review the computed evidence above."

# ── Default model ─────────────────────────────────────────────────────────────
DEFAULT_MODEL_ID = "ibm/granite-3-8b-instruct"


class GraniteClient:
    """
    Thin wrapper around ibm-watsonx-ai ModelInference.

    Usage
    -----
    Production (reads credentials from environment):
        client = GraniteClient()

    Tests (inject a mock ModelInference):
        client = GraniteClient(model=mock_model)

    If no credentials are present and no model is injected the client will
    return the fallback string on every call instead of raising.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
        url: Optional[str] = None,
        model_id: Optional[str] = None,
        model: object = None,          # injectable mock for tests
        timeout: int = 30,
    ) -> None:
        self.model_id    = model_id or os.environ.get("WATSONX_MODEL_ID", DEFAULT_MODEL_ID)
        self.temperature = TEMPERATURE
        self.timeout     = timeout

        self.max_tokens_anomaly  = MAX_TOKENS_ANOMALY
        self.max_tokens_decision = MAX_TOKENS_DECISION
        self.max_tokens_copilot  = MAX_TOKENS_COPILOT

        # If a pre-built model object is injected (e.g. a MagicMock), use it directly.
        if model is not None:
            self._model = model
            return

        # Resolve credentials — explicit args take priority over env vars.
        resolved_api_key    = api_key    or os.environ.get("WATSONX_API_KEY")
        resolved_project_id = project_id or os.environ.get("WATSONX_PROJECT_ID")
        resolved_url        = url        or os.environ.get("WATSONX_URL", "https://us-south.ml.ibm.com")

        if not resolved_api_key or not resolved_project_id:
            logger.warning(
                "GraniteClient: WATSONX_API_KEY or WATSONX_PROJECT_ID not set. "
                "All calls will return the fallback message."
            )
            self._model = None
            return

        try:
            from ibm_watsonx_ai import Credentials
            from ibm_watsonx_ai.foundation_models import ModelInference

            credentials = Credentials(
                api_key=resolved_api_key,
                url=resolved_url,
            )
            self._model = ModelInference(
                model_id=self.model_id,
                credentials=credentials,
                project_id=resolved_project_id,
                params={
                    "temperature": self.temperature,
                    "max_new_tokens": self.max_tokens_anomaly,  # overridden per call
                },
            )
        except Exception as exc:  # pragma: no cover — SDK import/network error
            logger.error("GraniteClient: failed to initialise ModelInference: %s", exc)
            self._model = None

    # ── Internal generate helper ──────────────────────────────────────────────

    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Send prompt to Granite; return text or fallback string on any error."""
        if self._model is None:
            return _UNAVAILABLE
        try:
            response = self._model.generate(
                prompt=prompt,
                params={
                    "temperature": self.temperature,
                    "max_new_tokens": max_tokens,
                },
            )
            # ibm-watsonx-ai SDK response shape:
            # {"results": [{"generated_text": "..."}]}
            text = response["results"][0]["generated_text"].strip()
            return text if text else _UNAVAILABLE
        except Exception as exc:
            logger.error("GraniteClient: generate failed: %s", exc)
            return _UNAVAILABLE

    # ── Public call methods ────────────────────────────────────────────────────

    def explain_anomaly(self, prompt: str) -> str:
        """Generate an anomaly explanation (max 300 tokens)."""
        return self._generate(prompt, self.max_tokens_anomaly)

    def narrate_decision(self, prompt: str) -> str:
        """Generate a decision tradeoff narrative (max 400 tokens)."""
        return self._generate(prompt, self.max_tokens_decision)

    def answer_copilot(self, prompt: str) -> str:
        """Generate a copilot Q&A response (max 250 tokens)."""
        return self._generate(prompt, self.max_tokens_copilot)

    # ── Convenience property for tests ────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        """True when a real or injected model object is present."""
        return self._model is not None
