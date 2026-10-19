# Super Intelligent Incidents — [sii.wtf](https://sii.wtf)

A compiled list of links to public production incidents (security or otherwise) caused by AI agents. Most recent on top.

Inspired by [k8s.af](https://k8s.af/).

## Adding an incident

Either [open an issue](../../issues/new?template=incident.yml) using the incident form, or:

1. Fork this repo.
2. Add an entry to [`_data/incidents.yml`](_data/incidents.yml). A field reference and a copy-paste template are at the top of that file.
3. Run `ruby scripts/validate.rb` and open a pull request.

What qualifies:

- The source is **public** (blog post, postmortem, news report, GitHub issue, advisory).
- It **happened to a real deployment**. Researcher proof-of-concepts and lab exercises are out of scope; [MITRE ATLAS](https://atlas.mitre.org/studies) catalogues those.
- An **AI agent did the thing**, or was the attack surface: it ran the command, sent the email, leaked the data, agreed to the $1 car.
- Keep `impact` to one line and keep opinions out of the entry. Link, don't editorialise.

## Labels

`kind` is a list of one or more labels. The label names the team that would be paged, not what the agent did. Most incidents get one; use more than one (shown as **mixed** on the site) only when the incident genuinely belongs to more than one team, e.g. `[security, reliability]` for a breach that also caused an outage. For each label, decide in this order:

| ask | if yes | covers |
|---|---|---|
| Was there an adversary, or did untrusted input steer the agent? | `security` | leaks, exfiltration, supply chain, prompt injection, jailbreaks |
| No adversary, but the system did the wrong thing or didn't work? | `reliability` | outages, data loss, elevated error rates, wrong output in production |
| No adversary, nothing wrong, but worse than it should be? | `performance` | latency, saturation, runaway resource or cost consumption |

Definitions live in [`_data/kinds.yml`](_data/kinds.yml) and render as tooltips on the site.

`url` is the primary link the title points to. Add `links:` (a list of `{text, url}`) for extra sources such as a technical report, video, independent investigation or press coverage.

Every entry whose `kind` includes `security` **must** carry `atlas:` with at least one [MITRE ATLAS](https://atlas.mitre.org/) technique ID (`AML.T….`) or case-study ID (`AML.CS….`). Non-security entries must not have one. ATLAS catalogues adversarial techniques, so a security incident that maps to none of them is a sign the label is wrong.

## Validation

CI runs `ruby scripts/validate.rb` on every push and pull request. It checks required fields, label and source values, date and URL formats, duplicate URLs, the security-to-ATLAS rule above, and that every ATLAS ID exists in the current ATLAS release. Run it locally before opening a PR:

```sh
ruby scripts/validate.rb
```

## Hacker News scout

A daily GitHub Action (`.github/workflows/hn-scout.yml`) runs `scripts/hn_scout.py`:

1. Pulls the last 36 hours of Hacker News stories with 5+ points.
2. Drops anything whose URL is already listed or whose HN id was already filed.
3. Sends the titles to Claude, which flags stories that might be a qualifying incident.
4. For each flagged story, Claude reads the article, the HN thread and the primary source, then drafts an entry.
5. The draft is run through `scripts/validate.rb`. If it passes, the bot opens an issue (with its reasoning) and a PR that adds the entry and closes the issue. If it fails, or Claude judges the incident still evolving (no postmortem yet, facts unconfirmed), only the issue is opened, labeled `evolving`, to be published once the facts settle.

A human still reads the source before merging. The bot's PRs are labeled `hn-scout`.

### Setup

1. Add the Claude API key as a repository secret (you will be prompted to paste it):

   ```sh
   gh secret set ANTHROPIC_API_KEY -R saurabhjha1/sii
   ```

2. Allow Actions to open pull requests: Settings → Actions → General → Workflow permissions → "Read and write" and tick "Allow GitHub Actions to create and approve pull requests". Or:

   ```sh
   printf '{"default_workflow_permissions":"write","can_approve_pull_request_reviews":true}' \
     | gh api -X PUT repos/saurabhjha1/sii/actions/permissions/workflow --input -
   ```

3. Do a dry run over three days of HN. It prints candidates and drafts in the Actions log and opens nothing:

   ```sh
   gh workflow run "hn scout" -R saurabhjha1/sii -f hours=72 -f dry_run=true
   gh run watch -R saurabhjha1/sii
   ```

4. Run it for real, or just wait for the daily schedule (06:17 UTC):

   ```sh
   gh workflow run "hn scout" -R saurabhjha1/sii
   ```

Optional: add a `HN_SCOUT_TOKEN` secret (a fine-grained PAT with contents, issues and pull-requests write) so the bot's PRs trigger the validate workflow. PRs opened with the default `GITHUB_TOKEN` do not trigger other workflows, so without it the validate check will not appear on bot PRs (the validator still ran inside the bot).

### Run it locally

```sh
pip install -r scripts/requirements.txt
ANTHROPIC_API_KEY=... python scripts/hn_scout.py --dry-run --hours 72
python scripts/hn_scout.py --self-test   # exercises render + validate without calling Claude
```

## Running locally

The site is plain [Jekyll](https://jekyllrb.com/) and builds on GitHub Pages with no custom plugins.

```sh
gem install bundler jekyll
jekyll serve
```

Then open http://localhost:4000.
