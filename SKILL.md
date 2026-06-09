---
name: preflight-audit
description: Systematic pre-project audit to avoid repeating past mistakes. Use before starting a new project, building a new skill, or choosing a technical approach — especially on Omnibot's constrained Alpine/Android runtime. Encodes lessons from the tg-gateway incident (existing solution missed, heavy SDK vs raw HTTP, unclosed feedback loop).
---

# Preflight Audit

Run this skill **before** starting a new implementation task. It prevents the three mistakes from the tg-gateway incident:
1. Skipping existing solutions because they looked irrelevant
2. Choosing heavy SDKs when lightweight alternatives work better
3. Failing to persist constraints back to memory

## Core Principles

| # | Principle | Why |
|---|-----------|-----|
| 1 | **Check first, build second** | Installed skills may already solve your problem — even with empty descriptions |
| 2 | **Lightweight over feature-rich** | On proot Alpine, import time & RAM matter more than API elegance |
| 3 | **Close the feedback loop** | Every constraint discovered during a project must reach long-term memory |
| 4 | **Platform-aware dependency choice** | SDKs that work on desktop may be unusable on mobile Alpine |

## Preflight Workflow (mandatory before new projects)

### Phase 1 — Audit Existing Assets

Run `preflight.py audit <project-description>` with a short description of what you're building. This:

- **Searches installed skills** by keyword — reads SKILL.md bodies when hits are found, even if the index description is empty
- **Searches long-term memory** for platform constraints or prior failures
- **Searches workspace files** for pre-existing implementations
- **Checks short-term memory** (last 7 days) for related context

Output: a structured report with three sections:
- ✅ **Likely existing solution** (read the code before building)
- ⚠️ **Known constraints** (import times, process lifetime, platform limits)
- 📋 **Fresh implementation needed** (no pre-existing solution found)

### Phase 2 — Dependency Decision

For any library/SDK dependency, ask:

1. **Can this be done with raw HTTP?** → Prefer `httpx` over SDK wrappers
2. **Does this library import quickly on Alpine?** → Time `import` in a terminal before committing
3. **Is there a stdlib-only alternative?** → Prefer zero dependencies
4. **Is the SDK's API surface actually needed?** → Most Telegram/API projects only need 3-5 endpoints

If a heavy SDK is the only option: log the import time to memory and verify it works before building the rest.

### Phase 3 — Close the Loop

After any project:

- Run `preflight.py close-loop` to persist any new constraints discovered during implementation
- This records: what was attempted, what failed, what worked instead, and the root constraint
- The constraint is upserted to long-term memory with a date stamp

## Trigger Examples

| User says | Trigger |
|-----------|---------|
| "Build a Telegram bot" | Phase 1: `preflight.py audit "telegram bot"` → finds tg-gateway already exists |
| "Generate images with API X" | Phase 1: checks if codex-image / gpt-image-gen / nano-banana already installed |
| "Let's use library Y" | Phase 2: check import speed, check if raw HTTP suffices |
| "Why did that fail?" | Phase 3: log the failure and constraint |
| "We should remember this for next time" | Phase 3: close the loop |

## Scripts

- `scripts/preflight.py` — CLI tool for Phase 1 (audit) and Phase 3 (close-loop)

## Failure Handling

- If `preflight.py audit` fails (missing deps), fall back to manual search using `skills_list`, `memory_search`, `file_search`
- If no existing solution is found after audit, proceed with Phase 2 (dependency decision) before building
- If a constraint is discovered during implementation but the project isn't finished yet, still log it with `preflight.py close-loop --interim "constraint description"`
