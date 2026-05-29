# Spec-Forge

A spec-driven AI pipeline that takes a structured feature specification and produces an implementation plan, working code, automated tests, and deployment evidence — with human approval gates at key stages via GitHub PRs.

Built as a technical assessment prototype. The pipeline is opinionated about what "done" means: code must pass ruff, mypy, pytest, and bandit before a human ever sees it.

## How it works

You write a YAML spec. The pipeline does the rest.

```
specs/example_feature.yaml
        │
        ▼
   Planner (LLM)          → generates implementation plan → plan.md
        │
        ▼
   Checkpoint 1           → opens GitHub PR for plan review
        │  (you merge)
        ▼
   Implementer (LLM)      → writes code into target repo
        │
        ▼
   Test Generator (LLM)   → writes pytest tests
        │
        ▼
   Reviewer (LLM)         → scores the output (0–10)
        │
        ▼
   Quality Gates           → ruff · mypy · pytest · bandit
        │
        ▼
   Checkpoint 2           → opens GitHub PR for deploy review
        │  (you merge)
        ▼
   Done — generated code merged into target repo
```

Every step is logged to an append-only `audit.jsonl`. State is persisted after every stage so you can inspect exactly what happened and when.


## Prerequisites

- Python 3.12
- A [Groq](https://console.groq.com) account (free tier, no card required) — or any OpenAI-compatible LLM provider
- A GitHub account with two repos: one for this pipeline, one as the code target
- An [ngrok](https://ngrok.com) account (free tier) for exposing the webhook

## Setup

```bash
git clone https://github.com/your-username/Spec-Forge.git
cd Spec-Forge

python3.12 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Fill in your credentials — see Environment configuration below
```

Add a `pytest.ini` at the project root if it doesn't exist:

```ini
[pytest]
testpaths = tests
pythonpath = .
```

Verify everything wires up:

```bash
pytest tests/ -v
```

---

## Environment configuration

Copy `.env.example` to `.env` and fill in every value.

| Variable | Required | Description |
|---|---|---|
| `LLM_API_KEY` | ✅ | API key for your LLM provider (Groq: `gsk_...`, OpenAI: `sk-...`) |
| `LLM_BASE_URL` | ✅ | Provider endpoint. Groq: `https://api.groq.com/openai/v1` |
| `LLM_MODEL` | ✅ | Model name. Groq: `llama-3.3-70b-versatile` |
| `GITHUB_TOKEN` | ✅ | Personal access token with `repo` scope |
| `GITHUB_TARGET_REPO` | ✅ | Repo where generated code is written. Format: `owner/repo` |
| `GITHUB_SOURCE_REPO` | ✅ | This pipeline's own repo. Format: `owner/repo` |
| `GITHUB_WEBHOOK_SECRET` | ✅ | Secret for validating GitHub webhook payloads |
| `NGROK_AUTH_TOKEN` | ✅ | Your ngrok auth token |
| `NGROK_DOMAIN` | ✅ | Your static ngrok domain (bare domain, no `https://`) |
| `ALLOWED_DIRS` | ❌ | Colon-separated dirs the implementer may write into. Default: `src:tests` |
| `PIPELINE_BASE_BRANCH` | ❌ | Default: `main` |
| `MAX_RETRIES` | ❌ | Per-agent retry cap. Default: `3` |
| `WEBHOOK_PORT` | ❌ | Local port for the webhook listener. Default: `8080` |
| `LOG_DIR` | ❌ | Where run state and audit logs are written. Default: `./runs` |
| `PROMPTS_DIR` | ❌ | Where prompt `.txt` files live. Default: `./prompts` |

**Generating a webhook secret:**

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output into both `GITHUB_WEBHOOK_SECRET` in `.env` and the Secret field when adding the webhook on GitHub.

---

## GitHub webhook setup

On your **target repo** (not this one):

1. Settings → Webhooks → Add webhook
2. Payload URL: `https://your-ngrok-domain/webhook`
3. Content type: `application/json`
4. Secret: your `GITHUB_WEBHOOK_SECRET` value
5. Events: **Pull requests** only
6. Save

Also disable auto-merge on the target repo: Settings → General → uncheck **Allow auto-merge**. Without this, GitHub merges PRs automatically and the pipeline skips past the human review stage.

---

## Running the pipeline

**Terminal 1 — start ngrok (keep this open):**

```bash
ngrok http --url=your-static-domain.ngrok-free.app 8080
```

**Terminal 2 — run the pipeline:**

```bash
source .venv/bin/activate
python -m pipeline.main run --spec specs/example_feature.yaml
```

**What you'll see:**

```
Run initialised: run_20260529T040029Z
State:           runs/run_20260529T040029Z/state.json
Audit log:       runs/run_20260529T040029Z/audit.jsonl
Checkpoint 1 — plan review PR: https://github.com/owner/target/pull/1
```

The pipeline blocks here. Go to the PR, review the plan, and click **Merge pull request**. It continues automatically:

```
Checkpoint 2 — deploy review PR: https://github.com/owner/target/pull/2
```

Review the generated code and merge again:

```
Pipeline completed successfully: run_20260529T040029Z
```

**Run artefacts** land in `runs/{run_id}/`:

```
runs/run_20260529T040029Z/
├── state.json      ← pipeline state after every stage
├── audit.jsonl     ← append-only event log
├── plan.md         ← human-readable implementation plan
└── repo/           ← clone of the target repo with all generated files
    ├── src/
    └── tests/
```

If port 8080 is still held from a previous crashed run:

```bash
lsof -ti:8080 | xargs kill -9 2>/dev/null
```

---

## Running with Docker

```bash
docker compose up --build
```

In a separate terminal:

```bash
docker compose exec pipeline python -m pipeline.main run --spec specs/example_feature.yaml
```

The ngrok dashboard is at `http://localhost:4040` — useful for inspecting webhook deliveries in real time.

---

## Writing your own spec

Specs live in `specs/` and are YAML files. Use `specs/example_feature.yaml` as a template. Required fields:

```yaml
feature_objective: >
  One paragraph describing what you're building and why.

user_story: >
  As a <role>, I want to <action> so that <outcome>.

business_rules:
  - Rule 1
  - Rule 2

acceptance_criteria:
  - "Concrete, testable criterion 1."
  - "Concrete, testable criterion 2."

non_functional_requirements:
  - Performance, security, or quality constraints.

out_of_scope:
  - Explicitly state what this iteration does NOT cover.
```

Wrap any criterion that contains `{`, `}`, or `:` in double quotes to avoid YAML parse errors.

---

## Architecture

### Orchestrator

The orchestrator is a deterministic state machine — it reads `PipelineState` and decides the next stage by inspecting which agents have succeeded. No LLM is involved in routing decisions. This eliminates the routing loops that occur when LLMs misread state, and cuts token usage to zero on the happy path.

The LLM is only called when an agent fails, to decide whether to retry or abort.

### Agents

Each agent (`planner`, `implementer`, `test_generator`, `reviewer`) inherits from `BaseAgent`, which handles:
- Loading the prompt from `prompts/{agent}.txt`
- Calling the LLM with `response_format={"type": "json_object"}`
- Rate limit backoff (up to 5 retries with exponential wait)
- Catching `BadRequestError` (malformed LLM JSON) and returning it as a retryable failure

### Quality gate runner

Before running ruff, mypy, pytest, and bandit, the gate runner prepares the generated repo:

1. Installs the repo's `requirements.txt` (if present)
2. Scans source imports and installs any missing packages (`bcrypt`, `PyJWT`, `fastapi`, etc.)
3. Patches empty `if/else/try/except` blocks with `pass` (common LLM omission)
4. Quarantines files that fail `py_compile` by renaming them to `.py.broken`
5. Creates `__init__.py` in every package directory
6. Creates a `conftest.py` that adds `src/` to `sys.path`

This means the generated code doesn't need to be perfect — the runner cleans up the most common LLM mistakes before tools run.

### Approval flow

Each checkpoint:
1. Commits artefacts to a unique branch (`pipeline/plan-{run_id}` or `pipeline/code-{run_id}`)
2. Pushes and opens a PR via PyGithub
3. Blocks on a `threading.Event` until the webhook fires with a confirmed merge
4. Falls back to a GitHub API pre-check to handle PRs merged before the listener registered

Webhook payloads are validated with `hmac.compare_digest` against `GITHUB_WEBHOOK_SECRET` (constant-time comparison, prevents timing attacks).

---

## Design decisions

**Deterministic orchestration over LLM routing.** The original design routed every decision through an LLM. In practice this caused routing loops (the model re-routing to an already-completed stage), token exhaustion, and crashes when the retry decision called the wrong next agent. The pipeline sequence is fixed — there is no reason to ask an LLM what comes after the planner. Routing is now pure Python; the LLM is reserved for tasks only an LLM can do.

**Provider-agnostic LLM client.** Three config values (`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`) make the pipeline work with any OpenAI-compatible provider. Tested with Groq (free tier, `llama-3.3-70b-versatile`) and OpenAI (`gpt-4o`). Switch providers by changing `.env` only.

**Sandbox path normalisation.** The implementer normalises every LLM-generated file path through `_normalize_path` before sandbox validation. This strips leading `../` segments that the LLM sometimes emits (e.g. `../src/auth.py` → `src/auth.py`), preventing the sandbox from rejecting valid paths due to LLM path formatting inconsistencies.

**Per-run unique branch names.** Every run creates branches named `pipeline/plan-{run_id}` and `pipeline/code-{run_id}`. This prevents GitHub from treating a new PR as already merged (which happens when a branch has been merged before and its commits are already in `main`).

**Append-only audit log.** `AuditLogger` opens the file in append mode inside a `threading.Lock` on every write. Correctness over throughput — the audit log is the source of truth for any post-mortem.

**Atomic state writes.** `StateStore.save()` writes to a `.tmp` file then calls `os.replace()`. On POSIX this is atomic — a crash mid-write cannot corrupt the live state file.

---

## Trade-offs

| Decision | Upside | Downside |
|---|---|---|
| Deterministic routing | Zero routing tokens, no loops | Less flexible; novel failure modes need code changes |
| JSON file for state | Zero infrastructure, inspectable | Single run at a time; no concurrency |
| JSONL for audit | Append-only, crash-safe, greppable | No indexing; large logs require streaming reads |
| Quality gate post-processing | Tolerates imperfect LLM output | Masks real code quality issues |
| Subprocess for quality gates | Tools run in real environment | Sequential; slower than in-process |
| Webhook + `threading.Event` | Simple, no message broker | Single-process; doesn't survive a restart mid-wait |

---

## Limitations

- **Single run at a time.** Concurrent runs against the same target repo will cause git branch conflicts.
- **No mid-wait resume.** If the process is killed while waiting for a webhook, the `threading.Event` is gone. Re-running will open a new PR.
- **Quality gates are lenient on generated code.** Several mypy error codes are disabled (`name-defined`, `arg-type`, etc.) because generated code frequently has type annotation gaps that would block the gate without adding useful signal. The reviewer LLM handles code quality assessment.
- **Free tier token limits apply.** Groq's free tier is 100k tokens/day. A full pipeline run uses approximately 40–60k tokens. If you hit the limit mid-run, the pipeline will wait and retry automatically, but the daily cap requires waiting until midnight UTC.
- **No secret scanning.** The reviewer prompt flags hardcoded secrets, but there is no programmatic check before generated code is committed.

---

## Future improvements

- **Resume from checkpoint.** Add a `resume` CLI command that loads an existing `state.json` and re-enters the loop from the last successful stage, reusing the already-cloned repo.
- **Parallel quality gates.** Run ruff, mypy, pytest, and bandit concurrently with `concurrent.futures.ThreadPoolExecutor`.
- **Secret scanning gate.** Add `detect-secrets` or `truffleHog` as a fifth gate before the code PR opens.
- **Cost tracking.** Sum `tokens_used` across all `AgentResult` records and log an estimated cost in the `pipeline_completed` audit event.
- **Streaming audit dashboard.** A FastAPI SSE endpoint that tails `audit.jsonl` in real time — useful for watching a run without tailing log files.
- **SQLite state store.** Replace the JSON file with SQLite to support concurrent runs and cross-run querying.
- **Spec validation schema.** Define a JSON Schema for the YAML spec format and validate on intake, catching malformed specs before any LLM tokens are spent.
- **Implementer feedback loop.** When the reviewer scores below threshold, feed the issues list back into a second implementer call rather than aborting, closing the generate–review–fix cycle automatically.