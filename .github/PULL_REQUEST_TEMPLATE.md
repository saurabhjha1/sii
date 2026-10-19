## New incident checklist

- [ ] The source link is public and loads without a login
- [ ] It happened to a real deployment, not a researcher proof-of-concept
- [ ] An AI agent took the action (or was the attack surface), not just a chatbot saying something wrong with no consequence
- [ ] `kind` is a list of one or more of `security`, `reliability`, `performance`; more than one only if it really belongs to more than one team (see README)
- [ ] entries whose `kind` includes `security` have at least one `atlas` ID that exists on https://atlas.mitre.org; other kinds have none
- [ ] `ruby scripts/validate.rb` passes locally
- [ ] `date` is the publication date of the source in `YYYY-MM-DD`
- [ ] `impact` is one factual line
- [ ] Entry is added to `_data/incidents.yml` (order does not matter; the page sorts by date)
