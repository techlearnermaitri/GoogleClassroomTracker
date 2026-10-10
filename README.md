
# 🎮 Deadline Desk

A gamified student productivity dashboard that combines Google Classroom assignment tracking, cloud-powered reminders, personal task management, focus sessions, and subject-wise notes in a retro pixel-RPG interface.

## ✨ Features

### 📊 Dashboard
- Personalized greeting and overview of academic progress.
- Level, XP progress bar, daily streak, quests, and badges.
- Today's quests and next upcoming deadline.
- Quick access to Focus Mode through the **Start Focus** button.
- Upcoming deadlines, overdue tasks, and recent achievements.
- Overdue section appears only when overdue tasks exist.

### ☁️ Cloud-Powered Assignment Tracking
- Fetches assignments from **6 Google Classroom courses** using `python main.py`.
- Tracks assignment titles, due dates, due times, and submission status.
- Stores assignment data and persistent reminder flags in **Google Cloud Firestore**.
- Sends real push notifications using **Firebase Cloud Messaging (FCM)** at 7 days and 1 day before deadlines.
- Archives pipeline summaries in **Azure Blob Storage** and retrieves historical data for trend visualizations.
- Extracts marks from assignment titles (e.g., `(20 Marks)`) and calculates task priority using marks and time remaining.
- Skips malformed documents to prevent pipeline failures.

### 📋 Quest Board
- View Classroom assignments and personal tasks in separate groups.
- Filter tasks by subject and status, and search for specific tasks.
- Sort by due date, priority, or XP reward.
- View task status charts, historical trends, and cloud pipeline status.

### 🎯 Personal Tasks
- Create tasks with a title, subject, due date, time, and XP reward.
- Store tasks in Firestore alongside Classroom assignment data.
- Complete tasks to earn XP and track progress.

### 🕹️ Gamification
- Earn XP by completing tasks.
- Progress through levels, with **100 XP per level**.
- Maintain a daily streak.
- Unlock 6 achievements with achievement notifications.
- Receive reward notifications upon task completion.

### ⏱️ Focus Mode
- Select a quest to work on.
- Run a 25-minute focus timer.
- Complete the selected task and track progress.

### 📝 Subject-Wise Notes
- Organize notes by subject.
- Add headings and text, along with image and audio blocks.
- Display creation and last-modified dates.
- Upload and serve image and audio files through deployed **Zoho Catalyst File Store functions** (`uploadMedia` and `serveMedia`).

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| Programming language | Python |
| Assignment source | Google Classroom API |
| Database | Google Cloud Firestore |
| Authentication and notifications | Firebase Authentication / Firebase Cloud Messaging |
| Cloud storage and historical summaries | Microsoft Azure Blob Storage |
| Media storage | Zoho Catalyst File Store |
| Backend functions | Zoho Catalyst Serverless Functions |
| Frontend | HTML, CSS, JavaScript |
| Data visualization | Dashboard charts |
| Interface | Responsive, retro pixel-RPG design |

## 🏗️ Architecture

```text
Google Classroom
       |
       v
Python Data Pipeline
   (main.py)
       |
       v
Google Cloud Firestore
       |
       +------> Firebase Cloud Messaging
       |           |
       |           v
       |       Push Reminders
       |
       +------> Dashboard & Quest Board
       |
       +------> Personal Tasks & Gamification

Python Data Pipeline
       |
       v
Azure Blob Storage
       |
       v
Historical Trends & Charts

Notes Interface
       |
       v
Zoho Catalyst Functions
       |
       v
Zoho Catalyst File Store
       |
       v
Image & Audio Retrieval
```

## 🎨 UI & Design

- Retro pixel-RPG aesthetic.
- Sidebar navigation across dashboard sections.
- Gamified progress indicators, quests, and achievements.
- Responsive layout that adapts to smaller screens.

## 🚀 Core Workflow

1. Run the Python pipeline to retrieve assignments from Google Classroom.
2. Process assignment deadlines, marks, submission status, and priority.
3. Store assignment records and reminder states in Firestore.
4. Send deadline reminders through Firebase Cloud Messaging when applicable.
5. Archive pipeline summaries in Azure Blob Storage for historical analysis.
6. Track assignments and personal tasks through the dashboard.
7. Earn XP, unlock achievements, maintain streaks, and use Focus Mode.
8. Create subject-wise notes with text, images, and audio attachments.

## 🔐 Configuration

Configure the required credentials and environment variables for Google Classroom, Firebase, Azure Blob Storage, and Zoho Catalyst before running the relevant components.

**Security:** Never commit API keys, service-account credentials, access tokens, or environment files containing secrets to version control.

## 📌 Project Status

The dashboard, assignment pipeline, cloud integrations, gamification features, Focus Mode, personal tasks, and subject-wise notes are implemented. Image and audio uploads and retrieval through Zoho Catalyst have also been implemented.

---

**Deadline Desk — Turn deadlines into quests.** 🎮
