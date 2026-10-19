#!/usr/bin/env python3
"""Hacker News scout for sii.wtf.

Pulls recent HN stories, asks Claude to screen the titles for production incidents
caused by AI agents, has Claude read the promising ones in depth, drafts an entry for
_data/incidents.yml, runs scripts/validate.rb on it, and opens an issue + PR.

Usage:
  python scripts/hn_scout.py                  # full run (needs ANTHROPIC_API_KEY, GH_TOKEN)
  python scripts/hn_scout.py --dry-run        # everything except creating issues/PRs
  python scripts/hn_scout.py --hours 72       # widen the window
  python scripts/hn_scout.py --self-test      # no network to Claude: exercise render + validate

Environment:
  ANTHROPIC_API_KEY  Claude API key (or any credential the SDK resolves)
  GH_TOKEN           token for `gh` (GITHUB_TOKEN in Actions)
  SII_MODEL          override the model (default claude-opus-5-5)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

import requests
import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
INCIDENTS = ROOT / "_data" / "incidents.yml"
KINDS = ROOT / "_data" / "kinds.yml"
MODEL = os.environ.get("SII_MODEL", "claude-opus-5-5")
REPO = os.environ.get("GITHUB_REPOSITORY", "saurabhjha1/sii")
LABEL = "hn-scout"
HN_API = "https://hn.algolia.com/api/v1/search_by_date"
UA = "sii-wtf-hn-scout (+https://sii.wtf)"

CRITERIA = """\
sii.wtf lists PUBLIC PRODUCTION INCIDENTS CAUSED BY AI AGENTS. An entry qualifies only if ALL hold:
1. It happened to a real deployment: a real company, product, user, or infrastructure was affected.
   Researcher proof-of-concepts, lab exercises, red-team demos, CVE write-ups without in-the-wild
   impact, and "we could have" stories do NOT qualify (MITRE ATLAS catalogues those).
2. An AI agent did the thing, or was the attack surface. The agent ran the command, sent the email,
   deleted the data, leaked the secret, agreed to the deal, generated the attacker's commands, or was the
   poisoned tool/MCP server/extension that the attacker went through. A chatbot merely saying something
   wrong with no consequence does not qualify; a chatbot whose words had a real consequence does.
3. There is a public source: postmortem, advisory, news report, GitHub issue, blog post.

Out of scope: model releases, benchmarks, opinion pieces, policy and regulation news, AI-generated
spam or slop complaints, deepfakes and voice cloning (no agent), classic ML evasion, stolen API keys
used to call an LLM (no agent acted), funding and product news.

Labels (kind). Pick every label that applies; most incidents get exactly one:
- security:    an adversary or untrusted input steered the agent (leak, exfiltration, supply chain,
               prompt injection, jailbreak, agent-driven intrusion)
- reliability: no attacker; the agent failed at its job (outage, data loss, elevated error rate,
               wrong output in production with real consequences)
- performance: no attacker, nothing wrong, but worse than it should be (latency, saturation,
               runaway resource or cost consumption)
