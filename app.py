import os, sqlite3, uuid, json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, abort, make_response
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from io import BytesIO

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    psycopg = None
    dict_row = None

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "proposals.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "doc", "docx", "xls", "xlsx", "txt"}

class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class PgCursor:
    def __init__(self, cursor): self.cursor = cursor
    def fetchone(self):
        row = self.cursor.fetchone()
        return HybridRow(row) if row is not None else None
    def fetchall(self): return [HybridRow(row) for row in self.cursor.fetchall()]

class PgConnection:
    def __init__(self, conn): self.conn = conn
    def execute(self, sql, params=()):
        return PgCursor(self.conn.execute(sql.replace("?", "%s"), params))
    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip(): self.conn.execute(statement)
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        if exc_type: self.conn.rollback()
        else: self.conn.commit()
        self.conn.close()

def db():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        if psycopg is None:
            raise RuntimeError("PostgreSQL driver missing. Install requirements.txt")
        database_url = database_url.replace("postgres://", "postgresql://", 1)
        return PgConnection(psycopg.connect(database_url, row_factory=dict_row))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


DEFAULT_SERVICE_ITEMS = [
    {"name": "Refund of accumulated ITC (new)", "amount": 7000.0},
    {"name": "Company audit", "amount": 10000.0},
    {"name": "GST returns (Apr 2025 – Mar 2026)", "amount": 12000.0},
    {"name": "Professional charges – accounting support", "amount": 8000.0},
    {"name": "Income tax return", "amount": 5000.0},
    {"name": "DIR-3 KYC", "amount": 1500.0},
    {"name": "ROC compliance", "amount": 5000.0},
]

def parse_service_items(raw):
    try:
        items = json.loads(raw or "[]")
        if isinstance(items, list):
            return [
                {"name": str(item.get("name", "")).strip()[:160],
                 "amount": max(0.0, float(item.get("amount", 0) or 0))}
                for item in items
                if isinstance(item, dict) and str(item.get("name", "")).strip()
            ]
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return []

def proposal_service_items(proposal):
    items = parse_service_items(proposal["service_items"] if "service_items" in proposal.keys() else "[]")
    return items or DEFAULT_SERVICE_ITEMS.copy()

def init_db():
    if os.environ.get("DATABASE_URL"):
        with db() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, company TEXT, email TEXT, phone TEXT,
                address TEXT, notes TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id BIGSERIAL PRIMARY KEY, client_id BIGINT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                title TEXT NOT NULL, description TEXT, services TEXT, service_items TEXT DEFAULT '[]', amount DOUBLE PRECISION DEFAULT 0,
                currency TEXT DEFAULT 'INR', status TEXT DEFAULT 'Draft', valid_until TEXT, terms TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id BIGSERIAL PRIMARY KEY, proposal_id BIGINT NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
                original_name TEXT NOT NULL, stored_name TEXT NOT NULL, uploaded_at TEXT NOT NULL
            );
            """)
    else:
        with db() as con:
            con.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, company TEXT, email TEXT, phone TEXT,
                address TEXT, notes TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                title TEXT NOT NULL, description TEXT, services TEXT,
                amount REAL DEFAULT 0, currency TEXT DEFAULT 'INR', status TEXT DEFAULT 'Draft',
                valid_until TEXT, terms TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
                original_name TEXT NOT NULL, stored_name TEXT NOT NULL, uploaded_at TEXT NOT NULL
            );
            """)


    # Backward-compatible migration for databases created by earlier versions.
    if os.environ.get("DATABASE_URL"):
        with db() as con:
            con.execute("ALTER TABLE proposals ADD COLUMN IF NOT EXISTS service_items TEXT DEFAULT '[]'")
    else:
        with db() as con:
            columns = [row["name"] for row in con.execute("PRAGMA table_info(proposals)").fetchall()]
            if "service_items" not in columns:
                con.execute("ALTER TABLE proposals ADD COLUMN service_items TEXT DEFAULT '[]'")

init_db()

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def get_proposal(pid):
    with db() as con:
        p = con.execute("""SELECT p.*, c.name AS client_name, c.company, c.email AS client_email
                           FROM proposals p JOIN clients c ON c.id=p.client_id WHERE p.id=?""", (pid,)).fetchone()
        if not p: abort(404)
        files = con.execute("SELECT * FROM attachments WHERE proposal_id=? ORDER BY id DESC", (pid,)).fetchall()
    return p, files

