"""GhostAI - a standard-library-only command-line AI assistant.

Kilo AI Gateway documentation:
    https://kilo.ai/docs/gateway/authentication
    https://kilo.ai/docs/gateway/api-reference

Authentication notes:
    * GET /models is public and requires no authentication.
    * Anonymous chat requests are allowed for free models only.
    * Anonymous requests are rate-limited per IP (200 requests/hour).
    * API keys are optional for free models and are never required by GhostAI.

GhostAI only selects and sends requests for models the gateway exposes as free
through its pricing information. It never falls back to a paid model.
"""

import getpass
import json
import os
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation

VERSION = "0.1.0"

BASE_URL = "https://ai-gateway.kilo.ai/api/v1"
MODELS_URL = BASE_URL + "/models"
CHAT_COMPLETIONS_URL = BASE_URL + "/chat/completions"
DEFAULT_TIMEOUT = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
MODELS_CACHE_PATH = os.path.join(BASE_DIR, "models.json")


class KiloError(Exception):
    """Base class for errors raised by the Kilo AI Gateway provider."""


class NetworkError(KiloError):
    """Raised when the gateway cannot be reached."""


class APIError(KiloError):
    """Raised when the gateway returns an invalid or unsuccessful response."""


class RateLimitError(APIError):
    """Raised when the gateway rate-limits the request."""


class ModelUnavailableError(APIError):
    """Raised when a model is unavailable or not in the free model list."""