"""


# ----------------------------------------------------------------------------- HN


def fetch_hn(hours: int, min_points: int) -> list[dict]:
    since = int(time.time()) - hours * 3600
    hits: list[dict] = []
    page = 0
    while True:
        r = requests.get(
            HN_API,
            params={
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>={min_points}",
                "hitsPerPage": 1000,
                "page": page,
            },
            headers={"User-Agent": UA},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        hits.extend(data["hits"])
        page += 1
        if page >= data.get("nbPages", 1):
            break
    stories = []
    for h in hits:
        stories.append(
            {
                "id": h["objectID"],
                "title": h.get("title") or "",
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                "hn_url": f"https://news.ycombinator.com/item?id={h['objectID']}",
                "points": h.get("points") or 0,
                "comments": h.get("num_comments") or 0,
                "created_at": h.get("created_at"),
                "text": (h.get("story_text") or "")[:400],
            }
        )
    return stories


# ----------------------------------------------------------------------------- dedup


def norm_url(u: str) -> str:
    u = u.strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u.rstrip("/")


def known_urls() -> set[str]:
    data = yaml.safe_load(INCIDENTS.read_text()) or []
    urls = set()
    for e in data:
        urls.add(norm_url(e["url"]))
        for l in e.get("links") or []:
            urls.add(norm_url(l["url"]))
    return urls


def gh(*args: str, check: bool = True, input: Optional[str] = None) -> str:
    p = subprocess.run(["gh", *args], capture_output=True, text=True, input=input)
    if check and p.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def seen_hn_ids() -> set[str]:
    """HN story IDs already filed as issues (open or closed) carry an <!-- hn:ID --> marker."""
    try:
        out = gh("issue", "list", "-R", REPO, "--label", LABEL, "--state", "all",
                 "--limit", "500", "--json", "body")
    except RuntimeError as e:
        print(f"warning: could not list issues ({e}); dedup by HN id disabled", file=sys.stderr)
        return set()
    ids = set()
    for issue in json.loads(out or "[]"):
        ids.update(re.findall(r"<!-- hn:(\d+) -->", issue.get("body") or ""))
    return ids


# ----------------------------------------------------------------------------- stage 1: screen


class Candidate(BaseModel):
    id: str = Field(description="HN story id, copied exactly")
    confidence: float = Field(ge=0, le=1, description="Probability this is a qualifying incident")
    reason: str = Field(description="One line: why it might qualify")


class Screen(BaseModel):
    candidates: List[Candidate]


def screen_titles(client, stories: list[dict], batch: int = 100) -> list[Candidate]:
    out: list[Candidate] = []
    for i in range(0, len(stories), batch):
        chunk = stories[i : i + batch]
        lines = []
        for s in chunk:
            extra = f" | {s['text']}" if s["text"] else ""
            lines.append(f"{s['id']} | {s['title']} | {s['url']} | {s['points']}pts/{s['comments']}c{extra}")
        prompt = (
            "Screen these Hacker News stories. Return every story that MIGHT be a qualifying incident, "
            "with a calibrated confidence. Err on recall: a 0.3 for a vague title is fine, we read the "
            "promising ones next. Return nothing for stories that are clearly out of scope.\n\n"
            "Format: id | title | url | points/comments | optional self-text\n\n" + "\n".join(lines)
        )
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=4000,
            output_config={"effort": "low"},
            system=CRITERIA,
            messages=[{"role": "user", "content": prompt}],
            output_format=Screen,
        )
        if resp.stop_reason == "refusal":
            print("warning: screening request refused", file=sys.stderr)
            continue
        out.extend(resp.parsed_output.candidates)
    return out


# ----------------------------------------------------------------------------- stage 2: read + draft


class Link(BaseModel):
    text: str
    url: str


class Entry(BaseModel):
    title: str = Field(description="Headline as the primary source calls it, or a neutral one-liner")
    org: str = Field(description="Who was affected or who published it")
    agent: str = Field(description="The AI agent / tool / model that did the thing")
    source: Literal["blog post", "news", "postmortem", "GitHub issue", "advisory"]
    kind: List[Literal["security", "reliability", "performance"]]
    atlas: List[str] = Field(description="MITRE ATLAS IDs like AML.T0051 or AML.CS0047. Required when kind includes security, else empty")
    date: str = Field(description="Publication date of the primary source, YYYY-MM-DD")
    url: str = Field(description="Primary source URL. Prefer the postmortem/advisory over news coverage")
    links: List[Link] = Field(description="Extra sources: technical report, video, independent investigation, news coverage. Not the primary url, not the HN thread")
    involved: List[str] = Field(description="3-6 short tags for the mechanisms behind the incident")
    impact: str = Field(description="One factual line on the consequences")


class Draft(BaseModel):
    qualifies: bool
    reasoning: str = Field(description="3-6 sentences: what happened, why it does or does not meet each criterion, what you were unsure about")
    entry: Optional[Entry] = Field(description="The drafted entry; null when it does not qualify")


def research(client, story: dict) -> str:
    """Let Claude read the article, the HN thread and a little surrounding coverage."""
    prompt = (
        f"Research this Hacker News story and decide whether it is a qualifying incident for sii.wtf.\n\n"
        f"Title: {story['title']}\nArticle: {story['url']}\nHN discussion: {story['hn_url']}\n\n"
        "Fetch the article and the HN discussion. If the article is secondary coverage, find and fetch the "
        "primary source (vendor postmortem, advisory, GitHub issue). Search for at most two additional "
        "reputable sources. Then write research notes covering: what happened and when (publication date "
        "of the primary source), who was affected, which AI agent acted or was the attack surface, "
        "whether it was a real deployment or a proof-of-concept, the mechanisms, the consequences, which "
        "sii.wtf labels apply and why, and for security incidents which MITRE ATLAS technique IDs fit "
        "(https://atlas.mitre.org/techniques). List every URL you relied on."
    )
    messages = [{"role": "user", "content": prompt}]
    tools = [
        {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 6},
        {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
    ]
    notes = []
    for _ in range(4):  # server tools may pause the turn; resume a few times
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            system=CRITERIA,
            tools=tools,
            messages=messages,
        ) as stream:
            resp = stream.get_final_message()
        messages.append({"role": "assistant", "content": resp.content})
        notes.extend(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason != "pause_turn":
            break
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"research refused: {resp.stop_details}")
    return "\n".join(notes).strip()


def draft_entry(client, story: dict, notes: str) -> Draft:
    resp = client.messages.parse(
        model=MODEL,
        max_tokens=8000,
        output_config={"effort": "medium"},
        system=CRITERIA,
        messages=[
            {
                "role": "user",
                "content": (
                    "Using ONLY these research notes, decide whether the story qualifies and, if so, draft "
                    "the sii.wtf entry. Be strict on criterion 1 (real deployment) and 2 (agent acted). "
                    "Use URLs only from the notes. Keep `impact` to one line and keep opinions out.\n\n"
                    f"HN story: {story['title']} ({story['hn_url']})\n\nResearch notes:\n{notes}"
                ),
            }
        ],
        output_format=Draft,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"draft refused: {resp.stop_details}")
    return resp.parsed_output


# ----------------------------------------------------------------------------- render + validate


def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def render_entry(e: Entry) -> str:
    lines = [
        f"- title: {q(e.title)}",
        f"  org: {q(e.org)}",
        f"  agent: {q(e.agent)}",
        f"  source: {e.source}",
        f"  kind: [{', '.join(e.kind)}]",
    ]
    if e.atlas:
        lines.append(f"  atlas: [{', '.join(e.atlas)}]")
    lines.append(f"  date: {e.date}")
    lines.append(f"  url: {e.url}")
    if e.links:
        lines.append("  links:")
        for l in e.links:
            lines.append(f"    - text: {q(l.text)}")
            lines.append(f"      url: {l.url}")
    lines.append(f"  involved: [{', '.join(q(t) for t in e.involved)}]")
    lines.append(f"  impact: {q(e.impact)}")
    return "\n".join(lines) + "\n"


def validate_with(entry_yaml: str) -> tuple[bool, str]:
    """Append the entry to a scratch copy of the data file and run the Ruby validator on it."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "_data").mkdir()
        (root / "scripts").mkdir()
        (root / "_data" / "kinds.yml").write_text(KINDS.read_text())
        (root / "_data" / "incidents.yml").write_text(INCIDENTS.read_text().rstrip("\n") + "\n\n" + entry_yaml)
        (root / "scripts" / "validate.rb").write_text((ROOT / "scripts" / "validate.rb").read_text())
        p = subprocess.run(["ruby", str(root / "scripts" / "validate.rb")], capture_output=True, text=True)
        return p.returncode == 0, (p.stdout + p.stderr).strip()