@app.route("/")
def dashboard():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "").strip()
    with db() as con:
        stats = {
            "clients": con.execute("SELECT COUNT(*) FROM clients").fetchone()[0],
            "proposals": con.execute("SELECT COUNT(*) FROM proposals").fetchone()[0],
            "accepted": con.execute("SELECT COUNT(*) FROM proposals WHERE status='Accepted'").fetchone()[0],
            "pending": con.execute("SELECT COUNT(*) FROM proposals WHERE status IN ('Sent','Draft')").fetchone()[0],
        }
        sql = """SELECT p.*, c.name AS client_name, c.company FROM proposals p
                 JOIN clients c ON c.id=p.client_id WHERE 1=1"""
        args = []
        if q:
            sql += " AND (p.title LIKE ? OR c.name LIKE ? OR c.company LIKE ?)"
            args += [f"%{q}%"]*3
        if status:
            sql += " AND p.status=?"; args.append(status)
        sql += " ORDER BY p.updated_at DESC LIMIT 100"
        proposals = con.execute(sql, args).fetchall()
        clients = con.execute("SELECT * FROM clients ORDER BY created_at DESC LIMIT 6").fetchall()
    return render_template("dashboard.html", stats=stats, proposals=proposals, clients=clients, q=q, status=status)

@app.route("/clients")
def clients():
    q = request.args.get("q", "").strip()
    with db() as con:
        rows = con.execute("""SELECT c.*, COUNT(p.id) AS proposal_count FROM clients c
            LEFT JOIN proposals p ON p.client_id=c.id
            WHERE c.name LIKE ? OR COALESCE(c.company,'') LIKE ? OR COALESCE(c.email,'') LIKE ?
            GROUP BY c.id ORDER BY c.created_at DESC""", (f"%{q}%",)*3).fetchall()
    return render_template("clients.html", clients=rows, q=q)

@app.route("/clients/new", methods=["GET","POST"])
@app.route("/clients/<int:cid>/edit", methods=["GET","POST"])
def client_form(cid=None):
    client = None
    if cid:
        with db() as con: client = con.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()
        if not client: abort(404)
    if request.method == "POST":
        data = [request.form.get(k,"").strip() for k in ("name","company","email","phone","address","notes")]
        if not data[0]:
            flash("Client name is required.", "error")
        else:
            with db() as con:
                if cid:
                    con.execute("""UPDATE clients SET name=?,company=?,email=?,phone=?,address=?,notes=? WHERE id=?""", (*data,cid))
                else:
                    con.execute("""INSERT INTO clients(name,company,email,phone,address,notes,created_at) VALUES(?,?,?,?,?,?,?)""", (*data,now()))
            flash("Client saved successfully.", "success")
            return redirect(url_for("clients"))
    return render_template("client_form.html", client=client)

@app.post("/clients/<int:cid>/delete")
def client_delete(cid):
    with db() as con: con.execute("DELETE FROM clients WHERE id=?", (cid,))
    flash("Client and associated proposals deleted.", "success")
    return redirect(url_for("clients"))

@app.route("/proposals/new", methods=["GET","POST"])
@app.route("/proposals/<int:pid>/edit", methods=["GET","POST"])
def proposal_form(pid=None):
    proposal = None
    if pid:
        with db() as con:
            proposal = con.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
        if not proposal: abort(404)
    with db() as con:
        clients_list = con.execute("SELECT id,name,company FROM clients ORDER BY name").fetchall()

    if request.method == "POST":
        client_id = request.form.get("client_id", type=int)
        title = request.form.get("title","").strip()
        if not client_id or not title:
            flash("Choose a client and enter a proposal title.", "error")
        else:
            names = request.form.getlist("service_name[]")
            amounts = request.form.getlist("service_amount[]")
            service_items = []
            for name, raw_amount in zip(names, amounts):
                name = name.strip()
                if not name:
                    continue
                try:
                    amount = max(0.0, float(raw_amount or 0))
                except ValueError:
                    amount = 0.0
                service_items.append({"name": name[:160], "amount": amount})
            service_total = round(sum(item["amount"] for item in service_items), 2)
            fields = (client_id, title, request.form.get("description","").strip(),
                      request.form.get("services","").strip(), json.dumps(service_items, ensure_ascii=False),
                      service_total, request.form.get("currency","INR"), request.form.get("status","Draft"),
                      request.form.get("valid_until",""), request.form.get("terms","").strip())
            if pid:
                with db() as con:
                    con.execute("""UPDATE proposals SET client_id=?,title=?,description=?,services=?,service_items=?,amount=?,currency=?,
                    status=?,valid_until=?,terms=?,updated_at=? WHERE id=?""", (*fields,now(),pid))
                flash("Proposal updated with individual service fees.", "success")
                return redirect(url_for("proposal_detail", pid=pid))
            else:
                with db() as con:
                    cur = con.execute("""INSERT INTO proposals(client_id,title,description,services,service_items,amount,currency,status,
                    valid_until,terms,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""", (*fields,now(),now()))
                    new_id = cur.fetchone()["id"]
                flash("Proposal created with individual service fees.", "success")
                return redirect(url_for("proposal_detail", pid=new_id))

    service_items = proposal_service_items(proposal) if proposal else DEFAULT_SERVICE_ITEMS.copy()
    return render_template("proposal_form.html", proposal=proposal, clients=clients_list,
                           service_items=service_items)

@app.route("/proposals/<int:pid>")
def proposal_detail(pid):
    proposal, files = get_proposal(pid)
    service_items = proposal_service_items(proposal)
    return render_template("proposal_detail.html", proposal=proposal, files=files,
                           service_items=service_items)

