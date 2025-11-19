#!/usr/bin/env python3
"""
Shared library for GPP4323 Power Supply interface and data handling
"""

import socket
import time
from typing import Callable, Tuple, Optional
from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass
class LoadReading:
    """Data structure for a single load reading"""
    voltage: float
    current: float
    power: float
    timestamp: datetime


class GPP4323:
    """Driver for GW Instek GPP4323 Power Supply"""

    def __init__(self, host: str, port: int = 1026, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None

    def connect(self) -> None:
        """Establish connection to the power supply"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))
        print(f"Connected to GPP4323 at {self.host}:{self.port}")

    def disconnect(self) -> None:
        """Close connection to the power supply"""
        if self.sock:
            self.sock.close()
            self.sock = None

    def send_command(self, command: str) -> None:
        """Send a command to the power supply"""
        if not self.sock:
            raise RuntimeError("Not connected")
        self.sock.sendall(f"{command}\n".encode())

    def query(self, command: str) -> str:
        """Send a query and return the response"""
        if not self.sock:
            raise RuntimeError("Not connected")
        self.sock.sendall(f"{command}\n".encode())
        response = self.sock.recv(1024).decode().strip()
        return response

    def get_idn(self) -> str:
        """Get instrument identification"""
        return self.query("*IDN?")

    def get_channel_load(self, channel: int = 1) -> Tuple[float, float, float]:
        """Get load reading from specified channel

        Returns:
            tuple: (voltage, current, power) in V, A, W
        """
        voltage_str = self.query(f"VOUT{channel}?")
        voltage = float(voltage_str.rstrip('V'))
        current_str = self.query(f"IOUT{channel}?")
        current = float(current_str.rstrip('A'))
        power = voltage * current
        return voltage, current, power


class DataCollector:
    """Collects data from a GPP4323 channel at specified sampling rate"""

    def __init__(self,
                 psu: GPP4323,
                 channel: int = 1,
                 rate: float = 10.0,
                 callback: Optional[Callable[[LoadReading], None]] = None):
        """
        Initialize data collector

        Args:
            psu: GPP4323 instance to collect data from
            channel: Channel number to monitor (default: 1)
            rate: Sampling rate in Hz (default: 10.0)
            callback: Function called with each new LoadReading
        """
        self.psu = psu
        self.channel = channel
        self.rate = rate
        self.interval = 1.0 / rate
        self.callback = callback
        self.is_running = False

    def start(self) -> None:
        """Start data collection loop"""
        self.is_running = True

        # Get instrument ID
        idn = self.psu.get_idn()
        print(f"Instrument: {idn}")

        # Set to local mode so front panel remains usable
        self.psu.send_command("LOCAL")
        print("Set to LOCAL mode")

        print(f"Data collection started at {self.rate} Hz on channel {self.channel}")

        while self.is_running:
            loop_start = time.time()

            # Get load reading
            voltage, current, power = self.psu.get_channel_load(channel=self.channel)
            timestamp = datetime.now(timezone.utc)

            # Create reading object
            reading = LoadReading(voltage, current, power, timestamp)

            # Call callback if provided
            if self.callback:
                self.callback(reading)

            # Sleep to maintain rate
            elapsed_time = time.time() - loop_start
            sleep_time = self.interval - elapsed_time
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop(self) -> None:
        """Stop data collection"""
        self.is_running = False
        print("Data collection stopped")
