#!/usr/bin/env python3
"""preflight.py — Pre-project audit tool for Omnibot.

Usage:
    python preflight.py audit <description>
        Runs a full preflight audit: searches skills, memory, and workspace
        for pre-existing solutions and known constraints.

    python preflight.py hack <goal>
        Searches for dirty workarounds and minimal viable approaches
        before committing to a full architecture.

    python preflight.py constraints <platform>
        Surfaces known platform constraints and limits for android, alpine,
        server, python, kotlin, etc.

    python preflight.py close-loop [--interim "constraint text"]
        Records a discovered constraint to long-term memory.
        Use --interim during a project (before it's complete).
        Also generates an actionable AGENTS.md rule if applicable.

    python preflight.py check-dep <package-name>
        Tests if a Python package import is fast enough on this platform.

    python preflight.py frustrated
        Called when you've attempted the same task 3+ times.
        Forces a strategy shift instead of repeating the same approach.

    python preflight.py list-constraints
        List available platform constraint sets.

    python preflight.py list-hacks
        List available hack categories.
"""

import json
import os
import re
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

SKILLS_ROOT = Path("/root/.openclaw-autoclaw/skills")
MEMORY_FILE = Path("/root/.openclaw-autoclaw/workspace") / "MEMORY.md"
SHORT_MEM_DIR = Path("/root/.openclaw-autoclaw/workspace") / "memory"
WORKSPACE = Path("/root/.openclaw-autoclaw/workspace")
AGENTS_FILE = Path("/root/.openclaw-autoclaw/workspace") / "AGENTS.md"
TOOLS_FILE = Path("/root/.openclaw-autoclaw/workspace") / "TOOLS.md"
RETRY_DB = SHORT_MEM_DIR / ".retry-tracker.json"
CLOSED_LOOPS_DB = SHORT_MEM_DIR / ".closed-loops.json"
HACK_DB_FILE = SHORT_MEM_DIR / ".hack-tracker.json"


