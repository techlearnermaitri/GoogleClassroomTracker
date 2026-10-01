import os
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

import re
import json
from datetime import datetime, timezone
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import firebase_admin
from firebase_admin import credentials, firestore, messaging

from azure_export import upload_summary_to_blob, fetch_recent_summaries

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.coursework.me.readonly',
    'https://www.googleapis.com/auth/classroom.student-submissions.me.readonly'
]

CLIENT_SECRET_FILE = 'client_secret_35280772694-vjo8u74df4ta7unled1ftud83d37f0ab.apps.googleusercontent.com.json'
FIREBASE_CRED_FILE = 'classroom-deadline-tracker-firebase-adminsdk-fbsvc-cc3353a382.json'

COURSE_IDS = [
    '863569830512',  # Enterprise Grade Connected Device Application: Self-Driving Cars
    '870758266592',  # TYBTECH-SEM V-Project Life Cycle Management
    '863568983745',  # Emerging Technologies
    '863567057196',  # Computer Vision and Deep Learning
    '863568775850',  # TY.BTECH VOYAGER Reinforcement Learning and NLP
    '863566662310',  # Cloud Application Development
]

DASHBOARD_DATA_FILE = 'dashboard_data.json'
DEFAULT_WEIGHT = 10


def get_firestore_client():
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_CRED_FILE)
        firebase_admin.initialize_app(cred)
    return firestore.client()


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
    return int(match.group(1)) if match else DEFAULT_WEIGHT


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
            courseId=course_id, courseWorkId=coursework_id
        ).execute()
        subs = submissions.get('studentSubmissions', [])
        if not subs:
            return False
        return subs[0].get('state') in ('TURNED_IN', 'RETURNED')
    except Exception as e:
        print(f"    (Could not fetch submission status for {coursework_id}: {e})")
        return False


def sync_course(service, assignments_ref, course_id):
    """Pulls one course's assignments + submission status into Firestore.
    Returns (course_name, inserted_count).
    """
    course = service.courses().get(id=course_id).execute()
    course_name = course.get('name')

    coursework_results = service.courses().courseWork().list(courseId=course_id).execute()
    coursework = coursework_results.get('courseWork', [])

    synced_at = datetime.now(timezone.utc).isoformat()
    inserted_count = 0

    for item in coursework:
        due_ts = due_date_to_timestamp(item.get('dueDate'), item.get('dueTime'))
        if due_ts is None:
            continue

        is_submitted = get_submission_status(service, course_id, item['id'])
        composite_id = f"{course_id}_{item['id']}"

        doc_ref = assignments_ref.document(composite_id)
        existing = doc_ref.get()
        # Preserve reminder flags across runs so we don't re-alert for the same deadline
        prior = existing.to_dict() if existing.exists else {}

        doc_ref.set({
            'course_id': course_id,
            'course_name': course_name,
            'title': item.get('title'),
            'due_timestamp': due_ts,
            'submitted': is_submitted,
            'reminder_sent_7day': prior.get('reminder_sent_7day', False),
            'reminder_sent_1day': prior.get('reminder_sent_1day', False),
            'synced_at': synced_at
        })
        inserted_count += 1

    return course_name, inserted_count


def send_push(device_token, title, body):
    """Sends a real push notification via Firebase Cloud Messaging. Returns True on success."""
    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            token=device_token
        )
        messaging.send(message)
        return True
    except Exception as e:
        print(f"[FCM SEND FAILED] {e}")
        return False


def get_device_token(db):
    doc = db.collection('device_tokens').document('browser').get()
    if doc.exists:
        return doc.to_dict().get('token')
    return None


def check_reminders(assignments_ref, device_token):
    """Scan all assignments, send escalating FCM push reminders, and return summary stats."""
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    docs = list(assignments_ref.stream())

    reminders_sent = 0
    overdue_count = 0
    upcoming_count = 0
    submitted_count = 0
    valid_count = 0

    for doc in docs:
        item = doc.to_dict()
        if 'due_timestamp' not in item or 'title' not in item:
            continue  # skip malformed/legacy documents (e.g. old manual test entries)
        valid_count += 1
        if item.get('submitted', False):
            submitted_count += 1
            continue

        due_ts = int(item['due_timestamp'])
        days_until_due = (due_ts - now_ts) / 86400
        title = item['title']

        if 0 < days_until_due <= 7 and not item.get('reminder_sent_7day', False):
            body = f"Due in {days_until_due:.1f} days."
            if device_token:
                if send_push(device_token, f"Reminder: {title}", body):
                    reminders_sent += 1
            else:
                print(f"[NO DEVICE REGISTERED] Would have reminded: '{title}' — {body}")
            assignments_ref.document(doc.id).update({'reminder_sent_7day': True})
            upcoming_count += 1

        if 0 < days_until_due <= 1 and not item.get('reminder_sent_1day', False):
            body = "Due in less than a day!"
            if device_token:
                if send_push(device_token, f"URGENT: {title}", body):
                    reminders_sent += 1
            else:
                print(f"[NO DEVICE REGISTERED] Would have sent urgent reminder: '{title}'")
            assignments_ref.document(doc.id).update({'reminder_sent_1day': True})

        if days_until_due < 0:
            print(f"[OVERDUE] '{title}' was due {abs(days_until_due):.1f} days ago and is still pending.")
            overdue_count += 1

    return {
        "total_assignments": valid_count,
        "submitted_count": submitted_count,
        "reminders_sent": reminders_sent,
        "overdue_count": overdue_count,
        "upcoming_count": upcoming_count
    }


