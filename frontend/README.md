# FaceTrack — Frontend

Next.js 14 (App Router) frontend for the FaceTrack AI Face Attendance System.

## Tech Stack

- **Framework:** Next.js 14 (App Router, TypeScript)
- **Styling:** Tailwind CSS 3.4 + Shadcn UI components
- **State:** Zustand
- **Charts:** Recharts
- **Icons:** Lucide React
- **HTTP:** Axios (with JWT interceptor)
- **Theming:** next-themes (dark / light)

## Getting Started

```bash
# Install dependencies
npm install

# Create env file
cp .env.local.example .env.local
# Default: NEXT_PUBLIC_API_URL=http://localhost:5000

# Development
npm run dev        # http://localhost:3000

# Production build
npm run build
npm start
```

## Pages

| Route                      | Role  | Description                   |
| -------------------------- | ----- | ----------------------------- |
| `/login`                   | Public | Login                        |
| `/register`                | Public | Registration                 |
| `/admin`                   | Admin  | Dashboard (stats + charts)   |
| `/admin/users`             | Admin  | Manage users                 |
| `/admin/train`             | Admin  | Train face model             |
| `/admin/group-scan`        | Admin  | Multi-face group scan        |
| `/admin/attendance`        | Admin  | Attendance records           |
| `/admin/reports`           | Admin  | Reports & analytics          |
| `/dashboard`               | User   | User dashboard               |
| `/dashboard/attendance`    | User   | Mark attendance (Solo/Group) |
| `/dashboard/records`       | User   | My records                   |
| `/dashboard/profile`       | User   | Profile settings             |

## Project Structure

```
src/
├── app/            # Next.js App Router pages & layouts
├── components/     # Reusable components + Shadcn UI
├── lib/            # Axios config, types, utils
├── store/          # Zustand auth store
├── providers/      # Theme & auth context providers
└── middleware.ts   # Route middleware
```

## Environment Variables

| Variable             | Default                  | Description       |
| -------------------- | ------------------------ | ----------------- |
| `NEXT_PUBLIC_API_URL`| `http://localhost:5000`  | Backend API URL   |
