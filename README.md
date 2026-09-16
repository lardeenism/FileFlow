# FileFlow – Concurrent File Processing & Organizer System

FileFlow is a presentation-ready Computer Science midterm project that demonstrates genuine operating-system concurrency concepts through a modern web file organizer. Users upload files into a FIFO task queue; real Python worker threads hash, categorize, and move those files while the browser displays live worker state, OS thread identifiers, queue activity, synchronization events, and persistent processing history.

This is not a simulated thread dashboard. The runtime uses `threading.Thread`, `queue.Queue`, `threading.Lock`, shared mutable state, synchronization, `Queue.join()`, and `Thread.join()`.

## Objectives

- Demonstrate concurrent I/O-bound work using a configurable Python thread pool.
- Show how a thread-safe queue distributes independent tasks.
- protect shared state and atomic file operations with locks.
- Demonstrate SHA-256 duplicate detection under concurrent load.
- Explain race conditions, synchronization, Python's GIL, and `join()` visually.
- Apply a modular presentation → route → service → manager → storage architecture.

## Features

- Dedicated responsive landing page with project overview, workflow, architecture, and demo launch
- Dark developer dashboard with live totals, worker progress, activity, and logs
- Multiple file upload by picker or drag-and-drop
- FIFO processing queue and configurable 1–12 worker threads (5 by default)
- Native operating-system thread IDs from `threading.get_native_id()`
- Live current file, status, progress, start time, and completion time per worker
- File categorization into Images, Documents, Spreadsheets, Presentations, Videos, Audio, Archives, and Others
- SHA-256 duplicate detection and a separate Duplicates folder
- Collision-free output naming: existing files are never silently overwritten
- Supabase PostgreSQL files, tasks, settings, and processing log records
- Processing history, downloadable results, CSV history export, and filtered terminal logs
- Supabase-backed reports for completed bytes, categories, duplicates, worker task distribution, and durations
- Printable/PDF report view and portable CSV report export
- Dedicated concurrency guide with an interactive thread, context-switch, deadlock, and data-race quiz
- One-click five-thread concurrent demonstration with 1–3 second randomized work delays
- Educational Safe vs Unsafe synchronization experiment using real threads
- Path confinement, filename normalization, executable blocking, and upload size limits

## Architecture

```text
Presentation Layer (HTML / CSS / JavaScript)
                    ↓
              Flask Routes
                    ↓
     File and Persistence Services
                    ↓
      Concurrent Processing Manager
                    ↓
      Worker Threads + Task Queue
                    ↓
   Supabase PostgreSQL + File System
```

The code is deliberately separated by responsibility:

```text
FileFlow/
├── app.py                         # Development entry point
├── requirements.txt
├── database/fileflow_supabase.sql # Optional Supabase SQL Editor schema
├── README.md
├── fileflow/
│   ├── __init__.py                # Flask application factory
│   ├── db.py                      # Supabase PostgreSQL adapter
│   ├── file_service.py            # Validation, hashing, categories, safe moves
│   ├── processing.py              # Queue, workers, locks, shared runtime state
│   ├── routes.py                  # Page and JSON API routes
│   ├── static/
│   │   ├── css/app.css
│   │   └── js/app.js
│   └── templates/
│       ├── base.html
│       ├── page.html
│       └── 404.html
└── tests/test_fileflow.py
```

Relational metadata is stored in Supabase PostgreSQL. Runtime file contents remain under `instance/`:

```text
instance/
└── storage/
    ├── incoming/
    └── organized/
        ├── Images/
        ├── Documents/
        ├── Spreadsheets/
        ├── Presentations/
        ├── Videos/
        ├── Audio/
        ├── Archives/
        ├── Others/
        └── Duplicates/
```

## How the threading works

`ProcessingManager.start_batch()` creates a fresh `queue.Queue`, enqueues database task IDs, and starts the configured number of genuine `threading.Thread` workers. Each worker blocks on `Queue.get()`, processes one file independently, calls `task_done()`, and asks for another task. Sentinel values tell workers when the current batch is complete.

The worker ID (`1`, `2`, and so on) is FileFlow's readable pool label. The thread ID is the native operating-system identifier returned inside that thread by `threading.get_native_id()`. Both values are written to Supabase PostgreSQL and shown in the Thread Monitor.

### Queue explanation

