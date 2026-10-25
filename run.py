import os
import re
import uuid
import sqlite3

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from database import get_db, init_db


# ---------------- APPLICATION CONFIGURATION ----------------

app = Flask(__name__)

app.secret_key = os.environ.get(
    "TRUSTVAULT_SECRET_KEY",
    "trustvault-development-key-change-before-deployment"
)

UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")
PROFILE_FOLDER = os.path.join(
    app.root_path, "static", "profile_images"
)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROFILE_FOLDER, exist_ok=True)


# ---------------- HELPER FUNCTIONS ----------------

def is_logged_in():
    return "user_id" in session


def is_admin():
    return session.get("role") == "admin"


def can_manage_documents():
    return session.get("role") in ("admin", "owner")


def allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def log_activity(conn, action, details):
    conn.execute(
        """
        INSERT INTO activity_logs (user_id, action, details)
        VALUES (?, ?, ?)
        """,
        (session["user_id"], action, details)
    )


def can_manage_document(conn, document_id):
    if is_admin():
        return conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,)
        ).fetchone()

    return conn.execute(
        """
        SELECT * FROM documents
        WHERE id = ? AND owner_id = ?
        """,
        (document_id, session["user_id"])
    ).fetchone()


def get_accessible_document(conn, document_id):
    if is_admin():
        return conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,)
        ).fetchone()

    return conn.execute(
        """
        SELECT d.*
        FROM documents d
        WHERE d.id = ?
        AND (
            d.owner_id = ?
            OR EXISTS (
                SELECT 1
                FROM shares s
                WHERE s.document_id = d.id
                AND s.shared_with_user_id = ?
            )
        )
        """,
        (document_id, session["user_id"], session["user_id"])
    ).fetchone()


def can_edit_document(conn, document_id):
    if is_admin():
        return conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (document_id,)
        ).fetchone()

    return conn.execute(
        """
        SELECT d.*
        FROM documents d
        WHERE d.id = ?
        AND (
            d.owner_id = ?
            OR EXISTS (
                SELECT 1 FROM shares s
                WHERE s.document_id = d.id
                AND s.shared_with_user_id = ?
                AND s.permission = 'edit'
            )
        )
        """,
        (document_id, session["user_id"], session["user_id"])
    ).fetchone()


# ---------------- ERROR HANDLERS ----------------

@app.errorhandler(413)
def file_too_large(error):
    flash("File is too large. Maximum allowed size is 5 MB.")
    return redirect(url_for("my_documents"))


# ---------------- HOME ----------------

