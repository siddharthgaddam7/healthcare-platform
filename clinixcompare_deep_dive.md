# ClinixCompare — Complete System Deep Dive

> **Senior developer level explanation. Every component. Zero skipped.**

---

## 🔥 1. PROJECT ARCHITECTURE — BIG PICTURE

### What is this project?

ClinixCompare (Hyderabad Health) is a **healthcare test price transparency platform**. Users can search for medical tests (CBC, Thyroid, etc.), compare prices across Hyderabad labs, book tests, and manage their bookings. Think of it as a "price comparison engine for diagnostic labs."

### Architecture Overview (Text Diagram)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER'S BROWSER / PHONE                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  HTTPS (port 443)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│               VERCEL (Frontend CDN — Global)                        │
│   Serves:  login.html, index.html, admin.html, doctor.html          │
│            style.css, script.js                                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │  HTTP API calls → http://15.206.125.164
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│               AWS EC2 (t3.micro, Ubuntu 22.04)                      │
│               Public IP: 15.206.125.164                             │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  NGINX  (port 80 — reverse proxy)                           │   │
│  │  Listens on port 80, forwards to Gunicorn on port 10000     │   │
│  └──────────────────────────────┬──────────────────────────────┘   │
│                                 │  internal forward                  │
│  ┌──────────────────────────────▼──────────────────────────────┐   │
│  │  GUNICORN  (port 10000 — WSGI server, 4 workers)            │   │
│  │  Runs app.py as production WSGI application                 │   │
│  └──────────────────────────────┬──────────────────────────────┘   │
│                                 │                                    │
│  ┌──────────────────────────────▼──────────────────────────────┐   │
│  │  FLASK APP  (app.py — 1008 lines, 30+ API endpoints)        │   │
│  └──────────────────────────────┬──────────────────────────────┘   │
└─────────────────────────────────┼───────────────────────────────────┘
                                  │
          ┌───────────────────────┼────────────────────┐
          ▼                       ▼                     ▼
┌─────────────────┐   ┌───────────────────────┐  ┌───────────────────┐
│  MongoDB Atlas  │   │  SendGrid Email API   │  │  GitHub Repo      │
│  (Cloud DB)     │   │  (booking emails)     │  │  (source of truth)│
└─────────────────┘   └───────────────────────┘  └───────────────────┘
```

### Full Request-Response Lifecycle Example — Login

```
1. User types username + password in login.html
2. doLogin() function runs (JavaScript)
3. fetch("http://15.206.125.164/login", { method: "POST", body: JSON })
4. Request travels: Browser → Vercel CDN → EC2 port 80
5. Nginx receives at port 80, forwards to Gunicorn on port 10000
6. Gunicorn picks a worker (one of 4 processes) and calls Flask
7. Flask /login route runs:
   a. Reads JSON body → gets username, password
   b. Checks hardcoded admin (admin/admin123)
   c. OR queries MongoDB: users.find_one({username: ...})
   d. bcrypt.checkpw() to verify password hash
   e. Sets session cookie: session["user_id"] = user._id
8. Flask returns: {"success": true, "role": "user"}
9. Gunicorn sends response back to Nginx
10. Nginx sends HTTP response back to browser
11. JavaScript reads response → redirects to index.html
```

---

## 🔥 2. FRONTEND ANALYSIS

### File-by-File Breakdown

#### `frontend/login.html` — The Entry Point
- **What it does:** The login/register/forgot-password page (all-in-one, tab-based UI)
- **Has inline CSS** (its own 200+ lines of styles — no external CSS link)
- **Has inline JavaScript** (`<script>` block at bottom — no script.js loaded)
- **Key functions:**
  - `showTab('login' | 'register' | 'forgot')` — switches panels by adding/removing `.active` class
  - `doLogin()` — calls `POST /login`
  - `doRegister()` — calls `POST /register`
  - `forgotStep1()` → `forgotStep2()` → `forgotStep3()` — 3-step password reset flow
- **BASE_URL defined here:** `const BASE = "http://15.206.125.164";` (line 305)
- **Session:** After login, Flask sets a server-side session cookie. Frontend just redirects on success.

#### `frontend/index.html` — Main Search Page
- **What it does:** The main user-facing portal — search tests, view prices, cart, bookings
- **No inline script** — loads `script.js` externally at line 140
- **Key HTML elements:**
  - `#testQuery` — text input for typing test names
  - `#testDropdown` — populated dropdown of all tests
  - `#suggestBox` — autosuggest dropdown (appears below input)
  - `#results` — where search results are injected as HTML
  - `#cartSidebar` — slides in from right (cart)
  - `#bookingsSidebar` — slides in from right (bookings list)
  - `#bookingModal` — center popup for booking a test

#### `frontend/script.js` — The Brain of index.html
- **466 lines of pure JavaScript**
- **BASE_URL defined here:** `const BASE = "http://15.206.125.164";` (line 2)