`queue.Queue` is a synchronized FIFO structure. Its internal synchronization makes it safe for several workers to request work concurrently; a task is handed to only one worker. Workers do not need to scan a shared list or compete over array indexes.

```python
task_queue.put(task_id)
task_id = task_queue.get()
process(task_id)
task_queue.task_done()
task_queue.join()
```

### Lock and synchronization explanation

FileFlow uses two synchronization locks:

1. `state_lock` is a `threading.RLock` protecting shared mutable runtime dictionaries and counters used by the live UI.
2. `organization_lock` is a `threading.Lock` around duplicate detection and the small metadata-reservation update.

That second critical section matters. Without it, two workers hashing identical new files could both query before either has recorded its result, and both could incorrectly decide they are originals. The lock makes the check-and-reserve sequence atomic relative to other workers. Slow hashing and file movement remain outside the lock so other workers can continue. Lock waiting and release are recorded in the Logs page.

### Race condition explanation

A race condition occurs when a result depends on unpredictable thread interleaving. A shared counter increment is conceptually a read, a calculation, and a write. Two threads can read the same old value and later overwrite one another's result, producing lost updates.

The Settings page includes a deterministic educational experiment. Five unsafe threads deliberately align their stale reads with barriers, exposing lost increments. Five safe threads wrap increments in `with lock:`, preserving the expected total. These are real Python threads, not calculated UI examples.

### The GIL

CPython's Global Interpreter Lock (GIL) normally allows only one thread at a time to execute Python bytecode in a process. It does **not** make compound application operations automatically safe, so locks are still necessary for shared state and multi-step file/database decisions.

The GIL also does not make threads useless. Python releases it during many blocking I/O operations. While one FileFlow worker waits for disk reads, writes, moves, or PostgreSQL access, another can make progress. Threads are therefore a good teaching and implementation fit for this project's I/O-heavy workload. For CPU-heavy transformations, a process pool would usually be more appropriate.

### I/O-bound processing

Hashing reads files from storage in 1 MB chunks, organization writes/moves files, and each task updates Supabase PostgreSQL several times. Those operations spend meaningful time waiting on I/O rather than only executing Python calculations. The demo's randomized 1–3 second delay makes overlapping workers easy to observe during a classroom presentation; normal uploaded files do not receive this artificial delay.

### `join()` explanation

The batch coordinator calls `task_queue.join()` and waits until every queued item has received `task_done()`. It then calls `join()` on each worker thread. Only after both steps complete does FileFlow set the batch message to:

```text
ALL FILES PROCESSED!
```

The HTTP request does not stay blocked during this wait. A background coordinator performs the joins so the browser can continue polling and displaying live progress.

## Database

The main application uses the PostgreSQL database provided by Supabase. On startup, FileFlow connects with Psycopg over SSL and initializes four tables:

- `files`: name, type, size, category, SHA-256, duplicate relationship, assigned worker/thread, status, progress, paths, timestamps, and error
- `tasks`: file relationship, worker/thread, status, progress, queue/start/completion timestamps, and error
- `processing_logs`: level, event type, message, worker/thread/file context, and timestamp
- `settings`: persistent key/value runtime configuration

Every Flask request and worker application context opens its own PostgreSQL connection; connections are never shared unsafely across worker threads. Indexed hashes, statuses, categories, and relationships support reporting and duplicate checks. Foreign keys cascade task deletion and safely clear duplicate references.

FileFlow uses Supabase PostgreSQL exclusively and reads its connection string from `SUPABASE_DB_URL`.

The Supabase schema enables Row Level Security without adding anonymous Data API policies. FileFlow connects from its trusted Flask backend using the database connection string; never expose that string in browser JavaScript.
## Security decisions

- Werkzeug's `secure_filename()` removes path components and unsafe filename characters.
- Every computed file path is resolved and verified to remain under the configured storage root.
- Randomized staging names and collision-numbered output names prevent automatic overwrite.
- Common executable/script extensions are rejected.
- Flask limits upload requests to 1 GB by default. Set `FILEFLOW_MAX_UPLOAD_MB` before startup to choose another limit (up to 10 GB).
- Download and delete operations re-check storage-root confinement.
- User-facing errors are bounded; full Python tracebacks stay in server diagnostics.

This is a local educational application. For public deployment, add authentication, CSRF protection, malware scanning, a production WSGI server, and a reverse-proxy upload policy.

