import os
from functools import wraps
import bcrypt
from mysql.connector import IntegrityError

from flask import Flask, render_template, request, redirect, session
from werkzeug.middleware.proxy_fix import ProxyFix
from matcher import get_top_matches, get_connection
from chat_logic import MAX_ACTIVE_CHATS, active_chat_limit_message, can_accept_chat

app = Flask(__name__, template_folder="Templates")
app.secret_key = os.environ.get("SECRET_KEY", "friend-finder-development-key")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


@app.before_request
def force_https():
    forwarded_proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    if not app.debug and forwarded_proto.split(",", 1)[0].strip().lower() != "https":
        return redirect(request.url.replace("http://", "https://", 1), code=301)


def ensure_chat_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SHOW COLUMNS FROM users LIKE 'password_hash'")
    if cursor.fetchone() is None:
        cursor.execute("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL")

    cursor.execute("SHOW COLUMNS FROM users LIKE 'phone'")
    if cursor.fetchone() is None:
        cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(30) NULL")

    for column, definition in (
        ("gender", "VARCHAR(10) NULL"),
        ("preferred_gender", "VARCHAR(10) NULL"),
        ("year", "INT NULL"),
        ("preferred_year", "VARCHAR(10) NULL"),
    ):
        cursor.execute(f"SHOW COLUMNS FROM users LIKE '{column}'")
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER TABLE users ADD COLUMN `{column}` {definition}")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences_meta (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            question_id INT NOT NULL,
            importance INT NOT NULL DEFAULT 3,
            openness INT NOT NULL DEFAULT 3
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user1_id INT NOT NULL,
            user2_id INT NOT NULL,
            status ENUM('active', 'pending', 'archived') NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_requests (
            id INT AUTO_INCREMENT PRIMARY KEY,
            from_user INT NOT NULL,
            to_user INT NOT NULL,
            status ENUM('pending', 'accepted', 'rejected') NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INT AUTO_INCREMENT PRIMARY KEY,
            chat_id INT NULL,
            sender_id INT NOT NULL,
            receiver_id INT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute("SHOW COLUMNS FROM messages LIKE 'chat_id'")
    if cursor.fetchone() is None:
        cursor.execute("ALTER TABLE messages ADD COLUMN chat_id INT NULL AFTER id")

    cursor.execute("SHOW COLUMNS FROM messages LIKE 'created_at'")
    if cursor.fetchone() is None:
        cursor.execute(
            """
            ALTER TABLE messages
            ADD COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            """
        )

    conn.commit()
    cursor.close()
    conn.close()


ensure_chat_tables()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return view(*args, **kwargs)

    return wrapped_view


def get_user_auth(user_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, password_hash FROM users WHERE id = %s",
        (user_id,),
    )
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def get_active_chat_count(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM chats
        WHERE status = 'active'
          AND (user1_id = %s OR user2_id = %s)
        """,
        (user_id, user_id),
    )
    count = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return count or 0


def get_existing_chat(user1, user2):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT *
        FROM chats
        WHERE (
            (user1_id = %s AND user2_id = %s)
            OR (user1_id = %s AND user2_id = %s)
        )
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user1, user2, user2, user1),
    )
    chat = cursor.fetchone()
    cursor.close()
    conn.close()
    return chat


def get_chat(chat_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True, buffered=True)
    cursor.execute("SELECT * FROM chats WHERE id = %s", (chat_id,))
    chat = cursor.fetchone()
    cursor.close()
    conn.close()
    return chat


def get_user_name(user_id):
    conn = get_connection()
    cursor = conn.cursor(buffered=True)
    cursor.execute("SELECT name FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else f"User {user_id}"


def get_pending_requests_for_user(user_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT cr.id, cr.from_user, cr.to_user, cr.created_at, u.name AS from_name
        FROM chat_requests cr
        JOIN users u ON u.id = cr.from_user
        WHERE cr.to_user = %s AND cr.status = 'pending'
        ORDER BY cr.created_at DESC
        """,
        (user_id,),
    )
    requests = cursor.fetchall()
    cursor.close()
    conn.close()
    return requests


def get_user_inbox(user_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
         SELECT c.id, c.user1_id, c.user2_id, c.status,
             CASE WHEN c.user1_id = %s THEN c.user2_id ELSE c.user1_id END AS other_user_id,
             CASE WHEN c.user1_id = %s THEN u2.name ELSE u1.name END AS other_name
        FROM chats c
         JOIN users u1 ON u1.id = c.user1_id
         JOIN users u2 ON u2.id = c.user2_id
        WHERE c.status = 'active' AND (c.user1_id = %s OR c.user2_id = %s)
        ORDER BY c.updated_at DESC
        """,
         (user_id, user_id, user_id, user_id),
    )
    active_chats = cursor.fetchall()

    cursor.execute(
        """
        SELECT cr.id, cr.from_user, cr.to_user, cr.created_at, u.name AS from_name
        FROM chat_requests cr
        JOIN users u ON u.id = cr.from_user
        WHERE cr.to_user = %s AND cr.status = 'pending'
        ORDER BY cr.created_at DESC
        """,
        (user_id,),
    )
    pending_requests = cursor.fetchall()

    cursor.execute(
        """
         SELECT c.id, c.user1_id, c.user2_id, c.status,
             CASE WHEN c.user1_id = %s THEN c.user2_id ELSE c.user1_id END AS other_user_id,
             CASE WHEN c.user1_id = %s THEN u2.name ELSE u1.name END AS other_name
        FROM chats c
         JOIN users u1 ON u1.id = c.user1_id
         JOIN users u2 ON u2.id = c.user2_id
        WHERE c.status = 'archived' AND (c.user1_id = %s OR c.user2_id = %s)
        ORDER BY c.updated_at DESC
        """,
         (user_id, user_id, user_id, user_id),
    )
    archived_chats = cursor.fetchall()

    cursor.close()
    conn.close()
    return active_chats, pending_requests, archived_chats


def get_chat_messages(user1, user2):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sender_id, message, created_at
        FROM messages
        WHERE (sender_id=%s AND receiver_id=%s)
           OR (sender_id=%s AND receiver_id=%s)
        ORDER BY created_at ASC
        """,
        (user1, user2, user2, user1),
    )
    messages = cursor.fetchall()
    cursor.close()
    conn.close()
    return messages


def get_chat_messages_by_id(chat_id, user1, user2):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sender_id, message, created_at
        FROM messages
        WHERE chat_id = %s
           OR (chat_id IS NULL AND (
                (sender_id = %s AND receiver_id = %s)
                OR (sender_id = %s AND receiver_id = %s)
           ))
        ORDER BY created_at ASC
        """,
        (chat_id, user1, user2, user2, user1),
    )
    messages = cursor.fetchall()
    cursor.close()
    conn.close()
    return messages


def request_exists(from_user, to_user):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id
        FROM chat_requests
        WHERE status = 'pending'
          AND ((from_user = %s AND to_user = %s) OR (from_user = %s AND to_user = %s))
        LIMIT 1
        """,
        (from_user, to_user, to_user, from_user),
    )
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return bool(result)

