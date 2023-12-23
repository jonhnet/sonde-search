#!/usr/bin/env python3

# Adds the email_lc field to any user entry that doesn't
# have it. Transitional program meant to only be used once.

import sys
import os
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import table_definitions
import util

def go():
    t = table_definitions.TableClients()

    # Get all users
    users = util.dynamodb_to_dataframe(t.users.scan)

    for _, user in users.iterrows():
        if 'email_lc' in user and not pd.isna(user['email_lc']):
            continue
        print(user['email'])
        t.users.update_item(
            Key={
                'uuid': user['uuid'],
            },
            UpdateExpression='set email_lc = :e',
            ExpressionAttributeValues={
                ':e': user['email'].lower()
            }
        )

if __name__ == "__main__":
    go()
