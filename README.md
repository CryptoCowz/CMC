# CMC lesson radar

CryptoCowz comments on CoinMarketCap are lessons, not tips. Mom, Dad, and the Blue Twin never call a price. This repo is a radar: it finds large coins that moved and pairs each one with a pre-approved lesson card and a ready-to-paste comment. A person reviews the digest and hand-posts two cards a week, on Wednesday and Friday (America/New_York). The script never posts.

## Schedule

`.github/workflows/crypto_scan.yml` runs `scripts/scan_and_prompt.py` every day at 12:00 UTC. The script writes `output/cmc_movers_latest.md` only on Wednesday and Friday in America/New_York. Any other day it exits without writing. Starting the workflow by hand (`workflow_dispatch`) writes a digest immediately.

The workflow commits that one markdown file and copies it into the job summary. It does not commit images.

## Universe

CoinGecko public markets feed, top 100 by market cap. No key is required. An optional `COINGECKO_API_KEY` may be set as a GitHub Actions secret (sent as the demo header). Keys stay in Actions secrets, never in the repo.

`config/skip_coins.txt` drops stablecoins, pegged cash, tokenized treasury funds, and wrapped or staked stand-ins (USDT, USDC, DAI, WBTC, STETH, and the rest of the file). Add a symbol, a coin name, or a CoinGecko id to leave a coin off the radar, including when scam or fraud news is already known. The script does not fetch news.

A coin whose name, symbol, or id would put a banned word into the comment is left off as well.

## Cards

Three static images in `assets/cards/`:

- `cmc-mom-lesson-card-1080.png` — largest gainer
- `cmc-dad-lesson-card-1080.png` — largest loser
- `cmc-twin-lesson-card-1080.png` — Blue Twin, for the heaviest tape

The art has no coin name, coin logo, arrow, price, or percent on it. The script does not draw charts.

**Blue Twin heuristic:** highest 24-hour volume divided by market cap (turnover) inside the filtered top 100. Mom and Dad keep their own coins. Blue Twin takes the next coin when the turnover leader is already a Mom or Dad pick, so the three cards can cover three coins.

The digest also lists the other top gainers (Mom card) and top losers (Dad card). It shows coin name, symbol, and a CoinMarketCap link only. The slug starts from the CoinGecko id, with known fixes in the script for ids that point at the wrong page. Confirm the page before posting.

## Comment

Busy day for [coin]. Here's the herd's plain-words lesson 🐄 More at cryptocowz.substack.com

The comment and the digest stay free of these words: up, down, buy, sell, pump, dump, moon. No prices and no percent figures.
