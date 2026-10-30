# Workflows

Source: *Project Workflow, Use Cases & Detail Features* (FigJam export, web + mobile). Written as step lists so they can be implemented directly. Admin = HRD Admin. Anyone not authorized for a page gets "Page not found".

## Navigation after login
- Admin panel: Overview (Dashboard, AI Assistant, AI Agent, Data Management); Students (Students, Attendance, Scores, At-risk students, Student Evaluation, Allowance); Instructors (Instructors, Overtime); Alumni; Sign out.
- Instructor panel: Overview (Dashboard, AI Assistant, Students, Attendance, Scores, At-risk students); Teaching (Feedback, Teaching materials, Standby overtime); Sign out.

## Authentication
1. Enter email + password. Success: go to Admin/Instructor panel by role. Failure: error, retry.
2. Forgot password: enter email, validate; send OTP to email; verify OTP page (resend OTP available; incorrect and expired token messages); then new password page (validate new password) and finish.

## Notifications
- Monitor data (attendance, scores, alumni, schedule). Rules: attendance < 85% -> low attendance; monthly score drop -> academic decline; alumni form sent -> alumni updated; instructor overtime -> overtime reminder before and after.
- Save notification; if in-app is not the channel, send email. Admin receives alumni updated, academic decline, low attendance. Instructor receives overtime, academic decline, low attendance.
- Bell icon opens the notification panel (list all). "Mark all read" clears the unread badge.

## Dashboard (admin + instructor)
1. Check role; others get Page not found. Load data from RDA, Assessments, own DB. Generation filter defaults to all.
2. KPI cards: total, active, graduated, dropped. Charts: gender donut, attendance donut (present, late, absent, permission), students by generation.
3. At-risk table: if no student meets a risk rule show an empty table; otherwise list by academic score and by attendance; view each student and all.
4. Top students: top 5 for academic score, extra-class hours, IT score, Korean score.
5. Admin only: alumni card (total alumni, employment status employed/freelance/further studies/unemployed with % and count, employed count and percent, bar per generation). Export report: choose CSV or PDF, preview, download.

## Student management
- Admin and instructor: list students (search name/email; filter generation, class, course, status); student detail (personal info, attendance with date/class/status filters, academic performance, instructor feedback/evaluation).
- Attendance: list records, search by student name, filter by date, class, status.
- Scores: list, filter by class and score range, search by name; types: assignment, quiz, exam, homework.
- At-risk tracking: system auto-identifies students; if at risk push alert to admin; list all at-risk; filter by high, medium, low.
- Instructor only: evaluation list; submit new, edit, delete; rate behaviour, soft skill, hard skill.
- Admin only: Allowance, Extra class, Overtime (below).

## Allowance (admin only)
1. Load students, allowance rules, extra-class hours, scores. Select month (default current). Total per student = sum of all active rules.
2. Page: KPI cards (total payable, students paid, extra class), student monthly allowance table (columns: student, meal, Korean, IT score, extra class, leader, attitude, other, total), class filter, "recalculate for selected month", info note (sample amounts until HRD confirms policy).
3. Click a student for allowance history (received this term, extra-class hours, IT score band, class leader, monthly history table). Export CSV/Excel via popup (choose period and allowance types; CSV plain rows, Excel formatted + summary per class).
4. Allowance Types & Rules: rule cards (name, calculation type, amount/tiers, qualifying students). Toggle on/off (off = excluded from monthly total); edit rule (meal fixed amount; Korean score tiers; IT score tiers; extra class rate per hour; class leader amount per leader; attitude & attendance tiers); save then recalculate; new rule popup with calculation type fixed, per unit, tiered, ranked, manual.
5. Coding Challenge: banner (basic course, one-off team prize pool), prize podium (top 3, amount per member), challenge settings (date, max team size, included-in-allowance toggle, payout month), teams & results table (team, members, placing, team prize, per student), add/edit/delete team (confirm delete), edit prizes popup.

