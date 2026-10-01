importScripts('https://www.gstatic.com/firebasejs/10.13.1/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.13.1/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: "AIzaSyC0TtBJdWZBgI4vxMaQZLUJ1fQO19IMZZw",
  authDomain: "classroom-deadline-tracker.firebaseapp.com",
  projectId: "classroom-deadline-tracker",
  storageBucket: "classroom-deadline-tracker.firebasestorage.app",
  messagingSenderId: "35280772694",
  appId: "1:35280772694:web:98cf8fb72940b7ad53e5f7"
});

const messaging = firebase.messaging();

messaging.onBackgroundMessage((payload) => {
  const title = (payload.notification && payload.notification.title) || 'Deadline Desk';
  const body = (payload.notification && payload.notification.body) || '';
  self.registration.showNotification(title, { body });
});
