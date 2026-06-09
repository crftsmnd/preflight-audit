# Preflight Audit

Run this skill **before** starting a new implementation task. It prevents the three mistakes from the tg-gateway incident:
1. Skipping existing solutions because they looked irrelevant
2. Choosing heavy SDKs when lightweight alternatives work better
3. Failing to persist constraints back to memory

Additionally, it now prevents the **root cause**: agent blind spots in problem-solving approach.

## Core Principles

| # | Principle | Why |
|---|-----------|-----|
| 1 | **Check first, build second** | Installed skills may already solve your problem — even with empty descriptions |
| 2 | **Lightweight over feature-rich** | On proot Alpine, import time & RAM matter more than API elegance |
| 3 | **Close the feedback loop** | Every constraint discovered during a project must reach long-term memory |
| 4 | **Platform-aware dependency choice** | SDKs that work on desktop may be unusable on mobile Alpine |
| 5 | **Constraint-first, not solution-first** | List platform limits before proposing ANY architecture |
| 6 | **Dirty workaround over clean architecture** | Always check for the 10-line version before committing to a full build |
| 7 | **Strategy shift after 3 failures** | If the same approach fails 3+ times, do something fundamentally different |

## Commands

### Phase 1 — Audit Existing Assets

```
preflight.py audit <description>
```

Searches installed skills, long-term memory, short-term memory, and workspace for existing solutions and known constraints. Outputs a structured report.

**Agent consumption:** `preflight.py audit <desc> --json` returns structured JSON.

### Phase 0 — Constraint-First Thinking

```
preflight.py constraints <platform>
```

Surfaces hard platform constraints **before** you start designing. Available platforms:
- `android` — Android OS process lifetime, RAM, signal handling limits
- `alpine` — musl libc, memory pressure, proot limitations
- `server` — cloud machine capabilities (unrestricted)
- `python` — GIL, startup time, import costs
- `kotlin` — JVM warmup, memory, Gradle build times
- `android-kotlin` — Combined Android + Kotlin constraints

Use `preflight.py constraints auto` to see all platforms. This step prevents proposing architectures that can't survive the target environment.

### Phase 0b — Workaround-First Thinking

```
preflight.py hack <goal>
```

Searches for dirty workarounds and minimal viable approaches **before** committing to a full architecture. This is the fix for the root problem: agents jumping to complex solutions when simpler ones exist.

Categories include: telegram bot hacks, persistence workarounds, build shortcuts, API free-tier patterns, and MCP tricks.

### Phase 2 — Dependency Decision

```
preflight.py check-dep <package-name>
```

Tests if a Python package imports fast enough on this platform.

### Phase 3 — Close the Loop

```
preflight.py close-loop [--interim "constraint text"]
```

Records a discovered constraint to long-term memory. **Automatically generates an AGENTS.md rule** if the constraint matches known patterns (Android, Telegram, OOM, workarounds, etc.).

Use `--interim` during a project (before it's complete) to log mid-project realizations.

### Phase 4 — Stuck Detection

```
preflight.py frustrated
```

Call this when you've attempted the same task 3+ times. Forces a strategy shift instead of repeating the same approach. Provides a checklist of fundamentally different approaches to try.

## Agent Problem-Solving Protocol

This section encodes the **real lesson** from the tg-gateway incident — the problem wasn't technical, it was about **how the agent approaches problems**.

### Before starting any project:

1. **Run:** `preflight.py audit "<project>"` — what already exists?
2. **Run:** `preflight.py constraints <platform>` — what are the hard limits?
3. **Run:** `preflight.py hack "<goal>"` — what's the dirty workaround?
4. **Ask:** "What assumptions am I making?" — question every default choice
5. **Ask:** "What's the 10-line version?" — prove the concept before architecting

### When stuck:

1. **Run:** `preflight.py frustrated` — forces strategy shift
2. **List which approaches you've tried** — if they're all similar, do the opposite
3. **Check closed loops:** `preflight.py close-loop` stores past failures in `.closed-loops.json`
4. **Question your assumptions** — the problem is often your starting premise, not the code

### After any project:

1. **Run:** `preflight.py close-loop "discovered constraint"`
2. This logs to memory AND auto-generates an AGENTS.md rule
3. The rule prevents the SAME blind spot from recurring

## Trigger Examples

| User says | Trigger |
|-----------|---------|
| "Build a Telegram bot" | Phase 1: audit → hacks → constraints |
| "I've tried 4 times and nothing works" | Phase 4: frustrated mode |
| "Why did that fail?" | Phase 3: close-loop |
| "We should remember this" | Phase 3: close-loop → generates AGENTS.md rule |
| "Let's use library Y" | Phase 2: check-dep |
| "What works for this?" | Phase 0b: hack search |

## Scripts

- `scripts/preflight.py` — CLI tool for all phases

## Failure Handling

- If `preflight.py audit` fails (missing deps), fall back to manual search
- If no existing solution found, proceed with Phase 0b (hack search) before building
- If stuck, use `frustrated` command before attempting same approach again
- If constraint discovered during implementation, still log with `close-loop --interim`