def build_dashboard_payload(assignments_ref, pipeline_status, history):
    """Read all assignments from Firestore and build a JSON-friendly structure for the dashboard."""
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())

    assignments = []
    for doc in assignments_ref.stream():
        item = doc.to_dict()
        if 'due_timestamp' not in item or 'title' not in item or 'course_name' not in item:
            continue  # skip malformed/legacy documents (e.g. old manual test entries)
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
            "course_id": item.get('course_id', ''),
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


def run_pipeline():
    pipeline_status = {
        "google_classroom": {"status": "pending"},
        "firestore": {"status": "pending"},
        "fcm_notifications": {"status": "pending"},
        "azure_blob": {"status": "pending"}
    }

    db = get_firestore_client()
    assignments_ref = db.collection('assignments')
    print("Connected to Firestore.\n")

    # --- Pull real data from Google Classroom, across all tracked courses ---
    service = get_classroom_service()
    total_inserted = 0
    synced_course_names = []
    failed_courses = []

    for course_id in COURSE_IDS:
        try:
            print(f"Syncing course {course_id}...")
            course_name, inserted_count = sync_course(service, assignments_ref, course_id)
            total_inserted += inserted_count
            synced_course_names.append(course_name)
            print(f"  -> '{course_name}': {inserted_count} assignments with due dates")
        except Exception as e:
            failed_courses.append(course_id)
            print(f"  [COURSE SYNC FAILED] {course_id}: {e}")

    if synced_course_names:
        pipeline_status["google_classroom"] = {
            "status": "ok",
            "assignments_synced": total_inserted,
            "courses_synced": synced_course_names,
            "synced_at": datetime.now(timezone.utc).isoformat()
        }
        pipeline_status["firestore"] = {
            "status": "ok",
            "assignments_synced": total_inserted,
            "note": "Real Firestore (Native mode), Firebase Spark plan"
        }
        if failed_courses:
            pipeline_status["google_classroom"]["detail"] = f"{len(failed_courses)} course(s) failed: {failed_courses}"
    else:
        pipeline_status["google_classroom"] = {"status": "error", "detail": "No courses synced successfully."}
        pipeline_status["firestore"] = {"status": "error", "detail": "No data to write."}

    print(f"\nInserted/updated {total_inserted} assignments across {len(synced_course_names)} course(s) in Firestore.\n")

    print("Current Firestore contents:")
    for doc in assignments_ref.stream():
        item = doc.to_dict()
        if 'due_timestamp' not in item or 'title' not in item or 'course_name' not in item:
            print(f"  (skipping malformed document '{doc.id}' — missing expected fields)")
            continue
        due_readable = datetime.fromtimestamp(int(item['due_timestamp']), tz=timezone.utc)
        label = "SUBMITTED" if item.get('submitted') else "PENDING"
        print(f"- [{label}] {item['title']} | due: {due_readable} | course: {item['course_name']}")

    # --- Reminders via real Firebase Cloud Messaging ---
    print("\n--- Checking for due reminders ---")
    device_token = get_device_token(db)
    if not device_token:
        print("No device registered yet — open the dashboard and click 'Enable reminders' at least once.")

    stats = check_reminders(assignments_ref, device_token)
    pipeline_status["fcm_notifications"] = {
        "status": "ok" if device_token else "pending",
        "reminders_sent": stats["reminders_sent"],
        "detail": "Real push via Firebase Cloud Messaging" if device_token
                   else "No device registered yet — enable reminders on the dashboard"
    }

    # --- Export summary to Azure Blob Storage ---
    print("\n--- Exporting summary to Azure Blob Storage ---")
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), **stats}
    azure_result = upload_summary_to_blob(summary)
    if azure_result["status"] == "ok":
        pipeline_status["azure_blob"] = {
            "status": "ok", "blob_name": azure_result["blob_name"], "container": azure_result["container"]
        }
    else:
        pipeline_status["azure_blob"] = {"status": "error", "detail": azure_result["detail"]}

    # --- Read run history back from Azure for the trend view ---
    print("\n--- Fetching run history from Azure for trend view ---")
    history = fetch_recent_summaries(limit=10)

    # --- Write local dashboard data file ---
    print(f"\n--- Writing dashboard data to {DASHBOARD_DATA_FILE} ---")
    dashboard_payload = build_dashboard_payload(assignments_ref, pipeline_status, history)
    with open(DASHBOARD_DATA_FILE, 'w') as f:
        json.dump(dashboard_payload, f, indent=2)
    print(f"Wrote {len(dashboard_payload['assignments'])} assignments to {DASHBOARD_DATA_FILE}")


if __name__ == '__main__':
    run_pipeline()