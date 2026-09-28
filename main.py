import os
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

import re
import json
import boto3
from moto import mock_aws
from datetime import datetime, timezone
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from azure_export import upload_summary_to_blob, fetch_recent_summaries

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.coursework.me.readonly',
    'https://www.googleapis.com/auth/classroom.student-submissions.me.readonly'
]

CLIENT_SECRET_FILE = 'client_secret_35280772694-vjo8u74df4ta7unled1ftud83d37f0ab.apps.googleusercontent.com.json'
COURSE_ID = '863566662310'  # Cloud Application Development
DASHBOARD_DATA_FILE = 'dashboard_data.json'
DEFAULT_WEIGHT = 10  # assumed mark-weight when none is found in the title


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


def extract_weight(title):
    """Pulls a mark-weight out of a title like 'Mini-Project (20 Marks)'. Falls back to DEFAULT_WEIGHT."""
    match = re.search(r'(\d+)\s*[Mm]arks?', title)
    if match:
        return int(match.group(1))
    return DEFAULT_WEIGHT


def compute_priority_score(weight, days_until_due):
    """Combines mark-weight and urgency into a single score, higher = more deserving of attention now."""
    if days_until_due < 0:
        return round(weight * 5, 1)
    urgency = 1 / max(days_until_due, 0.25)
    return round(weight * urgency, 1)


def get_submission_status(service, course_id, coursework_id):
    """Returns True if the assignment has been turned in (or is otherwise done), False if still pending."""
    try:
        submissions = service.courses().courseWork().studentSubmissions().list(
            courseId=course_id,
            courseWorkId=coursework_id
        ).execute()
        subs = submissions.get('studentSubmissions', [])
        if not subs:
            return False
        state = subs[0].get('state')
        return state in ('TURNED_IN', 'RETURNED')
    except Exception as e:
        print(f"  (Could not fetch submission status for {coursework_id}: {e})")
        return False


def check_reminders(table, sns_client, sns_topic_arn):
    """Scan all assignments, send escalating SNS reminders, and return summary stats."""
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    response = table.scan()
    items = response['Items']

    reminders_sent = 0
    overdue_count = 0
    upcoming_count = 0
    submitted_count = 0

    for item in items:
        if item.get('submitted', False):
            submitted_count += 1
            continue

        due_ts = int(item['due_timestamp'])
        days_until_due = (due_ts - now_ts) / 86400

        title = item['title']
        assignment_id = item['assignment_id']

        if 0 < days_until_due <= 7 and not item.get('reminder_sent_7day', False):
            message = f"⏰ Reminder: '{title}' is due in {days_until_due:.1f} days."
            sns_client.publish(TopicArn=sns_topic_arn, Message=message, Subject="Assignment Reminder")
            print(f"[SNS ALERT SENT] {message}")
            table.update_item(
                Key={'assignment_id': assignment_id},
                UpdateExpression='SET reminder_sent_7day = :val',
                ExpressionAttributeValues={':val': True}
            )
            reminders_sent += 1
            upcoming_count += 1

        if 0 < days_until_due <= 1 and not item.get('reminder_sent_1day', False):
            message = f"🚨 URGENT: '{title}' is due in less than 1 day!"
            sns_client.publish(TopicArn=sns_topic_arn, Message=message, Subject="URGENT Assignment Reminder")
            print(f"[SNS ALERT SENT] {message}")
            table.update_item(
                Key={'assignment_id': assignment_id},
                UpdateExpression='SET reminder_sent_1day = :val',
                ExpressionAttributeValues={':val': True}
            )
            reminders_sent += 1

        if days_until_due < 0:
            print(f"[OVERDUE] '{title}' was due {abs(days_until_due):.1f} days ago and is still pending.")
            overdue_count += 1

    return {
        "total_assignments": len(items),
        "submitted_count": submitted_count,
        "reminders_sent": reminders_sent,
        "overdue_count": overdue_count,
        "upcoming_count": upcoming_count
    }


