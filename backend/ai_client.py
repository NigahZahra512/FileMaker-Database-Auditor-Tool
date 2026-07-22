"""
ai_client.py

DAY 3 SUPPORT MODULE: safe AI wrapper (used by script_reviewer.py and
sql_reviewer.py)
-----------------------------------------------------------------------
This is NOT one of the two Day 3 deliverables itself -- it's the shared
plumbing both of them use, so I only have to solve "call the AI and get
back safe JSON, no matter what" ONCE, in one place.

WHY THIS FILE EXISTS (ties directly to success criterion #6):
  "Script and SQL modules return valid, parseable JSON every time --
   no exceptions."

That means, no matter what happens:
  - the API key is missing
  - the network call fails / times out
  - the AI wraps its answer in ```json fences or adds a sentence before it
  - the AI returns a JSON object instead of a JSON array
  - the AI leaves out a field, or invents a severity value that isn't
    Critical/Warning/Info
...this module must NEVER raise an exception out to the caller. It
always hands back a Python list of finding-dicts (possibly empty, or
possibly a single "AI review failed" finding), never crashes, and
whatever gets written to disk with json.dump() is guaranteed valid JSON
because it was already a plain Python list/dict to begin with.

PROVIDER SUPPORT:
  Three providers, chosen with provider="claude" / "gemini" / "grok".
  All three are wrapped behind the same call_ai() function so
  script_reviewer.py and sql_reviewer.py don't care which one is
  actually being used. Grok (xAI) speaks the OpenAI-compatible API, so
  it's called through the `openai` package pointed at xAI's base_url.

SETUP:
  Put your key(s) in a .env file next to this script:
      AI_PROVIDER=grok
      ANTHROPIC_API_KEY=sk-ant-...
      GEMINI_API_KEY=...
      GROK_API_KEY=xai-...
  (pip install python-dotenv anthropic google-generativeai openai)
"""

import os
import json
import re
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv is a convenience, not a hard requirement -- if it's not
    # installed we just fall back to whatever is already in the
    # environment (os.environ).
    pass

DEFAULT_PROVIDER = os.environ.get("AI_PROVIDER", "claude")
CLAUDE_MODEL = "claude-sonnet-4-6"
GEMINI_MODEL = "gemini-2.0-flash"
GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

VALID_SEVERITIES = {"Critical", "Warning", "Info"}


# ---------------------------------------------------------------------------
# Runtime settings: lets a non-technical user paste their own API key into
# the web UI's Settings panel instead of editing a .env file by hand.
# Stored IN-MEMORY ONLY -- never written to disk, resets when the server
# restarts. Falls back to whatever's in .env if the UI hasn't set anything.
# ---------------------------------------------------------------------------
_runtime = {
    "provider": None,       # "claude" | "gemini" | "grok" | "groq" | "custom"
    "keys": {},              # provider -> api key (in memory only)
    "custom_base_url": None,
    "custom_model": None,
}


def set_runtime_config(provider: str, api_key: str,
                        custom_base_url: str | None = None,
                        custom_model: str | None = None) -> None:
    _runtime["provider"] = provider
    if api_key:
        _runtime["keys"][provider] = api_key
    if provider == "custom":
        _runtime["custom_base_url"] = custom_base_url
        _runtime["custom_model"] = custom_model


def get_active_provider() -> str:
    return _runtime["provider"] or DEFAULT_PROVIDER


def _env_key_for(provider: str) -> str | None:
    return {
        "claude": os.environ.get("ANTHROPIC_API_KEY"),
        "gemini": os.environ.get("GEMINI_API_KEY"),
        "grok": os.environ.get("GROK_API_KEY"),
        "groq": os.environ.get("GROQ_API_KEY"),
        "custom": os.environ.get("CUSTOM_API_KEY"),
    }.get(provider)


def _get_key(provider: str) -> str | None:
    """UI-entered key wins if present, otherwise fall back to .env."""
    return _runtime["keys"].get(provider) or _env_key_for(provider)


