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
    now = time.time()
    cutoff_seconds = days * 86400

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
# 1. Global Asset Discovery Engine
# ----------------------------------------------------
REPO_ASSET_MAP = {}
print("Indexing repository image assets...")

# Search both current working directory and the parent of scripts/
search_roots = [os.getcwd(), os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))]
search_roots = list(set(search_roots))

for base in search_roots:
    for root, dirs, files in os.walk(base):
        # Skip git and output folders
        if ".git" in root or "output" in root:
            continue
        for file in files:
            stem, ext = os.path.splitext(file)
            if ext.lower() in [".png", ".jpg", ".jpeg"]:
                key = stem.lower()
                full_path = os.path.join(root, file)
                # Store if not already mapped or if in assets folder
                if key not in REPO_ASSET_MAP or "assets" in full_path.lower():
                    REPO_ASSET_MAP[key] = full_path

print(f"Found {len(REPO_ASSET_MAP)} indexed asset(s): {list(REPO_ASSET_MAP.keys())}")

def load_asset_image(stem_name: str) -> Image.Image:
    """Loads an asset, handling transparent PNGs or dark-backed JPEGs automatically."""
    path = REPO_ASSET_MAP.get(stem_name.lower())
    if not path or not os.path.exists(path):
        print(f"[!] Asset '{stem_name}' not found anywhere in repo.")
        return None

    img = Image.open(path).convert("RGBA")

    # If it's a JPEG or solid background image, key out dark background (< 15 RGB)
    datas = img.getdata()
    new_data = []
    has_alpha = False
    for item in datas:
        if item[3] < 240:
            has_alpha = True
            new_data.append(item)
        elif item[0] < 15 and item[1] < 15 and item[2] < 15:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(item)

    if not has_alpha:
        img.putdata(new_data)

    return img

# ----------------------------------------------------
# 2. Fetch Top 5 Gainers & Top 5 Losers (CoinGecko)
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
# 3. Gemini Commentary for CoinMarketCap Community
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
# 4. Canvas Drawing Engine (1200 x 675 px)
# ----------------------------------------------------
font_title = None
for path in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf"
]:
    if os.path.exists(path):
        try:
            font_title = ImageFont.truetype(path, 42)
            break
        except Exception:
            pass

if font_title is None:
    font_title = ImageFont.load_default()

def draw_sample_style_card(filename: str, name: str, symbol: str, price: float, change: float, direction: str):
    img = Image.new("RGBA", (1200, 675), color=(255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 1. Header Placement
    display_name = f"{name.upper()} ({symbol})"
    if len(display_name) > 18:
        display_name = f"{name[:15].upper()}... ({symbol})"

    price_str = f"${price:,.4f}" if price < 1 else f"${price:,.2f}"
    change_str = f"{'+' if change > 0 else ''}{change}% 24h"

    draw.text((60, 48), display_name, fill=(0, 0, 0), font=font_title)
    draw.text((550, 48), price_str, fill=(0, 0, 0), font=font_title)
    draw.text((880, 48), change_str, fill=(0, 0, 0), font=font_title)

    # 2. 14 Candlesticks Arc
    num_candles = 14
    candle_w = 46
    candle_spacing = 71
    start_x = 88
    
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

        is_green = (direction == "PUMP") if (random.random() > 0.22) else (direction != "PUMP")
        color = teal if is_green else coral

        body_h = random.randint(24, 44)
        wick_h = random.randint(12, 22)

        top_b = y - (body_h // 2)
        bot_b = y + (body_h // 2)

        center_x = x + (candle_w // 2)
        draw.line([(center_x, top_b - wick_h), (center_x, bot_b + wick_h)], fill=color, width=4)
        draw.rectangle([(x, top_b), (x + candle_w, bot_b)], fill=color)

    # 3. Lower-Left Logo (CC_logo.png)
    logo_img = load_asset_image("cc_logo")
    if logo_img:
        logo_img.thumbnail((250, 100), Image.Resampling.LANCZOS)
        img.paste(logo_img, (55, 675 - logo_img.height - 35), mask=logo_img)
    else:
        print("[!] cc_logo could not be pasted.")

    # 4. Lower-Right Character
    if direction == "PUMP":
        candidates = ["p1", "p2", "p3", "3"]
    else:
        candidates = ["n1", "n2", "n3"]

    random.shuffle(candidates)
    char_img = None
    chosen_name = None
    for cand in candidates:
        char_img = load_asset_image(cand)
        if char_img:
            chosen_name = cand
            break

    if char_img:
        char_img.thumbnail((300, 315), Image.Resampling.LANCZOS)
        char_x = 1200 - char_img.width
        char_y = 675 - char_img.height
        img.paste(char_img, (char_x, char_y), mask=char_img)
        print(f"[✓] Pasted character '{chosen_name}' for {symbol}")
    else:
        print(f"[!] No character image found from options: {candidates}")

    final_output = img.convert("RGB")
    final_output.save(filename, "PNG")

# ----------------------------------------------------
# 5. Execution Loop
# ----------------------------------------------------
markdown_lines = ["# Daily Top Movers: CMC Community Visuals & Posts\n"]

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

print("All 10 graphics generated successfully.")
