"""
News filter utilities.

- get_upcoming_news() uses FINNHUB_API_KEY if set (free tier available).
- is_safe_to_trade() returns False if high-impact events within next N hours.

If no API key is configured, returns conservative defaults.
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta
import os
import logging
import requests

logger = logging.getLogger(__name__)

FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')


def get_upcoming_news(hours: int = 24) -> List[Dict[str, Any]]:
    """Return upcoming economic events. Requires FINNHUB_API_KEY.

    If no API key, returns empty list.
    """
    if not FINNHUB_API_KEY:
        logger.warning('FINNHUB_API_KEY not set; returning empty news list')
        return []

    try:
        now = datetime.utcnow()
        to_ts = int((now + timedelta(hours=hours)).timestamp())
        from_ts = int(now.timestamp())
        url = f'https://finnhub.io/api/v1/calendar/economic?from={now.strftime("%Y-%m-%d")}&to={(now+timedelta(days=7)).strftime("%Y-%m-%d")}&token={FINNHUB_API_KEY}'
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            logger.warning('finnhub returned non-200 for calendar')
            return []
        data = resp.json()
        events = []
        for d in data.get('economicCalendar', []):
            # map to minimal schema
            evt_time = d.get('date')
            events.append({
                'country': d.get('country'),
                'impact': d.get('impact'),
                'title': d.get('title'),
                'date': evt_time,
            })
        return events
    except Exception as e:
        logger.exception('get_upcoming_news error')
        return []


def is_safe_to_trade(hours: int = 2) -> Dict[str, Any]:
    """Return whether it is safe to trade in the next `hours` based on high-impact news."""
    events = get_upcoming_news(hours=24)
    now = datetime.utcnow()
    cutoff = now + timedelta(hours=hours)
    high = []
    for e in events:
        # attempt parse
        try:
            evt_dt = datetime.fromisoformat(e.get('date'))
        except Exception:
            continue
        if now <= evt_dt <= cutoff and e.get('impact') in ('high', 'High', 'H'):
            high.append(e)
    if high:
        return {'safe': False, 'reason': 'high_impact_event', 'events': high}
    return {'safe': True, 'reason': None, 'events': []}