# ----------------------------------------------------------------------------- github


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]


def open_issue(story: dict, draft: Draft, entry_yaml: Optional[str], validation: str, valid: bool) -> str:
    title = f"[incident] {draft.entry.title if draft.entry else story['title']}"
    body = [
        f"<!-- hn:{story['id']} -->",
        f"Found by the HN scout. Story: {story['hn_url']} ({story['points']} points, {story['comments']} comments)",
        "",
        "## Why it qualifies",
        draft.reasoning,
        "",
    ]
    if entry_yaml:
        body += ["## Draft entry", "```yaml", entry_yaml.rstrip(), "```", ""]
        body += ["## Validator", "```", validation, "```", ""]
        if not valid:
            body += ["The draft failed validation, so no PR was opened. Fix the entry and open one by hand.", ""]
    body += ["Please double-check every link, the date, the labels and the ATLAS IDs before merging."]
    out = gh("issue", "create", "-R", REPO, "--title", title, "--label", LABEL, "--body", "\n".join(body))
    return out.strip().splitlines()[-1]


def open_pr(story: dict, draft: Draft, entry_yaml: str, issue_url: str) -> str:
    e = draft.entry
    branch = f"hn-scout/{story['id']}-{slug(e.title)}"
    run = lambda *a: subprocess.run(a, check=True, capture_output=True, text=True)
    run("git", "config", "user.name", "sii hn-scout")
    run("git", "config", "user.email", "hn-scout@sii.wtf")
    run("git", "checkout", "-B", branch)
    INCIDENTS.write_text(INCIDENTS.read_text().rstrip("\n") + "\n\n" + entry_yaml)
    run("git", "add", str(INCIDENTS))
    run("git", "commit", "-m", f"Add incident: {e.title}\n\nFound on Hacker News: {story['hn_url']}\nRefs {issue_url}")
    run("git", "push", "-u", "origin", branch, "--force")
    body = (
        f"Closes {issue_url}\n\nFound on Hacker News: {story['hn_url']}\n\n"
        f"## Why it qualifies\n{draft.reasoning}\n\n"
        "## Checklist\n"
        "- [ ] Primary link is public and loads\n"
        "- [ ] It happened to a real deployment, not a proof-of-concept\n"
        "- [ ] An AI agent took the action or was the attack surface\n"
        "- [ ] Labels and ATLAS IDs are right\n"
        "- [ ] Date is the primary source's publication date\n\n"
        "Drafted by the HN scout and checked by `scripts/validate.rb`. A human still has to read the source."
    )
    out = gh("pr", "create", "-R", REPO, "--base", "main", "--head", branch, "--label", LABEL,
             "--title", f"Add incident: {e.title}", "--body", body)
    run("git", "checkout", "main")
    return out.strip().splitlines()[-1]