class KiloProvider:
    def __init__(self, api_key=None, timeout=DEFAULT_TIMEOUT):
        self.api_key = (api_key or os.environ.get("KILO_API_KEY") or "").strip()
        self.timeout = timeout
        self._free_models = []
        self._validated = False

    def has_api_key(self):
        return bool(self.api_key)

    def set_free_models(self, models):
        """Seed the free model list, usually from the local cache.

        The cache is not trusted for sending requests; the first chat call
        refreshes the catalog so a model that is no longer free is rejected.
        """
        self._free_models = [
            model for model in models
            if isinstance(model, dict) and isinstance(model.get("id"), str)
        ]
        self._validated = False

    def fetch_free_models(self):
        """Fetch the public model catalog and return only free chat models.

        A model is considered free only when the API exposes pricing and every
        pricing field is zero. Models with missing or non-zero pricing are
        excluded so GhostAI cannot silently use a paid model.
        """
        payload = self._request(MODELS_URL)
        if not isinstance(payload, dict):
            raise APIError("Kilo Gateway returned an unexpected models response.")

        items = payload.get("data")
        if not isinstance(items, list):
            raise APIError("Kilo Gateway models response did not contain a model list.")

        models = []
        for item in items:
            model = self._free_model(item)
            if model is not None:
                models.append(model)

        models.sort(key=lambda model: model["name"].lower())
        self._free_models = models
        self._validated = True
        return models

    def chat(self, model, messages):
        """Send an OpenAI-compatible chat completion request."""
        if not model:
            raise KiloError("No model is selected.")
        if not isinstance(messages, list) or not messages:
            raise KiloError("Conversation messages are empty.")

        if not self._validated:
            self.fetch_free_models()
        if not self._free_models:
            raise ModelUnavailableError(
                "No free models are currently available from the gateway."
            )

        free_ids = set(item["id"] for item in self._free_models)
        if model not in free_ids:
            raise ModelUnavailableError(
                "Model '{}' is not in the current free model list. "
                "Use /model to choose an available free model.".format(model)
            )

        payload = self._request(
            CHAT_COMPLETIONS_URL,
            {
                "model": model,
                "messages": messages,
                "stream": False,
            },
        )

        if not isinstance(payload, dict):
            raise APIError("Kilo Gateway returned an unexpected chat response.")

        error = payload.get("error")
        if error:
            raise APIError(
                "Kilo Gateway error: {}".format(self._format_error(error))
            )

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise APIError("Kilo Gateway returned no completion choices.")

        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None

        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            content = "".join(parts)

        if not isinstance(content, str) or not content.strip():
            refusal = message.get("refusal") if isinstance(message, dict) else None
            if isinstance(refusal, str) and refusal.strip():
                raise APIError("The model refused the request: {}".format(refusal))
            finish_reason = first.get("finish_reason") if isinstance(first, dict) else None
            raise APIError(
                "Kilo Gateway returned no assistant text{}.".format(
                    " (finish_reason: {})".format(finish_reason)
                    if finish_reason else ""
                )
            )

        return content

    def _request(self, url, payload=None):
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "GhostAI/0.1.0",
            "X-KiloCode-Version": "GhostAI/0.1.0",
        }

        if payload is not None:
            try:
                data = json.dumps(payload).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise APIError("Could not encode the request: {}".format(exc))
            headers["Content-Type"] = "application/json"

        if self.api_key:
            headers["Authorization"] = "Bearer {}".format(self.api_key)

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST" if data is not None else "GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except (OSError, ValueError):
                body = ""
            detail = self._extract_error_detail(body)
            retry_after = None
            if exc.headers is not None:
                retry_after = exc.headers.get("Retry-After")
            raise self._http_error(exc.code, detail, retry_after)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise NetworkError("Could not reach Kilo Gateway: {}".format(reason))
        except OSError as exc:
            raise NetworkError(
                "Network error while contacting Kilo Gateway: {}".format(exc)
            )

        if not raw.strip():
            raise APIError("Kilo Gateway returned an empty response.")

        try:
            return json.loads(raw)
        except ValueError:
            raise APIError("Kilo Gateway returned invalid JSON.")

    def _http_error(self, status, detail, retry_after=None):
        suffix = ": {}".format(detail) if detail else "."
        lower = detail.lower()

        if status == 401:
            return APIError(
                "The gateway requires authentication for this model. "
                "Anonymous access is available only for free models; "
                "use /model to choose one."
            )
        if status == 402:
            return APIError(
                "Insufficient balance. GhostAI does not use paid models; "
                "choose a free model with /model."
            )
        if status == 403:
            return APIError("The gateway denied access to this model{}".format(suffix))
        if status == 404 or any(phrase in lower for phrase in (
            "model not found",
            "unknown model",
            "invalid model",
            "model is not available",
            "model unavailable",
            "no available model",
            "does not exist",
        )):
            return ModelUnavailableError(
                "The selected model is unavailable{}".format(suffix)
            )
        if status == 413:
            return APIError(
                "The request exceeds the gateway's 20MB payload limit."
            )
        if status == 429:
            message = (
                "Rate limit reached. Anonymous free access is limited to "
                "200 requests/hour per IP. Try again later or configure an "
                "optional KILO_API_KEY with /key."
            )
            if retry_after:
                message += " Retry after {} seconds.".format(retry_after)
            if detail:
                message += " ({})".format(detail)
            return RateLimitError(message)
        if status in (500, 502, 503):
            return APIError(
                "Kilo Gateway or the upstream provider is temporarily "
                "unavailable (HTTP {}){}".format(status, suffix)
            )
        return APIError(
            "Kilo Gateway returned HTTP {}{}".format(status, suffix)
        )

    def _free_model(self, item):
        if not isinstance(item, dict):
            return None

        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            return None

        pricing = item.get("pricing")
        if not isinstance(pricing, dict):
            return None
        if "prompt" not in pricing or "completion" not in pricing:
            return None

        for value in pricing.values():
            if not self._is_zero_price(value):
                return None

        architecture = item.get("architecture")
        if isinstance(architecture, dict):
            outputs = architecture.get("output_modalities")
            if isinstance(outputs, list) and outputs:
                if "text" not in outputs:
                    return None
                if any(mode != "text" for mode in outputs):
                    return None
            inputs = architecture.get("input_modalities")
            if isinstance(inputs, list) and inputs and "text" not in inputs:
                return None

        context_length = item.get("context_length")
        if not isinstance(context_length, int):
            top_provider = item.get("top_provider")
            if isinstance(top_provider, dict):
                context_length = top_provider.get("context_length")

        return {
            "id": model_id,
            "name": item.get("name") or model_id,
            "context_length": context_length if isinstance(context_length, int) else None,
        }

    @staticmethod
    def _is_zero_price(value):
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return value == 0
        if isinstance(value, str):
            try:
                return Decimal(value.strip()) == 0
            except (InvalidOperation, ValueError):
                return False
        return False

    @staticmethod
    def _format_error(error):
        if isinstance(error, dict):
            message = error.get("message")
            metadata = error.get("metadata")
            if isinstance(metadata, dict) and metadata.get("raw"):
                if message:
                    return "{} ({})".format(message, metadata["raw"])
                return str(metadata["raw"])
            if message:
                return str(message)
        return str(error)

    @classmethod
    def _extract_error_detail(cls, body):
        if not body:
            return ""
        try:
            parsed = json.loads(body)
        except ValueError:
            return body.strip()[:300]

        if isinstance(parsed, dict):
            error = parsed.get("error")
            if error:
                return cls._format_error(error)
            if parsed.get("message"):
                return str(parsed["message"])
        return body.strip()[:300]


