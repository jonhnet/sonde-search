#!/usr/bin/env python3
"""
GPP4323 Power Supply Web Logger with Streaming Chart
"""

import time
import argparse
import csv
import json
import threading
import os
from datetime import datetime, timezone
from typing import Optional, TextIO, Any
import pandas as pd
import numpy as np
from flask import Flask, render_template, Response, request
from gpp4323_lib import GPP4323, DataCollector, LoadReading


class DataStore:
    """Central data storage for power supply measurements"""

    def __init__(self, logfile_path: str, max_buffer_size: int = 1000):
        self.lock = threading.Lock()
        self.data = pd.DataFrame({
            'elapsed': pd.Series(dtype='float64'),
            'voltage': pd.Series(dtype='float64'),
            'current': pd.Series(dtype='float64'),
            'power': pd.Series(dtype='float64'),
            'energy_wh': pd.Series(dtype='float64')
        })
        self.max_buffer_size = max_buffer_size
        self.start_timestamp: Optional[datetime] = None
        self.logfile_path = logfile_path
        self.log_file: TextIO
        self.total_sample_count = 0  # Track total samples written to file
        self.total_energy_wh = 0.0  # Track cumulative energy
        self.last_sample_time: Optional[datetime] = None
        self.csv_writer: Any  # csv.writer, will be set in open_log_file()

    def load_historical_data(self) -> None:
        """Load historical data from CSV file using pandas"""
        if not os.path.exists(self.logfile_path):
            print(f"No existing log file found at {self.logfile_path}")
            return

        try:
            # Read CSV with pandas
            df = pd.read_csv(self.logfile_path)

            if len(df) > 0:
                # Restore start timestamp from Unix epoch before dropping the column
                self.start_timestamp = datetime.fromtimestamp(df['timestamp'].iloc[0], tz=timezone.utc)

                # Track total count and energy from historical file
                self.total_sample_count = len(df)
                self.total_energy_wh = df['energy_wh'].iloc[-1]

                # Drop timestamp column - only needed in CSV, not in memory
                df = df.drop(columns=['timestamp'])

                with self.lock:
                    # Keep only last max_buffer_size rows
                    self.data = df.tail(self.max_buffer_size).reset_index(drop=True)

                print(f"Loaded {len(df)} historical data points from {self.logfile_path}")
                print(f"Buffered last {len(self.data)} points in memory")
                print(f"Session started at: {self.start_timestamp}")
                print(f"Total energy so far: {self.total_energy_wh:.6f} Wh")

        except Exception as e:
            print(f"Error loading historical data: {e}")

    def open_log_file(self) -> None:
        """Open the log file for appending

        Raises:
            IOError: If the log file cannot be opened
        """
        file_exists = os.path.exists(self.logfile_path)
        try:
            self.log_file = open(self.logfile_path, 'a', newline='')
        except Exception as e:
            raise IOError(f"Failed to open log file {self.logfile_path}: {e}") from e

        self.csv_writer = csv.writer(self.log_file)
        # Write header only if file is new
        if not file_exists:
            self.csv_writer.writerow(['timestamp', 'elapsed', 'voltage', 'current', 'power', 'energy_wh'])
        print(f"Logging to file: {self.logfile_path} (append mode)")

    def close_log_file(self) -> None:
        """Close the log file"""
        self.log_file.close()

    def handle_reading(self, reading: LoadReading) -> None:
        """Process a new reading from the data collector"""
        # Initialize start time on first reading
        if self.start_timestamp is None:
            self.start_timestamp = reading.timestamp
            self.last_sample_time = reading.timestamp

        # Calculate elapsed time
        elapsed = (reading.timestamp - self.start_timestamp).total_seconds()

        # Calculate energy (integrate power over time)
        if self.last_sample_time is not None:
            time_delta = (reading.timestamp - self.last_sample_time).total_seconds()
            energy_delta_wh = (reading.power * time_delta) / 3600.0
            self.total_energy_wh += energy_delta_wh
        self.last_sample_time = reading.timestamp

        # Append to data store
        with self.lock:
            new_row = pd.DataFrame([{
                'elapsed': elapsed,
                'voltage': reading.voltage,
                'current': reading.current,
                'power': reading.power,
                'energy_wh': self.total_energy_wh
            }])
            self.data = pd.concat([self.data, new_row], ignore_index=True)

            # Keep only last max_buffer_size rows
            if len(self.data) > self.max_buffer_size:
                self.data = self.data.tail(self.max_buffer_size).reset_index(drop=True)

            # Write to log file (timestamp as Unix epoch)
            self.csv_writer.writerow([
                f'{reading.timestamp.timestamp():.3f}',
                f'{elapsed:.3f}',
                f'{reading.voltage:.4f}',
                f'{reading.current:.4f}',
                f'{reading.power:.4f}',
                f'{self.total_energy_wh:.6f}'
            ])
            self.log_file.flush()

            # Increment total sample count
            self.total_sample_count += 1

    def get_latest(self) -> Optional[pd.Series]:
        """Get the latest data point as a pandas Series"""
        with self.lock:
            if len(self.data) > 0:
                return self.data.iloc[-1]
            return None

    def get_new_data(self, last_elapsed: float) -> pd.DataFrame:
        """Get new data since last_elapsed as a view"""
        with self.lock:
            return self.data[self.data['elapsed'] > last_elapsed]

    def get_total_sample_count(self) -> int:
        """Get total sample count"""
        with self.lock:
            return self.total_sample_count


