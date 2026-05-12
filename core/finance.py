"""
Finance Manager — stock prices, crypto prices, currency conversion.
Uses free public APIs (no API key required).
"""

import requests
from typing import Optional


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EXCHANGE_RATE_URL = "https://api.exchangerate-api.com/v4/latest/"


class FinanceManager:

    @staticmethod
    def stock_price(symbol: str) -> Optional[dict]:
        """Get current stock price for a ticker symbol (e.g. AAPL, TSLA)."""
        symbol = symbol.upper().strip()
        try:
            resp = requests.get(
                f"{YAHOO_CHART_URL}{symbol}",
                params={"range": "1d", "interval": "1m"},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("chart", {}).get("result", [None])[0]
            if not result:
                return None
            meta = result.get("meta", {})
            quotes = result.get("indicators", {}).get("quote", [{}])[0]
            closes = quotes.get("close", [])
            current = [c for c in closes if c is not None]
            return {
                "symbol": symbol,
                "name": meta.get("symbolName", symbol),
                "price": current[-1] if current else None,
                "previous_close": meta.get("chartPreviousClose"),
                "currency": meta.get("currency", "USD"),
                "exchange": meta.get("exchangeName", ""),
                "market_state": meta.get("marketState", ""),
                "change": round(current[-1] - meta.get("chartPreviousClose", current[-1]), 2)
                if current and meta.get("chartPreviousClose") else None,
            }
        except Exception:
            return None

    @staticmethod
    def stock_price_with_change(symbol: str) -> Optional[dict]:
        """Get stock price with percent change (using quote data)."""
        data = FinanceManager.stock_price(symbol)
        if not data or data.get("price") is None:
            return data
        prev = data.get("previous_close")
        price = data.get("price")
        if prev and prev > 0 and price:
            data["change_pct"] = round((price - prev) / prev * 100, 2)
            data["direction"] = "up" if price > prev else ("down" if price < prev else "flat")
        return data

    @staticmethod
    def crypto_price(coin: str = "bitcoin", currency: str = "usd") -> Optional[dict]:
        """Get current cryptocurrency price."""
        coin = coin.lower().strip()
        currency = currency.lower().strip()
        try:
            resp = requests.get(
                COINGECKO_URL,
                params={"ids": coin, "vs_currencies": currency, "include_24hr_change": "true"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if coin not in data:
                return None
            coin_data = data[coin]
            key = currency
            key_24h = f"{currency}_24h_change"
            return {
                "coin": coin,
                "price": coin_data.get(key),
                "currency": currency.upper(),
                "change_24h_pct": round(coin_data.get(key_24h, 0), 2) if coin_data.get(key_24h) else None,
            }
        except Exception:
            return None

    @staticmethod
    def convert_currency(amount: float, from_currency: str, to_currency: str) -> Optional[dict]:
        """Convert amount between currencies."""
        from_currency = from_currency.upper().strip()
        to_currency = to_currency.upper().strip()
        try:
            resp = requests.get(f"{EXCHANGE_RATE_URL}{from_currency}", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            rates = data.get("rates", {})
            if to_currency not in rates:
                return None
            rate = rates[to_currency]
            return {
                "amount": amount,
                "from": from_currency,
                "to": to_currency,
                "rate": rate,
                "result": round(amount * rate, 2),
                "last_updated": data.get("date", ""),
            }
        except Exception:
            return None

    @staticmethod
    def top_gainers() -> Optional[list]:
        """Get top market movers (simplified — returns popular tickers)."""
        popular = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
        results = []
        for sym in popular:
            data = FinanceManager.stock_price_with_change(sym)
            if data:
                results.append(data)
        return results


finance_manager = FinanceManager()
