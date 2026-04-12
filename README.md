# FaceTrack — AI Face Attendance System

> Real-time face-recognition attendance system with multi-face group check-in, role-based dashboards, and full reporting.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?logo=flask)
![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)
![TypeScript](https://img.shields.io/badge/TypeScript-5-blue?logo=typescript)
![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-3.4-06B6D4?logo=tailwindcss)
![DeepFace](https://img.shields.io/badge/DeepFace-Face_Recognition-orange)
![License](https://img.shields.io/badge/License-MIT-green)

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Running the Application](#running-the-application)
- [Default Credentials](#default-credentials)
- [API Reference](#api-reference)
- [Screenshots](#screenshots)
- [Contributing](#contributing)
- [License](#license)

---

## Features

### Core

- **Face Recognition** — powered by [DeepFace](https://github.com/serengil/deepface) with OpenCV detector backend
- **Multi-Face Group Check-in** — point the camera at a group; every recognized face is checked in / out simultaneously in a single scan
- **Solo Check-in** — individual face scan for personal attendance
- **Check-in / Check-out** — automatic session management with duplicate & frequency protection

### Admin Panel

- Dashboard with weekly attendance trend & user growth charts
- Manage users (view, search, delete)
- Train / retrain face recognition model
- **Group Scan** page — bulk attend a room of people at once
- Attendance records with date / user / department filters & CSV export
- Reports with department breakdown, status distribution, and monthly trend charts

### User Panel

- Personal dashboard with today's status, monthly stats, and attendance streak
- Mark attendance via webcam (Solo or Group mode)
- View personal attendance records with date filter
- Profile management (name, department, password, profile image)

### Security & UX

- JWT authentication with token expiry
- Role-based access control (Admin / User)
- Protected routes (server middleware + client guards)
- Dark / Light theme toggle
- Fully responsive design
- Toast notifications

---

## Tech Stack

| Layer      | Technology                                                                 |
| ---------- | -------------------------------------------------------------------------- |
| Frontend   | Next.js 14 (App Router), TypeScript, Tailwind CSS, Shadcn UI, Recharts    |
| State      | Zustand                                                                    |
| Backend    | Flask, Flask-CORS                                                          |
| Auth       | JWT (PyJWT) with Bearer tokens                                             |
| Database   | SQLite                                                                     |
| Face AI    | DeepFace, OpenCV                                                           |
| Icons      | Lucide React                                                               |
| Theming    | next-themes                                                                |

---

## Project Structure

```
face-attendance-system/
├── backend/
│   ├── app.py                 # Flask API server (all endpoints)
│   ├── database_setup.py      # DB schema, migrations & seed data
│   ├── check_attendance.py    # Standalone attendance checker (legacy)
│   ├── attendance.db          # SQLite database (auto-created)
│   └── dataset/               # Face image folders per user
│       ├── Brijesh/
│       └── ...
│
├── frontend/
│   ├── app/
│   │   ├── layout.tsx         # Root layout (theme, auth, toast providers)
│   │   ├── page.tsx           # Entry redirect (→ login / admin / dashboard)
│   │   ├── login/             # Login page
│   │   ├── register/          # Registration page
│   │   ├── admin/             # Admin panel (protected)
│   │   │   ├── page.tsx       #   Dashboard (stats + charts)
│   │   │   ├── users/         #   Manage users
│   │   │   ├── train/         #   Train face model
│   │   │   ├── group-scan/    #   Multi-face group attendance
│   │   │   ├── attendance/    #   Attendance records
│   │   │   └── reports/       #   Reports & analytics
│   │   └── dashboard/         # User panel (protected)
│   │       ├── page.tsx       #   User dashboard
│   │       ├── attendance/    #   Mark attendance (Solo / Group)
│   │       ├── records/       #   My records
│   │       └── profile/       #   Profile settings
│   ├── components/            # Reusable components (Sidebar, Topbar, etc.)
│   │   └── ui/                # Shadcn UI primitives
│   ├── lib/
│   │   ├── axios.ts           # Axios instance with JWT interceptor
│   │   ├── types.ts           # TypeScript interfaces
│   │   └── utils.ts           # cn() utility
│   ├── store/
│   │   └── auth-store.ts      # Zustand auth state management
│   ├── providers/             # Theme & auth providers
│   ├── middleware.ts           # Next.js middleware
│   └── .env.local             # Environment variables
│
└── README.md                  # ← You are here
```

---

## Prerequisites

| Tool    | Version |
| ------- | ------- |
| Python  | 3.10+   |
| Node.js | 18+     |
| npm     | 9+      |

> A webcam is required for face registration and attendance scanning.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/face-attendance-system.git
cd face-attendance-system
```

### 2. Backend setup

```bash
# Create and activate virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install flask flask-cors deepface opencv-python PyJWT numpy

# Initialize database (creates tables + seed accounts)
cd backend
python database_setup.py
```

### 3. Frontend setup

```bash
cd frontend
npm install
```

---

## Running the Application

### Start the backend (port 5000)

```bash
cd backend
python app.py
```

### Start the frontend (port 3000)

```bash
cd frontend
npm run dev
```

Open **http://localhost:3000** in your browser.

---

## Default Credentials

| Role  | Email                | Password  |
| ----- | -------------------- | --------- |
| Admin | admin@facetrack.com  | admin123  |
| User  | user@facetrack.com   | user123   |

> These are seeded by `database_setup.py`. Change them after first login.

---

## API Reference

### Authentication

| Method | Endpoint             | Description              | Auth  |
| ------ | -------------------- | ------------------------ | ----- |
| POST   | `/api/auth/login`    | Login (returns JWT)      | No    |
| POST   | `/api/auth/register` | Register new user        | No    |
| GET    | `/api/auth/me`       | Get current user profile | JWT   |

### Admin Endpoints

| Method | Endpoint                   | Description                        | Auth  |
| ------ | -------------------------- | ---------------------------------- | ----- |
| GET    | `/api/admin/stats`         | Dashboard statistics               | Admin |
| GET    | `/api/admin/users`         | List all users                     | Admin |
| DELETE | `/api/admin/users/:id`     | Delete a user                      | Admin |
| GET    | `/api/admin/untrained-users` | List untrained users             | Admin |
| POST   | `/api/admin/train`         | Train / retrain face model         | Admin |
| GET    | `/api/admin/attendance`    | Attendance records (filterable)    | Admin |
| GET    | `/api/admin/reports`       | Reports by period                  | Admin |

### User Endpoints

| Method | Endpoint                    | Description                        | Auth |
| ------ | --------------------------- | ---------------------------------- | ---- |
| GET    | `/api/user/stats`           | User dashboard stats               | JWT  |
| POST   | `/api/user/mark-attendance` | Mark attendance (single face)      | JWT  |
| GET    | `/api/user/attendance`      | User's attendance records          | JWT  |
| GET    | `/api/user/profile`         | Get profile                        | JWT  |
| PUT    | `/api/user/profile`         | Update profile / password / image  | JWT  |

### Multi-Face

| Method | Endpoint                | Description                                  | Auth |
| ------ | ----------------------- | -------------------------------------------- | ---- |
| POST   | `/api/multi-attendance` | Detect ALL faces in image & mark attendance  | JWT  |

---

## Environment Variables

### Frontend (`frontend/.env.local`)

```
NEXT_PUBLIC_API_URL=http://localhost:5000
```

### Backend

The Flask secret key is configured in `app.py`:

```python
app.config["SECRET_KEY"] = "facetrack_jwt_secret_key_2024"
```

> Change this to a strong random value in production.

---

## How It Works

### Face Registration

1. Admin creates a user or user self-registers
2. Face images are stored in `backend/dataset/<username>/`
3. Admin trains the model from the Train Model page (clears cached `.pkl` embeddings)

### Attendance Flow

1. User opens **Mark Attendance** → starts webcam
2. **Solo mode** — captures frame → sends base64 to `/api/user/mark-attendance` → DeepFace verifies identity → check-in or check-out
3. **Group mode** — captures frame → sends to `/api/multi-attendance` → DeepFace detects **all** faces → matches each against the dataset → marks attendance for every recognized user in one go
4. Duplicate protection: min 1 min between check-out, min 5 min between re-check-in
5. Late detection: check-in after 10 AM is marked as "late"

---

## Screenshots

> _Add screenshots of the login page, admin dashboard, group scan results, and user attendance page here._

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

**Built with** DeepFace + Next.js + Flask
