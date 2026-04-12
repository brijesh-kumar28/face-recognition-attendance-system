# Missing Backend APIs

During this Phase 1-2 implementation, no mandatory APIs were missing for the required core functionality. The current API surface provides the following endpoints:

- `POST /api/public/multi-attendance` (used by landing page)
- `POST /api/public/mark-attendance` (alternative public single-face)
- `POST /api/user/mark-attendance` (user portal face check)
- `GET /api/user/stats`, `GET /api/user/attendance`, `GET /api/user/profile` (user data)
- `GET /api/admin/stats`, `GET /api/admin/users`, `GET /api/admin/attendance`, `GET /api/admin/reports` (admin data)
- `/api/admin/train`, `/api/admin/upload-training-images`, `/api/admin/capture-training-images` etc.

## Potential enhancements (not required but useful)

1. API: `GET /api/public/healthcheck`
   - Purpose: quick health check for public scanner service.
   - Implemented in `backend/app.py`.
   - Module: Landing Page.

2. API: `GET /api/public/latest-attendance`
   - Purpose: fetch last N attendance events for live activity wall.
   - Implemented in `backend/app.py`.
   - Module: Landing Page / Admin Portal.

3. API: `GET /api/admin/recognition-report`
   - Purpose: more detailed recognition metrics (total detections, unmatched face ratio).
   - Implemented in `backend/app.py` and integrated in `frontend/app/admin/reports/page.tsx`.
   - Module: Admin Portal.
