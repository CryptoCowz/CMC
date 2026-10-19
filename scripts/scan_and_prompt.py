#!/usr/bin/env python3
"""Build a Wednesday/Friday CoinMarketCap review digest.

The digest names coins and pairs each one with a static lesson card
plus a ready-to-paste comment. It does not draw images and it does not post.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
SKIP_PATH = ROOT / "config" / "skip_coins.txt"
DIGEST_PATH = ROOT / "output" / "cmc_movers_latest.md"
NY = ZoneInfo("America/New_York")

MARKETS_URL = (
    "https://api.coingecko.com/api/v3/coins/markets"
    "?vs_currency=usd&order=market_cap_desc&per_page=100&page=1"
    "&sparkline=false&price_change_percentage=24h"
)

CARDS = {
    "mom": "assets/cards/cmc-mom-lesson-card-1080.png",
    "dad": "assets/cards/cmc-dad-lesson-card-1080.png",
    "twin": "assets/cards/cmc-twin-lesson-card-1080.png",
}
CARD_TITLES = {
    "mom": "Mom",
    "dad": "Dad",
    "twin": "Blue Twin",
}

# CoinGecko id -> CoinMarketCap slug, where the id itself is a broken
# page or a different coin. Anything absent here uses the id unchanged.
SLUG_OVERRIDES = {
    "binancecoin": "bnb",
    "ripple": "xrp",
    "near": "near-protocol",
    "leo-token": "unus-sed-leo",
    "hedera-hashgraph": "hedera",
    "crypto-com-chain": "cronos",
    "quant-network": "quant",
    "the-open-network": "gram",
    "render-token": "render",
    "kucoin-shares": "kucoin-token",
    "gatechain-token": "gatetoken",
    "injective-protocol": "injective",
    "pancakeswap-token": "pancakeswap",
    "pi-network": "pi",
    "blockstack": "stacks",
    "xdce-crowd-sale": "xdc-network",
    "worldcoin-wld": "worldcoin-org",
    "jupiter-exchange-solana": "jupiter",
    "bitget-token": "bitget-token-new",
    "htx-dao": "htx",
    "whitebit": "whitebit-token",
    "polkadot": "polkadot-new",
    "avalanche-2": "avalanche",
    "aster-2": "aster",
    "pearl-2": "pearlresearch",
    "midnight-3": "midnight-network",
    "bitway": "bitway-btw",
    "ether-fi": "ether-fi-ethfi",
    "world-liberty-financial": "world-liberty-financial-wlfi",
    "optimism": "optimism-ethereum",
    "fetch-ai": "artificial-superintelligence-alliance",
    "elrond-erd-2": "multiversx-egld",
    "theta-token": "theta-network",
    "dogwifcoin": "dogwifhat",
    "sei-network": "sei",
    "matic-network": "polygon",
    "staked-ether": "steth",
    "wrapped-steth": "lido-finance-wsteth",
}

# Whole words. "up" inside a longer coin name is still the coin's name.
WORD_BAN = re.compile(r"\b(up|down|buy|sell|pump|dump|moon)\b", re.IGNORECASE)
# These never belong in a pasted comment, even as part of a longer token.
SUBSTRING_BAN = ("pump", "dump", "buy", "sell", "moon")
PERCENT_BAN = re.compile(r"%|percent", re.IGNORECASE)

COMMENT = (
    "Busy day for {name}. Here's the herd's plain-words lesson 🐄 "
    "More at cryptocowz.substack.com"
)


class RadarError(Exception):
    """A clean failure the workflow can show without a stack trace."""


@dataclass
class Coin:
    name: str
    symbol: str
    coin_id: str
    change: float
    turnover: float | None

    @property
    def url(self) -> str:
        slug = SLUG_OVERRIDES.get(self.coin_id, self.coin_id)
        return f"https://coinmarketcap.com/currencies/{slug}/"


def is_review_day(now: datetime | None = None) -> bool:
    current = now or datetime.now(NY)
    if current.tzinfo is None:
        current = current.replace(tzinfo=NY)
    else:
        current = current.astimezone(NY)
    return current.weekday() in (2, 4)  # Wednesday, Friday


def forced_run(argv: list[str]) -> bool:
    flag = os.getenv("FORCE_DIGEST", "").strip().lower()
    return "--force" in argv or flag in {"1", "true", "yes"}


def load_skip_keys(path: Path) -> set[str]:
    if not path.is_file():
        raise RadarError(f"Skip list is missing: {path.relative_to(ROOT)}")
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip().lower()
        if line:
            keys.add(line)
    return keys


def clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def postable(name: str, symbol: str, coin_id: str) -> bool:
    """Keep a coin whose pasted comment would stay inside the wording rules."""
    blob = f"{name} {symbol} {coin_id}"
    lower = blob.lower()
    if any(token in lower for token in SUBSTRING_BAN):
        return False
    if WORD_BAN.search(lower) or PERCENT_BAN.search(blob) or "$" in blob:
        return False
    return True


def wording_problems(text: str) -> list[str]:
    problems: list[str] = []
    if PERCENT_BAN.search(text):
        problems.append("percent sign or the word percent")
    if "$" in text:
        problems.append("a currency mark")
    match = WORD_BAN.search(text)
    if match:
        problems.append(f"banned word {match.group(0)!r}")
    lower = text.lower()
    for token in SUBSTRING_BAN:
        if token in lower:
            problems.append(f"banned text {token!r}")
    return problems


def comment_for(name: str) -> str:
    return COMMENT.format(name=name)


def is_skipped(row: dict, skip_keys: set[str]) -> bool:
    fields = (
        clean_text(row.get("symbol")).lower(),
        clean_text(row.get("name")).lower(),
        clean_text(row.get("id")).lower(),
    )
    return any(field and field in skip_keys for field in fields)


def coin_from_row(row: dict) -> Coin | None:
    if not isinstance(row, dict):
        return None
    change = as_float(row.get("price_change_percentage_24h"))
    name = clean_text(row.get("name"))
    symbol = clean_text(row.get("symbol")).upper()
    coin_id = clean_text(row.get("id"))
    if change is None or not name or not symbol or not coin_id:
        return None
    cap = as_float(row.get("market_cap"))
    volume = as_float(row.get("total_volume"))
    turnover = None
    if cap is not None and volume is not None and cap > 0 and volume >= 0:
        turnover = volume / cap
    return Coin(name=name, symbol=symbol, coin_id=coin_id, change=change, turnover=turnover)


def prepare(rows: list, skip_keys: set[str]) -> tuple[list[Coin], int, int]:
    """Return postable coins plus how many the skip list and wording held back."""
    skipped = 0
    blocked = 0
    coins: list[Coin] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if is_skipped(row, skip_keys):
            skipped += 1
            continue
        coin = coin_from_row(row)
        if coin is None or coin.coin_id in seen:
            continue
        if not postable(coin.name, coin.symbol, coin.coin_id):
            blocked += 1
            continue
        seen.add(coin.coin_id)
        coins.append(coin)
    return coins, skipped, blocked


def top_gainers(coins: list[Coin], limit: int = 10) -> list[Coin]:
    ranked = [coin for coin in coins if coin.change > 0]
    ranked.sort(key=lambda coin: coin.change, reverse=True)
    return ranked[:limit]


def top_losers(coins: list[Coin], limit: int = 10) -> list[Coin]:
    ranked = [coin for coin in coins if coin.change < 0]
    ranked.sort(key=lambda coin: coin.change)
    return ranked[:limit]


def pick_hype(coins: list[Coin], reserved_ids: set[str]) -> Coin | None:
    """Highest 24h volume / market cap, skipping the Mom and Dad coins."""
    ranked = [coin for coin in coins if coin.turnover is not None]
    ranked.sort(key=lambda coin: coin.turnover or 0.0, reverse=True)
    for coin in ranked:
        if coin.coin_id not in reserved_ids:
            return coin
    return None


def fetch_markets(url: str, sleep_seconds: float = 3) -> list:
    headers = {
        "accept": "application/json",
        "user-agent": "CryptoCowzCMCRadar/1.0",
    }
    api_key = os.getenv("COINGECKO_API_KEY", "").strip()
    if api_key:
        headers["x-cg-demo-api-key"] = api_key

    last_status: int | None = None
    for attempt in range(2):
        try:
            response = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            if attempt == 0:
                time.sleep(sleep_seconds)
                continue
            raise RadarError("CoinGecko request failed. No digest written.") from exc

        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError as exc:
                raise RadarError(
                    "CoinGecko returned a body that is not JSON. No digest written."
                ) from exc
            if not isinstance(payload, list):
                raise RadarError(
                    "CoinGecko returned an unexpected payload. No digest written."
                )
            return payload

        last_status = response.status_code
        if response.status_code in {401, 403} and "x-cg-demo-api-key" in headers and attempt == 0:
            headers.pop("x-cg-demo-api-key", None)
            print("CoinGecko rejected the secret. Retrying on the public endpoint.")
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
            time.sleep(sleep_seconds)
            continue
        break

    status = last_status if last_status is not None else "unknown"
    raise RadarError(f"CoinGecko returned HTTP {status}. No digest written.")


def ensure_cards() -> None:
    missing = [path for path in CARDS.values() if not (ROOT / path).is_file()]
    if missing:
        raise RadarError("Lesson card files are missing: " + ", ".join(missing))


def _coin_lines(index: int | None, coin: Coin, card_key: str, pick: bool) -> list[str]:
    label = f"{index}. {coin.name} ({coin.symbol})" if index else f"{coin.name} ({coin.symbol})"
    if pick:
        label += " — Pick of the day"
    return [
        label,
        f"Page: {coin.url}",
        f"Card: {CARD_TITLES[card_key]} — {CARDS[card_key]}",
        f"Comment: {comment_for(coin.name)}",
        "",
    ]


def render_digest(
    when: datetime,
    gainers: list[Coin],
    losers: list[Coin],
    hype: Coin | None,
    skipped: int,
    blocked: int,
) -> str:
    local = when.astimezone(NY)
    mom = gainers[0] if gainers else None
    dad = losers[0] if losers else None
    lines = [
        "# CMC review digest",
        "",
        f"- When: {local:%A, %Y-%m-%d %H:%M} America/New_York",
        "- Who posts: a person, by hand, on Wednesday and Friday",
        "- What this file is: a radar for that review",
        "",
        "Links are a best effort. The slug starts from the CoinGecko id, with known",
        "fixes where that id points at the wrong page. Confirm the page before posting.",
        "",
        "## Picks of the day",
        "",
    ]

    if mom is None and dad is None and hype is None:
        lines.extend(["No coins left to list.", ""])
    if mom is not None:
        lines.append("### Mom card — largest gainer")
        lines.append("")
        lines.extend(_coin_lines(None, mom, "mom", True))
    if dad is not None:
        lines.append("### Dad card — largest loser")
        lines.append("")
        lines.extend(_coin_lines(None, dad, "dad", True))
    if hype is not None:
        lines.append("### Blue Twin card — highest turnover")
        lines.append("")
        lines.append(
            "Heuristic: 24h volume divided by market cap, across the filtered top 100."
        )
        lines.append(
            "Mom and Dad keep their own coins. Blue Twin takes the next coin when"
        )
        lines.append("the turnover leader is already one of those two.")
        lines.append("")
        lines.extend(_coin_lines(None, hype, "twin", True))

    lines.extend(["## Gainers", ""])
    if gainers:
        lines.append("Suggested card is Mom, unless the Blue Twin pick is in this list.")
        lines.append("")
        for index, coin in enumerate(gainers, start=1):
            card_key = "twin" if hype and coin.coin_id == hype.coin_id else "mom"
            pick = mom is not None and coin.coin_id == mom.coin_id
            lines.extend(_coin_lines(index, coin, card_key, pick or card_key == "twin"))
    else:
        lines.extend(["None today.", ""])

    lines.extend(["## Losers", ""])
    if losers:
        lines.append("Suggested card is Dad, unless the Blue Twin pick is in this list.")
        lines.append("")
        for index, coin in enumerate(losers, start=1):
            card_key = "twin" if hype and coin.coin_id == hype.coin_id else "dad"
            pick = dad is not None and coin.coin_id == dad.coin_id
            lines.extend(_coin_lines(index, coin, card_key, pick or card_key == "twin"))
    else:
        lines.extend(["None today.", ""])

    lines.extend(
        [
            "## Radar notes",
            "",
            f"- Skip list: {skipped}",
            f"- Names left off so the comment stays pasteable: {blocked}",
            "- Cards live in assets/cards/ and stay free of any coin name.",
            "",
        ]
    )
    text = "\n".join(lines)
    problems = wording_problems(text)
    if problems:
        raise RadarError("Digest blocked by wording check: " + "; ".join(problems))
    return text


def build_from_rows(rows: list, skip_keys: set[str], when: datetime) -> str:
    coins, skipped, blocked = prepare(rows, skip_keys)
    gainers = top_gainers(coins)
    losers = top_losers(coins)
    reserved = {coin.coin_id for coin in (gainers[:1] + losers[:1])}
    hype = pick_hype(coins, reserved)
    return render_digest(when, gainers, losers, hype, skipped, blocked)


def run_scan(argv: list[str]) -> int:
    now = datetime.now(NY)
    if not forced_run(argv) and not is_review_day(now):
        print(
            f"America/New_York is {now:%A}. "
            "Digest is written on Wednesday and Friday only."
        )
        return 0
    if forced_run(argv) and not is_review_day(now):
        print(f"Manual run on {now:%A}. Writing a digest anyway.")

    try:
        ensure_cards()
        skip_keys = load_skip_keys(SKIP_PATH)
        rows = fetch_markets(MARKETS_URL)
        text = build_from_rows(rows, skip_keys, now)
    except RadarError as exc:
        print(str(exc))
        return 1

    DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_PATH.write_text(text, encoding="utf-8")
    print("DIGEST_WRITTEN=1", flush=True)
    print(f"Wrote {DIGEST_PATH.relative_to(ROOT)}", flush=True)
    return 0


def run_self_check() -> None:
    from datetime import timezone

    wednesday = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    friday = datetime(2026, 10, 23, 8, 0, tzinfo=NY)
    monday = datetime(2026, 10, 19, 8, 0, tzinfo=NY)
    assert is_review_day(wednesday), wednesday.astimezone(NY)
    assert is_review_day(friday)
    assert not is_review_day(monday)

    assert comment_for("Bitcoin") == (
        "Busy day for Bitcoin. Here's the herd's plain-words lesson 🐄 "
        "More at cryptocowz.substack.com"
    )
    assert Coin("Bitcoin", "BTC", "bitcoin", 1, 0.1).url.endswith("/bitcoin/")
    assert Coin("BNB", "BNB", "binancecoin", 1, 0.1).url.endswith("/bnb/")
    assert Coin("Pearl", "PRL", "pearl-2", 1, 0.1).url.endswith("/pearlresearch/")
    assert Coin("Ether.fi", "ETHFI", "ether-fi", 1, 0.1).url.endswith("/ether-fi-ethfi/")
    assert Coin("Worldcoin", "WLD", "worldcoin-wld", 1, 0.1).url.endswith("/worldcoin-org/")
    assert Coin("Midnight", "NIGHT", "midnight-3", 1, 0.1).url.endswith("/midnight-network/")
    assert Coin("Bitway", "BTW", "bitway", 1, 0.1).url.endswith("/bitway-btw/")

    assert postable("Bitcoin", "BTC", "bitcoin")
    assert postable("Jupiter", "JUP", "jupiter-exchange-solana")
    assert not postable("Pump.fun", "PUMP", "pump-fun")
    assert not postable("Up Only", "UP", "up-only")

    keys = load_skip_keys(SKIP_PATH)
    assert is_skipped({"symbol": "USDT", "name": "Tether", "id": "tether"}, keys)
    assert is_skipped({"symbol": "stETH", "name": "Lido Staked Ether", "id": "staked-ether"}, keys)
    assert is_skipped({"symbol": "WBTC", "name": "Wrapped Bitcoin", "id": "wrapped-bitcoin"}, keys)
    assert not is_skipped({"symbol": "BTC", "name": "Bitcoin", "id": "bitcoin"}, keys)
    assert not is_skipped({"symbol": "WBT", "name": "WhiteBIT Coin", "id": "whitebit"}, keys)
    assert not is_skipped({"symbol": "ENA", "name": "Ethena", "id": "ethena"}, keys)

    rows = [
        {"id": "tether", "symbol": "usdt", "name": "Tether", "price_change_percentage_24h": 0.01,
         "market_cap": 1, "total_volume": 1, "current_price": 1},
        {"id": "pump-fun", "symbol": "pump", "name": "Pump.fun", "price_change_percentage_24h": 40,
         "market_cap": 10, "total_volume": 9, "current_price": 0.004},
        {"id": "quack-ai", "symbol": "q", "name": "Quack AI", "price_change_percentage_24h": 50,
         "market_cap": 100, "total_volume": 20, "current_price": 0.2},
        {"id": "injective-protocol", "symbol": "inj", "name": "Injective",
         "price_change_percentage_24h": 1, "market_cap": 100, "total_volume": 90, "current_price": 8},
        {"id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "price_change_percentage_24h": 0.4,
         "market_cap": 1000, "total_volume": 10, "current_price": 60000},
        {"id": "bitway", "symbol": "btw", "name": "Bitway", "price_change_percentage_24h": -8,
         "market_cap": 200, "total_volume": 4, "current_price": 0.1},
        {"id": "aerodrome-finance", "symbol": "aero", "name": "Aerodrome Finance",
         "price_change_percentage_24h": -4, "market_cap": 80, "total_volume": 4, "current_price": 0.5},
    ]
    text = build_from_rows(rows, keys, monday)
    assert "Quack AI (Q)" in text
    assert "Bitway (BTW)" in text
    assert "Injective (INJ)" in text
    assert "/injective/" in text
    assert "/bitway-btw/" in text
    assert "cmc-mom-lesson-card-1080.png" in text
    assert "cmc-dad-lesson-card-1080.png" in text
    assert "cmc-twin-lesson-card-1080.png" in text
    assert "Tether" not in text
    assert "Pump.fun" not in text
    for leaked in ("50", "0.4", "60000", "0.004", "%", "$"):
        assert leaked not in text, leaked
    assert wording_problems(text) == []
    assert "- Skip list: 1" in text
    assert "- Names left off so the comment stays pasteable: 1" in text

    _check_fetch_failures()
    print("Self-check passed.")


def _check_fetch_failures() -> None:
    seen: list[tuple[int, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            status, body = seen.pop(0)
            data = body.encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}/markets"
        seen.append((200, '{"error":"nope"}'))
        try:
            fetch_markets(base, sleep_seconds=0)
        except RadarError as exc:
            assert "unexpected payload" in str(exc)
        else:
            raise AssertionError("dict payload should fail")

        seen.append((404, "missing"))
        try:
            fetch_markets(base, sleep_seconds=0)
        except RadarError as exc:
            assert "HTTP 404" in str(exc)
        else:
            raise AssertionError("404 should fail")

        seen.extend([(429, "{}"), (200, "[]")])
        assert fetch_markets(base, sleep_seconds=0) == []
    finally:
        server.shutdown()

    try:
        fetch_markets("http://127.0.0.1:9/nope", sleep_seconds=0)
    except RadarError as exc:
        assert "request failed" in str(exc)
    else:
        raise AssertionError("closed port should fail")


def main(argv: list[str]) -> int:
    if "--self-check" in argv:
        run_self_check()
        return 0
    return run_scan(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
