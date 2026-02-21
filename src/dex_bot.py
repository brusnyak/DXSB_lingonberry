import json
import logging
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
load_dotenv()

from src.adapters.market_adapters import DexScreenerAdapter, BinanceAdapter, StockAdapter, Candle
from src.analysis.ict_analyst import ICTAnalyst
from src.core.reasoning_engine import ReasoningEngine
from src.core.performance_journal import PerformanceJournal

try:
    from web3 import Web3
except ImportError:  # Optional dependency for EVM gas checks
    Web3 = None


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("dxsb")


DEX_BASE_URL = "https://api.dexscreener.com"
HONEYPOT_URL = "https://api.honeypot.is/v2/IsHoneypot"
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{token}/report"


@dataclass
class SignalDecision:
    approved: bool
    reason: str
    signal: Optional[Dict] = None


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, message: str) -> bool:
        if not self.token or not self.chat_id:
            logger.warning("Telegram is not configured; message skipped")
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            response = requests.post(url, json=payload, timeout=12)
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Telegram send failed: %s", exc)
            return False

    def get_updates(self) -> List[str]:
        """Polls Telegram for new messages. Minimalist implementation."""
        if not self.token:
            return []
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        try:
            # We use a very short timeout and offset logic
            # For simplicity in this bot, we'll just fetch latest few
            resp = requests.get(url, params={"limit": 10, "timeout": 1}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                messages = []
                for result in data.get("result", []):
                    text = result.get("message", {}).get("text")
                    if text:
                        messages.append(text)
                # To avoid repeating same commands, a real bot would use 'offset'
                # but for this specific request, we'll assume the user sends it and we process.
                # Actually, let's use a simple offset to not double-trigger.
                if data.get("result"):
                    last_id = data["result"][-1]["update_id"]
                    requests.get(url, params={"offset": last_id + 1}, timeout=5)
                return messages
        except:
            pass
        return []


class DexScreenerClient:
    def __init__(self, timeout_sec: int = 10):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "DXSB-Lingonberry/1.0",
        })
        self.timeout_sec = timeout_sec

    def _get(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        url = f"{DEX_BASE_URL}{path}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout_sec)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("DexScreener request failed (%s): %s", path, exc)
            return None

    def fetch_latest_token_profiles(self) -> List[Dict]:
        data = self._get("/token-profiles/latest/v1")
        return data if isinstance(data, list) else []

    def fetch_pairs_by_tokens(self, chain_id: str, token_addresses: List[str]) -> List[Dict]:
        if not token_addresses:
            return []

        dedup: Dict[str, Dict] = {}
        for i in range(0, len(token_addresses), 30):
            chunk = token_addresses[i:i + 30]
            token_list = ",".join(chunk)
            data = self._get(f"/tokens/v1/{chain_id}/{token_list}")
            if isinstance(data, list):
                for pair in data:
                    pair_address = str(pair.get("pairAddress", "")).lower()
                    if pair_address:
                        dedup[pair_address] = pair
        return list(dedup.values())

    def search_pairs(self, query: str) -> List[Dict]:
        data = self._get("/latest/dex/search", params={"q": query})
        pairs = data.get("pairs", []) if isinstance(data, dict) else []
        return pairs if isinstance(pairs, list) else []

    def get_pair(self, chain_id: str, pair_address: str) -> Optional[Dict]:
        data = self._get(f"/latest/dex/pairs/{chain_id}/{pair_address}")
        if not isinstance(data, dict):
            return None

        if isinstance(data.get("pair"), dict):
            return data["pair"]

        pairs = data.get("pairs")
        if isinstance(pairs, list) and pairs:
            return pairs[0]

        return None


class RiskChecker:
    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.cache: Dict[str, Tuple[bool, str, float]] = {}  # {address: (pass, reason, expiry)}
        self.cache_ttl_sec = 3600  # 1 hour for risk checks

    def check(self, chain_id: str, token_address: str) -> Tuple[bool, str]:
        # Cache lookup
        if token_address in self.cache:
            success, reason, expiry = self.cache[token_address]
            if time.time() < expiry:
                return success, f"Cached: {reason}"

        if chain_id.lower() == "solana":
            success, reason = self._check_solana(token_address)
        else:
            success, reason = self._check_evm(token_address)
        
        # Only cache definitive results (don't cache rate limits or server errors)
        if "rate limited" not in reason.lower() and "unavailable" not in reason.lower():
            self.cache[token_address] = (success, reason, time.time() + self.cache_ttl_sec)
            
        return success, reason

    def _check_evm(self, token_address: str) -> Tuple[bool, str]:
        try:
            response = requests.get(HONEYPOT_URL, params={"address": token_address}, timeout=10)
            if response.status_code == 429:
                return False, "Rate limited by Honeypot.is"
            if response.status_code == 404:
                return True, "Honeypot: Not indexed (Unknown)"
            
            response.raise_for_status()
            data = response.json()

            if data.get("honeypotResult", {}).get("isHoneypot", False):
                return False, "Honeypot flagged"

            summary = data.get("summary", {})
            risk_level = str(summary.get("risk", "unknown")).lower()
            if risk_level in {"high", "critical"}:
                return False, f"High risk ({risk_level})"

            return True, "Honeypot check passed"
        except Exception as exc:
            if self.strict_mode:
                return False, f"Honeypot check unavailable ({exc})"
            return True, "Honeypot check skipped"

    def _check_solana(self, token_address: str) -> Tuple[bool, str]:
        try:
            url = RUGCHECK_URL.format(token=token_address)
            response = requests.get(url, timeout=10)
            if response.status_code == 429:
                return False, "Rate limited by Rugcheck"
            
            response.raise_for_status()
            data = response.json()

            score = data.get("score")
            if isinstance(score, (int, float)) and score < 600:
                return False, f"Rugcheck score too low ({score})"

            if data.get("isSupplyBundled") is True:
                return False, "Bundled supply detected"

            risks = data.get("risks", [])
            if isinstance(risks, list):
                severe = [r for r in risks if str(r.get("level", "")).lower() in {"high", "critical"}]
                if severe:
                    return False, "High-severity rugcheck risks"

            return True, "Rugcheck passed"
        except Exception as exc:
            if self.strict_mode:
                return False, f"Rugcheck unavailable ({exc})"
            return True, "Rugcheck skipped"


class Strategy:
    def __init__(self, config: Dict):
        self.config = config

    def evaluate(self, pair: Dict) -> SignalDecision:
        trade_cfg = self.config["trading"]
        filt = self.config["filters"]

        price = safe_float(pair.get("priceUsd"))
        liquidity = safe_float(pair.get("liquidity", {}).get("usd"))
        volume_24h = safe_float(pair.get("volume", {}).get("h24"))
        fdv = safe_float(pair.get("fdv"))
        age_hours = pair_age_hours(pair)

        if price <= 0:
            return SignalDecision(False, "Invalid price")
        if liquidity < filt["min_liquidity_usd"] or liquidity > filt["max_liquidity_usd"]:
            return SignalDecision(False, "Liquidity outside configured range")
        if volume_24h < filt["min_volume_24h_usd"]:
            return SignalDecision(False, "24h volume too low")
        if fdv > 0 and fdv > filt["max_fdv_usd"]:
            return SignalDecision(False, "FDV too high")
        if age_hours < filt["min_age_hours"] or age_hours > filt["max_age_hours"]:
            return SignalDecision(False, "Age outside configured range")

        score = quality_score(pair)
        quality = quality_bucket(score)
        if quality not in trade_cfg["allowed_quality_buckets"]:
            return SignalDecision(False, f"Quality bucket rejected ({quality})")

        risk_pct = trade_cfg["risk_by_quality_pct"][quality]
        stop_pct = liquidity_based_stop_pct(liquidity)
        tp1_pct = round(stop_pct * trade_cfg["tp1_rr"], 2)
        tp2_pct = round(stop_pct * trade_cfg["tp2_rr"], 2)

        bankroll = trade_cfg["bankroll_usd"]
        risk_usd = bankroll * (risk_pct / 100.0)
        position_usd = risk_usd / (stop_pct / 100.0)

        max_pos_usd = bankroll * (trade_cfg["max_position_pct_bankroll"] / 100.0)
        position_usd = min(position_usd, max_pos_usd)

        slippage_est = estimated_slippage_pct(position_usd, liquidity, trade_cfg["slippage_impact_multiplier"])
        if slippage_est > trade_cfg["max_slippage_pct"]:
            return SignalDecision(False, f"Slippage estimate too high ({slippage_est:.2f}%)")

        # Buy/Sell Ratio Analysis
        tx_24 = pair.get("txns", {}).get("h24", {}) if isinstance(pair.get("txns"), dict) else {}
        buys = safe_float(tx_24.get("buys"))
        sells = safe_float(tx_24.get("sells"))
        bs_ratio = buys / max(sells, 1) if buys > 0 else 0

        # Volume Health
        vol_h1 = safe_float(pair.get("volume", {}).get("h1"))
        vol_h24 = safe_float(pair.get("volume", {}).get("h24"))
        vol_consistency = (vol_h1 * 24) / max(vol_h24, 1)

        horizon = "intraday" if age_hours <= 24 else "swing"
        expected_hold = "2-12h" if horizon == "intraday" else "1-3d"
        max_hold_hours = 12 if horizon == "intraday" else 72

        signal = {
            "quality": quality,
            "score": round(score, 1),
            "horizon": horizon,
            "expected_hold": expected_hold,
            "entry_price": price,
            "stop_pct": stop_pct,
            "tp1_pct": tp1_pct,
            "tp2_pct": tp2_pct,
            "risk_pct": risk_pct,
            "risk_usd": round(risk_usd, 2),
            "position_usd": round(position_usd, 2),
            "slippage_est_pct": round(slippage_est, 2),
            "age_hours": round(age_hours, 1),
            "liquidity_usd": round(liquidity, 2),
            "volume_24h_usd": round(volume_24h, 2),
            "vol_h1_usd": round(vol_h1, 2),
            "fdv_usd": round(fdv, 2),
            "bs_ratio": round(bs_ratio, 2),
            "vol_consistency": round(vol_consistency, 2),
            "rr_to_tp2": round(tp2_pct / stop_pct, 2),
            "max_hold_hours": max_hold_hours,
        }
        return SignalDecision(True, "Approved", signal)


def liquidity_based_stop_pct(liquidity_usd: float) -> float:
    if liquidity_usd >= 1_000_000:
        return 6.5
    if liquidity_usd >= 500_000:
        return 8.0
    if liquidity_usd >= 250_000:
        return 9.5
    if liquidity_usd >= 100_000:
        return 11.0
    if liquidity_usd >= 50_000:
        return 13.0
    return 15.0


def estimated_slippage_pct(position_usd: float, liquidity_usd: float, multiplier: float) -> float:
    if liquidity_usd <= 0:
        return 99.0
    return (position_usd / liquidity_usd) * 100.0 * multiplier


def quality_score(pair: Dict) -> float:
    liquidity = safe_float(pair.get("liquidity", {}).get("usd"))
    volume_24h = safe_float(pair.get("volume", {}).get("h24"))
    volume_h1 = safe_float(pair.get("volume", {}).get("h1"))

    tx_24 = pair.get("txns", {}).get("h24", {}) if isinstance(pair.get("txns"), dict) else {}
    buys = safe_float(tx_24.get("buys"))
    sells = safe_float(tx_24.get("sells"))
    total_tx = buys + sells
    bs_ratio = buys / max(sells, 1) if buys > 0 else 0

    price_change_1h = safe_float(pair.get("priceChange", {}).get("h1"))
    price_change_6h = safe_float(pair.get("priceChange", {}).get("h6"))

    liq_component = clamp(math.log10(max(liquidity, 1)) / 6.0, 0, 1) * 25
    vol_component = clamp((volume_24h / max(liquidity, 1)) / 5.0, 0, 1) * 20
    tx_component = clamp(total_tx / 800.0, 0, 1) * 15
    trend_component = (
        clamp((price_change_1h + 10) / 20.0, 0, 1) * 15 +
        clamp((price_change_6h + 20) / 40.0, 0, 1) * 10
    )
    ratio_component = clamp(bs_ratio / 2.0, 0, 1) * 10
    vol_health = clamp((volume_h1 * 24) / max(volume_24h, 1), 0, 1) * 5

    return liq_component + vol_component + tx_component + trend_component + ratio_component + vol_health


def quality_bucket(score: float) -> str:
    if score >= 82:
        return "A+"
    if score >= 70:
        return "A"
    if score >= 58:
        return "B"
    return "C"


def safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def pair_age_hours(pair: Dict) -> float:
    created_ms = pair.get("pairCreatedAt")
    if not created_ms:
        return 0.0
    created_at = datetime.fromtimestamp(created_ms / 1000.0, tz=timezone.utc)
    return (datetime.now(tz=timezone.utc) - created_at).total_seconds() / 3600.0


class DexSignalBot:
    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.db = self._init_db(self.config["database_path"])
        self.dex_client = DexScreenerClient(timeout_sec=self.config["runtime"]["http_timeout_sec"])
        self.notifier = TelegramNotifier(
            token=self.config["telegram"]["bot_token"],
            chat_id=self.config["telegram"]["chat_id"],
        )
        self.risk_checker = RiskChecker(strict_mode=self.config["risk_checks"]["strict_mode"])
        self.strategy = Strategy(self.config)
        
        # New Modular Components
        self.ict_analyst = ICTAnalyst()
        self.reasoning = ReasoningEngine(self.config)
        self.journal = PerformanceJournal(self.config["database_path"])
        self.adapters = [
            DexScreenerAdapter(self.dex_client, self.config),
            BinanceAdapter(),
            StockAdapter(self.config)
        ]

    def _load_config(self, path: str) -> Dict:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        env_token = os.getenv("TELEGRAM_BOT_TOKEN")
        env_chat = os.getenv("TELEGRAM_CHAT_ID")
        if env_token:
            config["telegram"]["bot_token"] = env_token
        if env_chat:
            config["telegram"]["chat_id"] = env_chat

        required_paths = [
            ("telegram", "bot_token"),
            ("telegram", "chat_id"),
            ("trading", "bankroll_usd"),
            ("filters", "min_liquidity_usd"),
            ("filters", "max_liquidity_usd"),
        ]
        for section, key in required_paths:
            if key not in config.get(section, {}):
                raise ValueError(f"Missing config value: {section}.{key}")

        if config["runtime"]["scan_interval_sec"] < 30:
            raise ValueError("scan_interval_sec must be >= 30")

        return config

    def run(self):
        logger.info("DXSB Bot Started. Entering main loop...")
        while True:
            try:
                self._check_telegram_commands()
                self._update_open_signals()
                self.run_cycle()
            except Exception as exc:
                logger.exception("Main loop failure: %s", exc)
                time.sleep(30)

    def _init_db(self, db_path: str) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                chain_id TEXT NOT NULL,
                pair_address TEXT NOT NULL,
                token_address TEXT NOT NULL,
                symbol TEXT NOT NULL,
                quality TEXT NOT NULL,
                score REAL NOT NULL,
                horizon TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_pct REAL NOT NULL,
                tp1_pct REAL NOT NULL,
                tp2_pct REAL NOT NULL,
                risk_pct REAL NOT NULL,
                risk_usd REAL NOT NULL,
                position_usd REAL NOT NULL,
                slippage_est_pct REAL NOT NULL,
                max_hold_hours REAL NOT NULL,
                status TEXT NOT NULL,
                alert_state TEXT DEFAULT 'IDENTIFIED',
                reminder_count INTEGER DEFAULT 0,
                adapter_type TEXT DEFAULT 'DexScreenerAdapter',
                reasoning TEXT,
                close_reason TEXT,
                close_price REAL,
                close_ts_utc TEXT,
                pnl_r REAL,
                UNIQUE(chain_id, pair_address, ts_utc)
            )
            """
        )
        self._ensure_column(conn, "signals", "max_hold_hours", "REAL NOT NULL DEFAULT 24")
        self._ensure_column(conn, "signals", "alert_state", "TEXT DEFAULT 'IDENTIFIED'")
        self._ensure_column(conn, "signals", "reminder_count", "INTEGER DEFAULT 0")
        self._ensure_column(conn, "signals", "adapter_type", "TEXT DEFAULT 'DexScreenerAdapter'")
        self._ensure_column(conn, "signals", "reasoning", "TEXT")
        conn.commit()
        return conn

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str):
        cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if column_name not in {row[1] for row in cols}:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def _check_telegram_commands(self):
        """Polls Telegram for manual commands."""
        updates = self.notifier.get_updates()
        for text in updates:
            if text == "/stats":
                stats = self.journal.get_stats()
                msg = f"<b>📊 PERFORMANCE JOURNAL</b>\n\n"
                msg += f"Wins: {stats['wins']} | Losses: {stats['losses']}\n"
                msg += f"Win Rate: {stats['win_rate']:.1f}%\n"
                msg += f"Total PnL: {stats['total_pnl_pct']:.2f}%"
                self.notifier.send(msg)
            elif text == "/test":
                self._run_test_signal()

    def run_cycle(self):
        """Single processing cycle: Session check and scanning."""
        if self._in_active_session():
            self._scan_and_signal()
        else:
            logger.info("Outside active trading hours; signal generation paused")
        
        # Pause before next cycle
        time.sleep(self.config["runtime"]["scan_interval_sec"])

    def _scan_and_signal(self):
        for adapter in self.adapters:
            pairs = adapter.fetch_candidates()
            logger.info("Adapter %s: Collected %d candidate pairs", adapter.__class__.__name__, len(pairs))

            rejections = {"already_open": 0, "cooldown": 0, "max_signals": 0, "risk": 0, "gas": 0, "strategy": 0, "ict": 0}
            approved_count = 0

            for pair in pairs:
                chain_id = str(pair.get("chainId", "")).lower()
                pair_address = str(pair.get("pairAddress", ""))
                base = pair.get("baseToken", {})
                token_address = str(base.get("address", ""))
                symbol = str(base.get("symbol", "?")).upper()[:20]

                if not chain_id or not pair_address or not token_address:
                    continue
                if self._already_open(chain_id, pair_address):
                    rejections["already_open"] += 1
                    continue
                if self._in_cooldown(chain_id, pair_address):
                    rejections["cooldown"] += 1
                    continue
                if self._open_count() >= self.config["trading"]["max_open_signals"]:
                    rejections["max_signals"] += 1
                    break

                # Rate limit mitigation: tiny sleep between external API calls
                time.sleep(0.4)

                approved, reason = self.risk_checker.check(chain_id, token_address)
                if not approved:
                    rejections["risk"] += 1
                    logger.debug("Risk rejected %s (%s): %s", symbol, token_address, reason)
                    continue

                if not self._gas_check_passed(chain_id):
                    rejections["gas"] += 1
                    continue

                decision = self.strategy.evaluate(pair)
                if not decision.approved:
                    rejections["strategy"] += 1
                    continue

                # NEW: ICT Analysis
                candles = adapter.fetch_candles(pair_address, chain_id)
                patterns = self.ict_analyst.analyze(candles)
                
                # For now, we only alert if ICT patterns are found (strict mode approach)
                if not patterns:
                    rejections["ict"] += 1
                    continue

                signal = decision.signal
                reasoning_report = self.reasoning.generate_initial_report(patterns, signal["quality"])
                
                self._store_signal(chain_id, pair_address, token_address, symbol, signal, reasoning_report, adapter.__class__.__name__)
                self._send_signal_alert(pair, signal, reasoning_report)
                approved_count += 1
                logger.info("APPROVED SIGNAL: %s (%s) Score: %s | Reasoning: %s", symbol, chain_id, signal["score"], reasoning_report)

            logger.info(
                "Adapter %s summary: %d approved, %d rejected (Risk: %d, Strat: %d, ICT: %d, Open/CD: %d, Gas: %d)",
                adapter.__class__.__name__,
                approved_count,
                sum(rejections.values()),
                rejections["risk"],
                rejections["strategy"],
                rejections["ict"],
                rejections["already_open"] + rejections["cooldown"],
                rejections["gas"]
            )

    def _collect_pairs(self):
        # Removed as it's now handled by adapters
        return []

    def _in_active_session(self) -> bool:
        offset = self.config["runtime"]["timezone_offset_hours"]
        now_local = datetime.now(timezone.utc) + timedelta(hours=offset)
        active_hours = set(self.config["runtime"]["active_hours_local"])
        return now_local.hour in active_hours

    def _gas_check_passed(self, chain_id: str) -> bool:
        if chain_id == "solana":
            return True

        gas_cfg = self.config["risk_checks"]["gas"]
        if not gas_cfg["enabled"]:
            return True

        gas_gwei = self._get_chain_gas_gwei(chain_id)
        if gas_gwei is None:
            return not self.config["risk_checks"]["strict_mode"]

        return gas_gwei <= gas_cfg["max_gwei_by_chain"].get(chain_id, gas_cfg["default_max_gwei"])

    def _get_chain_gas_gwei(self, chain_id: str) -> Optional[float]:
        rpc_url = self.config.get("evm_rpc", {}).get(chain_id)
        if not rpc_url or Web3 is None:
            return None

        try:
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8}))
            gas_wei = w3.eth.gas_price
            return gas_wei / 1_000_000_000
        except Exception:
            return None

    def _already_open(self, chain_id: str, pair_address: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM signals WHERE chain_id = ? AND pair_address = ? AND status = 'OPEN' LIMIT 1",
            (chain_id, pair_address),
        ).fetchone()
        return row is not None

    def _in_cooldown(self, chain_id: str, pair_address: str) -> bool:
        cooldown_h = self.config["trading"]["signal_cooldown_hours"]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=cooldown_h)).isoformat()
        row = self.db.execute(
            """
            SELECT 1 FROM signals
            WHERE chain_id = ? AND pair_address = ? AND ts_utc >= ?
            LIMIT 1
            """,
            (chain_id, pair_address, cutoff),
        ).fetchone()
        return row is not None

    def _open_count(self) -> int:
        row = self.db.execute("SELECT COUNT(*) FROM signals WHERE status = 'OPEN'").fetchone()
        return int(row[0])

    def _store_signal(self, chain_id: str, pair_address: str, token_address: str, symbol: str, signal: Dict, reasoning: str, adapter_type: str):
        ts_utc = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """
            INSERT INTO signals (
                ts_utc, chain_id, pair_address, token_address, symbol,
                quality, score, horizon, entry_price, stop_pct, tp1_pct, tp2_pct,
                risk_pct, risk_usd, position_usd, slippage_est_pct, max_hold_hours, 
                status, alert_state, adapter_type, reasoning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 'SIGNAL_SENT', ?, ?)
            """,
            (
                ts_utc,
                chain_id,
                pair_address,
                token_address,
                symbol,
                signal["quality"],
                signal["score"],
                signal["horizon"],
                signal["entry_price"],
                signal["stop_pct"],
                signal["tp1_pct"],
                signal["tp2_pct"],
                signal["risk_pct"],
                signal["risk_usd"],
                signal["position_usd"],
                signal["slippage_est_pct"],
                signal["max_hold_hours"],
                adapter_type,
                reasoning,
            ),
        )
        self.db.commit()

    def _send_signal_alert(self, pair: Dict, signal: Dict, reasoning: str):
        chain_id = str(pair.get("chainId", "")).lower()
        symbol = str(pair.get("baseToken", {}).get("symbol", "?")).upper()[:20]
        pair_address = str(pair.get("pairAddress", ""))
        token_address = str(pair.get("baseToken", {}).get("address", ""))
        dex_url = pair.get("url") or f"https://dexscreener.com/{chain_id}/{pair_address}"
        exec_links = self._build_execution_links(chain_id, token_address, pair_address, dex_url)

        # User's requested short format: Short Signal + Divider + Reasoning
        msg = (
            f"<b>DXSB SIGNAL | {signal['quality']} | {symbol}</b>\n"
            f"{chain_id} | Entry ${signal['entry_price']:.8f} | SL -{signal['stop_pct']:.2f}% | TP2 +{signal['tp2_pct']:.2f}%\n"
            "--------\n"
            f"<i>{reasoning}</i>\n"
            "--------\n"
            f"Size ${signal['position_usd']:.2f} | {exec_links}"
        )

        self.notifier.send(msg)

    def _build_execution_links(self, chain_id: str, token_address: str, pair_address: str, dex_url: str) -> str:
        chain_templates = self.config.get("execution_links", {}).get(chain_id, {})
        if not isinstance(chain_templates, dict):
            return f"DexScreener: {dex_url}"

        links = []
        for label, template in chain_templates.items():
            if not template:
                continue
            try:
                url = str(template).format(
                    token=quote_plus(token_address),
                    pair=quote_plus(pair_address),
                    chain=quote_plus(chain_id),
                    dex=quote_plus(dex_url),
                )
                links.append(f"{label}: {url}")
            except Exception:
                continue

        if not links:
            links.append(f"DexScreener: {dex_url}")
        return " | ".join(links)

    def _update_open_signals(self):
        rows = self.db.execute(
            """
            SELECT id, chain_id, pair_address, symbol, entry_price, stop_pct, tp2_pct, 
                   ts_utc, max_hold_hours, reminder_count, reasoning, adapter_type
            FROM signals
            WHERE status = 'OPEN'
            """
        ).fetchall()

        for row in rows:
            signal_id, chain_id, pair_address, symbol, entry_price, stop_pct, tp2_pct, \
                ts_utc, max_hold_hours, reminder_count, old_reasoning, adapter_type = row
            
            # Find adapter for this signal
            adapter = next((a for a in self.adapters if a.__class__.__name__ == adapter_type), self.adapters[0])
            pair = adapter.get_market_data(pair_address, chain_id)
            if not pair:
                continue

            current_price = safe_float(pair.get("priceUsd"))
            if current_price <= 0:
                continue

            stop_price = entry_price * (1 - stop_pct / 100.0)
            tp2_price = entry_price * (1 + tp2_pct / 100.0)

            close_reason = None
            pnl_r = None

            if current_price <= stop_price:
                close_reason = "STOP"
                pnl_r = -1.0
            elif current_price >= tp2_price:
                close_reason = "TP2"
                pnl_r = round(tp2_pct / stop_pct, 2)
            else:
                opened = datetime.fromisoformat(ts_utc)
                age_h = (datetime.now(timezone.utc) - opened).total_seconds() / 3600.0
                
                # Handling Reminders and PA Updates
                if age_h >= max_hold_hours:
                    close_reason = "TIMEOUT"
                    pnl_r = round((current_price / entry_price - 1) / (stop_pct / 100.0), 2)
                else:
                    # Check for PA updates
                    candles = adapter.fetch_candles(pair_address, chain_id)
                    new_patterns = self.ict_analyst.analyze(candles)
                    pa_update = self.reasoning.evaluate_pa_change(old_reasoning, new_patterns)
                    if pa_update:
                        self.notifier.send(f"<b>DXSB UPDATE | {symbol}</b>\n{pa_update}")
                        self.db.execute("UPDATE signals SET reasoning = ? WHERE id = ?", (pa_update, signal_id))
                        self.db.commit()

                    # Check for Reminders
                    # Every 2 hours if no action taken, max 2 reminders
                    if reminder_count < 2 and age_h >= (reminder_count + 1) * 2:
                        reminder_msg = self.reasoning.generate_reminder(reminder_count + 1, {"symbol": symbol})
                        self.notifier.send(f"<b>DXSB ALERT | {symbol}</b>\n{reminder_msg}")
                        self.db.execute("UPDATE signals SET reminder_count = reminder_count + 1 WHERE id = ?", (signal_id,))
                        self.db.commit()

            if close_reason:
                now_ts = datetime.now(timezone.utc).isoformat()
                self.db.execute(
                    """
                    UPDATE signals
                    SET status = 'CLOSED', close_reason = ?, close_price = ?, close_ts_utc = ?, pnl_r = ?
                    WHERE id = ?
                    """,
                    (close_reason, current_price, now_ts, pnl_r, signal_id),
                )
                self.db.commit()
                self._send_close_alert(symbol, chain_id, close_reason, current_price, pnl_r)
                
                # Journal the result
                final_pnl_pct = ((current_price / entry_price) - 1) * 100
                self.journal.log_trade(
                    symbol=symbol,
                    chain_id=chain_id,
                    adapter=adapter_type,
                    entry=entry_price,
                    exit=current_price,
                    pnl_pct=final_pnl_pct,
                    outcome="TP" if close_reason == "TP2" else "SL" if close_reason == "STOP" else "EXPIRED",
                    reasoning=old_reasoning
                )

    def _send_close_alert(self, symbol: str, chain_id: str, reason: str, close_price: float, pnl_r: float):
        message = (
            f"<b>DXSB CLOSE | {symbol} | {reason}</b>\n"
            f"{chain_id} | Exit ${close_price:.8f}\n"
            "========\n"
            f"Result: {pnl_r}R"
        )
        self.notifier.send(message)

    def _run_test_signal(self):
        """Sends a manual test signal to verify Telegram connection and format."""
        logger.info("Running manual test signal...")
        test_pair = {
            "chainId": "solana",
            "pairAddress": "TEST_ADDR",
            "url": "https://dexscreener.com/solana/test",
            "baseToken": {"symbol": "TEST", "address": "TEST_TOKEN"}
        }
        test_signal = {
            "quality": "A+",
            "score": 95.5,
            "entry_price": 0.00123456,
            "stop_pct": 10.0,
            "tp2_pct": 30.0,
            "position_usd": 100.0,
        }
        test_reasoning = "ICT SETUP: BULLISH OB detected. | Reasoning: Institutional buy zone in A+ bucket. | Structure: BULLISH BoS confirmed."
        self._send_signal_alert(test_pair, test_signal, test_reasoning)
        logger.info("Test signal sent to Telegram.")

if __name__ == "__main__":
    import sys
    bot = DexSignalBot(config_path="config.json")
    if "--test" in sys.argv:
        bot._run_test_signal()
    else:
        bot.run()
