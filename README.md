# Support System

A multi-project support ticket management system. Teams create, assign, and
resolve tickets across many projects, with automatic email notifications, live
dashboards, comments, file attachments, full-text search, role-based access,
and a complete audit trail.

- **Backend:** FastAPI (Python 3.11), layered architecture (endpoint → service → repository)
- **Frontend:** Next.js (App Router) + TypeScript + TailwindCSS + React Query
- **Auth:** AWS Cognito (proxied through the backend)
- **Database:** Supabase (PostgreSQL)
- **Storage:** AWS S3 (attachments)
- **Email:** AWS SES or SMTP (e.g. Gmail)
- **Logging:** AWS CloudWatch
- **Integrations:** Jira (optional), Discord (per project)

---

## Table of contents

1. [Features](#features)
2. [How tickets work](#how-tickets-work)
3. [How email notifications work](#how-email-notifications-work)
4. [Public pages & routing](#public-pages--routing)
5. [Authentication & sessions](#authentication--sessions)
6. [Architecture](#architecture)
7. [Getting started](#getting-started)
8. [Configuration / settings](#configuration--settings)
   - [Backend environment variables](#backend-environment-variables)
   - [Frontend environment variables](#frontend-environment-variables)
9. [Running with Docker](#running-with-docker)
10. [Project structure](#project-structure)

---

## Features

- **Multi-project workspaces** — Group tickets by product or team. Each project
  has its own members, settings, an email kill switch, and an optional Discord
  webhook.
- **Full ticket lifecycle** — Track work through five statuses (Pending, In
  Progress, Paused, In Review, Completed), with a type and priority on every
  ticket.
- **Admin approval gate** — New tickets stay pending and hidden until an admin
  approves them (making them visible to all) or rejects them (permanent
  delete). Separate from the work-status lifecycle.
- **Inline editing** — Change status, type, and assignee directly from the
  ticket table without opening the ticket.
- **Email notifications** — Actor-aware transactional emails via AWS SES or
  SMTP for every meaningful change (see [below](#how-email-notifications-work)).
- **Comments & @mentions** — Discuss on the ticket timeline; mention teammates
  by email and they get their own notification.
- **File attachments** — Upload files backed by S3 with secure, time-limited
  download links.
- **Search & saved filters** — Full-text search plus filters for status, type,
  priority, assignee, and date range, with reusable saved filter sets.
- **Dashboards & insights**
  - **Personal dashboard** (protected) — your created / assigned / completed
    counts, completion rate, average resolution time, velocity vs. the prior
    period, average time per status, busiest weekdays, and ticket-type mix.
  - **Public insights** (no auth) — aggregate KPIs and charts across public
    projects.
- **Roles & permissions** — `admin` and `user` roles. Admins manage projects,
  users, assignments, and view the audit log.
- **Audit trail** — Every action is recorded and viewable by admins.
- **Landing page** — A public marketing/documentation page at `/` explaining
  how the system works.
- **Responsive UI** — Works on mobile with a slide-in sidebar drawer; the
  sidebar is always visible on large screens.

---

## How tickets work

Every ticket has a **type**, a **priority**, and moves through a **status**
lifecycle.

**Types:** `technical_error`, `bug`, `feature`, `remove`
**Priorities:** `critical`, `high`, `medium`, `low`

**Status lifecycle:**

| # | Status        | What it means |
|---|---------------|---------------|
| 1 | **Pending**     | Newly created. Admins are notified and the creator gets a confirmation email. |
| 2 | **In Progress** | Assigned and being worked on. The assignee is emailed. |
| 3 | **Paused**      | Temporarily on hold (blocked or awaiting input). |
| 4 | **In Review**   | Work is done and awaiting verification. |
| 5 | **Completed**   | Resolved. A completion email is sent and resolution time is recorded for analytics. |

Tickets also support comments (with @mentions), file attachments, an activity
timeline, and inline editing of status/type/assignee from the list view.

### Approval gate

Every new ticket starts in a **pending approval** state, separate from the work
`status` lifecycle above. While pending, a ticket is visible only to its creator
and to admins — everyone else gets a `404`, so pending tickets are never
enumerable.

- **Approve** (admin) — the ticket becomes visible to everyone who can see the
  project, and the deferred "new ticket" notification is sent at this point.
- **Reject** (admin) — the ticket is **permanently deleted** (an audit entry is
  recorded first).

Admins work through pending tickets from an **approval queue** scoped to the
current project. Approval is independent of the work-status lifecycle: a ticket
is approved or not regardless of whether it is Pending, In Progress, Paused, In
Review, or Completed. Existing tickets are treated as already approved, so
nothing historical is hidden.

---

## How email notifications work

Notifications are **actor-aware**, modeled on Jira: an event is attributed to
whoever caused it (the "actor"), and everyone *involved* with the ticket is
notified — **except the actor**, who already knows what they did. Recipients are
de-duplicated by email so nobody is emailed twice for one event.

**Events and their recipients:**

| Event                    | Recipients |
|--------------------------|------------|
| Ticket created           | All admins **+** a confirmation to the ticket owner |
| Status changed           | Ticket creator and assignee |
| Ticket completed         | Ticket creator and assignee |
| Ticket assigned          | The newly assigned user (unless self-assigned) |
| Ticket updated           | Owner + stakeholders (title, description, type, priority, tags) |
| Comment added            | Creator and assignee |
| @mention in a comment    | Each mentioned teammate gets their own email |

**Delivery & controls:**

- **Transport** is chosen by the `EMAIL_PROVIDER` setting: `ses` (AWS SES,
  default) or `smtp` (e.g. Gmail SMTP). SMTP has no sandbox, so it can email any
  recipient without per-address verification.
- **Two opt-outs** gate every send:
  - `project.email_enabled` — a per-project kill switch.
  - `user.email_notifications` — a per-recipient unsubscribe flag.
- If SES has no configured sender (`SES_FROM_EMAIL` empty), sends become no-ops
  so the app runs cleanly in local/dev without email set up.
- Sending is **best-effort** and runs in the background: a failure is logged and
  swallowed, never breaking the request that triggered it.

---

## Public pages & routing

| Path              | Access        | Description |
|-------------------|---------------|-------------|
| `/`               | Public        | Landing page: features, ticket lifecycle, notifications. |
| `/insights`       | Public        | Aggregate insights across public projects (standalone header, no app sidebar). |
| `/login`          | Guests only   | Sign in. Authenticated users are redirected away. |
| `/forgot-password`| Guests only   | Request and confirm a password reset. |
| `/signup`         | Guests only   | Informational (accounts are provisioned by an admin). |
| `/dashboard`      | Authenticated | Personal analytics dashboard. |
| `/tickets`        | Authenticated | Ticket list, search, filters, bulk actions. |
| `/tickets/new`    | Authenticated | Create a ticket. |
| `/tickets/[id]`   | Authenticated | Ticket detail, comments, attachments, timeline. |
| `/admin/projects` | Admin         | Manage projects. |
| `/admin/users`    | Admin         | Manage users. |
| `/admin/audit`    | Admin         | Audit log. |

---

## Authentication & sessions

- Auth is handled **server-side**: the frontend calls the backend `/auth/*`
  endpoints, which proxy to AWS Cognito. The frontend never talks to Cognito
  directly.
- Tokens issued by the backend are stored client-side and attached to each API
  request as a `Bearer` token.
- **Session expiry:** any `401` from an authenticated endpoint clears the stored
  tokens and redirects to `/login?session=expired`, preserving the attempted
  path via `?from=` so the user returns there after signing in.
- **Guest guard:** authenticated users cannot see `/login`, `/signup`, or
  `/forgot-password` — they are redirected to their intended page or the
  dashboard.

---

## Architecture

```
Browser (Next.js) ──HTTP──> FastAPI backend ──> Supabase (Postgres)
                                     │
                                     ├──> AWS Cognito (auth)
                                     ├──> AWS S3 (attachments)
                                     ├──> AWS SES / SMTP (email)
                                     ├──> AWS CloudWatch (logs)
                                     ├──> Jira (optional)
                                     └──> Discord (per project)
```

The backend follows a strict layered architecture:
`endpoint → service → repository`. See `docs/ARCHITECTURE.md`,
`docs/API_SPEC.md`, and `docs/DATABASE_SCHEMA.md` for detail.

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 18+ (or 20+)
- A Supabase project (PostgreSQL)
- AWS account with Cognito, S3, and SES/CloudWatch configured (or use SMTP for
  email in dev)

### 1. Backend

```bash
cd support-backend
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt

# Configure environment
cp .env.example .env   # then fill in values (see below)

# Run the API (http://localhost:8000)
uvicorn app.main:app --reload
```

API docs are available at `http://localhost:8000/docs`.

### 2. Frontend

```bash
cd support-frontend
npm install

# Configure environment
cp .env.local.example .env.local   # then set NEXT_PUBLIC_API_URL

# Run the dev server (http://localhost:3000)
npm run dev
```

---

## Configuration / settings

All backend settings are loaded from environment variables (see
`support-backend/app/config.py`). Copy `.env.example` to `.env` and fill in the
values. **Never commit real `.env` files.**

### Backend environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_ENV` | `development` | Environment name. `production` enables prod behavior. |
| `APP_URL` | `http://localhost:3000` | Public URL of the frontend (used in email links). |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated list of allowed CORS origins. |
| **Database** | | |
| `SUPABASE_URL` | — | Supabase project URL. |
| `SUPABASE_KEY` | — | Supabase service-role key. |
| **AWS general** | | |
| `AWS_REGION` | `us-east-1` | AWS region for all AWS services. |
| `AWS_ACCESS_KEY_ID` | — | AWS access key (optional if using an instance role). |
| `AWS_SECRET_ACCESS_KEY` | — | AWS secret key. |
| **Cognito (auth)** | | |
| `COGNITO_USER_POOL_ID` | — | Cognito user pool ID. |
| `COGNITO_APP_CLIENT_ID` | — | Cognito app client ID. |
| **S3 (attachments)** | | |
| `S3_BUCKET_NAME` | `support-system-uploads` | Bucket for file uploads. |
| **Email delivery** | | |
| `EMAIL_PROVIDER` | `ses` | Transport: `ses` (AWS SES) or `smtp` (e.g. Gmail). |
| `SES_FROM_EMAIL` | — | Verified SES sender address. Empty = email disabled. |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP host (used when `EMAIL_PROVIDER=smtp`). |
| `SMTP_PORT` | `587` | SMTP port. |
| `SMTP_USERNAME` | — | SMTP username. |
| `SMTP_PASSWORD` | — | SMTP password / app password. |
| `SMTP_FROM_EMAIL` | — | SMTP sender. Falls back to `SES_FROM_EMAIL` / `SMTP_USERNAME`. |
| **CloudWatch (logs)** | | |
| `CLOUDWATCH_LOG_GROUP` | `/support-system/api` | Log group name. |
| `CLOUDWATCH_LOG_STREAM` | `development` | Log stream name. |
| **Jira (optional)** | | |
| `JIRA_BASE_URL` | — | Jira base URL (leave empty to disable). |
| `JIRA_EMAIL` | — | Jira bot account email. |
| `JIRA_API_TOKEN` | — | Jira API token. |

> **Discord** is configured per project in the database, so there is no global
> Discord environment variable.

### Frontend environment variables

Copy `support-frontend/.env.local.example` to `.env.local`.

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | Base URL of the backend API. |

> The frontend does **not** need Cognito or S3 config — auth and uploads are
> proxied through the backend.

---

## Running with Docker

A `docker-compose.yml` is provided at the repository root:

```bash
docker compose up --build
```

Set the required environment variables (see above) before starting. The compose
file wires the backend and frontend together for local development.

---

## Project structure

```
Support System/
├── docs/                     # Architecture, API spec, DB schema, plans
├── docker-compose.yml
├── support-backend/          # FastAPI application
│   ├── app/
│   │   ├── api/v1/endpoints/  # HTTP endpoints
│   │   ├── services/          # Business logic
│   │   ├── db/repositories/   # Data access
│   │   ├── integrations/      # AWS, Discord, email, Jira
│   │   ├── audit/             # Audit logging
│   │   ├── core/              # Security, middleware, exceptions
│   │   └── config.py          # Settings (env vars)
│   └── .env.example
└── support-frontend/         # Next.js application
    ├── src/
    │   ├── app/
    │   │   ├── (auth)/         # login, signup, forgot-password (guests only)
    │   │   ├── (protected)/    # dashboard, tickets, admin (authenticated)
    │   │   ├── (public)/       # public insights
    │   │   └── page.tsx        # public landing page
    │   ├── components/         # UI, layout, charts, tickets
    │   ├── hooks/              # React Query hooks
    │   ├── lib/                # API client, token storage, helpers
    │   ├── providers/          # Auth, Project, Query, Toast providers
    │   └── types/              # Shared TypeScript types
    └── .env.local.example
```

For deeper documentation, see the `docs/` directory:

- `docs/ARCHITECTURE.md`
- `docs/API_SPEC.md`
- `docs/DATABASE_SCHEMA.md`
- `docs/BUILD_SEQUENCE.md`
- `docs/IMPLEMENTATION_PLAN.md`
