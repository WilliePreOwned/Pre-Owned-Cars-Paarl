name: Buyer Radar 7.1 - Public Discovery
on:
  workflow_dispatch:
  schedule:
    - cron: '17 6,12 * * *' # 08:17 and 14:17 South Africa time
permissions:
  contents: write
concurrency:
  group: buyer-radar-7-1
  cancel-in-progress: false
jobs:
  discover:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Discover public buyer requests
        run: python scripts/buyer_radar_7_1.py
      - name: Commit 7.1 results only
        run: |
          git config user.name 'github-actions[bot]'
          git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
          git add buyer-radar-7-1.json buyer-radar-7-1.csv buyer-radar-7-1-diagnostics.json
          if ! git diff --cached --quiet; then
            git commit -m 'Update Buyer Radar 7.1 results [skip ci]'
            git push
          fi
