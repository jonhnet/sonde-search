#/usr/bin/env python3

# These functions create the dynamodb tables needed by the
# service. They are uesd by both the local unit test framework to
# create tables in the dynamodb mock service, and can create
# production tables by running main.

def create_tables(ddb_client):
    ddb_client.create_table(
        TableName='sondesearch-notifier-subscriptions',
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
                'AttributeName': 'email',
                'AttributeType': 'S',
            },
        ],
        GlobalSecondaryIndexes=[
            {
                'IndexName': 'email-index',
                'KeySchema': [{
                    'AttributeName': 'email',
                    'KeyType': 'HASH',
                }],
                'Projection': {
                    'ProjectionType': 'ALL',
                },
            },
        ],
        BillingMode='PAY_PER_REQUEST',
    )

    ddb_client.create_table(
        TableName='sondesearch-notifier-prefs',
        KeySchema=[{
            'AttributeName': 'email',
            'KeyType': 'HASH',
        }],
        AttributeDefinitions=[
            {
                'AttributeName': 'email',
                'AttributeType': 'S',
            },
        ],
        BillingMode='PAY_PER_REQUEST',
    )