| Function | What it does | API Called |
|---|---|---|
| `window.onload` | Auth check, loads tests/cart/bookings | `GET /me` |
| `loadTests()` | Fills dropdown with all test names | `GET /tests` |
| `setupAutosuggest()` | Debounced typing → suggestions | `GET /suggest?q=...` |
| `search(q)` | Sends search, renders full results | `POST /search` |
| `renderResult(r)` | Builds HTML for one test result | (none) |
| `renderTable(testName, labs)` | Builds the lab price table | (none) |
| `handleAdd(btn)` | Adds test+lab to cart | `POST /cart/add` |
| `loadCart()` | Fetches cart and renders it | `GET /cart` |
| `removeCartItem(id)` | Removes from cart | `POST /cart/remove` |
| `clearCart()` | Empties cart | `POST /cart/clear` |
| `openBookingModal(btn)` | Shows booking popup | (none) |
| `submitBooking()` | Confirms booking | `POST /book` |
| `loadBookings()` | Shows user's booking history | `GET /bookings` |
| `cancelBooking(id)` | Cancels a booking | `POST /bookings/cancel` |
| `doLogout()` | Clears session | `POST /logout` |

**How fetch requests are structured (example):**
```javascript
const r = await fetch(BASE + "/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",    // ← CRITICAL: sends cookies with request
    body: JSON.stringify({ query: q })
});
const d = await r.json();
```
> `credentials: "include"` is mandatory — without it, the session cookie never reaches the Flask server and every protected route returns 401.

#### `frontend/admin.html` — Admin Dashboard
- **Purpose:** Admin sees all users, cart counts, total values
- **BASE_URL:** `const B = "http://15.206.125.164";` (line 173)
- **Auth guard:** On page load calls `/me` → if role ≠ "admin", redirects to login
- **Calls:** `GET /admin/users` → renders user table with stats

#### `frontend/doctor.html` — Doctor Dashboard
- **Purpose:** Doctor updates their profile, views all patient bookings, sees reviews
- **BASE_URL:** `const B = "http://15.206.125.164";` (line 277)
- **Auth guard:** Checks `/me` → if role ≠ "doctor", redirects to login
- **Calls:**
  - `GET /doctor/profile` → loads name, specialization, hospital, rating
  - `POST /doctor/profile` → saves updated profile
  - `GET /doctor/appointments` → shows all bookings made by any user

#### `frontend/style.css` — Design System (981 lines)
- Uses **CSS Custom Properties** (`:root` variables) for theming
- Color palette: White `#ffffff`, accent blue `#3a6ea5`, success green `#2d8a4e`
- Key design tokens:
  ```css
  --bg-base: #ffffff        /* white cards */
  --bg-secondary: #f5f6f7   /* light grey page background */
  --accent: #3a6ea5         /* brand blue */
  --border: #e5e5e5         /* thin borders */
  ```
- Implements: sticky navbar, cart/bookings slide-in sidebars, booking modal, price bar charts, autosuggest dropdown, responsive breakpoints at 600px

### How State/Session is Handled on Frontend

The frontend is **stateless** — it keeps no data in `localStorage` or `sessionStorage`. It relies entirely on **HTTP session cookies** set by Flask. Every page load calls `/me` to check who's logged in. The cookie is `HttpOnly` and managed by the browser automatically.

### Vercel Deployment

Vercel treats the `frontend/` folder as a **static site**. It serves HTML, CSS, JS files directly from its global CDN edge network. No server needed. Every file is just a static asset. When you push to GitHub, Vercel auto-detects the change and re-deploys within ~30 seconds.

---

## 🔥 3. BACKEND ANALYSIS (Flask)

### All API Endpoints — Complete List

