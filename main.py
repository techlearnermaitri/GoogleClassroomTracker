import os
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

import boto3
from moto import mock_aws
from datetime import datetime, timezone
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.coursework.me.readonly'
]

CLIENT_SECRET_FILE = 'client_secret_35280772694-vjo8u74df4ta7unled1ftud83d37f0ab.apps.googleusercontent.com.json'
COURSE_ID = '863566662310'  # Cloud Application Development


def get_classroom_service():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    return build('classroom', 'v1', credentials=creds)


def due_date_to_timestamp(due_date, due_time):
    """Convert Classroom's dueDate/dueTime dicts into a Unix timestamp. Returns None if no due date."""
    if not due_date:
        return None
    year = due_date.get('year')
    month = due_date.get('month')
    day = due_date.get('day')
    hours = due_time.get('hours', 23) if due_time else 23
    minutes = due_time.get('minutes', 59) if due_time else 59
    dt = datetime(year, month, day, hours, minutes, tzinfo=timezone.utc)
    return int(dt.timestamp())


def check_reminders(table, sns_client, sns_topic_arn):
    """Scan all assignments and send reminders for ones due soon."""
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    response = table.scan()
    items = response['Items']

    for item in items:
        due_ts = int(item['due_timestamp'])
        seconds_until_due = due_ts - now_ts
        days_until_due = seconds_until_due / 86400  # 86400 seconds in a day

        title = item['title']
        assignment_id = item['assignment_id']

        # 7-day reminder
        if 0 < days_until_due <= 7 and not item.get('reminder_sent_7day', False):
            message = f"⏰ Reminder: '{title}' is due in {days_until_due:.1f} days."
            sns_client.publish(TopicArn=sns_topic_arn, Message=message, Subject="Assignment Reminder")
            print(f"[SNS ALERT SENT] {message}")
            table.update_item(
                Key={'assignment_id': assignment_id},
                UpdateExpression='SET reminder_sent_7day = :val',
                ExpressionAttributeValues={':val': True}
            )

        # 1-day reminder (more urgent)
        if 0 < days_until_due <= 1 and not item.get('reminder_sent_1day', False):
            message = f"🚨 URGENT: '{title}' is due in less than 1 day!"
            sns_client.publish(TopicArn=sns_topic_arn, Message=message, Subject="URGENT Assignment Reminder")
            print(f"[SNS ALERT SENT] {message}")
            table.update_item(
                Key={'assignment_id': assignment_id},
                UpdateExpression='SET reminder_sent_1day = :val',
                ExpressionAttributeValues={':val': True}
            )

        # Overdue check (informational)
        if days_until_due < 0:
            print(f"[OVERDUE] '{title}' was due {abs(days_until_due):.1f} days ago.")

@mock_aws
def run_pipeline():
    # --- Set up mocked DynamoDB ---
    dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
    table = dynamodb.create_table(
        TableName='Assignments',
        KeySchema=[{'AttributeName': 'assignment_id', 'KeyType': 'HASH'}],
        AttributeDefinitions=[{'AttributeName': 'assignment_id', 'AttributeType': 'S'}],
        BillingMode='PAY_PER_REQUEST'
    )
    print("DynamoDB table ready.\n")

    # --- Pull real data from Google Classroom ---
    service = get_classroom_service()
    course = service.courses().get(id=COURSE_ID).execute()
    course_name = course.get('name')

    coursework_results = service.courses().courseWork().list(courseId=COURSE_ID).execute()
    coursework = coursework_results.get('courseWork', [])

    synced_at = datetime.now(timezone.utc).isoformat()
    inserted_count = 0

    for item in coursework:
        due_ts = due_date_to_timestamp(item.get('dueDate'), item.get('dueTime'))
        if due_ts is None:
            continue  # skip assignments with no due date, nothing to remind about

        table.put_item(Item={
            'assignment_id': item['id'],
            'course_name': course_name,
            'title': item.get('title'),
            'due_timestamp': due_ts,
            'reminder_sent_7day': False,
            'reminder_sent_1day': False,
            'synced_at': synced_at
        })
        inserted_count += 1

    print(f"Inserted {inserted_count} assignments with due dates into DynamoDB.\n")

    # --- Verify: scan the table and print everything ---
    response = table.scan()
    print("Current table contents:")
    for record in response['Items']:
        due_readable = datetime.fromtimestamp(int(record['due_timestamp']), tz=timezone.utc)
        print(f"- {record['title']} | due: {due_readable} | course: {record['course_name']}")
    # --- Set up mocked SNS ---
    sns = boto3.client('sns', region_name='us-east-1')
    topic = sns.create_topic(Name='AssignmentReminders')
    topic_arn = topic['TopicArn']
    sns.subscribe(TopicArn=topic_arn, Protocol='email', Endpoint='you@example.com')

    print("\n--- Checking for due reminders ---")
    check_reminders(table, sns, topic_arn)

if __name__ == '__main__':
    run_pipeline()