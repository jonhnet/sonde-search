"""UDP listener for radiosonde_auto_rx PAYLOAD_SUMMARY JSON broadcasts."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Union

log = logging.getLogger(__name__)

OnMessage = Callable[[dict], Union[None, Awaitable[None]]]


def enrich_time_epoch(msg: dict, now_utc: datetime | None = None) -> None:
    """Add `time_epoch` derived from the `time` HH:MM:SS field.

    Handles midnight rollover: if the parsed wall-clock time is more than
    12 hours ahead of `now`, assume it was yesterday.
    """
    time_str = msg.get("time", "")
    if not time_str:
        return
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    try:
        t = datetime.strptime(time_str, "%H:%M:%S").replace(
            year=now_utc.year, month=now_utc.month, day=now_utc.day,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return
    if (t - now_utc).total_seconds() > 43200:
        t -= timedelta(days=1)
    msg["time_epoch"] = int(t.timestamp())


class AutoRxProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_message: OnMessage):
        self._on_message = on_message

    def datagram_received(self, data: bytes, addr):
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            log.warning("Invalid JSON from %s", addr)
            return
        enrich_time_epoch(msg)
        log.info(
            "Rx from %s: %s (%s) frame=%s alt=%sm (%s, %s)",
            addr,
            msg.get("callsign", "?"),
            msg.get("model", "?"),
            msg.get("frame", "?"),
            msg.get("altitude", "?"),
            msg.get("latitude", "?"),
            msg.get("longitude", "?"),
        )
        result = self._on_message(msg)
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)


async def listen(port: int, on_message: OnMessage, host: str = "0.0.0.0") -> asyncio.BaseTransport:
    loop = asyncio.get_event_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: AutoRxProtocol(on_message),
        local_addr=(host, port),
    )
    log.info("Listening for auto_rx UDP on %s:%d", host, port)
    return transport