| Endpoint | Method | Auth? | What it does |
|---|---|---|---|
| `/health` | GET | No | Returns `{"status": "ok"}` — server health check |
| `/mongo-test` | GET | No | Tests MongoDB connection, returns collection stats |
| `/test-email` | GET | No | Debug: sends a test email via SendGrid |
| `/login` | POST | No | Authenticates user, sets session cookie |
| `/register` | POST | No | Creates new user, auto-logs them in |
| `/logout` | POST | No | Clears session |
| `/me` | GET | No | Returns current user's role + username |
| `/forgot-password` | POST | No | Step 1 of reset: returns security question |
| `/verify-reset` | POST | No | Step 2: verifies answer, issues reset token |
| `/reset-password` | POST | No | Step 3: sets new password using token |
| `/mfa/setup` | POST | Yes | Enables Multi-Factor Auth for logged-in user |
| `/mfa/verify` | POST | Yes | Verifies MFA during login |
| `/tests` | GET | No | Returns all canonical test names (for dropdown) |
| `/search` | POST | No | Fuzzy searches tests, returns labs + prices |
| `/suggest` | GET | No | Autosuggest: top 5 matches for typed query |
| `/cart` | GET | Yes | Returns user's cart items + total |
| `/cart/add` | POST | Yes | Adds a test+lab to cart |
| `/cart/remove` | POST | Yes | Removes one item from cart |
| `/cart/clear` | POST | Yes | Empties entire cart |
| `/book` | POST | Yes | Books a test, optionally sends email |
| `/bookings` | GET | Yes | Returns user's booking history |
| `/bookings/cancel` | POST | Yes | Cancels a booking by ID |
| `/doctor/profile` | GET | Yes (doctor) | Fetches doctor's profile |
| `/doctor/profile` | POST | Yes (doctor) | Updates doctor's profile |
| `/doctor/appointments` | GET | Yes (doctor) | Returns all bookings (doctor sees all) |
| `/doctor/reviews` | GET | Yes (doctor) | Returns reviews stored on doctor document |
| `/admin/users` | GET | Yes (admin) | Returns all non-admin users + cart stats |
| `/` | GET | No | Serves `login.html` (Flask static file serve) |

### Request → Processing → Response Flow (internal detail)

**Example: `/search`**
```python
@app.route("/search", methods=["POST"])
def search():
    data  = request.get_json()        # parse JSON body
    query = data.get("query", "")     # extract user query
    
    if mongo_db is not None:
        return _search_mongo(query)   # use MongoDB
    elif df is not None:
        return _search_pandas(query)  # fallback to Excel
    return jsonify({"results": []})
```

Inside `_search_mongo(query)`:
1. Normalize query (lowercase, strip punctuation)
2. Load ALL test documents from MongoDB `tests` collection
3. For each test, compare query against every alias using RapidFuzz:
   - `fuzz.token_sort_ratio` — handles word order differences
   - `fuzz.token_set_ratio` — handles extra words
   - `fuzz.partial_ratio` — handles substrings
   - Average the 3 scores → if ≥ 70, it's a match
4. Sort matches by score (best first)
5. For each matching test, run MongoDB Aggregation Pipeline on `labs` collection:
   - Filter by `canonical_name`
   - Group by `lab_name`, keep minimum price per lab
   - Sort by price ascending
6. Build response JSON with `matched_test`, `info`, `statistics`, `results` (labs array)

### Authentication Logic

- Flask `session` is a **server-side session** stored in a signed cookie
- Secret key: `app.secret_key = "hyd_health_secret_2026"` (used to sign cookie)
- On login success: `session["user_id"] = str(user["_id"])`
- The `login_required` decorator checks `session.get("user_id")`:
  ```python
  def login_required(f):
      @wraps(f)
      def wrapper(*args, **kwargs):
          if not session.get("user_id"):
              return jsonify({"error": "login required"}), 401
          return f(*args, **kwargs)
      return wrapper
  ```
- Admin is **hardcoded**: `username == "admin" and password == "admin123"`
- Regular users: bcrypt password hash stored in MongoDB

### CORS Configuration

```python
CORS(app, supports_credentials=True, resources={r"/*": {"origins": [
    "https://healthcare-platform-gamma.vercel.app",
    "https://healthcare-platform.vercel.app",
    "http://15.206.125.164",
    "http://localhost:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]}})
```

- `supports_credentials=True` → allows cookies to be sent cross-origin (needed for sessions)
- Only listed origins are allowed — any other origin gets CORS error
- `r"/*"` → applies to ALL routes

### SendGrid Email System

```python
def send_booking_email(to_email, test_name, lab_name, ...):
    recipient = GMAIL_USER if EMAIL_TEST_MODE else to_email
    message = Mail(
        from_email=GMAIL_USER,
        to_emails=recipient,
        subject=f"New Booking Request — {test_name} at {lab_name}",
        html_content=html_body
    )
    sg = SendGridAPIClient(SENDGRID_API_KEY)
    response = sg.send(message)
```

- **TEST_MODE=true**: emails always go to `GMAIL_USER` (your email), not the lab — so you can test without spamming labs
- **TEST_MODE=false**: emails go to the actual lab's email
- Sent in a **background daemon thread** so booking response is instant:
  ```python
  threading.Thread(target=send_booking_email, kwargs={...}, daemon=True).start()
  ```

### Error Handling Strategy

- Every route wrapped in try/except at the usage point
- Returns JSON error objects: `return jsonify({"error": "message"}), HTTP_CODE`
- MongoDB connection failure at startup → `mongo_db = None` → fallback to Excel (pandas)
- Missing env vars → warnings printed but app still starts

---

## 🔥 4. DATABASE & DATA FLOW

### MongoDB Atlas Setup

MongoDB Atlas is a **cloud-hosted MongoDB** service. You don't run a database on your server. The database lives on MongoDB's servers (free tier: M0 cluster), and Flask connects to it via a connection string (URI).

