"""Historical EUR reference rates from the European Central Bank."""

import csv
import logging
import os
import tempfile
import time
from datetime import date
from functools import lru_cache
from io import BytesIO, TextIOWrapper
from math import isfinite
from pathlib import Path
from threading import Lock
from zipfile import BadZipFile, ZipFile

import httpx

ECB_HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
REFRESH_SECONDS = 3600
RETRY_SECONDS = 300

logger = logging.getLogger(__name__)
_cache_lock = Lock()
_retry_after: dict[Path, float] = {}


class EcbRates:
    """A snapshot of the ECB's daily units per EUR."""

    def __init__(self, eur_rates: dict[str, dict[date, float]]):
        self._eur_rates = eur_rates

    def history(self, base: str, quote: str) -> dict[date, float]:
        """Return units of quote per unit of base on shared observation dates."""
        if base not in self._eur_rates or quote not in self._eur_rates:
            raise ValueError(f"No ECB exchange rate for {base}/{quote}.")
        quote_rates = self._eur_rates[quote]
        return {
            day: quote_rates[day] / rate
            for day, rate in self._eur_rates[base].items()
            if day in quote_rates
        }


def _parse_csv(stream: TextIOWrapper) -> EcbRates:
    rows = csv.reader(stream)
    header = next(rows, [])
    if not header or header[0] != "Date" or "USD" not in header:
        raise ValueError("Invalid ECB exchange-rate CSV header")
    columns = [(index, code) for index, code in enumerate(header[1:], 1) if code.strip()]
    rates: dict[str, dict[date, float]] = {code: {} for _, code in columns}
    rates["EUR"] = {}
    for row in rows:
        if not row:
            continue
        if len(row) <= columns[-1][0]:
            raise ValueError("Incomplete ECB exchange-rate row")
        day = date.fromisoformat(row[0])
        rates["EUR"][day] = 1.0
        for index, code in columns:
            value = row[index].strip()
            if value in {"", "N/A"}:
                continue
            rate = float(value)
            if not isfinite(rate) or rate <= 0:
                raise ValueError(f"Invalid ECB exchange rate for {code} on {day}")
            rates[code][day] = rate
    if not rates["USD"]:
        raise ValueError("ECB exchange-rate CSV contains no USD observations")
    return EcbRates(rates)


@lru_cache(maxsize=2)
def _parse_zip(payload: bytes) -> EcbRates:
    try:
        with ZipFile(BytesIO(payload)) as archive:
            with TextIOWrapper(archive.open("eurofxref-hist.csv"), encoding="utf-8-sig", newline="") as stream:
                return _parse_csv(stream)
    except (BadZipFile, KeyError, csv.Error) as exc:
        raise ValueError("Invalid ECB exchange-rate archive") from exc


@lru_cache(maxsize=2)
def _read_rates(path: Path, mtime_ns: int) -> EcbRates:
    """Parse a local snapshot once per modification time."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return _parse_csv(stream)
    return _parse_zip(path.read_bytes())


def _cache_path() -> Path:
    if directory := os.environ.get("PP_ECB_CACHE_DIR"):
        return Path(directory).expanduser() / "ecb-rates.zip"
    directory = os.environ.get("XDG_CACHE_HOME")
    root = Path(directory).expanduser() if directory else Path.home() / ".cache"
    return root / "pp-mcp" / "ecb-rates.zip"


def _write_cache(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_ecb_rates(archive: Path | None = None) -> EcbRates:
    """Read an explicit local snapshot or refresh the cache on demand.

    A valid cached snapshot remains usable if an ECB request fails. Concurrent
    readers share one refresh, and only a validated download replaces the cache.
    """
    if archive is not None:
        return _read_rates(archive, archive.stat().st_mtime_ns)

    path = _cache_path()
    with _cache_lock:
        cached = None
        try:
            stamp = path.stat()
            cached = _read_rates(path, stamp.st_mtime_ns)
            if (
                time.time() - stamp.st_mtime < REFRESH_SECONDS
                or time.monotonic() < _retry_after.get(path, 0)
            ):
                return cached
        except (OSError, ValueError):
            pass

        try:
            response = httpx.get(ECB_HISTORY_URL, timeout=10, follow_redirects=True)
            response.raise_for_status()
            rates = _parse_zip(response.content)
            _write_cache(path, response.content)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            if cached is None:
                raise OSError("Unable to load ECB exchange rates.") from exc
            _retry_after[path] = time.monotonic() + RETRY_SECONDS
            logger.warning("ECB rate refresh failed. Using the cached rates: %s", exc)
            return cached
        _retry_after.pop(path, None)
        return rates
