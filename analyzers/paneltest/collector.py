#!/usr/bin/env python3
"""
Rate-paced sampling loop and reading record for GPP4323-based logging.

App-layer helpers on top of the gpp4323 driver: DataCollector polls one channel
at a fixed rate and hands each timestamped LoadReading to a callback.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional


@dataclass
class LoadReading:
    """A single timestamped reading from one channel."""
    voltage: float
    current: float
    power: float
    timestamp: datetime


class DataCollector:
    """Polls a gpp4323 Channel at a fixed rate, delivering LoadReadings."""

    def __init__(self,
                 channel,
                 rate: float = 10.0,
                 callback: Optional[Callable[[LoadReading], None]] = None,
                 load_voltage: Optional[float] = None):
        """
        Args:
            channel: gpp4323 Channel to monitor.
            rate: Sampling rate in Hz.
            callback: Called with each new LoadReading.
            load_voltage: If set, configure the channel as a constant-voltage
                load at this voltage (V) and enable it before collecting.
        """
        self.channel = channel
        self.rate = rate
        self.interval = 1.0 / rate
        self.callback = callback
        self.load_voltage = load_voltage
        self.is_running = False

    def start(self) -> None:
        """Run the collection loop (blocking until stop())."""
        self.is_running = True

        if self.load_voltage is not None:
            self.channel.set_load(cv=self.load_voltage)
            self.channel.enable()
            self.channel.gpp.local()  # keep the front panel usable while logging
            print(f"CH{self.channel.n} set as CV load at {self.load_voltage} V")

        print(f"Data collection started at {self.rate} Hz on channel {self.channel.n}")

        next_sample = time.monotonic()
        while self.is_running:
            try:
                d = self.channel.meas()
                reading = LoadReading(d['voltage'], d['current'], d['power'],
                                      datetime.now(timezone.utc))
                if self.callback:
                    self.callback(reading)
            except TimeoutError:
                print("Warning: power supply read timed out, retrying")

            next_sample += self.interval
            sleep_time = next_sample - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # Fell behind — reset to avoid a burst of catch-up samples.
                next_sample = time.monotonic()

    def stop(self) -> None:
        """Stop the collection loop."""
        self.is_running = False
        print("Data collection stopped")