QUESTION_TEXT = {
    1: "social energy",
    2: "group activities",
    3: "going out",
    4: "movies and series",
    5: "fitness and gym habits",
    6: "music taste",
    7: "religious beliefs",
    8: "discipline and routine",
    9: "lifestyle fit",
    10: "shared interests",
    11: "openness to different beliefs",
    12: "openness to different personalities",
}

ALLOWED_EMAIL_DOMAIN = "@thapar.edu"


def normalize_thapar_email(value):
    email = (value or "").strip().lower()
    if not email or email.count("@") != 1 or not email.endswith(ALLOWED_EMAIL_DOMAIN):
        return None
    return email


def humanize_reason(reason):
    if isinstance(reason, str):
        return reason

    question_id = reason.get("question_id")
    label = reason.get("label", "similar")
    topic = QUESTION_TEXT.get(question_id, f"question {question_id}")

    if label == "very similar":
        return f"Both value {topic} in a very similar way."
    if label == "similar":
        return f"Your preferences for {topic} are well aligned."
    if label == "different":
        return f"Your preferences for {topic} are a little different."
    return f"Your preferences for {topic} are quite different."


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = normalize_thapar_email(request.form.get("email"))
        if email is None:
            return render_template(
                "login.html",
                error="Use your Thapar email ending in @thapar.edu.",
            )

        conn = get_connection()
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute(
            "SELECT id, password_hash FROM users WHERE email = %s",
            (email,),
        )
        users = cursor.fetchall()
        cursor.close()
        conn.close()

        if not users:
            return redirect("/form")
        user = users[0]
        if user["password_hash"]:
            return redirect(f"/login-password/{user['id']}")
        return redirect(f"/setup/{user['id']}")

    return render_template("login.html")


