"""The platform's own settings, kept from the owner's console (docs/plans/2026-11-10-admin-console.md, C, D and E): the
model each agent uses, the providers' keys, and the monthly limits the administrator is warned against.

Three files under `<read_root>/_platform/` (a name `admin_api` never lists as a company):
- `agents.json`: each agent's current setting and the history of changes, each with who, when and why;
- `keys.json`: the providers' keys. Every secret field is sealed with AES-GCM under the master key, which lives only
  in the server's environment (`MODELER_MASTER_KEY`, 32 random bytes in base64); the record keeps the field's last 4
  characters to be recognised by, who added it and when, its state (new, active, retired) and its last test. A key
  is added, tested, made active (the provider's active key is then retired) and retired; one active longer than
  `ROTATE_AFTER_DAYS` is due for rotation;
- `limits.json`: a monthly spend and token limit per company, project or person, and the history of changes. A limit
  only warns the administrator (at `WARN_AT` of it and when it is reached); it never stops an agent (answer 2);
- `paid_caps.json` and `paid_spend/<YYYY-MM>.jsonl`: the hard cap on **paid** models only (`PAID_PROVIDERS`; the
  owner's decision D3, 2026-11-24): a dollar cap per run and per calendar month, platform-wide, with the history of
  changes, and every paid call's cost (`modeler_agents.spend`). Reaching a cap pauses the Data room's run; free and
  in-house models keep the warn-only limits above;
- `companies.json`: the companies the console created (their names) and those it disabled (whose people it disabled,
  so enabling the company enables them again). People themselves are kept in Keycloak (`keycloak_admin`).

Secrets leave this module only to build an agent's model (`model_env`) or to test a key: no answer of the API holds
one. An agent left "as the environment says" keeps the server's own configuration (`MODELER_LLM_*`, `LITELLM_*`).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pbpk_domain.atomic_io import atomic_write_text, file_lock

FOLDER = "_platform"
ROTATE_AFTER_DAYS = 90

# The agents a setting is kept for, by the prefix of their run names (`A4-sheet-reading` is A4, `A10-writer` is A10).
# A6 … A10 are the Data room's five (plan 2026-11-21 v2 §9), each switched on its own.
AGENTS: dict[str, str] = {
    "A1": "A1 · reads the proposal (Start)",
    "A2": "A2 · searches the literature",
    "A3": "A3 · finds observed data",
    "A4": "A4 · reads the client's files",
    "A5": "A5 · drafts the model plan",
    "A6": "A6 · Data room: the question",
    "A7": "A7 · Data room: sorts the files",
    "A8": "A8 · Data room: extracts",
    "A9": "A9 · Data room: checks the extraction",
    "A10": "A10 · Data room: writes findings and requests",
}
# Where an agent's model comes from: the server's environment, nowhere (agents off), or a provider with a console key.
AGENT_PROVIDERS: dict[str, str] = {
    "environment": "As the server's environment says",
    "off": "Off (every step on its manual path)",
    "litellm": "In-house model (LiteLLM proxy)",
    "bedrock": "Claude on Amazon Bedrock",
    "anthropic": "Claude API (Anthropic Console key)",
    "groq": "gpt-oss-120b on GroqCloud",
    "nvidia": "NVIDIA API catalog",
    "openai_compat": "Another OpenAI-compatible service",
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")          # Claude's `output_config.effort`
GROQ_EFFORTS = ("low", "medium", "high")                     # gpt-oss's `reasoning_effort` (modeler_agents.llm)
# The one-click choices on each agent's row (plan 2026-11-21 v2 §9): a provider, a model and an effort each. Every one
# calls tools; `reads_scans`: the model reads a page image itself, which only Claude does (gpt-oss-120b and Qwen Coder
# read text only, so a scanned page reaches them as the OCR's text).
# `terms`: what happens to what the model is sent, as each service states it (checked 2026-11-22; sources in
# docs/USING_THE_TOOL.md §6a). Shown beside each choice and in the chain, so a cloud model is chosen knowingly.
MODEL_CHOICES: tuple[dict[str, Any], ...] = (
    {"id": "qwen-coder", "label": "Qwen Coder", "provider": "litellm", "model": "qwen-coder", "effort": "",
     "tools": True, "reads_scans": False, "terms": "On your server: client files stay there."},
    {"id": "claude", "label": "Claude", "provider": "bedrock", "model": "anthropic.claude-opus-5-5", "effort": "",
     "tools": True, "reads_scans": True,
     "terms": "Amazon Bedrock, in your AWS account: Bedrock does not use inputs to train models."},
    # Anthropic's own Claude API with the Console key (D1, 2026-11-24); paid: the hard cap of D3 applies
    {"id": "claude-api-opus", "label": "Claude Opus 5.5 (Claude API)", "provider": "anthropic", "model": "claude-opus-5-5",
     "effort": "", "tools": True, "reads_scans": True,
     "terms": "Anthropic's Claude API under its commercial terms: inputs are not used to train models (check the current "
              "terms in the Console). Paid: the per-run and monthly caps apply. Client files go to it only with the "
              "client's written permission recorded on the project."},
    {"id": "claude-api-sonnet", "label": "Claude Sonnet 5.5 (Claude API)", "provider": "anthropic",
     "model": "claude-sonnet-5-5", "effort": "", "tools": True, "reads_scans": True,
     "terms": "Anthropic's Claude API under its commercial terms: inputs are not used to train models (check the current "
              "terms in the Console). Paid: the per-run and monthly caps apply. Client files go to it only with the "
              "client's written permission recorded on the project."},
    {"id": "gpt-oss-120b", "label": "gpt-oss-120b", "provider": "groq", "model": "openai/gpt-oss-120b", "effort": "medium",
     "tools": True, "reads_scans": False,
     "terms": "GroqCloud: does not train on inputs; turn on Zero Data Retention in its console before sending client "
              "files. Free tier: 8,000 tokens a request."},
    # NVIDIA's flagship on its API catalog (the owner, 2026-11-22: a free cloud model to score the agents with)
    {"id": "nemotron-ultra", "label": "Nemotron Ultra", "provider": "nvidia", "model": "nvidia/nemotron-3-ultra-550b-a55b",
     "effort": "", "tools": True, "reads_scans": False,
     "terms": "NVIDIA's trial: inputs may be used to improve NVIDIA's products. For testing and made-up data, not "
              "client files."},
)
# One-click presets for every agent at once (plan 2026-11-24 §3, approved by the owner): each agent's provider, model,
# effort and fallback. A9 always runs on a model other than A8's: its second opinion must not be the extractor's own.
_NEMOTRON = ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "", "")
_GPT_OSS = ("groq", "openai/gpt-oss-120b", "medium", "")
_QWEN = ("litellm", "qwen-coder", "", "")
_SONNET = ("anthropic", "claude-sonnet-5-5", "", "")
_OPUS = ("anthropic", "claude-opus-5-5", "", "claude-sonnet-5-5")
PRESETS: tuple[dict[str, Any], ...] = (
    {"id": "free", "label": "Free",
     "what": "NVIDIA's Nemotron Ultra for every agent, GroqCloud's gpt-oss-120b for the second opinion (A9). Free trial "
             "services: for made-up data, or client files only with the client's written permission.",
     "agents": {a: (_GPT_OSS if a == "A9" else _NEMOTRON) for a in AGENTS}},
    {"id": "in-house", "label": "In-house only",
     "what": "The model on your server for every agent: client files never leave it.",
     "agents": dict.fromkeys(AGENTS, _QWEN)},
    {"id": "claude-demo", "label": "Claude demo",
     "what": "Claude Opus 5.5 extracts (A8); Claude Sonnet 5.5 for the question, sorting, the second opinion and the "
             "report. The split of plan §2.3. Paid: the per-run and monthly caps apply.",
     "agents": {a: (_OPUS if a == "A8" else _SONNET) for a in AGENTS}},
    {"id": "claude-opus", "label": "Claude, all Opus",
     "what": "Claude Opus 5.5 for every agent; Claude Sonnet 5.5 for the second opinion (A9). The most accurate, the "
             "most expensive. Paid: the per-run and monthly caps apply.",
     "agents": {a: (_SONNET if a == "A9" else _OPUS) for a in AGENTS}},
)

# Each provider's key fields: (name, label, secret, required). Bedrock takes a Bedrock API key, or an AWS access key
# with its secret (`anthropic.AnthropicBedrockMantle`); the region is not a secret. GroqCloud's address is fixed.
KEY_PROVIDERS: dict[str, dict[str, Any]] = {
    "litellm": {"label": "In-house model (LiteLLM proxy)",
                "fields": (("base_url", "Proxy address", False, True), ("key", "Proxy key", True, True))},
    "bedrock": {"label": "Claude on Amazon Bedrock",
                "fields": (("aws_region", "AWS region", False, True), ("api_key", "Bedrock API key", True, False),
                           ("aws_access_key", "AWS access key ID", True, False),
                           ("aws_secret_key", "AWS secret access key", True, False))},
    # Anthropic's own Claude API: one Console key, made in the Console workspace that carries the spend limit (D1)
    "anthropic": {"label": "Claude API (Anthropic Console)", "fields": (("api_key", "Claude API key", True, True),)},
    "groq": {"label": "gpt-oss-120b on GroqCloud", "fields": (("api_key", "GroqCloud API key", True, True),)},
    "nvidia": {"label": "NVIDIA API catalog (build.nvidia.com)", "fields": (("api_key", "NVIDIA API key", True, True),)},
    # any OpenAI-compatible Chat Completions service (Cerebras, NVIDIA's API catalog, OpenRouter …): its address and key;
    # the model is typed on the agent's row ("More…")
    "openai_compat": {"label": "Another OpenAI-compatible service",
                      "fields": (("base_url", "Service address (ending in /v1)", False, True),
                                 ("api_key", "API key", True, True))},
    # the console's people and companies (F): the realm's service-account client, `keycloak_admin`
    "keycloak": {"label": "Keycloak service account (people and companies)",
                 "fields": (("client_id", "Client ID (modeler-admin-api)", False, True),
                            ("client_secret", "Client secret", True, True))},
}


class SettingsError(ValueError):
    """A setting or key the rules refuse, or one that cannot be used, with what to do."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _folder(read_root: str) -> Path:
    from modeler_project.store import resolve_root

    return resolve_root(read_root) / FOLDER


