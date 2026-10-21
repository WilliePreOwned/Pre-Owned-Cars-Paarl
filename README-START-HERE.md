# Willie Buyer Radar 5.0 — Installation

**Free, public-RSS buyer-opportunity scanner + GitHub Pages dashboard. No email or credentials.**

Repository: https://github.com/WilliePreOwned/Pre-Owned-Cars-Paarl

## What is included

- `scripts/discover.py` — public RSS search, score, exclusion diagnostics, CSV + JSON output.
- `.github/workflows/buyer-discovery.yml` — hourly and manual GitHub Actions, commits dashboard data, uploads reports. Replaces your existing workflow.
- `buyer-radar.html` — mobile-friendly dashboard. Does not replace your existing `car-finder.html`.
- `buyer-radar-data.json` — empty initial data, populated by the workflow.
- `tests/test_discover.py` — offline tests (optional).

## Install in your existing repository

**Do not create a new repository. Do not delete `car-finder.html`.**

1. Download and unzip this package on your computer.
2. Open https://github.com/WilliePreOwned/Pre-Owned-Cars-Paarl
3. Upload/replace the files **in the exact locations shown above**. The simplest way is `Add file` → `Upload files` and drag the unzipped **contents** (not the enclosing `willie-buyer-radar-5` folder). GitHub's browser drag-and-drop may flatten folders, so **verify the paths before committing**. If it flattens them, edit `scripts/discover.py` and `.github/workflows/buyer-discovery.yml` individually using the GitHub pencil editor; use Add file → Create new file with the full relative path for missing files.
4. For the workflow file, open `.github/workflows/buyer-discovery.yml`, click pencil, select all, paste the new version, and click **Commit changes**. This **removes the email step entirely**.
5. Ensure repository **Settings → Actions → General → Workflow permissions** has **Read and write permissions**. This is necessary to automatically publish updated dashboard JSON. If organisation settings lock this option, a repository admin must enable it or an alternative publishing workflow is needed.
6. Ensure GitHub Pages publishes from **main / (root)**: `Settings → Pages → Build and deployment → Deploy from a branch → main → /(root)`. If your Pages site is already working from another source, check before changing it; the dashboard files must be in the published directory.
7. Open **Actions → Hourly Buyer Discovery → Run workflow → Run workflow**.
8. When green, open https://williepreowned.github.io/Pre-Owned-Cars-Paarl/buyer-radar.html and refresh. GitHub Pages can take a few minutes to deploy the new JSON.
9. For downloadable reports, open the Actions run and download artifact **buyer-opportunities-v5**.

## What the scores mean

- Buyer wording: +40
- Vehicle wording: +20
- Western Cape location **explicitly present in the result text**: +20
- Budget: +10
- Urgency: +10
- Score must be >=55 and **all** of buyer intent, vehicle, and location must match.
- Seller advertisements, older-than-45-day results (when dated), and invalid URLs are rejected.

**Important:** Location only in a search query is not enough; the result text must mention the location. This reduces false positives but can miss genuine local posts. Bing RSS search results are not guaranteed to be recent or to include social media posts. A zero-lead report is a legitimate outcome, not a scanner failure. Some RSS results may link to informational pages rather than buyers; manually verify everything.

## Diagnostics

`buyer_discovery_diagnostics_v5.txt` explains rejected results with samples. The dashboard shows the same information under “Why results were rejected.” A result can count under multiple reasons.

The scanner retains previously found dashboard opportunities for 45 days after first discovery, capped at 200. The state is committed in the repository and contains **hashes of public source URLs and first-seen timestamps only**.

## Privacy / safety

Only publicly available RSS items are accessed; no login, private-group scraping, contact harvesting, automated outreach, or buyer identity verification. Follow each website's rules before contacting anyone. Public source titles and snippets are displayed as-is and may be inaccurate.

## Test locally (optional)

From the repository root, run `python -m unittest discover -s tests`. No third-party Python packages are needed.