@app.post("/proposals/<int:pid>/delete")
def proposal_delete(pid):
    with db() as con:
        rows = con.execute("SELECT stored_name FROM attachments WHERE proposal_id=?", (pid,)).fetchall()
        con.execute("DELETE FROM proposals WHERE id=?", (pid,))
    for row in rows:
        path = os.path.join(UPLOAD_DIR, row["stored_name"])
        if os.path.exists(path): os.remove(path)
    flash("Proposal deleted.", "success")
    return redirect(url_for("dashboard"))

@app.post("/proposals/<int:pid>/duplicate")
def proposal_duplicate(pid):
    p, _ = get_proposal(pid)
    with db() as con:
        cur = con.execute("""INSERT INTO proposals(client_id,title,description,services,service_items,amount,currency,status,valid_until,
            terms,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (p["client_id"], p["title"]+" (Copy)", p["description"], p["services"], p["service_items"], p["amount"], p["currency"],
             "Draft", p["valid_until"], p["terms"], now(), now()))
        new_id = cur.fetchone()["id"]
    flash("Proposal duplicated as a new draft.", "success")
    return redirect(url_for("proposal_detail", pid=new_id))

@app.post("/proposals/<int:pid>/upload")
def upload(pid):
    get_proposal(pid)
    f = request.files.get("file")
    if not f or not f.filename:
        flash("Choose a file first.", "error")
    elif "." not in f.filename or f.filename.rsplit(".",1)[1].lower() not in ALLOWED_EXTENSIONS:
        flash("That file type is not allowed.", "error")
    else:
        original = secure_filename(f.filename)
        stored = uuid.uuid4().hex + "_" + original
        f.save(os.path.join(UPLOAD_DIR, stored))
        with db() as con:
            con.execute("INSERT INTO attachments(proposal_id,original_name,stored_name,uploaded_at) VALUES(?,?,?,?)",
                        (pid, original, stored, now()))
        flash("Attachment uploaded.", "success")
    return redirect(url_for("proposal_detail", pid=pid))

@app.route("/uploads/<path:filename>")
def download_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)

@app.post("/attachments/<int:aid>/delete")
def attachment_delete(aid):
    with db() as con:
        row = con.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if not row: abort(404)
        con.execute("DELETE FROM attachments WHERE id=?", (aid,))
    path = os.path.join(UPLOAD_DIR, row["stored_name"])
    if os.path.exists(path): os.remove(path)
    flash("Attachment deleted.", "success")
    return redirect(url_for("proposal_detail", pid=row["proposal_id"]))

@app.route("/proposals/<int:pid>/pdf")
def proposal_pdf(pid):
    p, _ = get_proposal(pid)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()
    story = [Paragraph("PROPOSAL", styles["Title"]), Spacer(1, 16)]
    story += [Paragraph(f"<b>{p['title']}</b>", styles["Heading1"]),
              Paragraph(f"Prepared for: {p['client_name']}"+(f" — {p['company']}" if p["company"] else ""), styles["Normal"]),
              Paragraph(f"Date: {p['created_at']} &nbsp;&nbsp; Status: {p['status']}", styles["Normal"]), Spacer(1, 14)]
    if p["description"]: story += [Paragraph("Overview", styles["Heading2"]), Paragraph(p["description"].replace("\n","<br/>"), styles["BodyText"]), Spacer(1, 10)]
    if p["services"]: story += [Paragraph("Services / Deliverables", styles["Heading2"]), Paragraph(p["services"].replace("\n","<br/>"), styles["BodyText"]), Spacer(1, 10)]
    service_items = proposal_service_items(p)
    data = [["Service", "Fee"]]
    for item in service_items:
        data.append([item["name"], f"{p['currency']} {item['amount']:,.2f}"])
    subtotal = sum(item["amount"] for item in service_items)
    igst = subtotal * 0.18
    data += [["Subtotal", f"{p['currency']} {subtotal:,.2f}"],
             ["IGST (18%)", f"{p['currency']} {igst:,.2f}"],
             ["Total payable", f"{p['currency']} {subtotal + igst:,.2f}"]]
    if p["valid_until"]: data.append(["Valid until", p["valid_until"]])
    t = Table(data, colWidths=[130, 320])
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.whitesmoke),("GRID",(0,0),(-1,-1),.4,colors.lightgrey),
                           ("PADDING",(0,0),(-1,-1),9),("FONTNAME",(0,0),(0,-1),"Helvetica-Bold")]))
    story += [t, Spacer(1, 14)]
    if p["terms"]: story += [Paragraph("Terms & Conditions", styles["Heading2"]), Paragraph(p["terms"].replace("\n","<br/>"), styles["BodyText"])]
    doc.build(story)
    response = make_response(buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'attachment; filename="proposal-{pid}.pdf"'
    return response

@app.errorhandler(413)
def too_large(e):
    flash("File is too large. Maximum upload size is 16 MB.", "error")
    return redirect(request.referrer or url_for("dashboard"))

if __name__ == "__main__":
    app.run(debug=True)
