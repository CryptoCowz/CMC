import io
import json
import os
import random
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

MANDATORY FOR IMAGE PROMPT:
Every image prompt MUST include a large, prominent digital candlestick chart display in the scene:
- For PUMP: A giant high-tech broadcast screen showing tall, glowing green candlestick bars breaking upward through a resistance line, with the token symbol and an arrow pointing up.
- For DUMP: A weather map radar or gritty alley terminal showing tall, plunging red candlestick bars dropping off a cliff, with red crash percentages and stormy graphics.
The aesthetic must be clean 2D vector animation style with bold outlines, flat cel shading, and CryptoCowz brand colors (pasture green #567D33, royal purple #6A0DAD, or corporate lavender #9F86C0).
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
# 3. Canvas Candlestick Chart Fallback Generator
# ----------------------------------------------------
os.makedirs("output/images", exist_ok=True)
markdown_lines = ["# Daily Top Movers: CMC Community Posts & Visuals\n"]

def draw_candlestick_chart(filename: str, symbol: str, direction: str, char: str, change: float, price: float):
    """Draws a complete 1200x675 branded candlestick chart graphic with gridlines and candles."""
    img = Image.new("RGB", (1200, 675), color=(18, 20, 24))
    draw = ImageDraw.Draw(img)

    # Header Panel
    header_color = (86, 125, 51) if direction == "PUMP" else (106, 13, 173)
    draw.rectangle([(0, 0), (1200, 110)], fill=header_color)
    draw.rectangle([(0, 106), (1200, 110)], fill=(255, 211, 0))

    draw.text((40, 25), f"MOO19 NEWS | THE PASTURE", fill=(255, 211, 0))
    draw.text((40, 58), f"${symbol}/USDT  •  24H {direction}", fill=(255, 255, 255))
    draw.text((850, 25), f"Price: ${price:,.4f}" if price < 1 else f"Price: ${price:,.2f}", fill=(255, 255, 255))
    draw.text((850, 58), f"24h Change: {'+' if change > 0 else ''}{change}%", fill=(0, 255, 128) if change > 0 else (255, 80, 80))

    # Chart Grid
    chart_x1, chart_y1, chart_x2, chart_y2 = 60, 150, 1140, 560
    draw.rectangle([(chart_x1, chart_y1), (chart_x2, chart_y2)], fill=(24, 27, 33), outline=(50, 56, 68), width=2)

    for y in range(chart_y1 + 50, chart_y2, 70):
        draw.line([(chart_x1, y), (chart_x2, y)], fill=(38, 43, 54), width=1)

    # Generate Synthetic Candlestick Series
    num_candles = 14
    candle_width = 44
    gap = (chart_x2 - chart_x1 - (num_candles * candle_width)) // (num_candles + 1)
    green_color = (38, 166, 154)
    red_color = (239, 83, 80)

    # Base price trajectory
    current_y = 440 if direction == "PUMP" else 220
    random.seed(hash(symbol))

    for i in range(num_candles):
        x = chart_x1 + gap + i * (candle_width + gap)

        if direction == "PUMP":
            is_green = True if i > (num_candles - 5) else (random.random() > 0.35)
            step = random.randint(10, 35) if is_green else random.randint(-15, 10)
            open_y = current_y
            close_y = max(chart_y1 + 30, open_y - step) if is_green else min(chart_y2 - 30, open_y + step)
        else:
            is_green = False if i > (num_candles - 5) else (random.random() > 0.65)
            step = random.randint(10, 35) if not is_green else random.randint(-10, 15)
            open_y = current_y
            close_y = min(chart_y2 - 30, open_y + step) if not is_green else max(chart_y1 + 30, open_y - step)

        current_y = close_y
        high_y = max(chart_y1 + 20, min(open_y, close_y) - random.randint(5, 25))
        low_y = min(chart_y2 - 20, max(open_y, close_y) + random.randint(5, 25))

        color = green_color if close_y < open_y else red_color

        # Draw Wick
        wick_x = x + (candle_width // 2)
        draw.line([(wick_x, high_y), (wick_x, low_y)], fill=color, width=3)

        # Draw Body
        top_body = min(open_y, close_y)
        bottom_body = max(open_y, close_y)
        if bottom_body - top_body < 4:
            bottom_body = top_body + 4
        draw.rectangle([(x, top_body), (x + candle_width, bottom_body)], fill=color)

    # Footer Reporter Badge
    draw.rectangle([(0, 595), (1200, 675)], fill=(12, 14, 18))
    draw.text((60, 620), f"MOO19 CORRESPONDENT: {char.upper()}", fill=(255, 211, 0))
    draw.text((800, 620), "CryptoCowz • The Pasture Edutainment", fill=(160, 160, 160))

    img.save(filename, "PNG")

# ----------------------------------------------------
# 4. Image Generation Loop
# ----------------------------------------------------
for idx, item in enumerate(movers_list, 1):
    symbol = item.symbol
    direction = item.direction
    char = item.character
    comment = item.comment
    img_prompt = item.image_prompt
    price = item.change_24h
    filename = f"output/images/{idx:02d}_{direction}_{symbol}.png"

    print(f"Generating chart visual {idx}/10: {symbol} ({direction}) with {char}...")

    image_saved = False
    try:
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
        print(f"Imagen generation unavailable for {symbol}: {e}")

    # Fallback to precise custom candlestick chart if AI image generation fails
    if not image_saved:
        draw_candlestick_chart(
            filename=filename,
            symbol=symbol,
            direction=direction,
            char=char,
            change=item.change_24h,
            price=next((p["price"] for p in selected_pulls if p["symbol"] == symbol), 0.0)
        )

    markdown_lines.append(f"## {idx}. {item.name} (${symbol}) — {item.change_24h}% ({direction})")
    markdown_lines.append(f"**Cast Member:** {char}")
    markdown_lines.append(f"**CMC Comment:** {comment}\n")
    markdown_lines.append(f"![{symbol} Candlestick Chart](images/{os.path.basename(filename)})\n")
    markdown_lines.append(f"**Google Flow / Scene Prompt:**\n> {img_prompt}\n")
    markdown_lines.append("---\n")

with open("output/cmc_prompts_latest.md", "w") as f:
    f.write("\n".join(markdown_lines))

print("Completed: All 10 candlestick charts and reports compiled.")
