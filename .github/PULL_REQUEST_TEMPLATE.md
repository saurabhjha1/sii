## New incident checklist

- [ ] The source link is public and loads without a login
- [ ] It happened to a real deployment, not a researcher proof-of-concept
- [ ] An AI agent took the action (or was the attack surface), not just a chatbot saying something wrong with no consequence
- [ ] `kind` is one of `security`, `reliability`, `performance` (see README for the decision order)
- [ ] `security` entries have at least one `atlas` ID that exists on https://atlas.mitre.org; other kinds have none
- [ ] `ruby scripts/validate.rb` passes locally
- [ ] `date` is the publication date of the source in `YYYY-MM-DD`
- [ ] `impact` is one factual line
- [ ] Entry is added to `_data/incidents.yml` (order does not matter; the page sorts by date)