def build_dashboard_payload(table, pipeline_status, history):
    """Scan the table and build a JSON-friendly structure for the dashboard to read."""
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    response = table.scan()
    items = response['Items']

    assignments = []
    for item in items:
        due_ts = int(item['due_timestamp'])
        days_until_due = (due_ts - now_ts) / 86400
        weight = extract_weight(item['title'])

        if item.get('submitted', False):
            status = "submitted"
            priority_score = 0
        else:
            priority_score = compute_priority_score(weight, days_until_due)
            if days_until_due < 0:
                status = "overdue"
            elif days_until_due <= 1:
                status = "urgent"
            elif days_until_due <= 7:
                status = "upcoming"
            else:
                status = "later"

        assignments.append({
            "title": item['title'],
            "course_name": item['course_name'],
            "due_date": datetime.fromtimestamp(due_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
            "days_until_due": round(days_until_due, 1),
            "status": status,
            "weight": weight,
            "priority_score": priority_score
        })

    assignments.sort(key=lambda a: a['days_until_due'])

    return {
        "generated_at": now.isoformat(),
        "assignments": assignments,
        "pipeline_status": pipeline_status,
        "history": history
    }


@mock_aws
def run_pipeline():
    pipeline_status = {
        "google_classroom": {"status": "pending"},
        "aws_pipeline": {"status": "pending"},
        "azure_blob": {"status": "pending"}
    }

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
    try:
        service = get_classroom_service()
        course = service.courses().get(id=COURSE_ID).execute()
        course_name = course.get('name')

        coursework_results = service.courses().courseWork().list(courseId=COURSE_ID).execute()
        coursework = coursework_results.get('courseWork', [])

        synced_at = datetime.now(timezone.utc).isoformat()
        inserted_count = 0

        print("Checking submission status for each assignment (this may take a moment)...")
        for item in coursework:
            due_ts = due_date_to_timestamp(item.get('dueDate'), item.get('dueTime'))
            if due_ts is None:
                continue

            is_submitted = get_submission_status(service, COURSE_ID, item['id'])

            table.put_item(Item={
                'assignment_id': item['id'],
                'course_name': course_name,
                'title': item.get('title'),
                'due_timestamp': due_ts,
                'submitted': is_submitted,
                'reminder_sent_7day': False,
                'reminder_sent_1day': False,
                'synced_at': synced_at
            })
            inserted_count += 1

        pipeline_status["google_classroom"] = {
            "status": "ok",
            "assignments_synced": inserted_count,
            "synced_at": synced_at
        }
        print(f"\nInserted {inserted_count} assignments with due dates into DynamoDB.\n")

    except Exception as e:
        pipeline_status["google_classroom"] = {"status": "error", "detail": str(e)}
        print(f"[CLASSROOM SYNC FAILED] {e}")

    # --- Verify: scan the table and print everything ---
    response = table.scan()
    print("Current table contents:")
    for record in response['Items']:
        due_readable = datetime.fromtimestamp(int(record['due_timestamp']), tz=timezone.utc)
        submitted_label = "SUBMITTED" if record.get('submitted') else "PENDING"
        print(f"- [{submitted_label}] {record['title']} | due: {due_readable} | course: {record['course_name']}")

    # --- Set up mocked SNS ---
    try:
        sns = boto3.client('sns', region_name='us-east-1')
        topic = sns.create_topic(Name='AssignmentReminders')
        topic_arn = topic['TopicArn']
        sns.subscribe(TopicArn=topic_arn, Protocol='email', Endpoint='you@example.com')

        print("\n--- Checking for due reminders ---")
        stats = check_reminders(table, sns, topic_arn)
        pipeline_status["aws_pipeline"] = {
            "status": "ok",
            "reminders_sent": stats["reminders_sent"],
            "note": "DynamoDB + SNS emulated locally via moto"
        }
    except Exception as e:
        pipeline_status["aws_pipeline"] = {"status": "error", "detail": str(e)}
        stats = {"total_assignments": 0, "submitted_count": 0, "reminders_sent": 0, "overdue_count": 0, "upcoming_count": 0}
        print(f"[AWS PIPELINE FAILED] {e}")

    # --- Export real summary to Azure Blob Storage ---
    print("\n--- Exporting summary to Azure Blob Storage ---")
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **stats
    }
    azure_result = upload_summary_to_blob(summary)
    if azure_result["status"] == "ok":
        pipeline_status["azure_blob"] = {
            "status": "ok",
            "blob_name": azure_result["blob_name"],
            "container": azure_result["container"]
        }
    else:
        pipeline_status["azure_blob"] = {"status": "error", "detail": azure_result["detail"]}

    # --- Read back run history from Azure for the trend view ---
    print("\n--- Fetching run history from Azure for trend view ---")
    history = fetch_recent_summaries(limit=10)

    # --- Write local dashboard data file (must happen inside mock_aws context, table is still live) ---
    print(f"\n--- Writing dashboard data to {DASHBOARD_DATA_FILE} ---")
    dashboard_payload = build_dashboard_payload(table, pipeline_status, history)
    with open(DASHBOARD_DATA_FILE, 'w') as f:
        json.dump(dashboard_payload, f, indent=2)
    print(f"Wrote {len(dashboard_payload['assignments'])} assignments to {DASHBOARD_DATA_FILE}")


if __name__ == '__main__':
    run_pipeline()