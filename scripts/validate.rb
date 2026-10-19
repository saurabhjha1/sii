#!/usr/bin/env ruby
# Validates _data/incidents.yml. Run locally with `ruby scripts/validate.rb`; CI runs it on every push and PR.
# Exit 1 on any error. Set ATLAS_YAML=path to use a local copy of MITRE ATLAS data; otherwise it is fetched.
require "yaml"
require "date"
require "net/http"
require "uri"
require "set"

ROOT = File.expand_path("..", __dir__)
REQUIRED = %w[title org agent source kind date url involved impact].freeze
SOURCES  = ["blog post", "news", "postmortem", "GitHub issue", "advisory"].freeze
ATLAS_ID = /\AAML\.(T\d{4}(\.\d{3})?|CS\d{4})\z/
ATLAS_URL = "https://raw.githubusercontent.com/mitre-atlas/atlas-data/main/dist/ATLAS.yaml"

errors = []
err = ->(e, msg) { errors << "#{(e['title'] || '<untitled>')[0, 60]}: #{msg}" }

kinds = YAML.load_file(File.join(ROOT, "_data/kinds.yml")).map { |k| k["id"] }
incidents = YAML.load_file(File.join(ROOT, "_data/incidents.yml"))
abort "incidents.yml must be a list" unless incidents.is_a?(Array)

# Known ATLAS IDs, if we can get them. Missing data downgrades the existence check to a warning.
atlas_ids = nil
begin
  raw = ENV["ATLAS_YAML"] ? File.read(ENV["ATLAS_YAML"]) : Net::HTTP.get(URI(ATLAS_URL))
  atlas = YAML.safe_load(raw, permitted_classes: [Date, Time], aliases: true)
  m = atlas["matrices"][0]
  atlas_ids = (m["techniques"].map { |t| t["id"] } + atlas["case-studies"].map { |c| c["id"] }).to_set
  puts "ATLAS #{atlas['version']}: #{atlas_ids.size} known IDs"
rescue => e
  warn "warning: could not load ATLAS data (#{e.class}: #{e.message}); skipping ID existence check"
end

seen_urls = {}
incidents.each do |e|
  REQUIRED.each { |f| err.(e, "missing `#{f}`") if e[f].nil? || (e[f].respond_to?(:empty?) && e[f].empty?) }

  ek = e["kind"]
  if !ek.is_a?(Array) || ek.empty?
    err.(e, "`kind` must be a non-empty list, e.g. [security] or [security, reliability] (got #{ek.inspect})")
    ek = []
  end
  (ek - kinds).each { |bad| err.(e, "`kind` #{bad.inspect} is not one of #{kinds.join(', ')}") }
  err.(e, "`kind` has duplicates") if ek.uniq.size != ek.size
  security = ek.include?("security")
  err.(e, "`source` must be one of #{SOURCES.join(', ')} (got #{e['source'].inspect})") unless SOURCES.include?(e["source"])

  d = e["date"]
  unless d.is_a?(Date) || (d.is_a?(String) && (Date.strptime(d, "%Y-%m-%d") rescue false))
    err.(e, "`date` must be YYYY-MM-DD (got #{d.inspect})")
  end

  [["url", e["url"]], *(e["links"] || []).map { |l| ["links", l.is_a?(Hash) && l["url"]] }].each do |field, u|
    err.(e, "`#{field}` must be an http(s) URL (got #{u.inspect})") unless u.is_a?(String) && u =~ %r{\Ahttps?://\S+\z}
  end
  (e["links"] || []).each do |l|
    err.(e, "each `links` item needs `text` and `url`") unless l.is_a?(Hash) && l["text"] && l["url"]
  end
  if e["url"] && seen_urls[e["url"]]
    err.(e, "duplicate `url`, already used by \"#{seen_urls[e['url']][0, 40]}\"")
  end
  seen_urls[e["url"]] = e["title"]

  err.(e, "`involved` must be a non-empty list") unless e["involved"].is_a?(Array) && e["involved"].any?

  atlas = e["atlas"]
  if atlas
    err.(e, "`atlas` must be a list") unless atlas.is_a?(Array)
    Array(atlas).each do |a|
      err.(e, "`atlas` ID #{a.inspect} is not of the form AML.T0000, AML.T0000.000 or AML.CS0000") unless a.is_a?(String) && a =~ ATLAS_ID
      err.(e, "`atlas` ID #{a} does not exist in MITRE ATLAS") if atlas_ids && a =~ ATLAS_ID && !atlas_ids.include?(a)
    end
  end
  if security && Array(atlas).empty?
    err.(e, "kind includes `security` but no `atlas` IDs. Every security incident must map to at least one MITRE ATLAS technique (https://atlas.mitre.org/techniques)")
  end
  if !security && atlas && Array(atlas).any?
    err.(e, "`atlas` IDs are only for `security` incidents (ATLAS catalogues adversarial techniques; this entry is #{ek.join('+')})")
  end
end

if errors.empty?
  puts "OK: #{incidents.size} incidents valid"
else
  warn "#{errors.size} error(s):"
  errors.each { |m| warn "  - #{m}" }
  exit 1
end