class Agent:
    def __init__(self, model=None, provider=None):
        self.model = model or ""
        self.provider = provider or KiloProvider()
        self.history = []

        self.system_prompt = (
            "You are GhostAI, a helpful AI assistant. "
            "Answer questions clearly and accurately. "
            "If you do not know something, say so."
        )

    def send_message(self, message):
        if not self.model:
            raise ValueError("No model is selected. Use /model to choose one.")

        self.history.append({
            "role": "user",
            "content": message
        })

        try:
            reply = self.provider.chat(self.model, self.get_messages())
        except Exception:
            # Keep failed turns out of history so a retry does not duplicate them.
            if self.history and self.history[-1].get("content") == message:
                self.history.pop()
            raise

        self.history.append({
            "role": "assistant",
            "content": reply
        })

        return reply

    def set_model(self, model):
        self.model = model

    def reset(self):
        self.history = []

    def get_messages(self):
        messages = [{
            "role": "system",
            "content": self.system_prompt
        }]
        messages.extend(self.history)
        return messages

    def get_history(self):
        return self.get_messages()

    def get_system_prompt(self):
        return self.system_prompt


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            config = json.load(file)
    except FileNotFoundError:
        print("No config.json found. Using defaults; run /model to choose a free model.")
        return {}
    except (OSError, ValueError) as exc:
        print("Error: Could not load config.json: {}".format(exc))
        return None

    if not isinstance(config, dict):
        print("Error: config.json must contain a JSON object.")
        return None

    return config


def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=4)
            file.write("\n")
    except OSError as exc:
        print("Error: Could not save config.json: {}".format(exc))
        return False
    return True


def load_cached_models():
    try:
        with open(MODELS_CACHE_PATH, "r", encoding="utf-8") as file:
            cached = json.load(file)
    except (OSError, ValueError):
        return []

    # Ignore legacy caches from other providers; only Kilo models are valid.
    if not isinstance(cached, dict) or cached.get("provider") != "kilo":
        return []

    models = cached.get("models")
    if not isinstance(models, list):
        return []

    valid = []
    for model in models:
        if isinstance(model, dict) and isinstance(model.get("id"), str):
            valid.append({
                "id": model["id"],
                "name": model.get("name") or model["id"],
                "context_length": model.get("context_length"),
            })
    return valid


def save_cached_models(models):
    try:
        with open(MODELS_CACHE_PATH, "w", encoding="utf-8") as file:
            json.dump({"provider": "kilo", "models": models}, file, indent=4)
            file.write("\n")
    except OSError:
        pass


def resolve_api_key(config):
    return (
        os.environ.get("KILO_API_KEY")
        or config.get("kilo_api_key")
        or ""
    ).strip()


def banner(model):
    print(r"""
          ____ _               _      _    ___
         / ___| |__   ___  ___| |_   / \  |_ _|
        | |  _| '_ \ / _ \/ __| __| / _ \  | |
        | |_| | | | | (_) \__ \ |_ / ___ \ | |
         \____|_| |_|\___/|___/\__/_/   \_\___|

        version: GhostAI v""" + VERSION + """
        source:  github.com/enesx32/ghostai-agent
        ai-mdl:  """ + (model or "not selected") + """
    """)


