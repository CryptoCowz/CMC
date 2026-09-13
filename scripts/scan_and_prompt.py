import io
import json
import os
import requests
from PIL import Image
from google import genai
from google.genai import types

# ----------------------------------------------------
# 1. Fetch Top 5 Gainers & Top 5 Losers (CoinGecko)
# ----------------------------------------------------
headers = {"accept": "application/json"}
cg_api_key = os.getenv("COINGECKO_API_KEY")
if cg_api_key:
    headers["x-cg-demo-api-key"] = cg_api_key

url = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1&sparkline=false&price_change_percentage=24h"
)

response = requests.get(url, headers=headers)
data = response.json()

# Filter coins with valid 24h price change
valid_coins = [c for c in data if c.get("price_change_percentage_24h") is not None]
sorted_by_change = sorted(valid_coins, key=lambda x: x["price_change_percentage_24h"], reverse=True)

top_gainers = sorted_by_change[:5]
top_losers = sorted_by_change[-5:]

selected_pulls = []
for c in top_gainers:
    selected_pulls.append({
        "direction": "PUMP",
        "name": c["name"],
        "symbol": c["symbol"].upper(),
        "price": c["current_price"],
        "change_24h": round(c["price_change_percentage_24h"], 2)
    })
for c in top_losers:
    selected_pulls.append({
        "direction": "DUMP",
        "name": c["name"],
        "symbol": c["symbol"].upper(),
        "price": c["current_price"],
        "change_24h": round(c["price_change_percentage_24h"], 2)
    })

# ----------------------------------------------------
# 2. Generate Satirical Commentary & Prompts via Gemini
# ----------------------------------------------------
client = genai.Client()

system_instruction = """
You are the creative director for The Pasture / CryptoCowz (MOO19 Newsroom).
For each coin provided, generate:
1. Assigned MOO19 Character:
   - For PUMP: Skip Zinfandel (smug anchor with pompadour), Chet Lively (clueless sports anchor), or VOLA (corporate AI CEO).
   - For DUMP: Sunshine Innocent Nimbus (goth weather girl who rejoices in disaster) or Frank Rizzo (cynical street reporter in trench coat).
2. CMC Comment: Max 2 sharp, satirical sentences suitable for the CoinMarketCap community section.
3. Image Prompt: Detailed prompt for a 2D clean cartoon illustration matching The Pasture brand guidelines:
   - Species: Anthropomorphic cow/bull.
   - Style: Clean bold 2D lines, flat vector cell shading, no hyper-realism.
   - Branding: Pasture green (#567D33), Royal Purple (#6A0DAD), or Corporate Lavender (#9F86C0).
   - Scene: Anchor desks, weather radars, or street corners with green/red candlestick charts and token logos.

Respond ONLY with a valid JSON array containing exactly 10 objects with keys:
"symbol", "name", "direction", "change_24h", "character", "comment", "image_prompt"
"""

prompt = f"Selected Movers (Top 5 Gainers & Top 5 Losers):\n{json.dumps(selected_pulls, indent=2)}"

chat_response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json"
    )
)

items = json.loads(chat_response.text)

# ----------------------------------------------------
# 3. Generate & Resize 1200x675 Images
# ----------------------------------------------------
os.makedirs("output/images", exist_ok=True)
markdown_lines = ["# Daily Top Movers: CMC Community Posts & Visuals\n"]

for idx, item in enumerate(items, 1):
    symbol = item["symbol"]
    direction = item["direction"]
    char = item["character"]
    comment = item["comment"]
    img_prompt = item["image_prompt"]
    filename = f"output/images/{idx:02d}_{direction}_{symbol}.png"

    print(f"Generating image {idx}/10: {symbol} ({direction}) with {char}...")

    try:
        img_res = client.models.generate_images(
            model="imagen-4.0-generate-001",
            prompt=img_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9"
            )
        )
        
        # Load image bytes and resize strictly to 1200x675
        img_bytes = img_res.generated_images[0].image.image_bytes
        img = Image.open(io.BytesIO(img_bytes))
        img = img.resize((1200, 675), Image.Resampling.LANCZOS)
        img.save(filename, "PNG")

        markdown_lines.append(f"## {idx}. {item['name']} (${symbol}) — {item['change_24h']}% ({direction})")
        markdown_lines.append(f"**Cast Member:** {char}")
        markdown_lines.append(f"**CMC Comment:** {comment}\n")
        markdown_lines.append(f"![{symbol} Graphic](images/{os.path.basename(filename)})\n")
        markdown_lines.append(f"**Google Flow / Engine Prompt:**\n> {img_prompt}\n")
        markdown_lines.append("---\n")
    except Exception as e:
        print(f"Failed image for {symbol}: {e}")
        markdown_lines.append(f"## {idx}. {item['name']} (${symbol}) — Error generating image: {e}\n")

with open("output/cmc_prompts_latest.md", "w") as f:
    f.write("\n".join(markdown_lines))

print("All 10 graphics processed and saved successfully.")
