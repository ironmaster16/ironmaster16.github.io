# Iceland Tourism Directory - Maintenance Guide

## Purpose
A curated directory of essential Iceland tourism resources maintained by locals. No affiliate links, just practical tools for tourists planning or visiting now.

**Target Audience**: English-speaking tourists planning trips or currently in Iceland

---

## Maintenance Schedule

### Automated (Cron)
- **3x daily** (07:00, 12:00, 18:00): News processing and publishing
- **Daily** (00:00): Cron log rotation (keeps 7 days, max 10MB)
- **Weekly**: Automated link checking (planned)
- **Weekly**: Database cleanup (planned)

### Manual Reviews
- **Weekly** (15 min): Check news quality, fix critical broken links
- **Monthly** (1 hour): Deep review one section, add 1-3 new links
- **Quarterly** (2 hours): Full site audit, update all verification dates

---

## Adding New Links

### Quick Vetting Checklist
- [ ] Official/reputable source
- [ ] Practical tourist need
- [ ] English or bilingual
- [ ] Active 6+ months
- [ ] Mobile friendly
- [ ] Free/accessible

### Process
1. Verify link works and is current
2. Choose section (emergency, weather, transportation, etc.)
3. Write 10-15 word description (what it does, not opinion)
4. Add to `_includes/[section].md`
5. Commit: "Add [Site Name] to [section]"
6. Log in TODO.md with date

### Format
```markdown
- **<a href="URL" target="_blank">Site Name</a>** - Brief description. <small>Language if not EN</small>
```

---

## News System

### Configuration
- **Sources**: RÚV English, Grapevine (see `iceland-news/config.json`)
- **Rating threshold**: 5/10 minimum
- **Minimum articles**: 10 (pulls from database if needed)
- **Lookback period**: 7 days
- **Display format**: Title with source and date inline

### How It Works
1. `process_news.py` fetches RSS feeds (RÚV, Grapevine, Iceland Review)
2. LLM rates articles 1-10 for tourist relevance
3. Stored in SQLite database
4. Top-rated articles → `output/tourist_news.md`
5. Automatically copies to website repo and git push (if enabled)

### Managing Sources
- Add/edit feeds in `iceland-news/config.json`
- Add blacklist terms to `blacklist.txt`
- Adjust rating prompt in `prompts/news_prompt.txt`

### Git Publishing Configuration
In `iceland-news/config.json`:
```json
"git": {
  "enabled": true,              // Toggle git push on/off
  "repo_path": "~/ironmaster16.github.io",
  "target_file": "_includes/tourist_news.md",
  "branch": "main",
  "commit_message": "Update tourist news - {timestamp}",
  "auto_push": true             // Auto push after commit
}
```
Set `"enabled": false` to test locally without pushing to GitHub.

---

## Folder Structure

```
ironmaster16.github.io/     (Website - GitHub Pages)
├── _includes/              (Content sections)
├── docs/                   (This folder - not published)
└── index.md

iceland-news/               (Automation - runs locally)
├── config.json
├── process_news.py
├── db/news.db
├── output/tourist_news.md  (auto-published)
└── scripts/

automation/                 (Planned - other scripts)
└── check_links.py
```

---

## Common Tasks

### Add News Source
Edit `iceland-news/config.json`, add feed:
```json
{
  "name": "Source Name",
  "url": "https://example.com/feed/",
  "enabled": true,
  "max_articles": 40
}
```

### Remove Broken Link
1. Remove from `_includes/[section].md`
2. Commit: "Remove [Site Name] - [reason]"
3. Note in TODO.md

### Update Section
Edit appropriate `_includes/[section].md` file, then commit and push.

### Check Logs
- News processing: `iceland-news/logs/news_filter.log`
- Cron jobs: `/var/log/syslog` or `~/.local/logs/`

---

## TODO Tracker

### Automation Setup
- [ ] Create database backup script
- [ ] Create database cleanup script (delete articles >90 days)
- [ ] Setup cron jobs for 3x daily news (07:00, 12:00, 18:00)
- [ ] Create link validation script
- [ ] Setup weekly automated link checking

### Immediate Content Updates
- [ ] Flatten news-media.md (remove subsections)
- [ ] Move tourist_news to top of index.md
- [ ] Update news format with inline source + date
- [ ] Update About section with verification statement

### Future
- [ ] Add Icelandic Times to news sources
- [ ] Create monthly section review rotation
- [ ] Consider analytics

---

## Quick Reference

**Run news manually**: `cd ~/iceland-news && ./run_news_processing.sh`

**Run news with git disabled**: Edit `config.json` → set `"git": {"enabled": false}`

**Setup automation**: `cd ~/iceland-news && ./scripts/setup_cron.sh`

**View cron logs**: `tail -f ~/iceland-news/logs/cron.log`

**Explore database**: `cd ~/iceland-news && python3 explore_database.py --help`

**Edit site locally**: Edit `_includes/[file].md` → commit → push

**Check GitHub Pages build**: https://github.com/ironmaster16/ironmaster16.github.io/actions

---

## Standards

- All links open in new tab (`target="_blank"`)
- Descriptions: concise, factual, 10-15 words
- Verified before adding, checked monthly
- No affiliate links, no subjective opinions
- Maintained by locals perspective