**Database name:** `healthcare_platform`

**Collections:**

| Collection | Purpose | Key Fields |
|---|---|---|
| `users` | Registered users | `username`, `password (bcrypt)`, `role`, `email`, `phone`, `security_question`, `security_answer`, `mfa_enabled`, `created_at` |
| `tests` | Canonical test info + aliases | `canonical_name`, `aliases[]`, `info{}` |
| `labs` | One doc per (lab × test × price) | `lab_name`, `canonical_name`, `price`, `phone`, `email`, `website`, `address`, `location` |
| `bookings` | All user bookings | `user_id`, `username`, `test_name`, `lab_name`, `price`, `mode`, `status`, `created_at` |
| `carts` | Cart items per user | `user_id`, `test_name`, `company`, `price`, `added_at` |
| `doctors` | Doctor profile data | `user_id`, `name`, `specialization`, `hospital`, `rating`, `reviews[]` |

### How Data is Queried

**Simple find:**
```python
user = mongo_db.users.find_one({"username": username})
```

**Aggregation pipeline (search):**
```python
pipeline = [
    {"$match": {"canonical_name": canonical}},
    {"$group": {
        "_id": "$lab_name",
        "price": {"$min": "$price"},  # cheapest price per lab
        "location": {"$first": "$location"},
    }},
    {"$sort": {"price": 1}},  # sort cheapest first
]
lab_results = list(mongo_db.labs.aggregate(pipeline))
```

### Excel Dataset — The Origin Story

The original data was in an Excel file called `enriched_with_canonical_updated.xlsx`. This file has columns: `test name`, `company name`, `price`, `location`, `canonical_name`, `phone`, `email`, `website`, `address`.

**Why `canonical_name`?** Multiple test names mean the same thing. "CBC", "Complete Blood Count", "CBP", "Hemogram" all map to canonical name "CBC". The canonical name is the standardized display name.

### Migration: Excel → MongoDB

`migrate_to_mongo.py` (one-time script):
1. Reads the Excel file with pandas
2. Builds `tests` collection — one doc per canonical test, with all aliases merged from the Excel variants + ALIASES dictionary
3. Builds `labs` collection — one doc per row in Excel (lab × test × price)
4. Creates indexes for fast querying
5. Loads `test_metadata.json` and embeds it in each test document as `info{}`

### How Fuzzy Search Works (RapidFuzz)

RapidFuzz is a fast string matching library. Instead of exact matching, it scores how similar two strings are (0-100%).

**Three algorithms used together:**
- `token_sort_ratio("blood cbc", "cbc blood")` → handles different word order
- `token_set_ratio("full blood count test", "blood count")` → handles extra words
- `partial_ratio("cbc", "complete blood count")` → finds match as substring

Average of 3 scores. If ≥ 70 (MongoDB) or ≥ 80 (Excel fallback) → it's a match.

This means if you type "thyrid" (typo), it still matches "Thyroid Panel" because the strings are very similar.

---

## 🔥 5. AWS DEPLOYMENT

### Why EC2?

**Render (old)** was the original backend host. It was switched to **AWS EC2** for:
- No auto-sleep (Render free tier sleeps after 15 minutes of inactivity, causing 30s cold start)
- More control over networking, ports, processes
- EC2 t3.micro is part of AWS Free Tier (750 hours/month free for first year)
- Custom domain + Nginx reverse proxy configuration

### EC2 Instance Details

| Setting | Value |
|---|---|
| Instance type | t3.micro |
| OS | Ubuntu 22.04 LTS |
| Public IP | 15.206.125.164 |
| Region | ap-south-1 (Mumbai) |
| Storage | 8GB gp2 |

### Security Groups (Firewall Rules)

| Port | Protocol | Source | Purpose |
|---|---|---|---|
| 22 | TCP | Your IP | SSH access to manage server |
| 80 | TCP | 0.0.0.0/0 | Nginx (HTTP) — public web traffic |
| 10000 | TCP | 0.0.0.0/0 | Gunicorn direct (used during setup, later removed from public URL) |

### What Happens Inside EC2 After Login

```bash
# SSH into the server
ssh -i "your-key.pem" ubuntu@15.206.125.164

# The project lives here
cd /home/ubuntu/mini_final

# Virtual environment is activated
source .venv/bin/activate

# Gunicorn is running as a background process or systemd service
# Nginx is running as a system service

# To pull latest code from GitHub
git pull origin main

# To restart Gunicorn after code changes
pkill gunicorn
gunicorn -w 4 -b 0.0.0.0:10000 backend.app:app &
# OR if using systemd:
sudo systemctl restart gunicorn
```

### Project Setup on EC2 (One-Time)

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Python, pip, git, nginx
sudo apt install python3 python3-pip python3-venv git nginx -y