# Platform Constraints Database
PLATFORM_CONSTRAINTS = {
    "android": [
        ("Process Lifetime", "Android kills background processes aggressively. Use Foreground Service with persistent notification."),
        ("RAM Limit", "Android systems kill apps under memory pressure. Keep daemon RAM under 50MB."),
        ("Signal Handling", "SIGKILL cannot be caught. No SIGTERM/SIGHUP in standard Android process model."),
        ("Bad Deaths", "Processes killed by OOM don't get cleanup hooks. Expect unclean shutdowns."),
        ("Python on Android", "Python via Termux/Pydroid has limited stdlib. Some modules (curses, tkinter) unavailable."),
        ("Threading", "Android UI thread != main thread in Python. Async work needs separate thread."),
        ("File System", "App-specific storage on /data. External SD unreliable. Prefer app-internal paths."),
        ("Background Execution", "JobScheduler / WorkManager for reliable bg work. Don't rely on persistent scripts."),
        ("Network", "VPN/Doze mode can delay connections. Wi-Fi to mobile handoff causes socket drops."),
        ("Notification Channels", "Android 8+ requires notification channels for Foreground Services."),
    ],
    "alpine": [
        ("Musl libc", "Alpine uses musl, not glibc. Some Python wheels (numpy, pandas) break or need compilation."),
        ("Memory Pressure", "proot Alpine on Android has ~256-512MB RAM. JVM/GraalVM are heavy; prefer raw compiled code."),
        ("Process Spawning", "fork/exec is slow on proot. Avoid spawning frequent subprocesses."),
        ("No systemd", "No service manager. Long-running processes rely on tmux/screen or terminal lifetime."),
        ("File Descriptors", "Limited FDs in proot (default 1024). API clients with many connections hit this."),
        ("Kernel Access", "No access to real kernel syscalls. Some features (pivot_root, cgroups) unavailable."),
        ("Python Performance", "Startup time ~200-500ms. Prefer long-lived processes over frequent CLI invocations."),
        ("Compilation", "gcc/clang present but linking is slow. Prefer pip prebuilt wheels when available."),
        ("Network", "TCP works but raw sockets / ICMP may be restricted by Android's VPN layer."),
        ("Persistence", "No daemon management. tmux session as daemon — restorable but not auto-recoverable."),
    ],
    "server": [
        ("Uptime", "This is a cloud machine. Long-running processes are safe. No Android kill risks."),
        ("Memory", "Typically 1-4GB. Python/web apps are fine. Heavy ML inference may struggle."),
        ("Disk", "SSD-backed. I/O is fast. /tmp is RAM-backed."),
        ("Network", "Full TCP/UDP with public IP or NAT. Ports may be restricted by cloud firewall."),
        ("Process", "systemd or Docker available. Persistent daemon lifecycle is reliable."),
        ("Python", "Full glibc Python. All wheels work. No compilation issues."),
    ],
    "python": [
        ("GIL", "Python's GIL prevents true parallelism. Use multiprocessing for CPU-bound work."),
        ("Startup Time", "Python CLI startup is ~100-300ms. Not suitable for latency-sensitive frequent invocations."),
        ("RAM per Process", "~10-50MB for a long-running Python daemon. 100-200MB for ML/LLM work."),
        ("Import Costs", "Some packages (numpy, pandas) take 1-3s to import. Heavy for CLI tools."),
        ("Async", "asyncio works well for I/O-bound work. Use aiohttp/httpx for async HTTP."),
        ("Packaging", "pip install works. uv/pipx for app-level installs. Avoid conda on Alpine."),
    ],
    "kotlin": [
        ("JVM Warmup", "Kotlin/JVM takes 1-3s to start. Use Kotlin/Native for CLI or keep JVM persistent."),
        ("Memory", "JVM base ~50-100MB. Heavy for CLI tools. Better for long-running services."),
        ("Android", "Kotlin is first-class on Android. Foreground Services, Coroutines, OkHttp all work."),
        ("Gradle", "Full builds are slow (2-10 min). Prefer incremental builds for iteration."),
        ("Cross-Platform", "Kotlin Multiplatform for iOS/Android sharing. Kotlin/Native for native binaries."),
    ],
    "android-kotlin": [
        ("Build Time", "Gradle assembleDebug takes 2-10 minutes. CI build takes 5-15 minutes."),
        ("APK Size", "Debug APK ~20-50MB. Release APK with ProGuard ~8-15MB."),
        ("Foreground Service", "Requires CHANNEL_ID + NOTIFICATION. Must survive app backgrounding."),
        ("OkHttp", "Use for HTTP/API calls. Handles connection pooling, retries natively."),
        ("Coroutines", "Use for async work. Structured concurrency prevents leaks."),
        ("Ktor", "Lightweight server. Works on Android for localhost HTTP (MCP server pattern)."),
        ("SharedPreferences / DataStore", "For small config. Room/SQLite for structured data."),
        ("MethodChannel", "Flutter to Kotlin bridge. Use for config flows, not high-frequency data."),
        ("Lifecycle", "Service lifecycle bound to app process. Bind to Application context for app-lifetime."),
    ],
}

# Hack/Workaround Database
DEFAULT_HACKS = {
    "telegram": [
        ("Long-polling via HTTP", "No websocket needed. Use GET getUpdates with offset parameter."),
        ("Inline webhook", "Drop-in webhook via ngrok for development. SetWebhook + local server."),
        ("PHP fallback", "Even cheap shared hosting runs Telegram bots. PHP can do it with curl."),
        ("AWS Lambda", "Serverless works. Stateless bot API handler fits Lambda perfectly."),
        ("Cloudflare Workers", "64MB RAM, 30s execution. Enough for simple bots. Free tier."),
        ("Gist-based config", "Store bot config as a Gist. Bot fetches it on startup. No DB needed."),
        ("SQLite instead of PostgreSQL", "Single file, zero config, enough for most bots."),
    ],
    "persistence": [
        ("tmux session", "Simplest daemon on proot Alpine. Attach/detach. Survives terminal close."),
        ("cron + healthcheck", "cron runs bot every 5 min. Healthcheck restarts if dead. Crude but works."),
        ("pm2", "Node.js process manager. Auto-restart. Works if Node is available."),
        ("systemd --user", "If systemd is available. Good for persistent services."),
        ("Foreground Service (Android)", "Most reliable on Android. Survives backgrounding. Shows notification."),
        ("termux-services", "If using Termux proper (not proot). Service management."),
        ("Android JobScheduler", "Periodic work. Not real-time but guaranteed to run eventually."),
    ],
    "build": [
        ("GitHub Actions CI", "Free CI for open-source repos. Build APK on push. Download artifact."),
        ("./gradlew assembleDebug", "Fast build. No signing needed for dev testing."),
        ("Incremental builds", "Change only one module. Use :app:assembleDebug if only app changed."),
        ("Copy APK via SCP/rsync", "Skip Play Store for dev. Direct side-load."),
        ("ngrok", "Expose localhost to internet for webhook testing. Free tier works."),
    ],
    "api": [
        ("Free tier exhaustion pattern", "Many APIs offer free tiers. Rotate API keys if hitting limits."),
        ("Cache at every level", "filesystem cache to memory cache to API fallback. Save money."),
        ("DuckDuckGo instead of Google API", "ddg-search is free, no key, no rate limit (for moderate use)."),
        ("MCP servers as free API bridge", "Use MCP tool calls instead of direct API integration."),
    ],
    "mcp": [
        ("MCP via Ktor localhost", "Lightweight HTTP server on Android for agent to service communication."),
        ("MCP stdio transport", "Simplest for CLI tools. Pipe JSON-RPC over stdin/stdout."),
        ("MCP over SSE", "For remote connections. Server-Sent Events as transport."),
    ],
}