## Extra class and overtime (admin only)
- Extra class: load extra-class data from DB; list; filter by date/class; view a student's extra class; search; approve extra-class request; edit extra-class rate (save confirmation); student allowance history; export CSV.
- Overtime (instructor overtime): list instructors with overtime; search by name; view allowance detail; edit overtime rate (save confirmation); export CSV/Excel.

## Instructors (admin only)
List instructors; search by name/email; filter by course; view instructor allowance detail; export CSV/Excel.

## Alumni management (admin only)
1. Statistics: total alumni, employment status, unemployed, update requests (KPI cards and charts); table view.
2. Profile management: create (validate input, save, "created successfully"), edit (load existing), search by name/email (no match: "No Results Found"), filter by main tech, employment, sector, salary, stage.
3. Employment tracking: update current status; add past/current jobs; save; history updated.
4. Profile update requests: manual (admin sends) or automatic (AI agent every 6 months) emails a form; alumnus fills and submits; if valid, update alumni data and notify admin in-app and by email (alumni job alert).

## Data management
- List all files and folders; sort by uploaded date, alphabetically, ownership, file type; filter; search by name; load from DB.
- Upload file/folder; create new folder (if the name exists in the same folder, ask for a new name).
- Per item: view details, rename, move, duplicate (copy and rename), delete, share (needs owner or editor), download (file) or export as ZIP (folder).
- Share: add a person or share to everyone, load members, set permission (view only or edit only), remove access, replace permission.
- If item is a folder: "Chat with Folder" (see AI chatbot).
- Mobile: Home / Shared with me tabs, view all, sort, filter, search, download, chat with folder; view-only for shared.

## AI chatbot
1. Choose new or past chat. Past: open history (recent 10 sessions), search, continue, rename, delete (confirm), load past messages and scope.
2. New: create session; if already 10 sessions show "Your session has reached the limit" and choose an old session or delete oldest.
3. Send message: text or voice. Text: validate (English, not empty) else "please rephrase". Voice: record, speech-to-text, confirm transcript or edit/re-record.
4. Pipeline: detect purpose, embed question, vector search in allowed docs, rank/pick top chunks; no relevant data -> "no information found"; else build prompt, generate with Local LLM, check grounded and attach sources.
5. Output type: text with sources; file/slides (TXT, MD, DOCX, PPTX, PDF) with preview and download; chart or table (bar, line, donut, table) exportable as image. Save message to chat history. Follow-up continues the loop.
6. Scope: general chat = all data the user owns or is shared; folder chat = only selected files in that folder.

## AI agents
1. Page open only to admin (instructor sees a limited agent list: Weekly Summary, At-Risk); others Page not found.
2. Agent list split into Scheduled (Weekly Summary, Feedback Summary, Alumni Profile Update) and Trigger-based (At-Risk, Alumni Job Alert). Select an agent: enabled toggle, agent info, flow board, live log, pause/resume, recent runs, view all runs, reports.
3. "Run now": starting, AI analyzes (step 1 of 3), AI drafts (step 2 of 3), completed. Outputs: Weekly Summary email preview + save PDF to Reports; Feedback Summary open full summary; Alumni Profile email preview; At-Risk review drafts (edit, review & send, AI assistant confirm send); Alumni Job Alert has no extra actions.
4. Reports page: table (report, source, generated, period, status), search/filter (type, period), open report, export (choose sections, PDF or Excel, preview, download, toast "Export started").

## Use cases (summary)
- Admin: login/forgot/change password, view student profiles, monitor attendance, monitor scores, track at-risk, view instructor feedback, dashboard & analytics, manage files & folders, general and folder AI chat, notifications, extra-class and monthly allowance, manage alumni, receive admin alerts & AI agent reports, overtime report.
- Instructor: login/password, view student profiles, attendance, scores, at-risk, manage & submit feedback, view AI feedback summary, dashboard, files, AI chat, notifications, overtime report.
