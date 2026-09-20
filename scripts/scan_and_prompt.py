import io
import json
import os
import random
import time
import requests
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types
from pydantic import BaseModel

# ----------------------------------------------------
# 0. Delete Images Older Than 3 Days
# ----------------------------------------------------
IMAGE_DIR = "output/images"
os.makedirs(IMAGE_DIR, exist_ok=True)

def cleanup_old_images(directory: str, days: int = 3):
    """Deletes images from the target directory older than specified days."""
    now = time.time()
    cutoff_seconds = days * 86400  # 3 days in seconds

    for filename in os.listdir(directory):
        filepath = os.path.join(directory, filename)
        if os.path.isfile(filepath) and filename.lower().endswith((".png", ".jpg", ".jpeg")):
            file_age = now - os.path.getmtime(filepath)
            if file_age > cutoff_seconds:
                try:
                    os.remove(filepath)
                    print(f"Removed expired image (>3 days old): {filename}")
                except Exception as e:
                    print(f"Error removing {filename}: {e}")

cleanup_old_images(IMAGE_DIR, days=3)

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
# 2. Gemini Commentary for CoinMarketCap Community
# ----------------------------------------------------
class MoverItem(BaseModel):
    symbol: str
    name: str
    direction: str
    change_24h: float
    character: str
    comment: str

class MarketResponse(BaseModel):
    items: list[MoverItem]

client = genai.Client()

system_instruction = """
You are the creative director for The Pasture / CryptoCowz.
Generate a sharp, 1-2 sentence satirical CoinMarketCap community comment for each coin:
- For PUMP: Witty commentary on greed, sudden wealth, or bullish mania.
- For DUMP: Deadpan commentary on panic selling, bagholding, or market disaster.
Assign an on-brand MOO19 character (Skip Zinfandel, Sunshine Innocent Nimbus, Frank Rizzo, or Professor Hartmut).
"""

prompt = f"Selected Movers:\n{json.dumps(selected_pulls, indent=2)}"

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
movers_dict = {item.symbol: item for item in parsed_payload.items}

# ----------------------------------------------------
# 3. Canvas Construction (Matching Reference Layout)
# ----------------------------------------------------
markdown_lines = ["# Daily Top Movers: CMC Community Visuals & Posts\n"]

# Font handling: Look for bold sans-serif fonts in GitHub Linux runner environments
font_title = None
for path in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf"
]:
    if os.path.exists(path):
        try:
            font_title = ImageFont.truetype(path, 54)
            break
        except Exception:
            pass

if font_title is None:
    font_title = ImageFont.load_default()

def find_asset(name_without_ext):
    """Finds image files matching .png, .jpg, or .jpeg in assets/."""
    for ext in [".png", ".jpg", ".jpeg"]:
        target = os.path.join("assets", f"{name_without_ext}{ext}")
        if os.path.exists(target):
            return target
    return None

def draw_sample_style_card(filename: str, name: str, symbol: str, price: float, change: float, direction: str):
    # 1. Base 1200x675 White Canvas
    img = Image.new("RGBA", (1200, 675), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 2. Upper Headers (Exact placement matching reference)
    price_str = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
    change_str = f"{'+' if change > 0 else ''}{change}% 24h"

    draw.text((58, 48), f"{name.upper()} ({symbol})", fill=(0, 0, 0), font=font_title)
    draw.text((508, 48), price_str, fill=(0, 0, 0), font=font_title)
    draw.text((850, 48), change_str, fill=(0, 0, 0), font=font_title)

    # 3. 14 Candlesticks Scaled to Reference Arc
    num_candles = 14
    candle_w = 46
    candle_spacing = 71
    start_x = 88
    
    # Exact RGB tones from reference
    teal = (51, 153, 142, 255)
    coral = (235, 91, 86, 255)

    if direction == "PUMP":
        start_y = 425
        y_step = -18
    else:
        start_y = 195
        y_step = 18

    random.seed(hash(symbol))
    for i in range(num_candles):
        x = start_x + (i * candle_spacing)
        y = start_y + (i * y_step) + random.randint(-6, 6)

        # High probability matching current trend
        is_green = (direction == "PUMP") if (random.random() > 0.22) else (direction != "PUMP")
        color = teal if is_green else coral

        body_h = random.randint(24, 44)
        wick_h = random.randint(12, 22)

        top_b = y - (body_h // 2)
        bot_b = y + (body_h // 2)

        # Thin center wick
        center_x = x + (candle_w // 2)
        draw.line([(center_x, top_b - wick_h), (center_x, bot_b + wick_h)], fill=color, width=4)

        # Candle body
        draw.rectangle([(x, top_b), (x + candle_w, bot_b)], fill=color)

    # 4. Lower-Left Logo (CC_logo.png scaled to ~250px wide)
    logo_path = find_asset("CC_logo")
    if logo_path:
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((250, 100), Image.Resampling.LANCZOS)
        # Position with ~55px left margin and ~35px bottom margin
        img.paste(logo, (55, 675 - logo.height - 35), logo)

    # 5. Lower-Right Character (Scaled to ~315px tall, flush to bottom-right)
    char_prefix = "p" if direction == "PUMP" else "n"
    chosen_code = f"{char_prefix}{random.choice([1, 2, 3])}"
    char_path = find_asset(chosen_code)

    if char_path:
        char_img = Image.open(char_path).convert("RGBA")
        # Scale to match reference height (~46% of 675px canvas)
        char_img.thumbnail((300, 315), Image.Resampling.LANCZOS)
        char_x = 1200 - char_img.width
        char_y = 675 - char_img.height
        img.paste(char_img, (char_x, char_y), char_img)

    # Flatten and save
    final_output = img.convert("RGB")
    final_output.save(filename, "PNG")

# ----------------------------------------------------
# 4. Execution Loop
# ----------------------------------------------------
for idx, coin in enumerate(selected_pulls, 1):
    symbol = coin["symbol"]
    direction = coin["direction"]
    name = coin["name"]
    price = coin["price"]
    change = coin["change_24h"]

    mover_meta = movers_dict.get(symbol)
    comment = mover_meta.comment if mover_meta else f"${symbol} is on the move today."
    character = mover_meta.character if mover_meta else "Skip Zinfandel"

    filename = os.path.join(IMAGE_DIR, f"{idx:02d}_{direction}_{symbol}.png")
    print(f"Generating graphic {idx}/10: {symbol} ({direction})...")

    draw_sample_style_card(filename, name, symbol, price, change, direction)

    markdown_lines.append(f"## {idx}. {name} (${symbol}) — {'+' if change > 0 else ''}{change}% ({direction})")
    markdown_lines.append(f"**Cast Member:** {character}")
    markdown_lines.append(f"**CMC Comment:** {comment}\n")
    markdown_lines.append(f"![{symbol} Graphic](images/{os.path.basename(filename)})\n")
    markdown_lines.append("---\n")

with open("output/cmc_prompts_latest.md", "w") as f:
    f.write("\n".join(markdown_lines))

print("All 10 graphics generated and expired files cleaned.")
