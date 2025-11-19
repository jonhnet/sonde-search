#!/usr/bin/env python3
"""
GPP4323 Power Supply Load Logger
Logs load readings from Channel 1 at 10 Hz
"""

import time
import argparse
import csv
import sys
from typing import TextIO, Optional, Any
from gpp4323_lib import GPP4323, DataCollector, LoadReading


class SimpleLogger:
    """Simple CSV logger for power supply readings"""

    def __init__(self, output_file: Optional[str] = None):
        self.output_file = output_file
        self.start_time: Optional[float] = None
        self.sample_count = 0
        self.csvfile: TextIO
        self.writer: Any  # csv.writer

    def open_output(self) -> None:
        """Open the output file or use stdout"""
        if self.output_file:
            self.csvfile = open(self.output_file, 'w', newline='')
            print(f"Writing to {self.output_file}")
        else:
            self.csvfile = sys.stdout

        self.writer = csv.writer(self.csvfile)
        self.writer.writerow(['timestamp', 'voltage_V', 'current_A', 'power_W'])

    def close_output(self) -> None:
        """Close the output file if it's not stdout"""
        if self.csvfile != sys.stdout:
            self.csvfile.close()

    def handle_reading(self, reading: LoadReading) -> None:
        """Callback for each new reading from the data collector"""
        if self.start_time is None:
            self.start_time = time.time()

        # Write to CSV (timestamp as Unix epoch)
        self.writer.writerow([
            f'{reading.timestamp.timestamp():.3f}',
            f'{reading.voltage:.4f}',
            f'{reading.current:.4f}',
            f'{reading.power:.4f}'
        ])

        if self.csvfile == sys.stdout:
            self.csvfile.flush()

        self.sample_count += 1

    def get_stats(self) -> tuple[int, float, float]:
        """Get logging statistics"""
        if self.start_time is None:
            return 0, 0.0, 0.0

        actual_duration = time.time() - self.start_time
        actual_rate = self.sample_count / actual_duration if actual_duration > 0 else 0.0
        return self.sample_count, actual_duration, actual_rate


def main():
    parser = argparse.ArgumentParser(
        description='Log GPP4323 Channel 1 load readings at 10 Hz'
    )
    parser.add_argument(
        '--host',
        default='gpp4323',
        help='Hostname or IP address of GPP4323 (default: gpp4323)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=1026,
        help='TCP port (default: 1026)'
    )
    parser.add_argument(
        '--rate',
        type=float,
        default=10.0,
        help='Sampling rate in Hz (default: 10.0)'
    )
    parser.add_argument(
        '--output',
        '-o',
        help='Output CSV file (default: stdout)'
    )

    args = parser.parse_args()

    # Create logger
    logger = SimpleLogger(output_file=args.output)

    # Connect to power supply
    psu = GPP4323(args.host, args.port)
    collector: Optional[DataCollector] = None

    try:
        psu.connect()

        # Open output file
        logger.open_output()

        print(f"Logging Channel 1 load at {args.rate} Hz")
        print("Press Ctrl+C to stop")
        print()

        # Create and start collector with logger callback
        collector = DataCollector(
            psu=psu,
            channel=1,
            rate=args.rate,
            callback=logger.handle_reading
        )

        # Start collection loop (blocking)
        try:
            collector.start()
        except KeyboardInterrupt:
            print(f"\nStopped by user after {logger.sample_count} samples")
        finally:
            collector.stop()

        # Print statistics
        sample_count, actual_duration, actual_rate = logger.get_stats()
        print(f"Collected {sample_count} samples in {actual_duration:.2f}s")
        print(f"Actual rate: {actual_rate:.2f} Hz")

    finally:
        if collector:
            collector.stop()
        psu.disconnect()
        logger.close_output()


if __name__ == '__main__':
    main()
