#!/usr/bin/env python3

# Prints a list of all subscriptions

import click
import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import table_definitions
import util

@click.command()
@click.option(
    '--cancellations',
    is_flag=True,
    default=False,
)
def show_subs(cancellations):
    t = table_definitions.TableClients()

    # Get all user and subscription data
    users = util.dynamodb_to_dataframe(t.users.scan)
    users['email_lc'] = users['email'].str.lower()
    users = users.sort_values('email_lc')

    subs = util.dynamodb_to_dataframe(t.subscriptions.scan)
    for c in ('subscribe_time', 'unsubscribe_time'):
        subs[c] = pd.to_datetime(subs[c].astype(float).fillna(0), unit='s', utc=True).dt.tz_convert(tz='US/Pacific')

    def print_time(t):
        if pd.isna(t) or t.year < 2000:
            return ' ' * 25
        else:
            return str(t.floor('s'))

    for _, user in users.iterrows():
        usubs = subs.loc[subs['subscriber'] == user['uuid']]
        usubs = usubs.sort_values(['subscribe_time', 'unsubscribe_time'])
        is_active = any(usubs['active'])
        is_cancellation = len(usubs) > 0 and not is_active

        if cancellations and not is_cancellation:
            continue

        print(f"{user['uuid']} {user['email']}")
        for _, sub in usubs.iterrows():
            s = '     '
            s += '* ' if sub['active'] else '  '
            s += f"[{sub['uuid']:.8}] "
            s += print_time(sub['subscribe_time'])
            s += ' - '
            s += print_time(sub['unsubscribe_time'])
            s += f"{sub['max_distance_mi']:9.1f}"
            s += f"{sub['lat']:10.4f}"
            s += f"{sub['lon']:11.4f}"
            print(s)

        print()

if __name__ == "__main__":
    show_subs()