@app.route("/login-password/<int:user_id>", methods=["GET", "POST"])
def login_password(user_id):
    user = get_user_auth(user_id)
    if user is None:
        return redirect("/login")

    error = ""
    if request.method == "POST":
        password = request.form.get("password", "")
        stored_hash = user["password_hash"]
        stored_hash_bytes = stored_hash if isinstance(stored_hash, bytes) else stored_hash.encode("utf-8")
        if stored_hash and bcrypt.checkpw(password.encode("utf-8"), stored_hash_bytes):
            session["user_id"] = user_id
            return redirect(f"/results/{user_id}")
        error = "Wrong password"

    return render_template("login_password.html", user_id=user_id, error=error)


@app.route("/setup/<int:user_id>", methods=["GET", "POST"])
def setup(user_id):
    user = get_user_auth(user_id)
    if user is None:
        return redirect("/login")
    if user["password_hash"]:
        return redirect(f"/login-password/{user_id}")

    if request.method == "POST":
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        if len(password) < 8:
            return render_template(
                "setup.html",
                user_id=user_id,
                error="Password must be at least 8 characters.",
            )
        if not phone:
            return render_template(
                "setup.html",
                user_id=user_id,
                error="Phone number is required.",
            )

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = %s, phone = %s WHERE id = %s",
            (password_hash, phone, user_id),
        )
        conn.commit()
        cursor.close()
        conn.close()
        session["user_id"] = user_id
        return redirect(f"/results/{user_id}")

    return render_template("setup.html", user_id=user_id, error="")


@app.route("/inbox/<int:user_id>")
@login_required
def inbox(user_id):
    if session["user_id"] != user_id:
        return redirect(f"/inbox/{session['user_id']}")

    active_chats, pending_requests, archived_chats = get_user_inbox(user_id)
    return render_template(
        "inbox.html",
        user_id=user_id,
        active_chats=active_chats,
        pending_requests=pending_requests,
        archived_chats=archived_chats,
    )


@app.route("/requests")
@login_required
def requests_page():
    pending_requests = get_pending_requests_for_user(session["user_id"])
    return render_template(
        "requests.html",
        user_id=session["user_id"],
        pending_requests=pending_requests,
    )


@app.route("/connect/<int:target_user_id>", methods=["POST"])
@login_required
def connect(target_user_id):
    from_user = session["user_id"]
    to_user = target_user_id

    if from_user == to_user:
        return redirect(f"/results/{from_user}")

    if request_exists(from_user, to_user):
        return redirect(f"/results/{from_user}")

    if get_existing_chat(from_user, to_user):
        return redirect(f"/results/{from_user}")

    if not can_accept_chat(get_active_chat_count(to_user)):
        return f"<h3>{active_chat_limit_message()}</h3><a href='/results/{from_user}'>Back</a>"

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_requests (from_user, to_user, status) VALUES (%s, %s, 'pending')",
        (from_user, to_user),
    )
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(f"/results/{from_user}")


@app.route("/request_chat/<int:from_user>/<int:to_user>")
@login_required
def legacy_request_chat(from_user, to_user):
    if session["user_id"] != from_user:
        return redirect("/login")
    return connect(to_user)