def decimate_data(df: pd.DataFrame, window_size: int) -> pd.DataFrame:
    """
    Decimate dataframe by averaging windows of size window_size

    Args:
        df: DataFrame to decimate
        window_size: Number of points to average per output point

    Returns:
        Decimated dataframe with averaged values. Only complete windows are processed;
        incomplete tail is discarded.
    """
    if window_size <= 1 or len(df) < window_size:
        return df

    # Only process complete windows, discard incomplete tail
    num_complete_windows = len(df) // window_size
    rows_to_process = num_complete_windows * window_size
    df_to_process = df.iloc[:rows_to_process]

    # Group data into windows and aggregate
    groups = df_to_process.groupby(np.arange(len(df_to_process)) // window_size)

    decimated = pd.DataFrame({
        'elapsed': groups['elapsed'].mean(),
        'voltage': groups['voltage'].mean(),
        'current': groups['current'].mean(),
        'power': groups['power'].mean(),
        'energy_wh': groups['energy_wh'].last()  # Last energy value (cumulative)
    })

    return decimated


def data_collection_thread(host: str, port: int, rate: float, store: DataStore) -> None:
    """Background thread for data collection"""
    psu = GPP4323(host, port)
    collector: Optional[DataCollector] = None

    try:
        psu.connect()

        # Open log file
        store.open_log_file()

        # Create collector with callback
        collector = DataCollector(
            psu=psu,
            channel=1,
            rate=rate,
            callback=store.handle_reading
        )

        # Start collection loop
        collector.start()

    except Exception as e:
        print(f"Data collection error: {e}")
    finally:
        if collector:
            collector.stop()
        psu.disconnect()
        store.close_log_file()


class WebServer:
    """Flask web server for GPP4323 monitoring"""

    def __init__(self, data_store):
        self.data_store = data_store
        self.app = Flask(__name__)
        self._setup_routes()

    def _setup_routes(self):
        """Setup Flask routes using decorators"""
        self.app.add_url_rule('/', view_func=self.index)
        self.app.add_url_rule('/api/timeseries', view_func=self.stream_timeseries)
        self.app.add_url_rule('/api/stats', view_func=self.stream_stats)

    def index(self):
        """Serve the main page"""
        return render_template('gpp4323_chart.html')

    def stream_timeseries(self):
        """Server-Sent Events stream for real-time timeseries data updates

        Query parameters:
        - range: Time range filter (1m, 1h, 6h, 24h, all). Default: 1m
        - max_points: Maximum points for decimation. Default: 500

        All modes are live-updating. The range determines the time window and decimation rate.
        """
        range_param = request.args.get('range', '1m')
        max_points = int(request.args.get('max_points', 500))

        def event_stream():
            last_elapsed_sent = -1

            # Define time range mappings
            RANGE_SECONDS = {
                '1m': 60,
                '1h': 3600,
                '6h': 6 * 3600,
                '24h': 24 * 3600
            }
            SAMPLING_RATE = 10  # Hz

            # Calculate decimation window size (same for initial and live updates)
            if range_param in RANGE_SECONDS:
                # Fixed time window
                range_seconds = RANGE_SECONDS[range_param]
                expected_points = range_seconds * SAMPLING_RATE
            else:
                # 'all' mode - calculate from current elapsed time
                latest = self.data_store.get_latest()
                if latest is not None:
                    expected_points = int(latest['elapsed'] * SAMPLING_RATE)
                else:
                    expected_points = max_points

            decimation_window = max(1, int(expected_points // max_points))

            # Load and send initial historical data from log file
            if os.path.exists(self.data_store.logfile_path):
                try:
                    # Read CSV with pandas, dropping timestamp column
                    df = pd.read_csv(self.data_store.logfile_path)
                    df = df.drop(columns=['timestamp'])

                    if len(df) > 0:
                        # Determine time range window
                        if range_param in RANGE_SECONDS:
                            # Fixed time window
                            range_seconds = RANGE_SECONDS[range_param]
                        else:
                            # 'all' mode - auto-calculate range from total elapsed time
                            range_seconds = df['elapsed'].iloc[-1]

                        latest_elapsed = df['elapsed'].iloc[-1]
                        cutoff_elapsed = latest_elapsed - range_seconds

                        # Filter by time range
                        filtered_df = df[df['elapsed'] >= cutoff_elapsed]

                        # Decimate and send initial data
                        decimated_df = decimate_data(filtered_df, decimation_window)

                        # Convert to list of dicts for JSON serialization
                        decimated_data = decimated_df.to_dict('records')
                        yield f"data: {json.dumps({'type': 'initial', 'data': decimated_data})}\n\n"

                        last_elapsed_sent = df['elapsed'].iloc[-1]

                except Exception as e:
                    yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

            # Stream live updates with batched decimation
            while True:
                time.sleep(1.0)  # Check for new data every second
                new_data = self.data_store.get_new_data(last_elapsed_sent)

                if len(new_data) >= decimation_window:
                    # Decimate the accumulated data (only complete windows)
                    decimated_new = decimate_data(new_data, decimation_window)

                    if len(decimated_new) > 0:
                        # Send as batch in same format as initial data
                        update_batch = decimated_new.to_dict('records')
                        yield f"data: {json.dumps({'type': 'update', 'data': update_batch})}\n\n"

                        # Update last_elapsed_sent to last point of last complete window
                        # (incomplete tail is preserved for next iteration)
                        num_complete_windows = len(new_data) // decimation_window
                        rows_processed = num_complete_windows * decimation_window
                        last_elapsed_sent = new_data.iloc[rows_processed - 1]['elapsed']

        return Response(event_stream(), mimetype='text/event-stream')

    def stream_stats(self):
        """Server-Sent Events stream for stats updates (always active)"""
        def event_stream():
            while True:
                time.sleep(1.0)  # Update stats every second
                latest_point = self.data_store.get_latest()
                if latest_point is not None:
                    start_time = (
                        self.data_store.start_timestamp.isoformat()
                        if self.data_store.start_timestamp else None
                    )
                    stats = {
                        'voltage': latest_point['voltage'],
                        'current': latest_point['current'],
                        'power': latest_point['power'],
                        'energy_wh': latest_point['energy_wh'],
                        'elapsed': latest_point['elapsed'],
                        'total_sample_count': self.data_store.get_total_sample_count(),
                        'start_time': start_time
                    }
                    yield f"data: {json.dumps(stats)}\n\n"

        return Response(event_stream(), mimetype='text/event-stream')

    def run(self, host='0.0.0.0', port=5000, debug=False):
        """Run the Flask web server"""
        self.app.run(host=host, port=port, debug=debug, threaded=True)


def main():
    parser = argparse.ArgumentParser(
        description='GPP4323 Web Logger with Streaming Chart'
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
        '--logfile',
        '-l',
        default='gpp4323_log.csv',
        help='CSV log file path (default: gpp4323_log.csv)'
    )
    parser.add_argument(
        '--web-port',
        type=int,
        default=5000,
        help='Web server port (default: 5000)'
    )

    args = parser.parse_args()

    # Initialize data store
    data_store = DataStore(logfile_path=args.logfile)

    # Load historical data from logfile if it exists
    print(f"Checking for existing log file: {args.logfile}")
    data_store.load_historical_data()
    print()

    # Start data collection thread
    collection_thread = threading.Thread(
        target=data_collection_thread,
        args=(args.host, args.port, args.rate, data_store),
        daemon=True
    )
    collection_thread.start()

    # Start web server
    print(f"\nWeb interface available at: http://localhost:{args.web_port}")
    web_server = WebServer(data_store)
    web_server.run(port=args.web_port)


if __name__ == '__main__':
    main()
