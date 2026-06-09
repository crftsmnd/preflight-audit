#!/usr/bin/env python3
"""preflight.py — Pre-project audit tool for Omnibot.

Usage:
    python preflight.py audit <description>
        Runs a full preflight audit: searches skills, memory, and workspace
        for pre-existing solutions and known constraints.

    python preflight.py close-loop [--interim "constraint text"]
        Records a discovered constraint to long-term memory.
        Use --interim during a project (before it's complete).

    python preflight.py check-dep <package-name>
        Tests if a Python package import is fast enough on this platform.
"""

import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

SKILLS_ROOT = Path("/workspace/.omnibot/skills")
MEMORY_FILE = SKILLS_ROOT.parent / "memory" / "MEMORY.md"
SHORT_MEM_DIR = SKILLS_ROOT.parent / "memory" / "short-memories"
WORKSPACE = Path("/workspace")


# ── Utilities ──────────────────────────────────────────────────────────

def blue(s): return f"\033[94m{s}\033[0m"
def green(s): return f"\033[92m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def red(s): return f"\033[91m{s}\033[0m"
def bold(s): return f"\033[1m{s}\033[0m"


def search_skills_index(keywords: list[str]) -> list[dict]:
    """Search installed skills index by keyword matching name, id, or description."""
    found = []
    if not SKILLS_ROOT.exists():
        return found
    for skill_dir in SKILLS_ROOT.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        text = skill_file.read_text(errors="replace")
        # Parse basic frontmatter
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
            # Grab first 150 chars of body for context
            body = re.sub(r"^---.*?---", "", text, flags=re.DOTALL).strip()
            context = body[:300].replace("\n", " ").strip()
            found.append({
                "id": skill_dir.name,
                "name": name,
                "description": desc[:200],
                "body_preview": context + ("..." if len(body) > 300 else ""),
                "path": str(skill_file),
                "has_scripts": (skill_dir / "scripts").exists(),
            })
    return found


def search_long_term_memory(keywords: list[str]) -> list[str]:
    """Search MEMORY.md for constraint lines matching keywords."""
    if not MEMORY_FILE.exists():
        return []
    text = MEMORY_FILE.read_text(errors="replace")
    lines = text.split("\n")
    hits = []
    for line in lines:
        line_s = line.strip()
        if not line_s or line_s.startswith("#"):
            continue
        if any(kw.lower() in line_s.lower() for kw in keywords):
            hits.append(line_s)
    return hits


def search_short_term_memory(keywords: list[str], days: int = 7) -> list[str]:
    """Search recent short-memory files for relevant entries."""
    if not SHORT_MEM_DIR.exists():
        return []
    hits = []
    now = datetime.now()
    for f in sorted(SHORT_MEM_DIR.iterdir(), reverse=True):
        if not f.name.endswith(".md"):
            continue
        text = f.read_text(errors="replace")
        if any(kw.lower() in text.lower() for kw in keywords):
            # Extract bullet points containing keywords
            for line in text.split("\n"):
                line_s = line.strip()
                if any(kw.lower() in line_s.lower() for kw in keywords) and line_s.startswith("-"):
                    hits.append(f"[{f.stem}] {line_s.lstrip('- ')}")
    return hits[:15]


def search_workspace_files(keywords: list[str]) -> list[str]:
    """Quick grep for keywords in workspace files (exclude heavy dirs)."""
    hits = []
    exclude = {".venv", "__pycache__", "node_modules", ".git", ".omnibot"}
    try:
        for root, dirs, files in os.walk(str(WORKSPACE)):
            dirs[:] = [d for d in dirs if d not in exclude]
            for fn in files:
                if not fn.endswith((".py", ".sh", ".md", ".json", ".toml", ".yaml", ".yml")):
                    continue
                fp = Path(root) / fn
                try:
                    text = fp.read_text(errors="replace", encoding="utf-8")
                    if any(kw.lower() in text.lower() for kw in keywords):
                        rel = fp.relative_to(WORKSPACE)
                        hits.append(str(rel))
                except Exception:
                    pass
    except Exception:
        pass
    return hits[:20]


def check_dependency_import_time(package_name: str) -> dict:
    """Measure how long it takes to import a package."""
    code = textwrap.dedent(f"""\
        import time
        start = time.time()
        __import__("{package_name}")
        elapsed = time.time() - start
        print(f"{{elapsed:.3f}}")
    """)
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=60
        )
        elapsed = float(result.stdout.strip())
        return {"name": package_name, "seconds": elapsed, "ok": elapsed < 5.0}
    except Exception as e:
        return {"name": package_name, "seconds": None, "ok": False, "error": str(e)}


def format_report(audit_data: dict) -> str:
    """Pretty-print the audit report."""
    lines = []
    lines.append(bold("═══ Preflight Audit Report ═══"))
    lines.append(f"  Query: {audit_data['query']}")
    lines.append(f"  Time:  {audit_data['timestamp']}")
    lines.append("")

    # Section 1: Existing skills
    skills = audit_data.get("skills", [])
    lines.append(bold("📦 Installed Skills"))
    if skills:
        for s in skills:
            flag = green("✅") if s["has_scripts"] else "📄"
            lines.append(f"  {flag} {blue(s['id'])}")
            lines.append(f"       {s['description'][:120]}")
            lines.append(f"       → {s['path']}")
    else:
        lines.append(yellow("  ⚠️  No matching installed skills found"))
    lines.append("")

    # Section 2: Memory constraints
    memories = audit_data.get("long_term_memory", [])
    short_mem = audit_data.get("short_term_memory", [])
    lines.append(bold("🧠 Known Constraints (from memory)"))
    if memories:
        for m in memories:
            lines.append(f"  ⚠️  {m[:150]}")
    if short_mem:
        for m in short_mem:
            lines.append(f"  📝 {m[:200]}")
    if not memories and not short_mem:
        lines.append(green("  ✅ No known constraints found"))
    lines.append("")

    # Section 3: Workspace files
    wf = audit_data.get("workspace_files", [])
    lines.append(bold("📁 Existing Workspace Files"))
    if wf:
        for f in wf[:10]:
            lines.append(f"  📄 {f}")
        if len(wf) > 10:
            lines.append(f"  ... and {len(wf) - 10} more")
    else:
        lines.append("  (none)")
    lines.append("")

    # Section 4: Recommendation
    lines.append(bold("🎯 Recommendation"))
    if skills:
        lines.append(green("  → Read the existing skill(s) above before building!"))
        lines.append("    Even if the description seems unrelated, read the full code.")
    else:
        lines.append(yellow("  → No pre-existing skill found. Proceed with Phase 2 (dependency decision)."))
    lines.append("")
    lines.append(bold("═══ End Report ═══"))
    return "\n".join(lines)


# ── Commands ───────────────────────────────────────────────────────────

def cmd_audit(args: list[str]):
    query = " ".join(args) if args else input("Describe what you're building: ")
    keywords = [kw.strip().lower() for kw in re.split(r"[\s,;]+", query) if len(kw.strip()) > 2]

    print(bold(f"\n🔍 Running audit for: \"{query}\"\n"))
    print(f"   Keywords: {keywords}\n")

    # Phase 1-a: Search installed skills
    print(blue("→ Searching installed skills..."))
    skills = search_skills_index(keywords)

    # Phase 1-b: Search long-term memory
    print(blue("→ Searching long-term memory..."))
    mem = search_long_term_memory(keywords)

    # Phase 1-c: Search short-term memory
    print(blue("→ Searching short-term memory (last 7 days)..."))
    short_mem = search_short_term_memory(keywords)

    # Phase 1-d: Search workspace
    print(blue("→ Searching workspace files..."))
    wf = search_workspace_files(keywords)

    report = format_report({
        "query": query,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "skills": skills,
        "long_term_memory": mem,
        "short_term_memory": short_mem,
        "workspace_files": wf,
    })

    print()
    print(report)
    print()

    # If skills found, prompt to read them
    if skills:
        print(yellow("💡 Tip: Read the found skills with: skills_read <skill-id>"))
        print("    Don't skip them even if the description seems empty or unrelated.")

    return 0


def cmd_close_loop(args: list[str]):
    interim = False
    constraint_text = None

    if "--interim" in args:
        idx = args.index("--interim")
        if idx + 1 < len(args):
            constraint_text = args[idx + 1]
        interim = True

    if not constraint_text:
        print(bold("🧠 Close the Loop — Record a Constraint\n"))
        print("Describe what you learned that should persist to long-term memory.")
        print("For example: 'On proot Alpine, python-telegram-bot imports in >180s'")
        print()
        constraint_text = input("Constraint: ").strip()

    if not constraint_text:
        print(red("No constraint text provided. Nothing recorded."))
        return 1

    date = datetime.now().strftime("%Y-%m-%d")
    entry = f"- {date}: {constraint_text}"

    # Append to MEMORY.md in a consistent section
    marker = "## Long-Term Memory"
    if MEMORY_FILE.exists():
        content = MEMORY_FILE.read_text(errors="replace")
        if marker in content:
            content = content.replace(marker, f"{marker}\n{entry}")
        else:
            content += f"\n\n{marker}\n{entry}\n"
    else:
        content = f"# MEMORY\n\n{marker}\n{entry}\n"

    MEMORY_FILE.write_text(content)
    print(green(f"✅ Constraint recorded to {MEMORY_FILE}"))
    print(f"   {entry}")

    if interim:
        print(yellow("   (marked as interim — update when project completes)"))
    return 0


def cmd_check_dep(args: list[str]):
    if not args:
        print(red("Usage: python preflight.py check-dep <package-name>"))
        return 1
    pkg = args[0]
    print(bold(f"⏱  Checking import time for '{pkg}'..."))
    result = check_dependency_import_time(pkg)
    if result["seconds"] is not None:
        status = green("✅ OK") if result["ok"] else red("⚠️  SLOW")
        print(f"   Import: {result['seconds']:.3f}s — {status}")
        if not result["ok"]:
            print(yellow(f"   ⚠️  Import took >5s. Consider a raw HTTP alternative."))
    else:
        print(red(f"   ❌ Failed to import: {result.get('error', 'unknown error')}"))
    return 0


def cmd_help():
    print(bold("preflight.py — Pre-project audit for Omnibot"))
    print()
    print("Usage:")
    print("  python preflight.py audit <description>     Run full preflight audit")
    print("  python preflight.py close-loop [--interim]  Record a constraint to memory")
    print("  python preflight.py check-dep <pkg>         Test package import speed")
    print()
    print("Examples:")
    print("  python preflight.py audit telegram bot")
    print('  python preflight.py close-loop --interim "httpx boots 50x faster than SDK"')
    print("  python preflight.py check-dep python-telegram-bot")
    return 0


# ── Main ──────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        return cmd_help()

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "audit": cmd_audit,
        "close-loop": cmd_close_loop,
        "check-dep": cmd_check_dep,
        "help": cmd_help,
        "--help": cmd_help,
    }

    if command not in commands:
        print(red(f"Unknown command: {command}"))
        return cmd_help()

    return commands[command](args)


if __name__ == "__main__":
    sys.exit(main())