@app.route("/")
def home():
    if is_logged_in():
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.")
            return render_template("register.html")

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return render_template("register.html")

        conn = get_db()

        try:
            conn.execute(
                """
                INSERT INTO users (name, email, password, role)
                VALUES (?, ?, ?, 'owner')
                """,
                (name, email, generate_password_hash(password))
            )
            conn.commit()

            flash("Registration successful. Please login.")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            conn.rollback()
            flash("This email is already registered.")

        except Exception:
            conn.rollback()
            app.logger.exception("Registration failed")
            flash("Registration failed.")

        finally:
            conn.close()

    return render_template("register.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()

        try:
            user = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            if user and check_password_hash(user["password"], password):
                conn.execute(
                    """
                    INSERT INTO activity_logs (user_id, action, details)
                    VALUES (?, ?, ?)
                    """,
                    (user["id"], "LOGIN", "User logged in")
                )
                conn.commit()

                session.clear()
                session["user_id"] = user["id"]
                session["user_name"] = user["name"]
                session["role"] = user["role"]

                return redirect(url_for("dashboard"))

        except Exception:
            app.logger.exception("Login failed")

        finally:
            conn.close()

        flash("Invalid email or password.")

    return render_template("login.html")


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
def dashboard():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        if is_admin():
            document_count = conn.execute(
                "SELECT COUNT(*) FROM documents"
            ).fetchone()[0]

            user_count = conn.execute(
                "SELECT COUNT(*) FROM users"
            ).fetchone()[0]
        else:
            document_count = conn.execute(
                "SELECT COUNT(*) FROM documents WHERE owner_id = ?",
                (session["user_id"],)
            ).fetchone()[0]

            user_count = 0

        shared_count = conn.execute(
            """
            SELECT COUNT(*) FROM shares
            WHERE shared_with_user_id = ?
            """,
            (session["user_id"],)
        ).fetchone()[0]

    finally:
        conn.close()

    return render_template(
        "dashboard.html",
        document_count=document_count,
        shared_count=shared_count,
        user_count=user_count
    )


# ---------------- PROFILE ----------------

@app.route("/profile", methods=["GET", "POST"])
def my_profile():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        user = conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()

        if not user:
            session.clear()
            return redirect(url_for("login"))

        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            image = request.files.get("profile_image")

            if not name or not email:
                flash("Name and email are required.")
                return render_template("profile.html", user=user)

            duplicate = conn.execute(
                "SELECT id FROM users WHERE email = ? AND id != ?",
                (email, session["user_id"])
            ).fetchone()

            if duplicate:
                flash("Email is already in use.")
                return render_template("profile.html", user=user)

            image_name = user["profile_image"]

            if image and image.filename:
                filename = secure_filename(image.filename)
                extension = os.path.splitext(filename)[1].lower()

                if extension not in ALLOWED_IMAGE_EXTENSIONS:
                    flash("Choose a PNG, JPG, JPEG or WEBP image.")
                    return render_template("profile.html", user=user)

                image_name = str(uuid.uuid4()) + extension
                image.save(os.path.join(PROFILE_FOLDER, image_name))

            conn.execute(
                """
                UPDATE users
                SET name = ?, email = ?, profile_image = ?
                WHERE id = ?
                """,
                (name, email, image_name, session["user_id"])
            )

            log_activity(conn, "UPDATE_PROFILE", "Profile updated")
            conn.commit()

            session["user_name"] = name
            flash("Profile updated successfully.")
            return redirect(url_for("my_profile"))

        return render_template("profile.html", user=user)

    finally:
        conn.close()


# ---------------- CHANGE PASSWORD ----------------

@app.route("/change-password", methods=["GET", "POST"])
@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if not is_logged_in():
        return redirect(url_for("login"))

    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(new_password) < 8:
            flash("Password must contain at least 8 characters.")
            return render_template("change_password.html")

        if new_password != confirm_password:
            flash("Passwords do not match.")
            return render_template("change_password.html")

        conn = get_db()

        try:
            user = conn.execute(
                "SELECT password FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()

            if not user or not check_password_hash(
                user["password"], current_password
            ):
                flash("Current password is incorrect.")
                return render_template("change_password.html")

            conn.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (
                    generate_password_hash(new_password),
                    session["user_id"]
                )
            )

            log_activity(conn, "CHANGE_PASSWORD", "Password changed")
            conn.commit()

            flash("Password changed successfully.")
            return redirect(url_for("dashboard"))

        finally:
            conn.close()

    return render_template("change_password.html")


# ---------------- UPLOAD DOCUMENT ----------------

@app.route("/upload", methods=["GET", "POST"])
def upload_document():
    if not is_logged_in():
        return redirect(url_for("login"))

    if not can_manage_documents():
        flash("Viewer cannot upload documents.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        file = request.files.get("document")
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "General").strip()
        description = request.form.get("description", "").strip()

        if not title or not file or not file.filename:
            flash("Enter a title and select a file.")
            return redirect(url_for("upload_document"))

        filename = secure_filename(file.filename)

        if not allowed_file(filename):
            flash("Only PDF, DOC, DOCX and TXT files are allowed.")
            return redirect(url_for("upload_document"))

        stored_filename = (
            str(uuid.uuid4()) +
            os.path.splitext(filename)[1].lower()
        )

        file_path = os.path.join(UPLOAD_FOLDER, stored_filename)
        conn = get_db()

        try:
            file.save(file_path)

            conn.execute(
                """
                INSERT INTO documents
                (owner_id, title, filename, stored_filename,
                 category, description)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session["user_id"], title, filename,
                    stored_filename, category or "General", description
                )
            )

            log_activity(conn, "UPLOAD", "Uploaded: " + title)
            conn.commit()
            flash("Document uploaded successfully.")

        except Exception:
            conn.rollback()
            app.logger.exception("Upload failed")

            if os.path.exists(file_path):
                os.remove(file_path)

            flash("Upload failed.")

        finally:
            conn.close()

        return redirect(url_for("my_documents"))

    return render_template("upload.html")


# ---------------- MY DOCUMENTS ----------------

@app.route("/documents")
def my_documents():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        if is_admin():
            documents = conn.execute(
                """
                SELECT d.*, 'Admin' AS access_type,
                       'owner' AS access_permission
                FROM documents d
                ORDER BY d.uploaded_at DESC
                """
            ).fetchall()
        else:
            documents = conn.execute(
                """
                SELECT d.*, 'Owner' AS access_type,
                       'owner' AS access_permission
                FROM documents d
                WHERE d.owner_id = ?

                UNION

                SELECT d.*, 'Shared' AS access_type,
                       s.permission AS access_permission
                FROM documents d
                JOIN shares s ON s.document_id = d.id
                WHERE s.shared_with_user_id = ?

                ORDER BY uploaded_at DESC
                """,
                (session["user_id"], session["user_id"])
            ).fetchall()

    finally:
        conn.close()

    return render_template("documents.html", documents=documents)


# ---------------- DOWNLOAD ----------------

@app.route("/download/<int:document_id>")
def download_document(document_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        document = get_accessible_document(conn, document_id)

        if document:
            log_activity(
                conn, "DOWNLOAD",
                "Downloaded: " + document["title"]
            )
            conn.commit()

    finally:
        conn.close()

    if not document:
        return "Document not found or access denied.", 404

    return send_from_directory(
        UPLOAD_FOLDER,
        document["stored_filename"],
        as_attachment=True,
        download_name=document["filename"]
    )


# ---------------- PREVIEW PDF ----------------

@app.route("/preview/<int:document_id>")
def preview_document(document_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        document = get_accessible_document(conn, document_id)
    finally:
        conn.close()

    if not document:
        return "Document not found or access denied.", 404

    if not document["filename"].lower().endswith(".pdf"):
        return "Preview is available only for PDF files.", 400

    return send_from_directory(
        UPLOAD_FOLDER,
        document["stored_filename"],
        as_attachment=False,
        mimetype="application/pdf"
    )


# ---------------- EDIT DOCUMENT ----------------

@app.route("/edit/<int:document_id>", methods=["GET", "POST"])
@app.route("/document/<int:document_id>/edit", methods=["GET", "POST"])
def edit_document(document_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        document = can_edit_document(conn, document_id)

        if not document:
            return "You do not have edit permission.", 403

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            category = request.form.get("category", "General").strip()
            description = request.form.get("description", "").strip()

            if not title:
                flash("Title is required.")
                return render_template(
                    "edit_document.html", document=document
                )

            conn.execute(
                """
                UPDATE documents
                SET title = ?, category = ?, description = ?
                WHERE id = ?
                """,
                (title, category or "General", description, document_id)
            )

            log_activity(conn, "EDIT_DOCUMENT", "Updated: " + title)
            conn.commit()
            flash("Document updated successfully.")
            return redirect(url_for("my_documents"))

        return render_template("edit_document.html", document=document)

    finally:
        conn.close()


# ---------------- SHARE DOCUMENT ----------------

@app.route("/share/<int:document_id>", methods=["GET", "POST"])
@app.route("/document/<int:document_id>/share", methods=["GET", "POST"])
def share_document(document_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    if not can_manage_documents():
        flash("Viewer accounts cannot share documents.")
        return redirect(url_for("my_documents"))

    conn = get_db()

    try:
        document = can_manage_document(conn, document_id)

        if not document:
            return "Only the owner or admin can share this document.", 403

        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            permission = request.form.get("permission", "view")

            if permission not in ("view", "edit"):
                flash("Invalid permission.")
                return redirect(
                    url_for("share_document", document_id=document_id)
                )

            user = conn.execute(
                "SELECT id, role FROM users WHERE email = ?",
                (email,)
            ).fetchone()

            if not user:
                flash("No registered user found with that email.")

            elif user["id"] == document["owner_id"]:
                flash("The owner already has access.")

            elif user["role"] == "admin":
                flash("Admin already has access.")

            else:
                conn.execute(
                    """
                    INSERT INTO shares
                    (document_id, shared_with_user_id, permission)
                    VALUES (?, ?, ?)
                    ON CONFLICT(document_id, shared_with_user_id)
                    DO UPDATE SET permission = excluded.permission
                    """,
                    (document_id, user["id"], permission)
                )

                log_activity(
                    conn, "SHARE",
                    "Shared document: " + document["title"]
                )
                conn.commit()
                flash("Document shared successfully!")

                return redirect(
                    url_for("share_document", document_id=document_id)
                )

        shared_users = conn.execute(
            """
            SELECT u.id, u.name, u.email, s.permission
            FROM shares s
            JOIN users u ON u.id = s.shared_with_user_id
            WHERE s.document_id = ?
            ORDER BY u.name
            """,
            (document_id,)
        ).fetchall()

        return render_template(
            "share.html",
            document=document,
            shared_users=shared_users
        )

    finally:
        conn.close()


# ---------------- REVOKE SHARING ----------------

@app.route(
    "/revoke-share/<int:document_id>/<int:shared_user_id>",
    methods=["POST"]
)
@app.route(
    "/document/<int:document_id>/revoke/<int:shared_user_id>",
    methods=["POST"]
)
def revoke_share(document_id, shared_user_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        document = can_manage_document(conn, document_id)

        if not document:
            return "Only the owner or admin can revoke access.", 403

        conn.execute(
            """
            DELETE FROM shares
            WHERE document_id = ? AND shared_with_user_id = ?
            """,
            (document_id, shared_user_id)
        )

        log_activity(
            conn, "REVOKE_SHARE",
            "Revoked access to: " + document["title"]
        )
        conn.commit()
        flash("Access revoked successfully.")

        return redirect(
            url_for("share_document", document_id=document_id)
        )

    finally:
        conn.close()


# ---------------- DELETE DOCUMENT ----------------

@app.route("/delete/<int:document_id>", methods=["POST"])
def delete_document(document_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()
    stored_filename = None

    try:
        document = can_manage_document(conn, document_id)

        if not document:
            return "Document not found or access denied.", 403

        stored_filename = document["stored_filename"]

        log_activity(
            conn, "DELETE",
            "Deleted document: " + document["title"]
        )

        conn.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,)
        )
        conn.commit()

    except Exception:
        conn.rollback()
        app.logger.exception("Delete failed")
        flash("Could not delete document.")
        return redirect(url_for("my_documents"))

    finally:
        conn.close()

    path = os.path.join(UPLOAD_FOLDER, os.path.basename(stored_filename))

    if os.path.isfile(path):
        os.remove(path)

    flash("Document deleted successfully.")
    return redirect(url_for("my_documents"))


# ---------------- SEARCH DOCUMENTS ----------------

@app.route("/search")
def search_documents():
    if not is_logged_in():
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    pattern = "%" + query + "%"

    sql = """
        SELECT DISTINCT d.*, u.name AS owner_name
        FROM documents d
        JOIN users u ON u.id = d.owner_id
        WHERE (
            d.title LIKE ?
            OR d.filename LIKE ?
            OR d.category LIKE ?
            OR u.name LIKE ?
            OR u.email LIKE ?
        )
    """

    params = [pattern, pattern, pattern, pattern, pattern]

    if date_from and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_from):
        sql += " AND date(d.uploaded_at) >= date(?)"
        params.append(date_from)

    if date_to and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to):
        sql += " AND date(d.uploaded_at) <= date(?)"
        params.append(date_to)

    if not is_admin():
        sql += """
            AND (
                d.owner_id = ?
                OR EXISTS (
                    SELECT 1 FROM shares s
                    WHERE s.document_id = d.id
                    AND s.shared_with_user_id = ?
                )
            )
        """
        params.extend([session["user_id"], session["user_id"]])

    sql += " ORDER BY d.uploaded_at DESC"

    conn = get_db()

    try:
        documents = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return render_template(
        "search.html",
        documents=documents,
        query=query,
        date_from=date_from,
        date_to=date_to
    )


# ---------------- CATEGORIES ----------------

@app.route("/categories")
def categories():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        if is_admin():
            category_list = conn.execute(
                """
                SELECT category, COUNT(*) AS total
                FROM documents
                GROUP BY category
                ORDER BY category
                """
            ).fetchall()
        else:
            category_list = conn.execute(
                """
                SELECT d.category, COUNT(DISTINCT d.id) AS total
                FROM documents d
                LEFT JOIN shares s ON s.document_id = d.id
                WHERE d.owner_id = ? OR s.shared_with_user_id = ?
                GROUP BY d.category
                ORDER BY d.category
                """,
                (session["user_id"], session["user_id"])
            ).fetchall()

    finally:
        conn.close()

    return render_template("categories.html", categories=category_list)


# ---------------- ADMIN: USERS ----------------

@app.route("/users")
@app.route("/admin/users")
def admin_users():
    if not is_logged_in():
        return redirect(url_for("login"))

    if not is_admin():
        return "Access denied: Admin only.", 403

    conn = get_db()

    try:
        users = conn.execute(
            """
            SELECT id, name, email, role, created_at
            FROM users
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()

    return render_template("users.html", users=users)


# ---------------- ADMIN: UPDATE USER ROLE ----------------

@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
def update_user_role(user_id):
    if not is_logged_in():
        return redirect(url_for("login"))

    if not is_admin():
        return "Access denied: Admin only.", 403

    role = request.form.get("role", "").strip().lower()

    if role not in ("admin", "owner", "viewer"):
        flash("Invalid role.")
        return redirect(url_for("admin_users"))

    if user_id == session["user_id"] and role != "admin":
        flash("You cannot remove your own admin role.")
        return redirect(url_for("admin_users"))

    conn = get_db()

    try:
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (role, user_id)
        )
        conn.commit()
        flash("User role updated successfully.")
    finally:
        conn.close()

    return redirect(url_for("admin_users"))


# ---------------- ACTIVITY LOGS ----------------

@app.route("/activity-logs")
@app.route("/activity_logs")
def activity_logs():
    if not is_logged_in():
        return redirect(url_for("login"))

    conn = get_db()

    try:
        if is_admin():
            logs = conn.execute(
                """
                SELECT activity_logs.*, users.name AS user_name
                FROM activity_logs
                LEFT JOIN users ON users.id = activity_logs.user_id
                ORDER BY activity_logs.created_at DESC
                """
            ).fetchall()
        else:
            logs = conn.execute(
                """
                SELECT activity_logs.*, users.name AS user_name
                FROM activity_logs
                LEFT JOIN users ON users.id = activity_logs.user_id
                WHERE activity_logs.user_id = ?
                ORDER BY activity_logs.created_at DESC
                """,
                (session["user_id"],)
            ).fetchall()

    finally:
        conn.close()

    return render_template("activity_logs.html", logs=logs)


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    if is_logged_in():
        conn = get_db()

        try:
            log_activity(conn, "LOGOUT", "User logged out")
            conn.commit()
        finally:
            conn.close()

    session.clear()
    flash("You have logged out.")
    return redirect(url_for("login"))


# ---------------- HEALTH CHECK ----------------

@app.route("/health")
def health():
    return {"status": "ok", "application": "TrustVault"}


# ---------------- START APPLICATION ----------------

if __name__ == "__main__":
    init_db()
    app.run(debug=True)