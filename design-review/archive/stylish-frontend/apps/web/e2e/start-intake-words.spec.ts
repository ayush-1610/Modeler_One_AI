// Why the intake agent stopped, said in plain words on Start (the owner, 2026-11-22: "read the proposal" stopped with no
// word why). A pure check of `intakeStopped`: no page, no API.
import { expect, test } from "@playwright/test";
import { intakeStopped } from "../lib/start";

test("each way the intake agent stops is said in plain words, never with a setting's name", () => {
  const cases: [string, string, RegExp][] = [
    ["INCOMPLETE", "stopped after 80 turns", /used all its turns/],
    ["INCOMPLETE", "stopped: it repeated the same calls with the same answers 5 turns in a row", /kept repeating/],
    ["LLM_UNAVAILABLE", "the agent's instructions and material do not fit the model's context window (4096 tokens) even with "
      + "its earlier turns left out; raise it on the server (Ollama: start it with OLLAMA_CONTEXT_LENGTH=32768 …)", /context window/],
    ["LLM_UNAVAILABLE", "the request is longer than the model takes (HTTP 413: Request too large …)", /longer than the AI model/],
    ["LLM_UNAVAILABLE", "the provider's daily limit is reached: Rate limit reached … tokens per day (TPD)", /daily allowance/],
    ["LLM_UNAVAILABLE", "groq rejected the key (HTTP 401: invalid); check GROQ_API_KEY", /Admin → Keys/],
    ["LLM_UNAVAILABLE", "litellm unavailable after 5 attempts: timed out", /could not be reached/],
    ["FAILED", "something else", /stopped with an error/],
  ];
  for (const [status, error, words] of cases) {
    const said = intakeStopped(status, error);
    expect(said).toMatch(words);
    expect(said).not.toMatch(/OLLAMA|GROQ|MODELER_|HTTP|litellm/);
  }
});