def _read(path: Path, empty: dict[str, Any]) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty


def _write(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False))


# --- the master key ------------------------------------------------------------------------------------------------


def cipher(master_key: str) -> AESGCM:
    """AES-256-GCM under the master key; SettingsError when it is missing or not 32 bytes of base64."""
    if not master_key.strip():
        raise SettingsError("no master key: set MODELER_MASTER_KEY in the server's secrets file (32 random bytes in "
                            "base64: python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())') "
                            "and restart the API")
    try:
        raw = base64.b64decode(master_key.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SettingsError("MODELER_MASTER_KEY is not base64") from exc
    if len(raw) != 32:
        raise SettingsError(f"MODELER_MASTER_KEY must be 32 bytes, not {len(raw)}")
    return AESGCM(raw)


def _seal(aes: AESGCM, value: str, binding: str) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + aes.encrypt(nonce, value.encode("utf-8"), binding.encode("utf-8"))).decode("ascii")


def _open(aes: AESGCM, sealed: str, binding: str) -> str:
    blob = base64.b64decode(sealed)
    try:
        return aes.decrypt(blob[:12], blob[12:], binding.encode("utf-8")).decode("utf-8")
    except InvalidTag as exc:
        raise SettingsError("a stored key cannot be opened with this MODELER_MASTER_KEY (was it changed?)") from exc


