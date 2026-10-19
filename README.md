# Super Intelligent Incidents — [sii.wtf](https://sii.wtf)

A compiled list of links to public incidents (security or otherwise) caused by AI agents. Most recent on top.

Inspired by [k8s.af](https://k8s.af/).

## Adding an incident

1. Fork this repo.
2. Add an entry to [`_data/incidents.yml`](_data/incidents.yml). Field reference is at the top of that file.
3. Open a pull request.

What qualifies:

- The source is **public** (blog post, postmortem, news report, GitHub issue, advisory, talk, research write-up).
- An **AI agent did the thing**, or was the attack surface: it ran the command, sent the email, leaked the data, agreed to the $1 car. Plain model-output mishaps (a bad chat answer with no action taken) are out of scope unless they caused real-world consequences.
- Keep `impact` to one line and keep opinions out of the entry. Link, don't editorialise.

## Running locally

The site is plain [Jekyll](https://jekyllrb.com/) and builds on GitHub Pages with no custom plugins.

```sh
gem install bundler jekyll
jekyll serve
```

Then open http://localhost:4000.
