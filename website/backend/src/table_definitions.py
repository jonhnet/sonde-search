#!/usr/bin/env python3

# These functions create the dynamodb tables needed by the
# service. They are used by both the local unit test framework to
# create tables in the dynamodb mock service, and can create
# production tables by running main.

import boto3

USER_TABLE_NAME = 'sondesearch-notifier-users'
SUBSCRIBER_TABLE_NAME = 'sondesearch-notifier-subscriptions'
NOTIFICATION_TABLE_NAME = 'sondesearch-notifier-notifications'
PENDING_VERIFICATION_TABLE_NAME = 'sondesearch-notifier-pending-verifications'


class TableClients:
    def __init__(self):
        ddb_client = boto3.resource('dynamodb')
        self.users = ddb_client.Table(USER_TABLE_NAME)
        self.subscriptions = ddb_client.Table(SUBSCRIBER_TABLE_NAME)
        self.notifications = ddb_client.Table(NOTIFICATION_TABLE_NAME)
        self.pending_verifications = ddb_client.Table(PENDING_VERIFICATION_TABLE_NAME)


def create_tables():
    ddb_client = boto3.resource('dynamodb')

    ddb_client.create_table(
        TableName=NOTIFICATION_TABLE_NAME,
        KeySchema=[
            {
                'AttributeName': 'subscription_uuid',
                'KeyType': 'HASH',
            },
            {
                'AttributeName': 'time_sent',
                'KeyType': 'RANGE'
            }
        ],
        AttributeDefinitions=[
            {
                'AttributeName': 'subscription_uuid',
                'AttributeType': 'S',
            },
            {
                'AttributeName': 'time_sent',
                'AttributeType': 'N',
            },
        ],
        BillingMode='PAY_PER_REQUEST',
    )

    ddb_client.create_table(
        TableName=USER_TABLE_NAME,
        KeySchema=[{
            'AttributeName': 'uuid',
            'KeyType': 'HASH',
        }],
        AttributeDefinitions=[
            {
                'AttributeName': 'uuid',
                'AttributeType': 'S',
            },
            {
                'AttributeName': 'email_lc',
                'AttributeType': 'S',
            },
        ],

        # An index for mapping an email address back to the user's
        # uuid
        GlobalSecondaryIndexes=[
            {
                'IndexName': 'email-lc-index',
                'KeySchema': [{
                    'AttributeName': 'email_lc',
                    'KeyType': 'HASH',
                }],
                'Projection': {
                    'ProjectionType': 'KEYS_ONLY',
                },
            },
        ],
        BillingMode='PAY_PER_REQUEST',
    )

    ddb_client.create_table(
        TableName=SUBSCRIBER_TABLE_NAME,
        KeySchema=[{
            'AttributeName': 'uuid',
            'KeyType': 'HASH',
        }],
        AttributeDefinitions=[
            {
                'AttributeName': 'uuid',
                'AttributeType': 'S',
            },
            {
                'AttributeName': 'subscriber',
                'AttributeType': 'S',
            },
        ],
        GlobalSecondaryIndexes=[
            {
                'IndexName': 'subscriber-index',
                'KeySchema': [{
                    'AttributeName': 'subscriber',
                    'KeyType': 'HASH',
                }],
                'Projection': {
                    'ProjectionType': 'ALL',
                },
            },
        ],
        BillingMode='PAY_PER_REQUEST',
    )

    # Table for pending email verifications. Stores the association between
    # pending_verification tokens (set in browser cookie during signup) and
    # user_tokens (sent via email). This prevents Gmail's link scanner from
    # authenticating users, since it won't have the browser cookie.
    ddb_client.create_table(
        TableName=PENDING_VERIFICATION_TABLE_NAME,
        KeySchema=[{
            'AttributeName': 'pending_token',
            'KeyType': 'HASH',
        }],
        AttributeDefinitions=[
            {
                'AttributeName': 'pending_token',
                'AttributeType': 'S',
            },
        ],
        BillingMode='PAY_PER_REQUEST',
    )

    # Enable TTL on the pending verifications table for automatic cleanup
    ddb_raw_client = boto3.client('dynamodb')
    ddb_raw_client.update_time_to_live(
        TableName=PENDING_VERIFICATION_TABLE_NAME,
        TimeToLiveSpecification={
            'Enabled': True,
            'AttributeName': 'ttl'
        }
    )


if __name__ == '__main__':
    create_tables()