@app.route("/accept_chat_request/<int:request_id>", methods=["POST"])
@login_required
def accept_chat_request(request_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, from_user, to_user, status FROM chat_requests WHERE id = %s",
        (request_id,),
    )
    request_row = cursor.fetchone()

    if not request_row:
        cursor.close()
        conn.close()
        return redirect("/")

    if request_row["to_user"] != session["user_id"]:
        cursor.close()
        conn.close()
        return redirect(f"/inbox/{session['user_id']}")

    if request_row["status"] != "pending":
        cursor.close()
        conn.close()
        return redirect(f"/inbox/{request_row['to_user']}")

    if not can_accept_chat(get_active_chat_count(request_row["to_user"])):
        cursor.close()
        conn.close()
        return f"<h3>{active_chat_limit_message()}</h3><a href='/inbox/{request_row['to_user']}'>Back</a>"

    existing = get_existing_chat(request_row["from_user"], request_row["to_user"])
    if existing is None:
        cursor.execute(
            "INSERT INTO chats (user1_id, user2_id, status) VALUES (%s, %s, 'active')",
            (request_row["from_user"], request_row["to_user"]),
        )
        chat_id = cursor.lastrowid
    else:
        cursor.execute(
            "UPDATE chats SET status = 'active' WHERE id = %s",
            (existing["id"],),
        )
        chat_id = existing["id"]

    cursor.execute(
        "UPDATE chat_requests SET status = 'accepted' WHERE id = %s",
        (request_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(f"/chat/{chat_id}")


@app.route("/reject_chat_request/<int:request_id>/<int:user_id>", methods=["POST"])
@login_required
def reject_chat_request(request_id, user_id):
    if session["user_id"] != user_id:
        return redirect(f"/inbox/{session['user_id']}")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_requests WHERE id = %s", (request_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(f"/inbox/{user_id}")


@app.route("/archive_chat/<int:chat_id>/<int:user_id>")
@login_required
def archive_chat(chat_id, user_id):
    if session["user_id"] != user_id:
        return redirect(f"/inbox/{session['user_id']}")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE chats SET status = 'archived' WHERE id = %s AND (user1_id = %s OR user2_id = %s)",
        (chat_id, user_id, user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(f"/inbox/{user_id}")

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/results/<int:user_id>")
@login_required
def results(user_id):
    if session["user_id"] != user_id:
        return redirect("/login")

    matches = get_top_matches(user_id)
    notification_count = len(get_pending_requests_for_user(user_id))

    formatted = []
    for match_id, name, email, score, reasons in matches:
        formatted.append({
            "id": match_id,
            "name": name,
            "email": email,
            "score": score,
            "reasons": [humanize_reason(r) for r in reasons]
        })

    return render_template(
        "results.html",
        matches=formatted,
        current_user_id=user_id,
        notification_count=notification_count,
    )
@app.route("/form")
def form():
    return render_template("form.html")
# @app.route("/submit", methods=["POST"])   
# def submit():
#     name = request.form.get("name")
#     email = request.form.get("email")
#     q1 = int(request.form.get("q1"))
#     q2 = int(request.form.get("q2"))

#     conn = get_connection()
#     cursor = conn.cursor()

#     # insert user
#     cursor.execute("INSERT INTO users (name, email) VALUES (%s, %s)", (name, email))
#     user_id = cursor.lastrowid

#     # insert responses
#     cursor.execute("INSERT INTO responses (user_id, question_id, value_number) VALUES (%s, 1, %s)", (user_id, q1))
#     cursor.execute("INSERT INTO responses (user_id, question_id, value_number) VALUES (%s, 2, %s)", (user_id, q2))

#     conn.commit()
#     cursor.close()
#     conn.close()

#     return redirect(f"/results/{user_id}")

@app.route("/find", methods=["GET", "POST"])
def find():
    if request.method == "POST":
        email = request.form.get("email")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM usersexplanation WHERE email = %s", (email,))
        user = cursor.fetchone()

        print("Searching for:", email)
        print("Result:", user)

        cursor.close()
        conn.close()
        if user:
            user_id = user[0]
            return redirect(f"/results/{user_id}")

        else:
            return "User not found. Please fill the form first."


    return '''
        <h2>Enter Your Email</h2>
        <form method="POST">
            <input type="email" name="email" placeholder="Enter Email" required>
            <button type="submit">See Matches</button>
        </form>
    '''

@app.route("/submit", methods=["POST"])
def submit():
    name = request.form.get("name")
    email = normalize_thapar_email(request.form.get("email"))
    roll = request.form.get("roll") or None
    gender = request.form.get("gender", "").strip().lower()
    preferred_gender = request.form.get("preferred_gender", "").strip().lower()
    preferred_year = request.form.get("preferred_year", "").strip().lower()

    try:
        year = int(request.form.get("year", ""))
    except ValueError:
        year = 0

    if email is None:
        return render_template(
            "form.html",
            error="Use your Thapar email ending in @thapar.edu.",
        )
    if gender not in {"male", "female"}:
        return render_template("form.html", error="Choose a valid gender.")
    if preferred_gender not in {"male", "female", "both"}:
        return render_template("form.html", error="Choose a preferred gender.")
    if year < 1:
        return render_template("form.html", error="Choose a valid year.")
    if preferred_year not in {"same", "all"}:
        return render_template("form.html", error="Choose a preferred year option.")

    # q1-q8 are compatibility responses.
    answers = []
    for i in range(1, 9):
        raw = request.form.get(f"q{i}")
        if raw is None:
            print(f"Missing q{i}")   # debug
            return f"Error: Missing q{i}"

        try:
            val = int(raw)
        except (TypeError, ValueError):
            return render_template("form.html", error=f"q{i} must be a number from 1 to 10.")
        if not 1 <= val <= 10:
            return render_template("form.html", error=f"q{i} must be between 1 and 10.")
        answers.append(val)

    # q9-q12 are preference metadata, not compatibility responses.
    preferences = []
    for i in range(9, 13):
        raw = request.form.get(f"q{i}")
        if raw is None:
            return render_template(
                "form.html",
                error=f"Missing q{i}",
            )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return render_template("form.html", error=f"q{i} must be a number from 1 to 10.")
        if not 1 <= value <= 10:
            return render_template("form.html", error=f"q{i} must be between 1 and 10.")
        preferences.append((i, value))

    conn = get_connection()
    cursor = conn.cursor()

    # insert user
    try:
        cursor.execute(
            """
            INSERT INTO users
                (name, email, gender, preferred_gender, `year`, preferred_year)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (name, email, gender, preferred_gender, year, preferred_year),
        )
    except IntegrityError as error:
        conn.rollback()
        cursor.close()
        conn.close()
        if error.errno == 1062:
            return render_template(
                "form.html",
                error="An account already exists for this email. Use a different email.",
            )
        raise

    user_id = cursor.lastrowid

    # insert responses
    for i, val in enumerate(answers, start=1):
        cursor.execute(
            "INSERT INTO responses (user_id, question_id, value_number) VALUES (%s, %s, %s)",
            (user_id, i, val)
        )

    for question_id, importance in preferences:
        cursor.execute(
            """
            INSERT INTO preferences_meta (user_id, question_id, importance, openness)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, question_id, importance, 3),
        )
    print("Inserted user:", name, email, user_id)

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(f"/setup/{user_id}")

@app.route("/send_message", methods=["POST"])
@login_required
def send_message():
    sender = request.form.get("sender_id")
    receiver = request.form.get("receiver_id")
    chat_id = request.form.get("chat_id")
    message = request.form.get("message")

    if not sender or not receiver or not message:
        return redirect("/form")

    if session["user_id"] != int(sender):
        return redirect(f"/results/{session['user_id']}")

    chat = get_chat(int(chat_id)) if chat_id else get_existing_chat(sender, receiver)
    if chat is None or chat["status"] != "active":
        return redirect(f"/inbox/{sender}")
    if session["user_id"] not in (chat["user1_id"], chat["user2_id"]):
        return redirect("/login")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO messages (chat_id, sender_id, receiver_id, message)
        VALUES (%s, %s, %s, %s)
        """,
        (chat["id"], sender, receiver, message),
    )

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(f"/chat/{sender}/{receiver}")

@app.route("/chat/<int:chat_id>")
@login_required
def chat(chat_id):
    chat_row = get_chat(chat_id)
    if not chat_row or session["user_id"] not in (chat_row["user1_id"], chat_row["user2_id"]):
        return redirect("/login")

    user1 = session["user_id"]
    user2 = chat_row["user2_id"] if chat_row["user1_id"] == user1 else chat_row["user1_id"]
    chat_name = get_user_name(user2)

    if chat_row["status"] != "active":
        return render_template(
            "chat.html",
            messages=[],
            user1=user1,
            user2=user2,
            chat_id=chat_id,
            chat_name=chat_name,
            chat_locked=True,
            chat_error="This chat is waiting for acceptance or has been archived.",
        )

    messages = get_chat_messages_by_id(chat_id, user1, user2)
    return render_template(
        "chat.html",
        messages=messages,
        user1=user1,
        user2=user2,
        chat_id=chat_id,
        chat_name=chat_name,
        chat_locked=False,
        chat_error="",
    )


@app.route("/chat/<int:user1>/<int:user2>")
@login_required
def legacy_chat(user1, user2):
    if session["user_id"] not in (user1, user2):
        return redirect("/login")
    chat_row = get_existing_chat(user1, user2)
    if not chat_row:
        return redirect(f"/results/{session['user_id']}")
    return redirect(f"/chat/{chat_row['id']}")

if __name__ == "__main__":
    app.run(debug=True)