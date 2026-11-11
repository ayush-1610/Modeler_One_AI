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
  only warns the administrator (at `WARN_AT` of it and when it is reached); it never stops an agent (answer 2).

Secrets leave this module only to build an agent's model (`model_env`) or to test a key: no answer of the API holds
one. An agent left "as the environment says" keeps the server's own configuration (`MODELER_LLM_*`, `LITELLM_*`).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pbpk_domain.atomic_io import atomic_write_text, file_lock

FOLDER = "_platform"
ROTATE_AFTER_DAYS = 90

# The agents a setting is kept for, by the prefix of their run names (`A4-sheet-reading` is A4).
AGENTS: dict[str, str] = {
    "A1": "A1 · reads the proposal (Start)",
    "A2": "A2 · searches the literature",
    "A3": "A3 · finds observed data",
    "A4": "A4 · reads the client's files",
    "A5": "A5 · drafts the model plan",
}
# Where an agent's model comes from: the server's environment, nowhere (agents off), or a provider with a console key.
AGENT_PROVIDERS: dict[str, str] = {
    "environment": "As the server's environment says",
    "off": "Off (every step on its manual path)",
    "litellm": "In-house model (LiteLLM proxy)",
    "bedrock": "Claude on Amazon Bedrock",
}
EFFORTS = ("low", "medium", "high", "xhigh", "max")          # Claude's `output_config.effort`
# Each provider's key fields: (name, label, secret, required). Bedrock takes a Bedrock API key, or an AWS access key
# with its secret (`anthropic.AnthropicBedrockMantle`); the region is not a secret.
KEY_PROVIDERS: dict[str, dict[str, Any]] = {
    "litellm": {"label": "In-house model (LiteLLM proxy)",
                "fields": (("base_url", "Proxy address", False, True), ("key", "Proxy key", True, True))},
    "bedrock": {"label": "Claude on Amazon Bedrock",
                "fields": (("aws_region", "AWS region", False, True), ("api_key", "Bedrock API key", True, False),
                           ("aws_access_key", "AWS access key ID", True, False),
                           ("aws_secret_key", "AWS secret access key", True, False))},
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
        claude = provider == "bedrock"
        if claude and effort and effort not in EFFORTS:
            raise SettingsError(f"effort is one of {', '.join(EFFORTS)}")
        if claude and fallback.strip() == model.strip():
            raise SettingsError("the fallback model must differ from the model")
        setting = {"provider": provider, "model": model.strip() if provider in KEY_PROVIDERS else "",
                   "effort": effort if claude else "", "fallback": fallback.strip() if claude else "",
                   "by": by, "at": _now(), "reason": reason.strip()}
        with file_lock(self.path):
            doc = _read(self.path, {"current": {}, "history": []})
            before = doc["current"].get(agent)
            doc["current"][agent] = setting
            doc["history"].append({"agent": agent, "before": before, **setting})
            _write(self.path, doc)
        return setting


def agent_of(run_agent: str) -> str | None:
    """The console's agent for a run's agent name ("A4-sheet-reading" is A4)."""
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
    if setting["provider"] == "litellm":
        return {"MODELER_LLM_PROVIDER": "litellm", "LITELLM_BASE": key["base_url"], "LITELLM_KEY": key["key"],
                "MODELER_LLM_MODEL": setting["model"]}
    if setting["provider"] == "bedrock":
        env = {"MODELER_LLM_PROVIDER": "bedrock", "MODELER_LLM_MODEL": setting["model"], "BEDROCK_REGION": key["aws_region"],
               "MODELER_LLM_EFFORT": setting.get("effort") or "", "MODELER_LLM_FALLBACK": setting.get("fallback") or ""}
        if key.get("api_key"):
            return env | {"BEDROCK_API_KEY": key["api_key"]}
        return env | {"AWS_ACCESS_KEY_ID": key["aws_access_key"], "AWS_SECRET_ACCESS_KEY": key["aws_secret_key"]}
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
