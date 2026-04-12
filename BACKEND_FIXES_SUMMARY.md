# Backend Fixes Summary

## Files changed
- `backend/app.py`

## What was fixed
- `user_mark_attendance` validation logic now ensures:
  - recognized face identity exists in users table
  - recognized identity must match the currently authenticated user
  - unauthorized identity mismatches are rejected with HTTP 403
- This aligns face recognition result with authenticated session context and prevents manual token/photo abuse.

## Why it was necessary
- Original behavior marked attendance for authenticated user regardless of recognized identity.
- That could produce inconsistent or fraudulent records when a user scanned a different registered face.

## Impact on frontend integration
- User Portal face scan remains consistent and secure.
- Landing page continues to use public endpoints; no auth change needed.
- Admin portal remains stable with no behavior regressions.