## Installation with Supabase

Python 3.10 or newer is recommended.

1. Create or open a Supabase project.
2. In the Supabase dashboard, click **Connect**.
3. On IPv4 networks, copy the **Session pooler** connection string. Direct connections are appropriate when the host supports IPv6.
4. Replace the password placeholder with the database password and keep `sslmode=require` enabled.
5. Install the Python dependencies and start FileFlow.

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Open .env and replace the Supabase connection placeholders.
python app.py
```

Use the exact connection string supplied by the dashboard; do not construct the pooler hostname manually. Password characters such as `@`, `#`, `?`, and spaces must be URL-encoded.

The application creates the tables automatically. Alternatively, paste `database/fileflow_supabase.sql` into the Supabase SQL Editor. Open <http://127.0.0.1:5000> after starting FileFlow.

## Deploying to Render

This repository includes a `render.yaml` Blueprint for a Render web service.

1. Push the repository to GitHub.
2. In Render, choose **New > Blueprint** and select the repository.
3. Enter `SUPABASE_DB_URL` when prompted. Use the PostgreSQL Session pooler URI from Supabase's **Connect** panel, not the REST API URL.
4. Apply the Blueprint and wait for the health check to pass.

The Blueprint runs `gunicorn` with one process and multiple request threads. Keeping one process is important because FileFlow's live processing monitor is held in process memory.

The free Render plan has an ephemeral filesystem, so uploaded and organized files are lost when the service restarts, spins down, or redeploys. PostgreSQL metadata remains in Supabase, but its stored local file paths then become stale. For durable uploads, change the service to a paid plan, attach a persistent disk at `/var/data/fileflow`, and set `FILEFLOW_STORAGE_ROOT=/var/data/fileflow`. A service with a persistent disk must remain a single instance.

## Supabase troubleshooting

- Confirm `SUPABASE_DB_URL` is set in the same terminal used to run `python app.py`.
- If a direct connection fails on an IPv4-only network, use the Session pooler string from the Connect panel.
- Ensure the password is URL-encoded and the connection uses SSL.
- Restart `python app.py` after changing database code or environment variables; an already-running Python process keeps its old configuration in memory.
- If port 5000 is already occupied, close the previous FileFlow terminal/process before starting another instance.
- A hard browser refresh (`Ctrl+F5`) loads the latest JavaScript and CSS after an update.
- FileFlow API database errors return a clear JSON `503` response instead of an HTML debugger page.
## Real queue workflow

1. Upload files from Files or the Thread Monitor.
2. Open Processing Queue or Thread Monitor.
3. Click **Run** beside one pending file to process only that task, or click **Run pending queue** to process every pending task.
4. A run started outside the Thread Monitor automatically opens it.
5. Watch actual worker IDs, OS thread IDs, live progress, duration, batch totals, and completion order update automatically.
6. Open History and Logs to inspect the persistent result and synchronization events.

## Demo instructions

1. Open the Dashboard.
2. Click **Start Concurrent Demo**.
3. Watch five worker cards change from starting to running.
4. Point out that each card displays a real thread ID.
5. Watch different files progress at the same time and the queue count decrease.
6. Open Logs to identify queue, thread, Lock, and join events.
7. Wait for **ALL FILES PROCESSED!**
8. Open Files to show categorization and the duplicate copy.
9. Open Settings and run **Safe vs Unsafe synchronization**.

The demo creates nine small sample files across multiple categories. Two text samples have identical bytes so SHA-256 duplicate detection is visible on every run.

## Running the tests

The test suite uses Python's standard `unittest` module. Database integration tests require a separate, disposable Supabase/PostgreSQL database in `FILEFLOW_TEST_DB_URL`; they are skipped when it is not configured and refuse to use the application's normal `SUPABASE_DB_URL`:

```powershell
python -m unittest discover -s tests -v
```

It verifies page rendering, secure path normalization, blocked executable uploads, real concurrent processing, actual thread IDs, join logging, SHA-256 duplicate handling, and safe-versus-unsafe shared counters.

## Suggested presentation flow

Start with the architecture diagram on Settings, then upload several files and open Processing Queue. Start the batch and move to Thread Monitor. Explain the distinction between FileFlow worker labels and real thread IDs. Use the Logs page to show synchronization events and `join()` completion. Finish with the race-condition experiment and explain why the GIL does not replace application-level locking.
