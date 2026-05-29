# Spec-Forge — Setup Guide

This guide walks you through setting up and running Spec-Forge on a new machine from scratch.

---

## What you need before starting

| Requirement | Where to get it |
|---|---|
| Docker Desktop | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop) |
| Git | Pre-installed on macOS/Linux. Windows: [git-scm.com](https://git-scm.com) |
| GitHub account | [github.com](https://github.com) |
| Groq API key (free) | [console.groq.com](https://console.groq.com) |
| ngrok account (free) | [ngrok.com](https://ngrok.com) |

---

## Step 1 — Create two GitHub repositories

You need two repos:

**Repo 1 — The pipeline repo (this codebase)**
- Go to github.com → New repository
- Name it `Spec-Forge`
- Private or public — your choice
- Do **not** initialise with a README

**Repo 2 — The target repo (where generated code lands)**
- Go to github.com → New repository
- Name it `pipeline-target`
- Set to **Private**
- Initialise with a README (so it has a `main` branch)
- **Important:** Go to Settings → General → scroll to Pull Requests → **uncheck Allow auto-merge**

---

## Step 2 — Get your GitHub personal access token

1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click **Generate new token (classic)**
3. Give it a name like `spec-forge`
4. Set expiry to 90 days
5. Check the **`repo`** scope (full repository access)
6. Click **Generate token**
7. Copy the token — it starts with `ghp_...`

---

## Step 3 — Get your Groq API key

1. Go to [console.groq.com](https://console.groq.com) and sign up (free, no card needed)
2. Left sidebar → **API Keys** → **Create API Key**
3. Copy the key — it starts with `gsk_...`

---

## Step 4 — Set up ngrok

1. Go to [ngrok.com](https://ngrok.com) and sign up (free)
2. Left sidebar → **Your Authtoken** → copy the token
3. Left sidebar → **Cloud Edge → Domains** → **New Domain**
4. You get one free static domain like `fuzzy-fox-freely.ngrok-free.app`
5. Copy the domain (bare domain, no `https://`)

---

## Step 5 — Clone and configure the pipeline

```bash
git clone https://github.com/YOUR-USERNAME/Spec-Forge.git
cd Spec-Forge
cp .env.example .env
```

Open `.env` and fill in every value:

```bash
# LLM
LLM_API_KEY=gsk_...your-groq-key...
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile

# GitHub
GITHUB_TOKEN=ghp_...your-token...
GITHUB_TARGET_REPO=your-username/pipeline-target
GITHUB_SOURCE_REPO=your-username/Spec-Forge
GITHUB_WEBHOOK_SECRET=paste-the-secret-you-generate-below

# Pipeline
PIPELINE_BASE_BRANCH=main
ALLOWED_DIRS=src:tests
MAX_RETRIES=3

# Webhook
WEBHOOK_PORT=8080
NGROK_AUTH_TOKEN=your-ngrok-auth-token
NGROK_DOMAIN=your-static-domain.ngrok-free.app

# Paths
LOG_DIR=./runs
PROMPTS_DIR=./prompts
```

**Generate the webhook secret** — run this and paste the output into `GITHUB_WEBHOOK_SECRET`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Step 6 — Configure the GitHub webhook on the target repo

1. Go to `github.com/your-username/pipeline-target`
2. Settings → Webhooks → **Add webhook**
3. Fill in:
   - **Payload URL:** `https://your-static-domain.ngrok-free.app/webhook`
   - **Content type:** `application/json`
   - **Secret:** the same value you put in `GITHUB_WEBHOOK_SECRET`
   - **Which events:** select **Let me select individual events** → check **Pull requests** only
4. Click **Add webhook**

---

## Step 7 — Push the pipeline code to GitHub

```bash
cd Spec-Forge
git remote add origin https://github.com/your-username/Spec-Forge.git
git branch -M main
git push -u origin main
```

---

## Step 8 — Start everything with Docker

Make sure Docker Desktop is running, then:

```bash
docker compose up --build
```

Wait for both containers to show as started:
```
✔ Container spec-forge-ngrok-1     Started
✔ Container spec-forge-pipeline-1  Started
```

---

## Step 9 — Open the UI

Open your browser and go to:

**http://localhost:8000**

You should see the Spec-Forge pipeline UI.

---

## Step 10 — Run the pipeline

1. Paste your feature specification YAML into the text area
2. Click **Run Pipeline**
3. Watch the timeline on the left light up as each stage completes
4. When **Checkpoint 1 — Plan Review PR** appears, click the PR link, review the plan, and click **Merge pull request** on GitHub
5. The pipeline continues automatically through code generation, testing, and review
6. When **Checkpoint 2 — Deploy Review PR** appears, review the generated code and merge
7. The pipeline completes — your generated code is now in `pipeline-target`

---

## Example spec to try

Paste this into the UI to run the bundled JWT authentication example:

```yaml
feature_objective: >
  Implement a secure, stateless user authentication system that issues
  short-lived JWT access tokens upon successful credential verification.

user_story: >
  As a registered user, I want to submit my email and password to a login
  endpoint so that I receive a signed JWT access token.

business_rules:
  - Passwords must be hashed with bcrypt using a minimum cost factor of 12.
  - JWT tokens must be signed with HS256 using a secret of at least 32 characters.
  - Access tokens must expire after 60 minutes from the time of issuance.
  - A login attempt with an unrecognised email must return the same error as a wrong password.

acceptance_criteria:
  - "POST /auth/login with valid credentials returns HTTP 200 with access_token and expires_in 3600."
  - "POST /auth/login with an invalid password returns HTTP 401 with detail Invalid credentials."
  - "POST /auth/login with a missing field returns HTTP 422."
  - "A protected endpoint with a valid token returns HTTP 200."
  - "A protected endpoint with an expired token returns HTTP 401."

non_functional_requirements:
  - P99 response time under 800ms at 50 concurrent users.
  - Zero high-severity Bandit findings.

out_of_scope:
  - OAuth 2.0 flows.
  - Refresh tokens.
  - User registration.
```

---

## Stopping the pipeline

```bash
docker compose down
```

---

## Troubleshooting

**Port 8080 already in use**
```bash
lsof -ti:8080 | xargs kill -9 2>/dev/null || true
docker compose restart
```

**ngrok "endpoint already online" error**
Your local ngrok is running. Stop it:
```bash
pkill ngrok
docker compose restart ngrok
```

**Pipeline hangs after merging checkpoint PR**
The webhook didn't reach the pipeline. Check:
1. The GitHub webhook shows a green tick in Settings → Webhooks → Recent Deliveries
2. ngrok is still running: `docker compose logs ngrok`
3. If the delivery shows a 502, it's a timing issue — run the pipeline again and wait 15 seconds before merging

**Groq rate limit (daily quota exhausted)**
The free tier allows 100k tokens/day. If you hit the limit:
- Wait until midnight UTC for the quota to reset
- Or create a new Groq account for a fresh 100k quota

**Docker can't pull images (no internet)**
Restart Docker Desktop — it sometimes loses DNS resolution.

---

## How it works (brief)

```
Your YAML spec
     ↓
Planner (LLM)        → generates implementation plan
     ↓
Checkpoint 1         → you review and merge a GitHub PR
     ↓
Implementer (LLM)    → writes Python source files
     ↓
Test Generator (LLM) → writes pytest tests
     ↓
Reviewer (LLM)       → scores the output 0-10
     ↓
Quality Gates        → ruff · mypy · pytest · bandit
     ↓
Checkpoint 2         → you review and merge the generated code
     ↓
Done — code is in your target repo
```

Every stage is logged to an append-only audit file at `runs/{run_id}/audit.jsonl`.