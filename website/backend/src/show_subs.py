#!/usr/bin/env python3

# Prints a list of all subscriptions

import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import table_definitions
import util

def show_subs():
    t = table_definitions.TableClients()

    # Get all user and subscription data
    users = util.dynamodb_to_dataframe(t.users.scan)
    users['email_lc'] = users['email'].str.lower()
    users = users.sort_values('email_lc')

    subs = util.dynamodb_to_dataframe(t.subscriptions.scan)
    for c in ('subscribe_time', 'unsubscribe_time'):
        subs[c] = pd.to_datetime(subs[c].astype(float).fillna(0), unit='s')

    def print_time(t):
        if pd.isna(t) or t.year < 2000:
            return ' ' * 19
        else:
            return str(t.floor('s'))

    for _, user in users.iterrows():
        print(f"{user['uuid']} {user['email']}")
        usubs = subs.loc[subs['subscriber'] == user['uuid']]
        usubs = usubs.sort_values(['subscribe_time', 'unsubscribe_time'])
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
