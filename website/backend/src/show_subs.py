#!/usr/bin/env python3

# Prints a list of all subscriptions

import sys
import os

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
    subs = subs.sort_values('active')

    for _, user in users.iterrows():
        print(f"{user['uuid']:.8s} {user['email']}")

        for _, sub in subs.loc[subs['subscriber'] == user['uuid']].iterrows():
            s = '     '
            s += '* ' if sub['active'] else '  '
            s += f"{sub['max_distance_mi']:.1f}"
            print(s)

        print()

if __name__ == "__main__":
    show_subs()