def get_runtime_status() -> dict:
    """Safe-to-expose status for the settings panel -- never returns the
    actual key, just whether one is configured."""
    provider = get_active_provider()
    return {
        "provider": provider,
        "configured": bool(_get_key(provider)),
        "custom_base_url": _runtime["custom_base_url"],
        "custom_model": _runtime["custom_model"],
    }


# ---------------------------------------------------------------------------
# Test Connection: makes ONE minimal real call to whichever provider the
# Settings panel currently has filled in -- using the key typed into the
# form, not necessarily the saved runtime key -- and returns the ACTUAL
# success/failure, with a human-readable reason.
#
# This exists because the _call_* functions above are deliberately silent
# on failure (print to the server console, return None) so a bad audit
# run never crashes -- but that same silence means a wrong key, wrong
# model name, or wrong base URL previously showed up to the user as
# "nothing happened" / "no details" with no indication why. Test
# Connection surfaces that reason immediately, before the user ever
# uploads a DDR or pastes a script.
# ---------------------------------------------------------------------------


def test_connection(provider: str, api_key: str,
                     custom_base_url: str | None = None,
                     custom_model: str | None = None) -> dict:
    if not api_key:
        return {"success": False, "message": "Enter an API key first."}

    try:
        if provider == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model=CLAUDE_MODEL, max_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            return {"success": True, "message": f"Connected -- {CLAUDE_MODEL} responded."}

        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name=GEMINI_MODEL)
            model.generate_content("Say OK")
            return {"success": True, "message": f"Connected -- {GEMINI_MODEL} responded."}

        elif provider == "grok":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
            client.chat.completions.create(
                model=GROK_MODEL, max_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            return {"success": True, "message": f"Connected -- {GROK_MODEL} responded."}

        elif provider == "groq":
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
            client.chat.completions.create(
                model=GROQ_MODEL, max_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            return {"success": True, "message": f"Connected -- {GROQ_MODEL} responded."}

        elif provider == "custom":
            if not custom_base_url or not custom_model:
                return {"success": False, "message": "Custom provider needs both a base URL and a model name."}
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=custom_base_url)
            client.chat.completions.create(
                model=custom_model, max_tokens=10,
                messages=[{"role": "user", "content": "Say OK"}],
            )
            return {"success": True, "message": f"Connected -- {custom_model} responded."}

        else:
            return {"success": False, "message": f"Unknown provider '{provider}'."}

    except ImportError as e:
        return {"success": False, "message": f"Missing package ({e}). Run: pip install -r requirements.txt"}
    except Exception as e:
        return {"success": False, "message": _friendly_connection_error(provider, e)}


def _friendly_connection_error(provider: str, e: Exception) -> str:
    text = str(e)
    lowered = text.lower()
    label = provider.capitalize()
    if "401" in text or "unauthorized" in lowered or "invalid api key" in lowered or "authentication" in lowered or "permission" in lowered:
        return f"{label} rejected the key -- check it's correct, active, and has not expired."
    if "404" in text and "model" in lowered:
        return f"{label} could not find that model -- check the model name is spelled correctly."
    if "429" in text or "quota" in lowered or "rate limit" in lowered or "resourceexhausted" in lowered:
        return f"{label} rate-limited or quota exceeded -- the key works, but try again shortly."
    if "connection" in lowered or "timed out" in lowered or "timeout" in lowered or "resolve" in lowered:
        return f"Could not reach {label} -- check the base URL and network/firewall access."
    return f"{label} call failed: {text[:200]}"


# ---------------------------------------------------------------------------
# Step 1: raw call to whichever provider -- returns plain text, or None
# ---------------------------------------------------------------------------

def _call_claude(system_prompt: str, user_prompt: str) -> str | None:
    try:
        import anthropic
    except ImportError:
        print("[ai_client] 'anthropic' package not installed -- run: "
              "pip install anthropic")
        return None

    api_key = _get_key("claude")
    if not api_key:
        print("[ai_client] No Claude API key -- set it in the Settings "
              "panel or ANTHROPIC_API_KEY in .env")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(
            block.text for block in response.content if block.type == "text"
        )
    except Exception as e:
        # Network error, auth error, rate limit, whatever -- never let
        # this bubble up and crash the whole audit run.
        print(f"[ai_client] Claude call failed: {e}")
        return None


def _call_gemini(system_prompt: str, user_prompt: str, max_retries: int = 2) -> str | None:
    try:
        import google.generativeai as genai
    except ImportError:
        print("[ai_client] 'google-generativeai' package not installed -- "
              "run: pip install google-generativeai")
        return None

    api_key = _get_key("gemini")
    if not api_key:
        print("[ai_client] No Gemini API key -- set it in the Settings "
              "panel or GEMINI_API_KEY in .env")
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=system_prompt,
    )

    for attempt in range(max_retries + 1):
        try:
            response = model.generate_content(user_prompt)
            return response.text
        except Exception as e:
            error_text = str(e)
            # Free-tier rate limits (429 / ResourceExhausted) come back
            # with a retry_delay the API itself suggests -- wait that
            # long (or a safe default) and try again, instead of just
            # giving up on the first hit.
            is_rate_limit = "429" in error_text or "quota" in error_text.lower() \
                or "ResourceExhausted" in error_text
            if is_rate_limit and attempt < max_retries:
                wait_seconds = 15
                match = re.search(r"seconds:\s*(\d+)", error_text)
                if match:
                    wait_seconds = int(match.group(1)) + 2  # small buffer
                print(f"[ai_client] Gemini rate-limited, waiting "
                      f"{wait_seconds}s before retry ({attempt + 1}/{max_retries})...")
                time.sleep(wait_seconds)
                continue
            print(f"[ai_client] Gemini call failed: {e}")
            return None

    return None


