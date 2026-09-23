import os
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/classroom.courses.readonly',
    'https://www.googleapis.com/auth/classroom.coursework.me.readonly'
]

flow = InstalledAppFlow.from_client_secrets_file(
    'client_secret_35280772694-vjo8u74df4ta7unled1ftud83d37f0ab.apps.googleusercontent.com.json',
    SCOPES
)
creds = flow.run_local_server(port=0)

service = build('classroom', 'v1', credentials=creds)

results = service.courses().list(pageSize=10).execute()
courses = results.get('courses', [])

if not courses:
    print('No courses found.')
else:
    print('Your courses:')
    for course in courses:
        print(f"- {course['name']} (id: {course['id']})")

# NEW PART: pull assignments for one course
course_id = '863566662310'  # Cloud Application Development

coursework_results = service.courses().courseWork().list(courseId=course_id).execute()
coursework = coursework_results.get('courseWork', [])

if not coursework:
    print(f'\nNo coursework found for course {course_id}.')
else:
    print(f'\nAssignments for course {course_id}:')
    for item in coursework:
        title = item.get('title')
        due = item.get('dueDate')
        due_time = item.get('dueTime')
        print(f"- {title} | due: {due} {due_time if due_time else ''}")
        