def choose_model(config, agent, provider):
    print("Fetching free models from Kilo AI Gateway...")
    models = []

    try:
        models = provider.fetch_free_models()
        save_cached_models(models)
    except KiloError as exc:
        print("Could not fetch models: {}".format(exc))
        models = load_cached_models()
        if models:
            print("Using cached models from models.json.")
            provider.set_free_models(models)

    if not models:
        print("No free models are available right now.")
        return None

    print()
    print("Available free models:")
    for index, model in enumerate(models, 1):
        print("  {:>3}. {}".format(index, model["name"]))
        print("       {}".format(model["id"]))

    print()
    print("Free models work without an account. Anonymous requests are "
          "rate-limited to 200 requests/hour per IP.")

    try:
        choice = input("Select a model number (Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("Cancelled.")
        return None

    if not choice:
        print("Cancelled.")
        return None

    try:
        selected_index = int(choice)
    except ValueError:
        print("Invalid selection.")
        return None

    if selected_index < 1 or selected_index > len(models):
        print("Invalid selection.")
        return None

    selected = models[selected_index - 1]
    config["provider"] = "kilo"
    config["model_id"] = selected["id"]
    config["default_model"] = selected["id"]

    saved = save_config(config)
    agent.set_model(selected["id"])

    print("Selected model: {}".format(selected["id"]))
    if not saved:
        print("The selection is active for this session only.")
    return selected["id"]


def configure_api_key(config, provider):
    print("Kilo API keys are optional. Free models work anonymously.")
    print("You do not need an account to use free models.")
    try:
        api_key = getpass.getpass(
            "Kilo API key (optional, Enter to cancel): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print("Cancelled.")
        return
    except Exception:
        try:
            api_key = input("Kilo API key (optional, Enter to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print("Cancelled.")
            return

    if not api_key:
        print("Cancelled.")
        return

    config["kilo_api_key"] = api_key
    provider.api_key = api_key

    if save_config(config):
        print("Kilo API key saved locally in config.json.")
    else:
        print("Kilo API key is active for this session only.")


def main():
    config = load_config()

    if config is None:
        return

    provider = KiloProvider(api_key=resolve_api_key(config))
    cached_models = load_cached_models()
    provider.set_free_models(cached_models)

    current_ai_model = config.get("model_id") or config.get("default_model") or ""
    if current_ai_model == "None":
        current_ai_model = ""
    invalid_cached_model = False
    if current_ai_model and cached_models:
        cached_ids = set(model["id"] for model in cached_models)
        if current_ai_model not in cached_ids:
            invalid_cached_model = True
            current_ai_model = ""

    agent = Agent(current_ai_model, provider=provider)

    clear()
    banner(current_ai_model)

    if invalid_cached_model:
        print("Configured model is not in the cached free model list; "
              "select one with /model.")
    print("Welcome to GhostAI.")
    print("Type /help for commands.")
    if provider.has_api_key():
        print("Using an optional Kilo API key.")
    else:
        print("Anonymous access: free models only, limited to "
              "200 requests/hour per IP. No account is required.")
    print()

    try:
        username = input("username? ")
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if username == "":
        return

    while True:
        try:
            message = input(f"{username} > ").strip()

            if not message:
                continue

            if message == "/exit":
                print("quitting GhostAI")
                break

            elif message == "/help":
                print("""
Commands:
  /help   Show commands
  /model  View and select free models
  /key    Save an optional Kilo API key locally
  /clear  Clear terminal
  /reset  Reset conversation
  /exit   Exit GhostAI
                """)

            elif message == "/clear":
                clear()
                banner(agent.model)

            elif message == "/reset":
                agent.reset()
                print("Conversation history cleared.")

            elif message == "/model":
                selected = choose_model(config, agent, provider)
                if selected:
                    banner(selected)

            elif message == "/key":
                configure_api_key(config, provider)

            else:
                if not agent.model:
                    print("GhostAI > No model selected. Use /model to choose a free model.")
                    continue

                try:
                    reply = agent.send_message(message)
                    print("GhostAI > " + reply)
                except RateLimitError as exc:
                    print("GhostAI > {}".format(exc))
                except KiloError as exc:
                    print("GhostAI > Error: {}".format(exc))
                except ValueError as exc:
                    print("GhostAI > {}".format(exc))

        except KeyboardInterrupt:
            print("\nquitting GhostAI")
            break


if __name__ == "__main__":
    main()