def ensure_label() -> None:
    gh("label", "create", LABEL, "-R", REPO, "--color", "5319e7",
       "--description", "Filed by the Hacker News scout", "--force", check=False)


# ----------------------------------------------------------------------------- main


def self_test() -> int:
    e = Entry(
        title="Self-test entry", org="Example Corp", agent="Example agent", source="news",
        kind=["security"], atlas=["AML.T0051"], date="2026-01-01", url="https://example.com/x",
        links=[Link(text="Coverage", url="https://example.com/y")],
        involved=["prompt injection", "test"], impact="nothing, this is a test",
    )
    y = render_entry(e)
    print(y)
    ok, out = validate_with(y)
    print(out)
    bad = e.model_copy(update={"kind": ["reliability"]})  # atlas on a non-security entry must fail
    ok2, out2 = validate_with(render_entry(bad))
    print("negative test:", "rejected as expected" if not ok2 else "UNEXPECTEDLY PASSED")
    return 0 if ok and not ok2 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=36)
    ap.add_argument("--min-points", type=int, default=5)
    ap.add_argument("--max-candidates", type=int, default=6)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--dry-run", action="store_true", help="do not create issues or PRs")
    ap.add_argument("--self-test", action="store_true", help="exercise render + validate without Claude")
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    import anthropic

    client = anthropic.Anthropic()

    stories = fetch_hn(args.hours, args.min_points)
    print(f"HN: {len(stories)} stories in the last {args.hours}h with >= {args.min_points} points")
    known = known_urls()
    seen = seen_hn_ids()
    stories = [s for s in stories if norm_url(s["url"]) not in known and s["id"] not in seen]
    print(f"after dedup: {len(stories)}")
    if not stories:
        return 0

    cands = screen_titles(client, stories)
    cands = sorted((c for c in cands if c.confidence >= args.threshold), key=lambda c: -c.confidence)
    by_id = {s["id"]: s for s in stories}
    cands = [c for c in cands if c.id in by_id][: args.max_candidates]
    print(f"stage 1: {len(cands)} candidates at >= {args.threshold}")
    for c in cands:
        print(f"  {c.confidence:.2f} {by_id[c.id]['title']}  ({c.reason})")
    if not cands:
        return 0

    if not args.dry_run:
        ensure_label()
    filed = 0
    for c in cands:
        story = by_id[c.id]
        print(f"\n== {story['title']}")
        try:
            notes = research(client, story)
            draft = draft_entry(client, story, notes)
        except Exception as e:  # one bad story must not kill the run
            print(f"  skipped: {e}", file=sys.stderr)
            continue
        if not draft.qualifies or draft.entry is None:
            print(f"  does not qualify: {draft.reasoning[:200]}")
            continue
        entry_yaml = render_entry(draft.entry)
        valid, out = validate_with(entry_yaml)
        print(f"  validator: {'OK' if valid else 'FAILED'}")
        print(entry_yaml)
        if not valid:
            print(out)
        if args.dry_run:
            continue
        issue_url = open_issue(story, draft, entry_yaml, out, valid)
        print(f"  issue: {issue_url}")
        if valid:
            pr_url = open_pr(story, draft, entry_yaml, issue_url)
            print(f"  pr: {pr_url}")
        filed += 1
    print(f"\nfiled {filed} incident(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
