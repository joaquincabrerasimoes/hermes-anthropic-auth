Name: OAuth sanitizer misses nousresearch URL
Keywords: anthropic_adapter, is_oauth, sanitization, nousresearch.com, HERMES_AGENT_HELP_GUIDANCE, extra usage classifier
FilePathReference: agent/anthropic_adapter.py:2572-2636 ; agent/prompt_builder.py:139-158
Short Description: OAuth branch's 4-string .replace() sanitizer leaves nousresearch.com domain intact in every request's system prompt.
---
## Finding

`agent/anthropic_adapter.py:2572-2636` — the `is_oauth` branch of `build_anthropic_kwargs()` applies Claude Code compatibility transforms. Step 2 (system-prompt sanitization, lines 2583-2592) is a blunt 4-literal `.replace()` chain run over every text block in the `system` param:

```python
text = text.replace("Hermes Agent", "Claude Code")
text = text.replace("Hermes agent", "Claude Code")
text = text.replace("hermes-agent", "claude-code")
text = text.replace("Nous Research", "Anthropic")
```

### Critical gap: nousresearch.com domain survives

`HERMES_AGENT_HELP_GUIDANCE` (`agent/prompt_builder.py:149-158`, unconditionally injected into every session's stable system-prompt tier at `agent/system_prompt.py:199`) contains the literal URL:

```
https://hermes-agent.nousresearch.com/docs
```

Tracing the 4 replacements against this string:
- `"hermes-agent"` → `"claude-code"` DOES match the URL's hyphenated segment → produces `https://claude-code.nousresearch.com/docs`
- `"Nous Research"` → `"Anthropic"` does NOT match `nousresearch.com` (different case, no space) — the domain is left **verbatim**.

Result: **every Anthropic OAuth request from Hermes ships the raw domain `nousresearch.com`** inside the system prompt, unless the user has disabled skills/help guidance somehow (it's unconditional). This mirrors exactly the OpenCode incident pattern (aggressive URL/branding removal was the fix there) but Hermes has no such paragraph-level stripping — only substring replace of 4 fixed literals.

### Other unsanitized brand leaks confirmed in same request path
- Bare "Hermes" (not "Hermes Agent") in `STEER_CHANNEL_NOTE` (`prompt_builder.py:642`), active-profile hint (`agent/system_prompt.py:397,406`), remote-backend environment hints (`prompt_builder.py:1182,1193`), `PLATFORM_HINTS["tui"/"desktop"/"webui"]` (`prompt_builder.py:765,775,890`).
- Literal `~/.hermes` paths, `$HERMES_KANBAN_TASK`/`$HERMES_KANBAN_WORKSPACE` env vars, `hermes kanban`, `hermes profile list`, `hermes setup`, `hermes config set`, `hermes tools`, `hermes status` CLI-command literals across KANBAN_GUIDANCE, Nous-subscription block, and skills-index intro.
- Tool **descriptions** are never touched by the OAuth sanitizer (only `system` text blocks and tool **names** are processed) — live "Hermes"/"Hermes Agent" branding found in `tools/browser_tool.py:1973`, `tools/file_tools.py:1971,2022`, `tools/mcp_oauth.py:34,1082`.
- Skills content, memory content, and user AGENTS.md/SOUL.md context-file content pass through the same 4-string filter only — anything not literally matching one of those 4 strings ships unsanitized.

## Existing classifier awareness (tool-name vector, GH-25255)

Hermes DOES have documented, empirically-verified handling for a different vector: single-underscore `mcp_` tool names. `agent/anthropic_adapter.py:2594-2611`:

> "Anthropic's subscription/OAuth billing classifier treats a single-underscore `mcp_` tool name as a third-party-app fingerprint and rejects the request with HTTP 400 'Third-party apps now draw from extra usage, not plan limits' (verified empirically...). GH-25255."

Full test coverage: `tests/agent/test_anthropic_mcp_prefix_strip.py:1-13` (docstring cites GH-25255 verbatim).

No git commit in this checkout references "extra usage" or "25255" (`git log --all --grep` both return empty) — the fix landed without a matching commit message; evidence lives only in code/test comments.

## Misleading user-facing message (matches user's stated symptom)

`agent/conversation_loop.py:291-306` classifies the Anthropic 400 "out of extra usage" purely as genuine billing exhaustion and tells the user:

> "{provider} reported that your Claude subscription usage is exhausted for {model} (included quota + extra-usage credits)." + "Options: wait for the billing cycle to reset, or add extra usage at https://claude.ai/settings/usage"

`agent/error_classifier.py:118` lists `"out of extra usage"` in `_BILLING_PATTERNS`, causing `agent_runtime_helpers.py:965-983` to auto-rotate the OAuth credential — no code path questions whether the 400 was actually a classifier false-positive triggered by prompt content rather than real quota depletion.

## Files read in full for this investigation
- agent/system_prompt.py (593 lines, full)
- agent/prompt_builder.py (2077 lines, full)
- agent/coding_context.py (887 lines, full)
- agent/anthropic_adapter.py (partial: lines 1-450, 1380-1460, 2400-2719 — sanitizer + OAuth constants + header spoofing)
- agent/agent_runtime_helpers.py (partial: 850-989 — credential recovery/billing classification)
- agent/conversation_loop.py (partial: 260-330 — billing message text)
- agent/context_compressor.py (partial: 1-90 — quota markers)
- agent/error_classifier.py (partial: 55-129, 685-740 — billing patterns, long-context tier)
- tests/agent/test_anthropic_mcp_prefix_strip.py (partial: 1-20, docstring + test structure)

## Open questions / next steps
1. Not verified whether nousresearch.com domain string itself triggers the classifier (only tool-name shape is empirically confirmed in-repo).
2. agent/message_sanitization.py only partially read (lines 1-80 of 477) — remaining ~400 lines not inspected for additional OAuth-relevant logic.
3. convert_tools_to_anthropic() (anthropic_adapter.py:2553) not read in full — unclear if it independently sanitizes tool descriptions.
