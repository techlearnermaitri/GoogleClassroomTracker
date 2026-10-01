import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate('classroom-deadline-tracker-firebase-adminsdk-fbsvc-cc3353a382.json')
firebase_admin.initialize_app(cred)

db = firestore.client()

db.collection('assignments').document('test-123').set({
    'title': 'Test Assignment',
    'due_timestamp': 1234567890,
    'submitted': False
})
print("Document written.")

doc = db.collection('assignments').document('test-123').get()
print("Retrieved:", doc.to_dict())