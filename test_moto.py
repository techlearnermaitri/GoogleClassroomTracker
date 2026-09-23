import boto3
from moto import mock_aws

@mock_aws
def test_dynamodb():
    # This creates a FAKE DynamoDB, entirely in-memory, no real AWS involved
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')

    table = dynamodb.create_table(
        TableName='Assignments',
        KeySchema=[
            {'AttributeName': 'assignment_id', 'KeyType': 'HASH'}  # partition key
        ],
        AttributeDefinitions=[
            {'AttributeName': 'assignment_id', 'AttributeType': 'S'}  # S = String
        ],
        BillingMode='PAY_PER_REQUEST'
    )

    print("Table created:", table.table_name)

    # Insert a fake assignment
    table.put_item(Item={
        'assignment_id': 'test-123',
        'title': 'Test Assignment',
        'due_timestamp': 1234567890,
        'reminder_sent_7day': False,
        'reminder_sent_1day': False
    })

    # Read it back
    response = table.get_item(Key={'assignment_id': 'test-123'})
    print("Retrieved item:", response['Item'])

test_dynamodb()