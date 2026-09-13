import io
import json
import os
import requests
from PIL import Image, ImageDraw
from google import genai
from google.genai import types
from pydantic import BaseModel

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

valid_coins = [c for c in data if isinstance(c, dict) and c.get("price_change_percentage_24h") is not None]
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
# 2. Strict Structured Schema for Gemini Commentary
# ----------------------------------------------------
class MoverItem(BaseModel):
    symbol: str
    name: str
    direction: str
    change_24h: float
    character: str
    comment: str
    image_prompt: str

class MarketResponse(BaseModel):
    items: list[MoverItem]

client = genai.Client()

system_instruction = """
You are the creative director for The Pasture / CryptoCowz (MOO19 Newsroom).
For each coin provided, select an appropriate cast character and write a satirical CoinMarketCap comment:
- For PUMP: Skip Zinfandel (smug anchor with pompadour), Chet Lively (sports anchor), or VOLA (corporate AI CEO).
- For DUMP: Sunshine Innocent Nimbus (goth weather girl celebrating disaster) or Frank Rizzo (gritty street reporter in trench coat).
Write a prompt for a 2D clean cartoon illustration in The Pasture animation style with Pasture green (#567D33) or Royal Purple (#6A0DAD) accents.
"""

prompt = f"Movers Data:\n{json.dumps(selected_pulls, indent=2)}"

chat_response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents=prompt,
    config=types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=MarketResponse,
    )
)

parsed_payload = MarketResponse.model_validate_json(chat_response.text)
movers_list = parsed_payload.items

# ----------------------------------------------------
# 3. Image Generation & 1200x675 Canvas Formatting
# ----------------------------------------------------
os.makedirs("output/images", exist_ok=True)
markdown_lines = ["# Daily Top Movers: CMC Community Posts & Visuals\n"]

def generate_branded_placeholder(filename: str, symbol: str, direction: str, char: str, change: float):
    """Generates a 1200x675 branded fallback card using CryptoCowz brand colors."""
    # Pasture green for pump, Royal purple for dump
    bg_color = (86, 125, 51) if direction == "PUMP" else (106, 13, 173)
    img = Image.new("RGB", (1200, 675), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Frame Border
    draw.rectangle([(20, 20), (1180, 655)], outline=(255, 255, 255), width=4)

    # Content
    draw.text((60, 60), "MOO19 NEWS | THE PASTURE", fill=(255, 211, 0))
    draw.text((60, 160), f"${symbol}  ({'+' if change > 0 else ''}{change}%)", fill=(255, 255, 255))
    draw.text((60, 260), f"Status: {direction}", fill=(255, 255, 255))
    draw.text((60, 360), f"On Scene: {char}", fill=(220, 220, 220))
    draw.text((60, 560), "CryptoCowz Edutainment Universe", fill=(200, 200, 200))

    img.save(filename, "PNG")

for idx, item in enumerate(movers_list, 1):
    symbol = item.symbol
    direction = item.direction
    char = item.character
    comment = item.comment
    img_prompt = item.image_prompt
    filename = f"output/images/{idx:02d}_{direction}_{symbol}.png"

    print(f"Generating visual {idx}/10: {symbol} ({direction}) with {char}...")

    image_saved = False
    try:
        # Calls Imagen 3 directly via Developer API
        img_res = client.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=img_prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="16:9"
            )
        )
        if img_res.generated_images:
            raw_bytes = img_res.generated_images[0].image.image_bytes
            img = Image.open(io.BytesIO(raw_bytes))
            img = img.resize((1200, 675), Image.Resampling.LANCZOS)
            img.save(filename, "PNG")
            image_saved = True
    except Exception as e:
        print(f"Image generation unavailable for {symbol}: {e}")

    if not image_saved:
        generate_branded_placeholder(filename, symbol, direction, char, item.change_24h)

    markdown_lines.append(f"## {idx}. {item.name} (${symbol}) — {item.change_24h}% ({direction})")
    markdown_lines.append(f"**Cast Member:** {char}")
    markdown_lines.append(f"**CMC Comment:** {comment}\n")
    markdown_lines.append(f"![{symbol} Graphic](images/{os.path.basename(filename)})\n")
    markdown_lines.append(f"**Google Flow / Scene Prompt:**\n> {img_prompt}\n")
    markdown_lines.append("---\n")

with open("output/cmc_prompts_latest.md", "w") as f:
    f.write("\n".join(markdown_lines))

print("All 10 assets and markdown reports compiled successfully.")