def _call_grok(system_prompt: str, user_prompt: str) -> str | None:
    try:
        from openai import OpenAI
    except ImportError:
        print("[ai_client] 'openai' package not installed -- run: "
              "pip install openai  (Grok/xAI uses the OpenAI-compatible API)")
        return None

    api_key = _get_key("grok")
    if not api_key:
        print("[ai_client] No Grok API key -- set it in the Settings "
              "panel or GROK_API_KEY in .env")
        return None

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
        response = client.chat.completions.create(
            model=GROK_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        # Same rule as every other provider call here -- never let this
        # bubble up and crash the whole audit run.
        print(f"[ai_client] Grok call failed: {e}")
        return None


def _call_groq(system_prompt: str, user_prompt: str) -> str | None:
    """Groq (fast-inference LPU hosting of Llama/Mixtral/etc, console.groq.com)
    -- a DIFFERENT company from Grok/xAI, even though the name is nearly
    identical. Also speaks the OpenAI-compatible API."""
    try:
        from openai import OpenAI
    except ImportError:
        print("[ai_client] 'openai' package not installed -- run: "
              "pip install openai  (Groq uses the OpenAI-compatible API)")
        return None

    api_key = _get_key("groq")
    if not api_key:
        print("[ai_client] No Groq API key -- set it in the Settings "
              "panel or GROQ_API_KEY in .env")
        return None

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[ai_client] Groq call failed: {e}")
        return None


def _call_custom(system_prompt: str, user_prompt: str) -> str | None:
    """Any OpenAI-compatible provider (Groq, OpenRouter, Together, a local
    server, etc.) -- the Settings panel's 'Custom' option collects the
    base_url + model needed to talk to it."""
    try:
        from openai import OpenAI
    except ImportError:
        print("[ai_client] 'openai' package not installed -- run: "
              "pip install openai")
        return None

    api_key = _get_key("custom")
    base_url = _runtime["custom_base_url"]
    model = _runtime["custom_model"]
    if not api_key or not base_url or not model:
        print("[ai_client] Custom provider needs an API key, base URL, "
              "and model name -- set them in the Settings panel")
        return None

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[ai_client] Custom provider call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 2: strip AI chatter around the JSON (```json fences, a stray
# sentence before/after, etc.) and parse it safely
# ---------------------------------------------------------------------------

def _extract_json(raw_text: str):
    """
    AI models frequently do NOT return pure JSON even when told to --
    they wrap it in ```json ... ``` fences, or add a leading "Here is
    the analysis:" sentence. This pulls out the first {...} or [...]
    block and parses it. Returns None (never raises) if nothing valid
    is found.
    """
    if not raw_text:
        return None

    text = raw_text.strip()

    # Strip ```json ... ``` or ``` ... ``` fences if present
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try a direct parse first (the clean, expected case)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: grab the outermost [...] or {...} span and try that
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    return None


# ---------------------------------------------------------------------------
# Step 3: validate + normalise each finding so a malformed AI answer
# can never corrupt the final report
# ---------------------------------------------------------------------------

def _normalise_finding(item: dict, module: str) -> dict | None:
    if not isinstance(item, dict):
        return None

    severity = str(item.get("severity", "Info")).strip().capitalize()
    if severity not in VALID_SEVERITIES:
        severity = "Info"  # never let a bad value slip into the report

    location = str(item.get("location", "Unknown")).strip() or "Unknown"
    description = str(item.get("description", "")).strip()
    suggestion = str(item.get("suggestion", "")).strip()

    if not description:
        return None  # a finding with no description isn't useful -- drop it

    return {
        "module": module,
        "severity": severity,
        "location": location,
        "description": description,
        "suggestion": suggestion or "No suggestion provided.",
    }


# ---------------------------------------------------------------------------
# Public entry point used by script_reviewer.py / sql_reviewer.py
# ---------------------------------------------------------------------------

def call_ai_for_findings(system_prompt: str, user_prompt: str, module: str,
                          provider: str | None = None) -> list[dict]:
    """
    Calls the chosen AI provider and returns a GUARANTEED-safe list of
    finding-dicts. Never raises. Worst case, returns a single finding
    that says the AI review itself failed (so the human running the
    tool still sees *something* in the report instead of a silent gap).
    provider=None resolves to whatever is currently active (UI Settings
    panel choice, falling back to AI_PROVIDER in .env).
    """
    provider = provider or get_active_provider()
    try:
        if provider == "gemini":
            raw = _call_gemini(system_prompt, user_prompt)
        elif provider == "grok":
            raw = _call_grok(system_prompt, user_prompt)
        elif provider == "groq":
            raw = _call_groq(system_prompt, user_prompt)
        elif provider == "custom":
            raw = _call_custom(system_prompt, user_prompt)
        else:
            raw = _call_claude(system_prompt, user_prompt)

        parsed = _extract_json(raw) if raw else None

        if parsed is None:
            return [{
                "module": module,
                "severity": "Info",
                "location": "AI Review",
                "description": ("AI review could not be completed (no "
                                 "response, or response was not valid "
                                 "JSON)."),
                "suggestion": ("Re-run this module, or check that the "
                                "API key and network connection are "
                                "working."),
            }]

        # The AI might return a bare list, or {"findings": [...]}
        items = parsed if isinstance(parsed, list) else parsed.get("findings", [])
        if not isinstance(items, list):
            items = []

        findings = []
        for item in items:
            normalised = _normalise_finding(item, module)
            if normalised:
                findings.append(normalised)

        return findings

    except Exception as e:
        # Absolute last line of defence -- literally anything else
        # unexpected still comes back as a valid finding, not a crash.
        return [{
            "module": module,
            "severity": "Info",
            "location": "AI Review",
            "description": f"AI review raised an unexpected error: {e}",
            "suggestion": "Check ai_client.py logs and re-run.",
        }]