# --- keys ----------------------------------------------------------------------------------------------------------


class KeyStore:
    def __init__(self, read_root: str, master_key: str = ""):
        self.path = _folder(read_root) / "keys.json"
        self._master = master_key

    def records(self) -> list[dict[str, Any]]:
        return _read(self.path, {"keys": []})["keys"]

    def view(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Every key as the console shows it: its last 4 characters, never a secret."""
        now = now or datetime.now(UTC)
        out = []
        for r in sorted(self.records(), key=lambda r: r["added_at"], reverse=True):
            since = r.get("activated_at") if r["state"] == "active" else None
            age = (now - datetime.fromisoformat(since)).days if since else None
            out.append({k: r.get(k) for k in ("id", "provider", "label", "state", "added_by", "added_at", "activated_at",
                                               "retired_at", "tested_at", "test_ok", "test_message")}
                       | {"last4": {f: v["last4"] for f, v in r["secret"].items()}, "plain": dict(r["plain"]),
                          "active_days": age, "due": age is not None and age >= ROTATE_AFTER_DAYS})
        return out

    def add(self, provider: str, label: str, fields: dict[str, str], *, by: str) -> dict[str, Any]:
        spec = KEY_PROVIDERS.get(provider)
        if spec is None:
            raise SettingsError(f"unknown provider {provider!r}; one of: {', '.join(KEY_PROVIDERS)}")
        given = {k: (v or "").strip() for k, v in fields.items() if (v or "").strip()}
        names = {name for name, *_ in spec["fields"]}
        if unknown := sorted(set(given) - names):
            raise SettingsError(f"{provider} has no field {', '.join(unknown)}")
        if missing := [label_ for name, label_, _s, required in spec["fields"] if required and name not in given]:
            raise SettingsError(f"{spec['label']} needs: {', '.join(missing)}")
        if provider == "bedrock" and "api_key" not in given and not {"aws_access_key", "aws_secret_key"} <= set(given):
            raise SettingsError("Claude on Amazon Bedrock needs a Bedrock API key, or an AWS access key ID with its secret")
        aes = cipher(self._master)
        key_id = f"key_{uuid.uuid4().hex[:10]}"
        secret_names = {name for name, _l, secret, _r in spec["fields"] if secret}
        record = {"id": key_id, "provider": provider, "label": label.strip() or spec["label"], "state": "new",
                  "plain": {k: v for k, v in given.items() if k not in secret_names},
                  "secret": {k: {"last4": v[-4:], "sealed": _seal(aes, v, f"{key_id}/{k}")}
                             for k, v in given.items() if k in secret_names},
                  "added_by": by, "added_at": _now(), "activated_at": None, "retired_at": None,
                  "tested_at": None, "test_ok": None, "test_message": None}
        with file_lock(self.path):
            doc = _read(self.path, {"keys": []})
            doc["keys"].append(record)
            _write(self.path, doc)
        return record

    def _change(self, key_id: str, change: Any) -> dict[str, Any]:
        with file_lock(self.path):
            doc = _read(self.path, {"keys": []})
            record = next((r for r in doc["keys"] if r["id"] == key_id), None)
            if record is None:
                raise KeyError(key_id)
            change(doc, record)
            _write(self.path, doc)
        return record

    def activate(self, key_id: str) -> tuple[dict[str, Any], str | None]:
        """Make the key its provider's active one; the one it replaces is retired (returned)."""
        replaced: list[str] = []

        def change(doc: dict[str, Any], record: dict[str, Any]) -> None:
            if record["state"] != "new":
                raise SettingsError(f"only a new key can be made active; this one is {record['state']}")
            for other in doc["keys"]:
                if other["provider"] == record["provider"] and other["state"] == "active":
                    other.update(state="retired", retired_at=_now())
                    replaced.append(other["id"])
            record.update(state="active", activated_at=_now())

        return self._change(key_id, change), (replaced[0] if replaced else None)

    def retire(self, key_id: str) -> dict[str, Any]:
        def change(_doc: dict[str, Any], record: dict[str, Any]) -> None:
            if record["state"] == "retired":
                raise SettingsError("this key is retired already")
            record.update(state="retired", retired_at=_now())

        return self._change(key_id, change)

    def record_test(self, key_id: str, ok: bool, message: str) -> dict[str, Any]:
        return self._change(key_id, lambda _d, r: r.update(tested_at=_now(), test_ok=ok, test_message=message[:300]))

    def fields(self, key_id: str) -> tuple[str, dict[str, str]]:
        """The key's provider and every field opened (for a test or an agent's model only)."""
        record = next((r for r in self.records() if r["id"] == key_id), None)
        if record is None:
            raise KeyError(key_id)
        aes = cipher(self._master)
        return record["provider"], dict(record["plain"]) | {k: _open(aes, v["sealed"], f"{key_id}/{k}")
                                                            for k, v in record["secret"].items()}

    def active(self, provider: str) -> dict[str, str] | None:
        record = next((r for r in self.records() if r["provider"] == provider and r["state"] == "active"), None)
        return self.fields(record["id"])[1] if record else None


# --- agents' models ------------------------------------------------------------------------------------------------


class AgentSettings:
    def __init__(self, read_root: str):
        self.path = _folder(read_root) / "agents.json"

    def doc(self) -> dict[str, Any]:
        return _read(self.path, {"current": {}, "history": []})

    def current(self, agent: str) -> dict[str, Any] | None:
        return self.doc()["current"].get(agent)

    def set(self, agent: str, provider: str, model: str, *, by: str, reason: str, effort: str = "",
            fallback: str = "") -> dict[str, Any]:
        if agent not in AGENTS:
            raise SettingsError(f"unknown agent {agent!r}; one of: {', '.join(AGENTS)}")
        if provider not in AGENT_PROVIDERS:
            raise SettingsError(f"unknown provider {provider!r}; one of: {', '.join(AGENT_PROVIDERS)}")
        if provider in KEY_PROVIDERS and not model.strip():
            raise SettingsError(f"{AGENT_PROVIDERS[provider]} needs a model name")
        claude, groq = provider in ("bedrock", "anthropic"), provider == "groq"
        if claude and effort and effort not in EFFORTS:
            raise SettingsError(f"effort is one of {', '.join(EFFORTS)}")
        if groq and effort and effort not in GROQ_EFFORTS:
            raise SettingsError(f"effort on GroqCloud is one of {', '.join(GROQ_EFFORTS)}")
        if claude and fallback.strip() == model.strip():
            raise SettingsError("the fallback model must differ from the model")
        setting = {"provider": provider, "model": model.strip() if provider in KEY_PROVIDERS else "",
                   "effort": effort if claude or groq else "", "fallback": fallback.strip() if claude else "",
                   "by": by, "at": _now(), "reason": reason.strip()}
        with file_lock(self.path):
            doc = _read(self.path, {"current": {}, "history": []})
            before = doc["current"].get(agent)
            doc["current"][agent] = setting
            doc["history"].append({"agent": agent, "before": before, **setting})
            _write(self.path, doc)
        return setting


# --- what an agent goes on with when its model fails (the owner, 2026-11-22) -------------------------------------------

#: what the admin console says before the chain is saved: a model further down may be a cloud service, which then
#: receives the client's files the agent was reading
CHAIN_NOTICE = ("When an agent's model cannot answer (no answer in time, a daily limit spent, the service down), the "
                "same request goes at once to the next model below, and the agent goes on there. A cloud model in this "
                "list receives the client's files the agent is reading: list only services whose terms you accept for "
                "client data.")


def chain_doc(read_root: str) -> dict[str, Any]:
    """The ordered one-click choices an agent goes on with when its own model fails (empty: none)."""
    return AgentSettings(read_root).doc().get("chain") or {"choices": [], "by": None, "at": None, "reason": None}


def set_chain(read_root: str, choices: list[str], *, by: str, reason: str) -> dict[str, Any]:
    known = {c["id"] for c in MODEL_CHOICES}
    unknown = [c for c in choices if c not in known]
    if unknown:
        raise SettingsError(f"unknown model choice {', '.join(unknown)}; one of: {', '.join(sorted(known))}")
    if len(set(choices)) != len(choices):
        raise SettingsError("a model is listed twice")
    store = AgentSettings(read_root)
    entry = {"choices": list(choices), "by": by, "at": _now(), "reason": reason.strip()}
    with file_lock(store.path):
        doc = _read(store.path, {"current": {}, "history": []})
        doc["chain"] = entry
        doc.setdefault("chain_history", []).append(entry)
        _write(store.path, doc)
    return entry


def chain_envs(read_root: str, master_key: str, agent: str | None) -> list[tuple[str, dict[str, str]]]:
    """The models an agent goes on with, in order, each as (label, configuration): the chain's choices whose provider has
    an active key, without the agent's own model."""
    if not read_root:
        return []
    own = AgentSettings(read_root).current(agent) if agent else None
    keys = KeyStore(read_root, master_key)
    out = []
    for cid in chain_doc(read_root)["choices"]:
        choice = next((c for c in MODEL_CHOICES if c["id"] == cid), None)
        key = keys.active(choice["provider"]) if choice else None
        if choice is None or key is None:
            continue
        if own and (own.get("provider"), own.get("model")) == (choice["provider"], choice["model"]):
            continue
        out.append((choice["label"], setting_env({"provider": choice["provider"], "model": choice["model"],
                                                  "effort": choice["effort"]}, key)))
    return out


def agent_of(run_agent: str) -> str | None:
    """The console's agent for a run's agent name ("A4-sheet-reading" is A4, "A10-writer" is A10)."""
    head = run_agent.split("-", 1)[0]
    return head if head in AGENTS else None


def model_env(read_root: str, master_key: str, agent: str) -> dict[str, str] | None:
    """The configuration `modeler_agents.llm.chat_model_from_env` reads, from the console's setting for `agent` and its
    provider's active key; None when the agent follows the server's environment."""
    if not read_root:
        return None
    setting = AgentSettings(read_root).current(agent)
    if setting is None or setting["provider"] == "environment":
        return None
    if setting["provider"] == "off":
        return {"MODELER_LLM_PROVIDER": "disabled"}
    key = KeyStore(read_root, master_key).active(setting["provider"])
    if key is None:
        raise SettingsError(f"{AGENTS[agent]} is set to {AGENT_PROVIDERS[setting['provider']]}, which has no active key: "
                            "add one in the admin console (Keys) and make it active")
    return setting_env(setting, key)


def setting_env(setting: dict[str, Any], key: dict[str, str]) -> dict[str, str]:
    """The configuration a provider and model run on, with the provider's key."""
    if setting["provider"] == "litellm":
        return {"MODELER_LLM_PROVIDER": "litellm", "LITELLM_BASE": key["base_url"], "LITELLM_KEY": key["key"],
                "MODELER_LLM_MODEL": setting["model"]}
    if setting["provider"] == "bedrock":
        env = {"MODELER_LLM_PROVIDER": "bedrock", "MODELER_LLM_MODEL": setting["model"], "BEDROCK_REGION": key["aws_region"],
               "MODELER_LLM_EFFORT": setting.get("effort") or "", "MODELER_LLM_FALLBACK": setting.get("fallback") or ""}
        if key.get("api_key"):
            return env | {"BEDROCK_API_KEY": key["api_key"]}
        return env | {"AWS_ACCESS_KEY_ID": key["aws_access_key"], "AWS_SECRET_ACCESS_KEY": key["aws_secret_key"]}
    if setting["provider"] == "anthropic":
        return {"MODELER_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": key["api_key"], "MODELER_LLM_MODEL": setting["model"],
                "MODELER_LLM_EFFORT": setting.get("effort") or "", "MODELER_LLM_FALLBACK": setting.get("fallback") or ""}
    if setting["provider"] == "groq":
        return {"MODELER_LLM_PROVIDER": "groq", "GROQ_API_KEY": key["api_key"], "MODELER_LLM_MODEL": setting["model"],
                "MODELER_LLM_EFFORT": setting.get("effort") or ""}
    if setting["provider"] == "nvidia":
        return {"MODELER_LLM_PROVIDER": "nvidia", "NVIDIA_API_KEY": key["api_key"], "MODELER_LLM_MODEL": setting["model"]}
    if setting["provider"] == "openai_compat":
        return {"MODELER_LLM_PROVIDER": "openai_compat", "OPENAI_COMPAT_BASE": key["base_url"],
                "OPENAI_COMPAT_KEY": key["api_key"], "MODELER_LLM_MODEL": setting["model"]}
    raise SettingsError(f"{setting['provider']} cannot run an agent yet")


# --- E: monthly limits ---------------------------------------------------------------------------------------------

LIMIT_SCOPES: dict[str, str] = {"company": "Company", "project": "Project", "person": "Person"}
WARN_AT = 0.8          # the administrator is warned at 80 % of a limit, and again when it is reached (answer 2)


def limit_id(scope: str, tenant_id: str, subject: str = "") -> str:
    """`company:acme`, `project:acme/p-1`, `person:acme/ana`."""
    return f"{scope}:{tenant_id}" if scope == "company" else f"{scope}:{tenant_id}/{subject}"


class LimitSettings:
    """The monthly limits on the agents' use (estimated spend in USD, tokens in and out), per company, project or
    person. Either measure may be left without a limit; with neither the limit is removed."""

    def __init__(self, read_root: str):
        self.path = _folder(read_root) / "limits.json"

    def doc(self) -> dict[str, Any]:
        return _read(self.path, {"limits": {}, "history": []})

    def set(self, scope: str, tenant_id: str, subject: str, *, usd: float | None, tokens: int | None, by: str,
            reason: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Set (or, with neither measure, remove) one limit; the limit before and after."""
        if scope not in LIMIT_SCOPES:
            raise SettingsError(f"a limit applies to one of: {', '.join(LIMIT_SCOPES)}")
        subject = subject.strip()
        if not tenant_id.strip() or (scope != "company") != bool(subject):
            raise SettingsError("a company's limit names the company; a project's or a person's names the company and "
                                "the project or the person")
        if (usd is not None and usd <= 0) or (tokens is not None and tokens <= 0):
            raise SettingsError("a limit is above zero (leave a measure empty for no limit on it)")
        if not reason.strip():
            raise SettingsError("say why (kept with the change)")
        key = limit_id(scope, tenant_id, subject)
        with file_lock(self.path):
            doc = _read(self.path, {"limits": {}, "history": []})
            before = doc["limits"].get(key)
            if usd is None and tokens is None:
                if before is None:
                    raise SettingsError("there is no limit to remove")
                after = None
                doc["limits"].pop(key)
            else:
                after = {"scope": scope, "tenant_id": tenant_id, "subject": subject, "usd": usd, "tokens": tokens,
                         "by": by, "at": _now(), "reason": reason.strip()}
                doc["limits"][key] = after
            doc["history"].append({"id": key, "usd": usd, "tokens": tokens, "by": by, "at": _now(), "reason": reason.strip()})
            _write(self.path, doc)
        return before, after


# --- the hard cap on paid models (plan 2026-11-24 §2.4; the owner's decision D3) -------------------------------------

#: the providers that cost money for each call: a cap stops them; every other provider (the in-house model, NVIDIA's and
#: GroqCloud's free tiers, another OpenAI-compatible service) keeps the warn-only limits. "anthropic" is the direct
#: Claude API (plan §3), named here before its provider exists so the cap holds from its first call.
PAID_PROVIDERS: tuple[str, ...] = ("bedrock", "anthropic")
PAID_CAP_DEFAULTS = {"run_usd": 10.0, "month_usd": 90.0}
PAID_CAP_DEFAULT_REASON = "the owner's decision D3 (2026-11-24): $10 a run, $90 a month, for paid models only"


class PaidCaps:
    """The dollar caps on paid models: per run and per calendar month (UTC), platform-wide. Defaults until the
    administrator sets them; each change keeps who, when and why."""

    def __init__(self, read_root: str):
        self.path = _folder(read_root) / "paid_caps.json"

    def doc(self) -> dict[str, Any]:
        return _read(self.path, {"current": None, "history": []})

    def current(self) -> dict[str, Any]:
        return self.doc()["current"] or {**PAID_CAP_DEFAULTS, "by": None, "at": None, "reason": PAID_CAP_DEFAULT_REASON}

    def set(self, *, run_usd: float, month_usd: float, by: str, reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Set both caps; the caps before and after."""
        if run_usd <= 0 or month_usd <= 0:
            raise SettingsError("a cap is above zero")
        if run_usd > month_usd:
            raise SettingsError("a run's cap cannot be above the month's")
        if not reason.strip():
            raise SettingsError("say why (kept with the change)")
        after = {"run_usd": float(run_usd), "month_usd": float(month_usd), "by": by, "at": _now(), "reason": reason.strip()}
        with file_lock(self.path):
            doc = _read(self.path, {"current": None, "history": []})
            before = doc["current"] or {**PAID_CAP_DEFAULTS, "by": None, "at": None, "reason": PAID_CAP_DEFAULT_REASON}
            doc["current"] = after
            doc["history"].append(after)
            _write(self.path, doc)
        return before, after


class PaidSpend:
    """Every paid model call's cost, one append-only file per calendar month (UTC): what the month's cap is checked
    against, and what a run spent (by its id)."""

    def __init__(self, read_root: str):
        self.folder = _folder(read_root) / "paid_spend"

    def _month(self, when: datetime) -> Path:
        return self.folder / f"{when:%Y-%m}.jsonl"

    def record(self, row: dict[str, Any]) -> None:
        path = self._month(datetime.now(UTC))
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path), path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    def rows(self, when: datetime | None = None) -> list[dict[str, Any]]:
        path = self._month(when or datetime.now(UTC))
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:          # a line a crash cut short
                continue
        return out

    def month_usd(self, when: datetime | None = None) -> float:
        return round(float(sum(float(r.get("usd") or 0) for r in self.rows(when))), 6)

    def run_usd(self, run_id: str) -> float:
        """A run's paid spend: this month's calls and last month's (a run that went on past the month's end)."""
        now = datetime.now(UTC)
        last = now.replace(day=1) - timedelta(days=1)
        return round(float(sum(float(r.get("usd") or 0) for when in (last, now) for r in self.rows(when)
                               if r.get("run_id") == run_id)), 6)


# --- F: companies ----------------------------------------------------------------------------------------------------


class CompanyRegistry:
    """The companies the console names, disables and enables. A company is a tenant: its folder in the store and the
    `tenant_id` its people carry in Keycloak; nothing here is ever removed."""

    def __init__(self, read_root: str):
        self.path = _folder(read_root) / "companies.json"

    def doc(self) -> dict[str, Any]:
        return _read(self.path, {"companies": {}})

    def get(self, tenant_id: str) -> dict[str, Any] | None:
        return self.doc()["companies"].get(tenant_id)

    def _change(self, tenant_id: str, change: Any) -> dict[str, Any]:
        with file_lock(self.path):
            doc = _read(self.path, {"companies": {}})
            record = doc["companies"].setdefault(tenant_id, {"name": "", "created_by": None, "created_at": None,
                                                             "disabled": None})
            change(record)
            _write(self.path, doc)
        return record

    def add(self, tenant_id: str, name: str, *, by: str) -> dict[str, Any]:
        if self.get(tenant_id) is not None:
            raise SettingsError(f"the company {tenant_id!r} exists already")
        return self._change(tenant_id, lambda r: r.update(name=name.strip(), created_by=by, created_at=_now()))

    def disable(self, tenant_id: str, people: list[str], *, by: str, reason: str) -> dict[str, Any]:
        if (self.get(tenant_id) or {}).get("disabled"):
            raise SettingsError(f"the company {tenant_id!r} is disabled already")
        return self._change(tenant_id, lambda r: r.update(disabled={"by": by, "at": _now(), "reason": reason.strip(),
                                                                    "people": people}))

    def enable(self, tenant_id: str) -> list[str]:
        """Enable the company again; the people its disabling disabled (to enable them again)."""
        disabled = (self.get(tenant_id) or {}).get("disabled")
        if not disabled:
            raise SettingsError(f"the company {tenant_id!r} is not disabled")
        self._change(tenant_id, lambda r: r.update(disabled=None))
        return list(disabled.get("people") or [])