# Utilities
def blue(s): return f"\033[94m{s}\033[0m"
def green(s): return f"\033[92m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def red(s): return f"\033[91m{s}\033[0m"
def bold(s): return f"\033[1m{s}\033[0m"

def search_skills(keywords):
    found = []
    if not SKILLS_ROOT.exists():
        return found
    for skill_dir in sorted(SKILLS_ROOT.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        text = skill_file.read_text(errors="replace")
        fm = {}
        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if m:
            for line in m.group(1).split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip()
        name = fm.get("name", skill_dir.name)
        desc = fm.get("description", "")
        haystack = f"{name} {desc} {skill_dir.name}".lower()
        if any(kw.lower() in haystack for kw in keywords):
            body = re.sub(r"^---.*?---", "", text, flags=re.DOTALL).strip()
            context = body[:300].replace("\n", " ").strip()
            found.append({
                "id": skill_dir.name,
                "name": name,
                "description": desc[:200],
                "preview": context[:200],
                "path": str(skill_file),
                "has_scripts": (skill_dir / "scripts").exists(),
            })
    return found

def search_memory(keywords):
    results = []
    if MEMORY_FILE.exists():
        for kw in keywords:
            for line in MEMORY_FILE.read_text(errors="replace").split("\n"):
                if kw.lower() in line.lower():
                    s = line.strip()
                    if s and s not in results:
                        results.append(s)
    if SHORT_MEM_DIR.exists():
        now = datetime.now(timezone.utc)
        for f in sorted(SHORT_MEM_DIR.iterdir(), reverse=True):
            if not f.name.endswith(".md"):
                continue
            try:
                ts = datetime.strptime(f.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if (now - ts).days > 7:
                    continue
            except ValueError:
                continue
            for kw in keywords:
                for line in f.read_text(errors="replace").split("\n"):
                    if kw.lower() in line.lower():
                        s = line.strip()
                        if s and s not in results:
                            results.append(f"[{f.stem}] {s}")
    return results

def search_workspace(keywords, limit=15):
    results = []
    if not WORKSPACE.exists():
        return results
    count = 0
    for f in sorted(WORKSPACE.rglob("*"))[:500]:
        if count >= limit:
            break
        if not f.is_file() or f.name.startswith("."):
            continue
        rel = str(f.relative_to(WORKSPACE))
        if any(kw.lower() in rel.lower() for kw in keywords):
            results.append(rel)
            count += 1
    return results

def load_json_db(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}

def save_json_db(path, db):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(db, indent=2))

def load_hacks():
    db = {}
    if HACK_DB_FILE.exists():
        try:
            db = json.loads(HACK_DB_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    for cat, hacks in DEFAULT_HACKS.items():
        if cat not in db:
            db[cat] = hacks
        else:
            existing = {h[0] for h in db[cat]}
            for h in hacks:
                if h[0] not in existing:
                    db[cat].append(h)
    return db


async def cmd_audit(query, json_mode=False):
    keywords = [w for w in re.sub(r"[^a-zA-Z0-9 ]", " ", query).lower().split() if len(w) > 1]
    result = {
        "query": query, "keywords": keywords,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skills": [], "constraints": [], "workspace_files": [], "closed_loops": [],
        "recommendation": "proceed",
    }

    skills = search_skills(keywords)
    mem_results = search_memory(keywords)
    files = search_workspace(keywords)

    # Check closed loops
    loops = load_json_db(CLOSED_LOOPS_DB)
    relevant_loops = []
    for tag, entries in loops.items():
        if any(kw.lower() in tag.lower() for kw in keywords):
            relevant_loops.extend(entries)

    if json_mode:
        result["skills"] = skills
        result["constraints"] = mem_results
        result["workspace_files"] = files
        result["closed_loops"] = relevant_loops
        return result

    print(f"\n{bold('???')} Running audit for: {query}")
    print(f"   Keywords: {keywords}")
    print(f"\n{blue('→ Searching installed skills...')}")
    if skills:
        print(f"  {green(f'Found {len(skills)} skill(s):')}")
        for s in skills:
            print(f"    {green('?')} {blue(s['name'])}{' + scripts' if s['has_scripts'] else ''}")
            if s['description']:
                print(f"       {s['description']}")
            print(f"       {s['path']}")
    else:
        print(f"  {yellow('No matching skills found.')}")

    print(f"\n{blue('→ Searching memory...')}")
    if mem_results:
        for m in mem_results:
            print(f"  {yellow('?')} {m}")
    else:
        print(f"  {yellow('No matching constraints in memory.')}")

    print(f"\n{blue('→ Searching workspace files...')}")
    if files:
        for f in files[:12]:
            print(f"  {green('?')} {f}")
        if len(files) > 12:
            print(f"  ... and {len(files) - 12} more")
    else:
        print(f"  {yellow('No matching workspace files.')}")

    if relevant_loops:
        print(f"\n{red('? Closed-Loop Patterns to Watch')}")
        for entry in relevant_loops[-3:]:
            e = entry if isinstance(entry, dict) else {"constraint": entry}
            print(f"  {red('!')} {e.get('constraint', entry)}")

    print(f"\n{bold('=== Preflight Audit Report ===')}")
    if skills:
        print(f"{green('? Read the existing skill(s) above before building!')}")
        print(f"    Even if the description seems unrelated, read the full code.")
    else:
        print(f"{yellow('? No pre-existing solution found. Proceed with Phase 2.')}")
        cmd_hint = 'preflight.py hack "' + query + '"'
        print(f"    Consider running: {bold(cmd_hint)}")
        print(f"    And: {bold('preflight.py constraints auto')}")
    print(f"{bold('=== End Report ===')}")
    return None


def cmd_hack(goal, json_mode=False):
    keywords = [w.lower() for w in re.sub(r"[^a-zA-Z0-9 ]", " ", goal).split() if len(w) > 1]
    hacks = load_hacks()
    found = []
    seen = set()
    for cat, entries in hacks.items():
        for title, detail in entries:
            if title in seen:
                continue
            hack_text = f"{title} {detail}".lower()
            if any(kw in cat.lower() or kw in hack_text for kw in keywords):
                found.append({"title": title, "workaround": detail, "category": cat})
                seen.add(title)

    mem = search_memory(keywords)

    if json_mode:
        return {"goal": goal, "keywords": keywords, "hacks": found, "memory_hits": mem}

    print(f"\n{bold('? Hack/Workaround Search: ' + goal)}")
    print(f"  Looking for dirty workarounds — what works NOW?")
    if found:
        print(f"\n{green(f'Found {len(found)} hack(s):')}")
        for h in found:
            print(f"  {green('?')} {blue(h['title'])} [{h['category']}]")
            print(f"    {h['workaround']}")
    else:
        print(f"\n{yellow('No workarounds found in database.')}")

    if mem:
        print(f"\n{blue('Memory hits:')}")
        for m in mem[:5]:
            print(f"  {yellow('?')} {m}")

    print(f"\n{yellow(bold('? Hack Check'))}")
    print(f"  1. Can I solve this with a curl command?")
    print(f"  2. What's the minimum code that proves the concept?")
    print(f"  3. Is there an MCP tool or existing skill that already does this?")
    return None


def cmd_constraints(platform, json_mode=False):
    platform = platform.lower().strip()
    if platform in ("auto", "all"):
        all_data = {}
        for pf, constraints in sorted(PLATFORM_CONSTRAINTS.items()):
            all_data[pf] = [{"title": c[0], "detail": c[1]} for c in constraints]
        if json_mode:
            return all_data
        print(f"\n{bold('=== All Platform Constraints ===')}")
        for pf, constraints in sorted(PLATFORM_CONSTRAINTS.items()):
            print(f"\n{bold(pf.upper())}")
            for title, detail in constraints:
                print(f"  {red('?')} {blue(title)}")
                print(f"    {detail}")
        print(f"\n{bold('=== End ===')}")
        return None

    if platform not in PLATFORM_CONSTRAINTS:
        matches = [k for k in PLATFORM_CONSTRAINTS if platform in k]
        if not matches:
            if json_mode:
                return {"error": f"Unknown: {platform}", "available": list(PLATFORM_CONSTRAINTS.keys())}
            print(f"{red('Unknown platform:')} {platform}")
            print(f"  Available: {', '.join(PLATFORM_CONSTRAINTS.keys())}")
            return None
        platform = matches[0]

    constraints = PLATFORM_CONSTRAINTS[platform]
    if json_mode:
        return {"platform": platform, "constraints": [{"title": c[0], "detail": c[1]} for c in constraints]}

    print(f"\n{bold(f'? Platform Constraints: {platform}')}")
    print(f"  Review before designing your architecture.\n")
    for title, detail in constraints:
        print(f"  {red('?')} {blue(title)}")
        print(f"    {detail}")
    return None


async def cmd_close_loop(constraint_text=None, interim=False, gen_rule=True):
    loops = load_json_db(CLOSED_LOOPS_DB)
    constraint_lower = (constraint_text or "").lower()

    categories = []
    if any(kw in constraint_lower for kw in ["android", "foreground service", "notification", "alpine", "proot"]):
        categories.append("platform")
    if any(kw in constraint_lower for kw in ["python", "kotlin", "java", "gradle", "build"]):
        categories.append("language/build")
    if any(kw in constraint_lower for kw in ["api", "telegram", "http", "mcp", "webhook"]):
        categories.append("integration")
    if any(kw in constraint_lower for kw in ["memory", "ram", "oom", "kill", "process"]):
        categories.append("resource")
    if any(kw in constraint_lower for kw in ["workaround", "hack", "simpler", "minimal"]):
        categories.append("approach")
    if not categories:
        categories = ["uncategorized"]

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "constraint": constraint_text or "(no description)",
        "categories": categories,
        "interim": interim,
    }

    for cat in categories:
        if cat not in loops:
            loops[cat] = []
        loops[cat].append(record)
        loops[cat] = loops[cat][-50:]
    save_json_db(CLOSED_LOOPS_DB, loops)

    print(f"\n{bold('? Closed Loop Recorded')}")
    print(f"  Constraint: {record['constraint']}")
    print(f"  Categories: {', '.join(categories)}")
    print(f"  Interim: {record['interim']}")

    # Auto-generate AGENTS.md rule
    if gen_rule and constraint_text and AGENTS_FILE.exists():
        rules_db = []
        if "python" in constraint_lower and "android" in constraint_lower:
            rules_db.append(("Python on Android is fragile", "When building a long-running service for Android, default to Kotlin over Python. Python via Termux/proot is unreliable due to OOM kills, signal handling limits, and musl libc issues."))
        if ("process" in constraint_lower or "kill" in constraint_lower or "oom" in constraint_lower):
            rules_db.append(("Always use Android Foreground Service for persistent daemons", "Android kills background processes aggressively. Always use a Foreground Service (with persistent notification) for any daemon that must survive backgrounding."))
        if "telegram" in constraint_lower:
            rules_db.append(("Check existing skills before building Telegram bots", "Before building a Telegram bot from scratch, run `preflight.py audit 'telegram bot'` to check for existing gateway implementations."))
        if "workaround" in constraint_lower or "hack" in constraint_lower:
            rules_db.append(("Check for workarounds before committing to architecture", "Before committing to a full architecture, run `preflight.py hack '<goal>'` to search for dirty workarounds."))
        if "dependency" in constraint_lower or "sdk" in constraint_lower:
            rules_db.append(("Prefer raw HTTP over heavy SDK wrappers", "On constrained platforms, prefer raw HTTP clients (OkHttp, httpx) over SDK wrappers. Most API integrations only need 3-5 endpoints."))

        if rules_db:
            summary, rule_text = rules_db[0]
            agents_text = AGENTS_FILE.read_text()
            if summary not in agents_text:
                agents_text += f"\n\n## Auto-Rule ({datetime.now().strftime('%Y-%m-%d')})\n"
                agents_text += f"**{summary}**\n{rule_text}\n"
                AGENTS_FILE.write_text(agents_text)
                print(f"\n{green('? AGENTS.md rule generated:')} {summary}")

    # Log to daily memory
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily = SHORT_MEM_DIR / f"{date_str}.md"
    daily.parent.mkdir(parents=True, exist_ok=True)
    entry = f"[{datetime.now(timezone.utc).strftime('%H:%M UTC')}] CLOSED-LOOP: {record['constraint']} | Cats: {', '.join(categories)} | Interim: {record['interim']}"
    if daily.exists():
        text = daily.read_text()
        if "## Closed Loop" not in text:
            text += "\n## Closed Loop\n"
        text += f"- {entry}\n"
    else:
        text = f"# {date_str}\n\n## Closed Loop\n- {entry}\n"
    daily.write_text(text)
    print(f"  Logged to: {daily}")
    return None


def cmd_frustrated(json_mode=False):
    if json_mode:
        return {"frustrated": True, "recommendation": "STRATEGY_SHIFT"}

    print(f"\n{bold(red('??? FRUSTRATED MODE'))}")
    print(f"  {red('Stop iterating. Switch strategy entirely.')}")
    print(f"\n{blue(bold('Checklist:'))}")
    print(f"  1. {green('Step away for 5 minutes')}")
    print("  2. " + green("Run: preflight.py hack <goal>"))
    print(f"  3. {green('Run: preflight.py constraints auto')}")
    print(f"  4. {green('List 3 approaches tried and why each failed')}")
    print(f"  5. {green('If all 3 were similar, try the OPPOSITE approach')}")
    print(f"\n{red(bold('Rules:'))}")
    print(f"  - 3+ same approach attempts -> switch strategy entirely")
    print(f"  - If building complex -> check for 10-line version")
    print(f"  - If designing architecture -> ask 'what workaround?'")
    print(f"  - If using a library -> check raw HTTP")
    print(f"\n{red(bold('Run now:'))}")
    print("  " + yellow("Run: preflight.py hack <goal>"))
    print(f"  {yellow('preflight.py constraints auto')}")
    print(f"\n{bold('=== End Frustrated ===')}")
    return None


def cmd_check_dep(package):
    print(f"\n{bold('? Checking dependency: ' + package)}")
    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", f"import time,sys;t0=time.time();__import__('{package}');print(f'Import: {{time.time()-t0:.3f}}s')"],
            capture_output=True, text=True, timeout=30
        )
        dur = time.time() - start
        if proc.returncode == 0:
            out = proc.stdout.strip()
            print(f"  {out}")
            print(f"  Total: {dur:.3f}s")
            if "Import:" in out:
                t = float(out.split(":")[1].strip().rstrip("s"))
                if t >= 1:
                    print(f"\n{yellow('? Consider a lighter alternative')}")
        else:
            print(f"  {red('Failed:')} {proc.stderr[:300]}")
    except subprocess.TimeoutExpired:
        print(f"  {red('Timed out after 30s - too slow.')}")
    except Exception as e:
        print(f"  {red(f'Error: {e}')}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "audit":
        import asyncio
        query = " ".join([a for a in sys.argv[2:] if not a.startswith("--")])
        json_mode = "--json" in sys.argv
        if not query:
            query = input("What are you building? ")
        result = asyncio.run(cmd_audit(query, json_mode=json_mode))
        if json_mode and result:
            print(json.dumps(result, indent=2))

    elif cmd == "hack":
        goal = " ".join([a for a in sys.argv[2:] if not a.startswith("--")])
        json_mode = "--json" in sys.argv
        if not goal:
            goal = input("What's the goal? ")
        cmd_hack(goal, json_mode=json_mode)

    elif cmd == "constraints":
        platform = sys.argv[2] if len(sys.argv) > 2 else "auto"
        json_mode = "--json" in sys.argv
        result = cmd_constraints(platform, json_mode=json_mode)
        if json_mode and result:
            print(json.dumps(result, indent=2))

    elif cmd == "close-loop":
        import asyncio
        interim = "--interim" in sys.argv
        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        text = " ".join(args) if args else None
        asyncio.run(cmd_close_loop(text, interim=interim))

    elif cmd == "frustrated":
        json_mode = "--json" in sys.argv
        cmd_frustrated(json_mode=json_mode)

    elif cmd == "check-dep":
        if len(sys.argv) < 3:
            print("Usage: preflight.py check-dep <package-name>")
            sys.exit(1)
        cmd_check_dep(sys.argv[2])

    elif cmd == "list-constraints":
        print(f"Platforms: {', '.join(PLATFORM_CONSTRAINTS.keys())}")

    elif cmd == "list-hacks":
        hacks = load_hacks()
        for cat, entries in hacks.items():
            print(f"\n{blue(f'[{cat}]')} ({len(entries)} hacks)")
            for t, d in entries[:5]:
                print(f"  {green('?')} {t}")

    else:
        print(f"Unknown: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
