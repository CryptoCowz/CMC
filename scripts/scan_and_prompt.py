import json
import os
import requests
from google import genai

# 1. Fetch Trending & Top Performing Coins (CoinGecko free public API)
url = "https://api.coingecko.com/api/v3/search/trending"
headers = {"accept": "application/json"}
response = requests.get(url, headers=headers)
data = response.json()

trending_coins = [
    f"{c['item']['name']} (${c['item']['symbol']}) - Rank #{c['item']['market_cap_rank']}"
    for c in data.get("coins", [])[:5]
]
market_summary = "\n".join(trending_coins)

# 2. Configure Gemini Client
client = genai.Client()

system_instruction = """
You are the creative director for The Pasture / CryptoCowz (MOO19 Newsroom).
Based on the current trending cryptocurrencies, generate 3 satirical, short CoinMarketCap community comments with accompanying Google Flow image prompts.
Each entry must feature one of the MOO19 cast (Skip Zinfandel, Sunshine Innocent Nimbus, Frank Rizzo, or Professor Hartmut) reacting to the token's market action in 2D animation style.
"""

prompt = f"""
Trending / Noteworthy Coins Today:
{market_summary}

Format each entry as:
- Token & Ticker:
- Cast Character:
- CMC Comment (Satirical, witty, max 2 sentences):
- Google Flow Image Prompt: [2D cartoon illustration in The Pasture animation style, detailing character pose, expression, and market charts/elements]
"""

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
    config={"system_instruction": system_instruction},
)

# 3. Save output to Markdown file
output_path = "output/cmc_prompts_latest.md"
os.makedirs("output", exist_ok=True)
with open(output_path, "w") as f:
    f.write(f"# CMC Top Scans & Community Prompts\n\n{response.text}")

print(f"Generated successfully: {output_path}")
