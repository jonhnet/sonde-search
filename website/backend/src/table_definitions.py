#!/usr/bin/env python3

# These functions create the dynamodb tables needed by the
# service. They are uesd by both the local unit test framework to
# create tables in the dynamodb mock service, and can create
# production tables by running main.

import boto3

USER_TABLE_NAME = 'sondesearch-notifier-users'
SUBSCRIBER_TABLE_NAME = 'sondesearch-notifier-subscriptions'
NOTIFICATION_TABLE_NAME = 'sondesearch-notifier-notifications'

class TableClients:
    def __init__(self):
        ddb_client = boto3.resource('dynamodb')
        self.users = ddb_client.Table(USER_TABLE_NAME)
        self.subscriptions = ddb_client.Table(SUBSCRIBER_TABLE_NAME)
        self.notifications = ddb_client.Table(NOTIFICATION_TABLE_NAME)

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

if __name__ == '__main__':
    create_tables()