# 3. Clone GitHub repo
git clone https://github.com/siddharthgaddam7/healthcare-platform.git mini_final

# 4. Create virtual environment
cd mini_final
python3 -m venv .venv
source .venv/bin/activate

# 5. Install dependencies
pip install -r backend/requirements.txt

# 6. Set environment variables
export MONGO_URI="mongodb+srv://user:pass@cluster.mongodb.net/"
export SENDGRID_API_KEY="SG.xxxxx"
export GMAIL_USER="your@email.com"
export EMAIL_TEST_MODE="true"

# 7. Start Gunicorn
gunicorn -w 4 -b 0.0.0.0:10000 backend.app:app
```

---

## 🔥 6. NGINX + GUNICORN EXPLAINED

### Why Not Flask's Built-in Server?

Flask's `app.run()` is a **development server**. It:
- Handles only 1 request at a time
- Crashes under load
- Is not optimized for production
- Has no process management

### What Gunicorn Does

Gunicorn (**G**reen **U**nicorn) is a production WSGI server. It:
- Spawns **multiple worker processes** (`-w 4` = 4 workers)
- Each worker handles one request at a time
- So 4 workers = 4 concurrent requests handled simultaneously
- If Flask crashes in one worker, Gunicorn restarts it
- Runs your Flask app code (`backend.app:app` = the `app` variable in `backend/app.py`)

```bash
gunicorn -w 4 -b 0.0.0.0:10000 backend.app:app
#          ↑           ↑              ↑
#     4 workers   bind all IPs    module:variable
#                 on port 10000
```

### What Nginx Does

Nginx is a **reverse proxy** — sits in front of Gunicorn. It:
- Listens on port 80 (standard HTTP, no port in URL)
- Forwards requests to Gunicorn on port 10000 (internal, not exposed publicly)
- Can serve static files directly (faster)
- Handles SSL termination if HTTPS is configured
- Buffers slow clients so Gunicorn workers aren't blocked

### Nginx Config (how it looks on server)

Located at `/etc/nginx/sites-available/healthcare`:
```nginx
server {
    listen 80;
    server_name 15.206.125.164;

    location / {
        proxy_pass http://127.0.0.1:10000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### Request Flow Step-by-Step

```
User types: http://15.206.125.164/search

1. Request arrives at EC2 on port 80
2. Nginx receives it (listening on port 80)
3. Nginx matches "/" location block
4. Nginx forwards to http://127.0.0.1:10000 (loopback — internal only)
5. Gunicorn receives it on port 10000
6. Gunicorn assigns to a free worker process
7. Worker calls Flask's app.py /search route
8. Flask processes → returns JSON
9. Gunicorn sends response back to Nginx
10. Nginx sends response back to user's browser
```

### Why Port 10000 Was Removed from Public URL

Originally the frontend was calling `http://15.206.125.164:10000` (Gunicorn directly). This was changed to `http://15.206.125.164` (port 80, via Nginx) because:
- Cleaner URL (no port number visible)
- Nginx provides a proper production layer
- Port 80 can eventually be blocked from Gunicorn, adding security
- Allows future HTTPS upgrade on Nginx level without changing Flask

---

## 🔥 7. ENVIRONMENT VARIABLES

| Variable | Used In | Purpose | If Missing |
|---|---|---|---|
| `MONGO_URI` | `app.py` line 102 | MongoDB Atlas connection string | `mongo_db = None`, falls back to Excel (if on EC2 without Excel file, app breaks) |
| `SENDGRID_API_KEY` | `app.py` line 51 | Authenticate with SendGrid to send emails | Email feature silently disabled, booking still works |
| `GMAIL_USER` | `app.py` line 50 | The "from" email address and TEST_MODE recipient | SendGrid emails fail (no sender) |
| `EMAIL_TEST_MODE` | `app.py` line 52 | If "true", all emails go to GMAIL_USER, not the lab | Defaults to "true" (safe default) |
| `PORT` | `app.py` line 1007 | Which port Gunicorn listens on | Defaults to 10000 |

**Example `.env` on EC2:**
```bash
export MONGO_URI="mongodb+srv://username:password@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
export SENDGRID_API_KEY="SG.xxxxxxxxxxxxxxxxxxxxxxxxx"
export GMAIL_USER="youremail@gmail.com"
export EMAIL_TEST_MODE="true"
export PORT="10000"
```

> ⚠️ These are NEVER committed to GitHub. They live only on the EC2 server (or in `/etc/environment` / systemd unit file).

---

## 🔥 8. GITHUB + DEPLOYMENT FLOW

### Repo Structure on GitHub (`siddharthgaddam7/healthcare-platform`)

```
mini_final/
├── backend/
│   ├── app.py                          ← Main Flask backend (1008 lines)
│   ├── requirements.txt                ← Python dependencies
│   ├── migrate_to_mongo.py             ← One-time DB migration script
│   ├── enriched_with_canonical_updated.xlsx  ← Excel dataset (fallback)
│   ├── test_metadata.json              ← Test descriptions/info
│   └── utils/
│       ├── data_loader.py              ← Pandas data loading utility
│       └── search_utils.py             ← RapidFuzz utility (early version)
├── frontend/
│   ├── index.html                      ← Main search page
│   ├── login.html                      ← Login/register/forgot
│   ├── admin.html                      ← Admin dashboard
│   ├── doctor.html                     ← Doctor dashboard
│   ├── style.css                       ← Full design system (981 lines)
│   └── script.js                       ← Frontend logic (466 lines)
├── data/
│   └── tests_hyderabad.xlsx            ← Original raw dataset
└── [Excel + PPTX files at root]        ← Data iterations, presentations
```

### Deployment Flow

**Frontend (Vercel):**
```
Developer → git push → GitHub → Vercel webhook fires → Vercel builds/deploys → CDN updated (30s)
```

**Backend (EC2):**
```
Developer → git push → GitHub (no auto-deploy)
         → SSH into EC2 → git pull → restart Gunicorn (manual)
```

Vercel is connected to the GitHub repo and auto-deploys only the `frontend/` folder. Changes to `backend/` are ignored by Vercel.

---

## 🔥 9. API COMMUNICATION — FULL EXAMPLES

### Complete Flow: User Clicks "Book" Button

```
1. User sees search results table
2. Clicks "Book" button on a lab row

3. [frontend/script.js] openBookingModal(btn) runs:
   - Reads data-test, data-lab, data-price from button attributes
   - Fills booking modal with test name, lab name, price
   - Shows modal

4. User selects "Direct Contact" or "Email Request"
5. Clicks "Confirm Booking"

6. [frontend/script.js] submitBooking() runs:
   fetch("http://15.206.125.164/book", {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       credentials: "include",  ← sends session cookie
       body: JSON.stringify({
           test_name: "CBC",
           lab_name: "SRL Diagnostics",
           mode: "email_request"
       })
   })

7. [EC2/Nginx] Receives on port 80 → forwards to Gunicorn:10000

8. [backend/app.py] /book route runs:
   a. @login_required checks session cookie → user_id found → OK
   b. Finds lab in MongoDB: labs.find_one({lab_name, canonical_name})
   c. Gets price from lab doc
   d. Creates booking document:
      {user_id, username, test_name, lab_name, price, mode: "email_request", status: "pending"}
   e. Inserts into bookings collection → gets booking_id
   f. Fetches user's email/phone from users collection
   g. Starts background thread → send_booking_email()
      - SendGrid API called with lab's email as recipient
      - Returns instantly (non-blocking)
   h. Returns: {"success": true, "booking_id": "...", "email_sent": true}

9. [frontend] JavaScript reads response:
   - Hides booking form
   - Shows success message with booking_id
   - Calls loadBookings() to refresh sidebar
```

### All HTTP Methods Used

| Method | When Used | Example |
|---|---|---|
| `GET` | Fetching data with no body | `/me`, `/tests`, `/cart`, `/bookings`, `/suggest?q=cbc` |
| `POST` | Creating/updating data with JSON body | `/login`, `/search`, `/book`, `/cart/add`, `/logout` |

No `PUT`, `DELETE`, or `PATCH` — this project uses `POST` for all writes (including cancellations and removals).

---

## 🔥 10. COMMON ISSUES & FIXES

### 1. CORS Errors

**What happened:** Frontend on `https://healthcare-platform-gamma.vercel.app` calling backend on `http://15.206.125.164`. Browser blocks this by default (different origin = different protocol/domain).

**Fix:** Add the Vercel domain to Flask-CORS:
```python
CORS(app, supports_credentials=True, resources={r"/*": {"origins": [
    "https://healthcare-platform-gamma.vercel.app",
    ...
]}})
```

**Why it happens:** Browsers enforce the Same-Origin Policy. CORS headers from the server explicitly tell the browser "yes, this origin is allowed."

---

### 2. Mixed Content (HTTPS Frontend → HTTP Backend)

**What happened:** Vercel serves the frontend over HTTPS. The backend API is `http://15.206.125.164` (plain HTTP). Modern browsers block HTTPS pages from making HTTP (insecure) requests.

**Root cause:** EC2 doesn't have SSL/HTTPS set up (no domain, no certificate).

**Current workaround:** The HTTPS→HTTP calls technically still work in most browsers when the backend IP is hardcoded (not a domain) and because the user explicitly installs the APK on Android side. Long-term fix: add a domain + Let's Encrypt SSL on Nginx.

---

### 3. SESSION_COOKIE_SECURE Issue

**What happened:** Flask's `SESSION_COOKIE_SECURE = True` (the default in some configs) means the session cookie is ONLY sent over HTTPS. Since the backend runs on HTTP, the browser never sends the cookie → every request is treated as unauthenticated (401).

**Fix:**
```python
app.config["SESSION_COOKIE_SECURE"] = False   # allow over HTTP
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"  # allow cross-site but same navigation
```

---

### 4. Port 10000 in Public URL

**What happened:** Frontend originally called `http://15.206.125.164:10000` (Gunicorn directly). This requires port 10000 to be open in the EC2 security group AND is not standard (port 80 is the default HTTP port).

**Fix:** Set up Nginx as a reverse proxy on port 80, changed all frontend `BASE` constant to `http://15.206.125.164` (no port). Base URL updated across: `script.js`, `login.html`, `admin.html`, `doctor.html`.

---

### 5. SendGrid 400 Error

**What happened:** SendGrid returned HTTP 400 (Bad Request) when trying to send emails.

**Root cause:** The "from" email address (GMAIL_USER) was not verified as a sender in SendGrid's dashboard. SendGrid requires sender verification (either single sender or domain authentication).

**Fix:** Go to SendGrid → Settings → Sender Authentication → verify the email address used as `GMAIL_USER`.

---

### 6. Missing Environment Variables

**What happened:** App started but no MongoDB connection. Search returned empty, login failed.

**Root cause:** EC2 server restarted (or new SSH session) and env vars weren't persisted.

**Fix options:**
1. Add to `~/.bashrc`: `export MONGO_URI="..."` → runs on every login
2. Add to `/etc/environment` → system-wide persistent
3. Create a systemd service file that includes `Environment=MONGO_URI=...`

---

## 🔥 11. FINAL PRODUCTION ARCHITECTURE

```
                    ┌──────────────┐
                    │   USER       │
                    │ (Browser/App)│
                    └──────┬───────┘
                           │ HTTPS
                           ▼
┌──────────────────────────────────────────────────────┐
│              VERCEL — Frontend CDN                    │
│  Globally distributed edge network                    │
│  Serves: login.html, index.html, admin.html,          │
│          doctor.html, style.css, script.js            │
│  Auto-deploys from GitHub on every push               │
└──────────────────────────┬───────────────────────────┘
                           │ HTTP API calls
                           │ http://15.206.125.164
                           ▼
┌──────────────────────────────────────────────────────┐
│         AWS EC2 — t3.micro, Mumbai, Ubuntu 22.04      │
│         IP: 15.206.125.164                            │
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │  NGINX (port 80)                               │  │
│  │  - Terminates client connection                │  │
│  │  - Forwards to Gunicorn via proxy_pass         │  │
│  └─────────────────────┬──────────────────────────┘  │
│                         │ localhost:10000              │
│  ┌──────────────────────▼──────────────────────────┐  │
│  │  GUNICORN (port 10000, 4 workers)               │  │
│  │  - WSGI production server                       │  │
│  │  - Process management + concurrency             │  │
│  └─────────────────────┬──────────────────────────┘  │
│                         │                             │
│  ┌──────────────────────▼──────────────────────────┐  │
│  │  FLASK APP (app.py)                             │  │
│  │  - 30+ API routes                              │  │
│  │  - Session management                          │  │
│  │  - Business logic                              │  │
│  └──────┬───────────────────────────┬─────────────┘  │
└─────────┼───────────────────────────┼────────────────┘
          │                           │
          ▼                           ▼
┌──────────────────┐        ┌──────────────────────────┐
│  MongoDB Atlas   │        │  SendGrid Email API       │
│  (Cloud DB)      │        │  (Booking notifications)  │
│                  │        │                           │
│  Collections:    │        │  - Sends HTML emails to   │
│  - users         │        │    labs or GMAIL_USER in  │
│  - tests         │        │    test mode              │
│  - labs          │        └──────────────────────────┘
│  - bookings      │
│  - carts         │
│  - doctors       │
└──────────────────┘
```

### Each Component's Role

| Component | Role |
|---|---|
| **Vercel** | CDN for static frontend files. No server needed. Free, fast, auto-deploys. |
| **EC2** | Linux virtual machine that runs your backend 24/7. You control everything. |
| **Nginx** | The gatekeeper. Accepts public requests on port 80, passes them internally to Gunicorn. |
| **Gunicorn** | The actual Python process runner. Spawns N workers, handles concurrency. |
| **Flask** | Your application code. Defines routes, reads DB, returns JSON. |
| **MongoDB Atlas** | Cloud database. Stores users, labs, tests, bookings. No DB server to manage. |
| **SendGrid** | Email delivery service. Used to email labs when user requests an appointment via email mode. |

---

## 🔥 12. TEAM CONTRIBUTION BREAKDOWN (4 Members)

| Member | Role | Owns |
|---|---|---|
| **Member 1 — Frontend** | UI/UX Developer | `login.html`, `index.html`, `style.css` — all UI, forms, responsive design, cart/booking sidebars, booking modal, autosuggest dropdown, price chart bars |
| **Member 2 — Backend** | Flask Developer | `app.py` — all API endpoints, authentication (bcrypt), session management, password reset flow, MFA, CORS, email integration (SendGrid), booking logic |
| **Member 3 — Data/DB** | Data Engineer | Excel dataset collection + cleaning, `migrate_to_mongo.py`, `test_metadata.json` (10 tests with detailed metadata), MongoDB schema design, search alias mapping, `utils/data_loader.py`, `utils/search_utils.py` |
| **Member 4 — DevOps** | Infrastructure Lead | AWS EC2 setup, Nginx configuration, Gunicorn deployment, environment variable management, GitHub-to-EC2 deployment workflow, security groups, `admin.html`, `doctor.html` dashboards |

---

## 🔥 13. SIMPLIFIED EXPLANATION — BEGINNER STORY FORMAT

> 👉 Forget all the technical words. Here's what happens when a real user uses your app.

---

### 🧑 The Story of Ravi Searching for a Blood Test

**Step 1: Ravi opens the app**

He goes to `https://healthcare-platform-gamma.vercel.app`. His browser contacts Vercel's servers (which are located all over the world). Vercel immediately sends back the login page `login.html`. It's just an HTML file — like a Word document translated to web language.

---

**Step 2: Ravi logs in**

He types his username `ravi123` and password `mypass`. He clicks "Sign In."

The page's JavaScript code runs and does this: *"Hey, backend server! Here are Ravi's credentials. Is he legit?"*

This message (called an API request) travels from Ravi's browser → through the internet → to a computer (EC2) at AWS's data center in Mumbai.

On that Mumbai computer:
- Nginx (the security guard) receives the request at the front door (port 80)
- Passes it to Gunicorn (the manager)
- Gunicorn gives it to one of 4 Flask workers (the actual employees doing the work)
- Flask looks up `ravi123` in MongoDB (the filing cabinet, hosted by MongoDB's servers)
- Finds Ravi's record, checks his password hash using bcrypt
- Confirms: "Yes, this is Ravi!" and creates a session (like giving him a VIP wristband)

Flask sends back: "Yes, logged in! Ravi is a regular user." The JavaScript reads this and says, "OK, go to index.html."

---

**Step 3: Ravi searches for "CBC"**

Now on `index.html`, Ravi types "CBC" in the search box and clicks Search.

JavaScript runs: *"Backend, what labs offer CBC and how much do they charge?"*

Flask receives this on the `/search` route:
1. Normalizes the query (removes punctuation, lowercase)
2. Looks at all tests in MongoDB (CBC, Thyroid Panel, etc.)
3. For each test, checks: is "cbc" similar to any of this test's nicknames? (using fuzzy matching)
4. Finds "CBC" matches perfectly (score ~95)
5. Runs a database query: "Give me all labs that offer CBC, sorted by price"
6. Gets back: SRL Diagnostics ₹350, Apollo Lab ₹420, Thyrocare ₹280...
7. Sends all this data back as JSON

JavaScript receives the data and builds a beautiful HTML table showing:
- A description of what CBC measures
- Min price, average price, max price cards
- A horizontal bar chart of prices
- A table with each lab, location, price, and Book button

---

**Step 4: Ravi books at Thyrocare**

Ravi sees Thyrocare is cheapest. He clicks "Book" → a popup appears showing the test name, lab name, and price. He selects "Email Request" and clicks Confirm.

JavaScript calls the `/book` API:
- Flask saves the booking in MongoDB (creates a booking document with status "pending")
- Flask starts an email in the background (so Ravi doesn't have to wait)
- SendGrid's email service sends an HTML email to Thyrocare's email address: "New booking request from Ravi for CBC!"
- Flask returns instantly: "Booked! Reference ID: 67abc123"

Ravi sees a success message with his reference ID. He can click "Bookings" in the navbar to see his booking history anytime.

---

**The whole thing, in one line:**

> Vercel delivers the website → User doesn't wait → JavaScript talks to Flask on AWS → Flask reads/writes MongoDB → SendGrid sends emails → everything stays in sync.

---

## 📋 QUICK REFERENCE CARD

```
Project Name : ClinixCompare / Hyderabad Health
Frontend URL : https://healthcare-platform-gamma.vercel.app
Backend URL  : http://15.206.125.164
Backend Port : 80 (public via Nginx)
Internal Port: 10000 (Gunicorn, internal only)
Database     : MongoDB Atlas → healthcare_platform
Admin Login  : username=admin, password=admin123 (hardcoded)
EC2 Region   : ap-south-1 (Mumbai)
EC2 IP       : 15.206.125.164
Tech Stack   : HTML/CSS/JS | Flask | MongoDB | Gunicorn | Nginx | Vercel | AWS EC2 | SendGrid
```
