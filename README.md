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

## Running locally

The site is plain [Jekyll](https://jekyllrb.com/) and builds on GitHub Pages with no custom plugins.

```sh
gem install bundler jekyll
jekyll serve
```

Then open http://localhost:4000.
