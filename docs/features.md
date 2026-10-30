# Features & Requirements

Source: *HRD Intelligence – System Overview, Scope & Design* (26-10-2026) and *Project Detail / Detail Features*.
Status column convention: this repo has no status info from the source docs, so everything below is **spec (planned)** unless you mark it otherwise here.

## 1. Roles & permissions

Only two roles exist in the schema (`roles.role_name`: `admin`, `instructor`). The overview text says "three main roles" but lists only two (see Open Questions in CLAUDE.md).

| Capability | Admin (web) | Instructor (web) | Admin (mobile) | Instructor (mobile) |
| --- | --- | --- | --- | --- |
| Authentication | Full | Full | Full | Full |
| Student management | Full | View | View | View |
| Attendance | Full | View | View | View |
| Scores | Full | View | Quick / View | View |
| Manage extra class | Full | — | Quick / View | — |
| Manage overtime | Full | — | Quick / View | — |
| Allowance | Full | — | Quick / View | — |
| Feedback (student evaluation) | Full | Full | View | View / Submit |
| Alumni | Full | — | View | — |
| Data management | Full | Upload / view / manage teaching materials | Full | View teaching materials |
| Notification | Full | Student risk alert / OT reminder | Full alert | Full alerts |
| AI chatbot | Full | Authorized data only | Full | Authorized data only |

## 2. Authentication (Keycloak, JWT)
- Login with email + password.
- Forgot password: enter email, receive reset link (features doc) / OTP flow (workflow doc: send OTP to email, verify OTP page, new password page, resend OTP, incorrect/expired token messages).
- Change password: current password, new password, confirmation.
- Passwords live in Keycloak only. `users.keycloak_id` links the app user to the Keycloak account.

## 3. Student management & attendance (Admin + Instructor)
- **Student profiles**: name, email, phone, gender, DOB, generation, classroom, course, enrollment date, university. Student detail tabs: personal profile, attendance, score, evaluation, risk & support. Search by name/email. Filter by class and status (active, dropped, graduated, all).
- **Attendance**: view records; filter by class, date (month or specific day), status (all, on time, late, miss scan, absent); search by student name.
- **Scores**: per subject; total and rank calculated automatically; search by student name; filter by classroom or monthly result.
- **At-risk tracking**: auto-identify students by low attendance and/or declining scores (also attitude); alerts by risk indicators; filter by risk level (high/medium/low) and type (all, attendance, score, attitude); sort (high to low, low to high, name A–Z).

### Admin only
- **Instructor overtime allowance**: view overtime records and total hours; auto-calculate allowance from hours; manage/update the overtime rate; export CSV.
- **Score weights**: admin sets the weight that affects total score calculation.
- **Extra class & allowance**: view students' extra-class records and total hours (filter by month); approve/reject extra-class requests; auto-calculate allowance from hours; update the extra-class rate; allowance history by student, class or month.
- **Monthly allowance**: manage types and amounts: meal, Korean language, IT score-based (tiers e.g. ≥90, ≥80), extra class, class leader, attitude & attendance, other. Update rules when policy changes. Auto-calculate each student's monthly total (sum of active rules). Export CSV/Excel (choose period and allowance types; Excel gets formatted summary per class). Rule calculation types for new rules: fixed, per unit, tiered, ranked (one-off prize by placing), manual. Rules can be toggled on/off; off rules are excluded from the total.
- **Coding challenge** (part of allowance): one-off team challenge for the basic course with a prize pool; top-3 team prizes with amount per member; teams and members; payout month; "included in allowance" toggle (if off, not paid through allowance); max students per team; add/edit/delete team.

### Instructor only
- **Student evaluation** (private, never visible to students): rate behavior/attitude, soft skills, hard skills (1–5) + comment; view/edit/manage own past evaluations; filter by class, course.
- **Overtime**: submit and view overtime reports; receive reminders for extra-class requests on standby days.

## 4. Alumni management (Admin only)
- CRUD alumni profile: personal info, education, generation, course, salary range, phone, industry, company, position, email, uploaded documents (cv, certificate, other).
- Search by name/email. Filter by generation, employment status (employed, freelance/self-employed, further studies, unemployed), sector, main tech, salary, stage.
- **Profile update requests**: manual (admin sends) or automatic (AI agent, every 6 months). Emailed form with a tokenized link (hash stored, link expires); when the alumnus submits, admin data updates and admin is notified (in-app + email, "alumni job alert").
- **Employment tracking**: current status plus history of past/current jobs (company, title, sector, location) via `employment_history` + `organizations`.
- Alumni statistics inside the module (total alumni, employment status, unemployed, update requests; KPI cards and charts).

## 5. Data management (Admin + Instructor)
- Formats: TXT, MD, XLSX, CSV, PDF, DOCX, PPTX, PNG, JPEG.
- Create, rename, move, delete, duplicate folders/files. Export folder as ZIP or download file. Soft delete (`deleted_at`).
- Ownership: creator is owner. Owner can share, manage/change permissions, permanently delete.
- Permissions: `viewer` (read-only), `editor` (view, download, rename, move, duplicate, share, delete); remove access revokes. Users only see items they own or that are shared with them.
- Search by name; filter by extension and ownership (own, shared, all); sort alphabetically or by upload date.
- Uploaded files are processed (text extraction/OCR, chunking, embedding) for RAG: `files.processing_status` = pending, processing, completed, failed.
- Folder-specific AI chat opens from a folder (see ai-and-agents.md).

## 6. Dashboard & analytics
- **Admin + Instructor**: student overview KPI cards (total, active, dropped, graduated); students at risk (academic score, attendance rate, risk level low/medium/high); daily attendance donut (present, absent, late, permission); gender donut; students by generation (bar); top 5 students by course score, extra-class hours, IT score, Korean score (filter by generation).
- **Admin only**: alumni overview (total alumni KPI, employment status employed/unemployed/other, generation bar chart); export dashboard report as CSV or PDF with customize, preview and choose-what-to-export.
- Data loaded from RDA API, Assessment API and own DB. `dashboard_snapshots` stores KPI snapshots.

## 7. Notifications
- Channels: in-app (bell icon, unread count, mark all read, notification panel) and email. Mobile push via Firebase Cloud Messaging.
- Triggers: **Admin + Instructor**: low attendance (rule in workflow: attendance < 85%), declining academic performance (monthly score drop). **Admin only**: alumni updated (alumnus submitted the form). **Instructor only**: overtime reminders (before and after, on standby days).
- Table: `notifications` (types: low_attendance, declining_academic, alumni_update, overtime_reminder).

## 8. Mobile app scope
Native apps: Android (Kotlin/Jetpack Compose) and iOS (Swift/SwiftUI). Mobile is mostly view/quick-action per the matrix in section 1. Mobile workflows exist for alumni, authentication, data management, AI chatbot, AI agents, dashboard, student management (see workflows.md).
