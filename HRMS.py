import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
import sqlite3
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

# ====================== CONFIG ======================
st.set_page_config(page_title="Kaunda HRMS", layout="wide", page_icon="🧑‍💼")
st.title("🧑‍💼 Kaunda HR Management System")

# ====================== DATABASE SETUP ======================
conn = sqlite3.connect("hr_system.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            employee_id TEXT UNIQUE,
            position TEXT,
            department TEXT,
            email TEXT,
            phone TEXT,
            national_id TEXT,
            hire_date DATE,
            contract_start DATE,
            contract_end DATE,
            actual_end_date DATE,
            separation_type TEXT,
            contract_type TEXT DEFAULT 'Fixed-Term',
            status TEXT DEFAULT 'active',
            emergency_contact_name TEXT,
            emergency_contact_phone TEXT,
            address TEXT,
            notes TEXT,
            created_at DATE DEFAULT (date('now'))
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payroll_settings (
            employee_id INTEGER PRIMARY KEY,
            basic_salary REAL DEFAULT 0.0,
            housing_allowance REAL DEFAULT 0.0,
            transport_allowance REAL DEFAULT 0.0,
            other_allowance REAL DEFAULT 0.0,
            tax_rate REAL DEFAULT 0.0,
            pension_rate REAL DEFAULT 0.0,
            other_deduction REAL DEFAULT 0.0,
            currency TEXT DEFAULT 'ZMW',
            updated_at DATE,
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payroll_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period_year INTEGER,
            period_month INTEGER,
            run_date DATE,
            status TEXT DEFAULT 'draft',
            notes TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payroll_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            employee_id INTEGER,
            basic_salary REAL,
            allowances REAL,
            gross_pay REAL,
            tax REAL,
            pension REAL,
            other_deduction REAL,
            net_pay REAL,
            payment_date DATE,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(run_id) REFERENCES payroll_runs(id),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    ''')

    # ---- Leave Tracker ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leave_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            leave_type TEXT,
            start_date DATE,
            end_date DATE,
            days_taken INTEGER,
            approval_status TEXT DEFAULT 'Pending',
            notes TEXT,
            created_at DATE DEFAULT (date('now')),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    ''')

    # ---- Disciplinary Tracker ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS disciplinary_tracker (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER,
            issue_date DATE,
            issue_type TEXT,
            description TEXT,
            action_taken TEXT,
            expiry_date DATE,
            status TEXT DEFAULT 'ACTIVE',
            created_at DATE DEFAULT (date('now')),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        )
    ''')

    # ---- System Settings ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # ---- Notification Log ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at DATETIME DEFAULT (datetime('now')),
            subject TEXT,
            recipient TEXT,
            body TEXT,
            status TEXT DEFAULT 'sent'
        )
    ''')

    # ---- Alert Rules ----
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alert_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_name TEXT,
            rule_type TEXT,
            threshold_days INTEGER DEFAULT 30,
            enabled INTEGER DEFAULT 1,
            created_at DATE DEFAULT (date('now'))
        )
    ''')

    cursor.execute("SELECT COUNT(*) FROM alert_rules")
    if cursor.fetchone()[0] == 0:
        default_rules = [
            ("Contract Expiry Warning", "contract_expiry", 30, 1),
            ("Probation Period End", "probation_end", 14, 1),
            ("Payroll Processed Notification", "payroll_processed", 0, 1),
            ("New Employee Added", "new_employee", 0, 1),
        ]
        cursor.executemany(
            "INSERT INTO alert_rules (rule_name, rule_type, threshold_days, enabled) VALUES (?,?,?,?)",
            default_rules
        )

    # Migration: add missing columns to employees table
    existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(employees)").fetchall()]
    new_cols = {
        "employee_id": "TEXT",
        "national_id": "TEXT",
        "contract_start": "DATE",
        "contract_end": "DATE",
        "actual_end_date": "DATE",
        "separation_type": "TEXT",
        "contract_type": "TEXT DEFAULT 'Fixed-Term'",
        "emergency_contact_name": "TEXT",
        "emergency_contact_phone": "TEXT",
        "address": "TEXT",
        "notes": "TEXT",
        "created_at": "DATE DEFAULT (date('now'))"
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE employees ADD COLUMN {col} {col_type}")

    conn.commit()

init_db()

# ====================== SETTINGS HELPERS ======================
def get_setting(key, default=""):
    try:
        cursor.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default
    except:
        return default

def save_setting(key, value):
    cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()

# ====================== LOGIN ======================
def init_login_session():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
    if "user_role" not in st.session_state:
        st.session_state.user_role = None
    if "username" not in st.session_state:
        st.session_state.username = None

def show_login_page():
    st.markdown("""
    <style>
    .login-container {
        background: linear-gradient(135deg, #E8F5E8 0%, #C8E6C9 100%);
        padding: 40px; border-radius: 15px;
        box-shadow: 0 8px 32px rgba(46,139,87,0.3);
        border: 1px solid #A5D6A7; margin: 20px 0;
    }
    .stButton > button {
        background: linear-gradient(135deg, #4CAF50 0%, #388E3C 100%);
        color: white; border: none; border-radius: 8px;
        padding: 12px 24px; font-size: 16px; font-weight: bold;
        width: 100%;
    }
    </style>""", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown('<div class="login-container">', unsafe_allow_html=True)
        st.markdown('<h2 style="color:#2E7D32;text-align:center">🔐 Admin Login</h2>', unsafe_allow_html=True)
        admin_user = get_setting("admin_username", "admin")
        admin_pass = get_setting("admin_password", "admin123")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                if username == admin_user and password == admin_pass:
                    st.session_state.logged_in = True
                    st.session_state.user_role = "admin"
                    st.session_state.username = username
                    st.success("✅ Login successful!")
                    st.rerun()
                else:
                    st.error("❌ Invalid credentials.")
        st.markdown('</div>', unsafe_allow_html=True)

# ====================== EMAIL ======================
def send_email(subject, body, recipient=None, html_body=None):
    smtp_host   = get_setting("smtp_host", "")
    smtp_port   = get_setting("smtp_port", "587")
    smtp_user   = get_setting("smtp_user", "")
    smtp_pass   = get_setting("smtp_password", "")
    from_name   = get_setting("company_name", "Kaunda HRMS")
    admin_email = get_setting("admin_email", "")
    to_email    = recipient or admin_email
    if not all([smtp_host, smtp_user, smtp_pass, to_email]):
        return False, "Email settings not fully configured."
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{from_name} <{smtp_user}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(body, "plain"))
        if html_body:
            msg.attach(MIMEText(html_body, "html"))
        context = ssl.create_default_context()
        port = int(smtp_port)
        if port == 465:
            with smtplib.SMTP_SSL(smtp_host, port, context=context) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, port) as server:
                server.ehlo(); server.starttls(context=context)
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())
        cursor.execute("INSERT INTO notification_log (subject, recipient, body, status) VALUES (?,?,?,?)",
                       (subject, to_email, body, "sent"))
        conn.commit()
        return True, "Email sent successfully!"
    except Exception as e:
        cursor.execute("INSERT INTO notification_log (subject, recipient, body, status) VALUES (?,?,?,?)",
                       (subject, to_email, body, f"failed: {e}"))
        conn.commit()
        return False, f"Email error: {e}"

def build_html_email(title, content_rows, footer=""):
    company = get_setting("company_name", "Kaunda HRMS")
    rows_html = "".join(
        f"<tr><td style='padding:6px 12px;border-bottom:1px solid #eee;font-weight:bold;width:40%;color:#555'>{k}</td>"
        f"<td style='padding:6px 12px;border-bottom:1px solid #eee;color:#222'>{v}</td></tr>"
        for k, v in content_rows
    )
    return f"""
    <html><body style='font-family:Arial,sans-serif;background:#f4f6f8;margin:0;padding:20px'>
    <div style='max-width:600px;margin:auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1)'>
      <div style='background:#2E7D32;padding:20px 30px;color:white'>
        <h2 style='margin:0'>🧑‍💼 {company}</h2>
        <p style='margin:4px 0 0;font-size:14px;opacity:.9'>{title}</p>
      </div>
      <div style='padding:24px 30px'>
        <table style='width:100%;border-collapse:collapse'>{rows_html}</table>
        {f'<p style="margin-top:20px;color:#777;font-size:13px">{footer}</p>' if footer else ''}
      </div>
      <div style='background:#f0f0f0;padding:12px 30px;font-size:12px;color:#999;text-align:center'>
        Sent by {company} HRMS &bull; {datetime.now().strftime('%d %b %Y %H:%M')}
      </div>
    </div></body></html>"""

# ====================== EXCEL EXPORT ======================
def export_to_excel(dataframes_dict, filename):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dataframes_dict.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            for cell in worksheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
                cell.alignment = Alignment(horizontal="center", vertical="center")
            for column in worksheet.columns:
                max_length = max((len(str(cell.value or "")) for cell in column), default=0)
                worksheet.column_dimensions[column[0].column_letter].width = min(max_length + 2, 50)
    output.seek(0)
    return output

init_login_session()
if not st.session_state.logged_in:
    show_login_page()
    st.stop()

# ====================== HELPERS ======================
def get_employees():
    try:
        return pd.read_sql("SELECT * FROM employees ORDER BY name", conn)
    except:
        return pd.DataFrame()

def get_today():
    return datetime.now().date()

def get_current_period():
    now = datetime.now()
    return now.year, now.month

def calculate_pay(emp_id, basic, housing, transport, other_all, tax_rate, pension_rate, other_ded):
    allowances = housing + transport + other_all
    gross = basic + allowances
    tax = gross * tax_rate
    pension = gross * pension_rate
    net = gross - (tax + pension + other_ded)
    return {"basic_salary": basic, "allowances": allowances, "gross_pay": gross,
            "tax": tax, "pension": pension, "other_deduction": other_ded, "net_pay": net}

def generate_employee_id(department):
    dept_code = department[:3].upper() if department else "EMP"
    cursor.execute("SELECT COUNT(*) FROM employees")
    count = cursor.fetchone()[0] + 1
    return f"EMP-{dept_code}-{count:03d}"

def contract_status(contract_end, actual_end_date, threshold=30):
    today = get_today()
    if actual_end_date:
        return "LEFT"
    if not contract_end:
        return "UNKNOWN"
    try:
        end = datetime.strptime(str(contract_end)[:10], "%Y-%m-%d").date()
        days_remaining = (end - today).days
        if days_remaining < 0:
            return "EXPIRED"
        elif days_remaining <= threshold:
            return "EXPIRING SOON"
        else:
            return "ACTIVE"
    except:
        return "UNKNOWN"

def disciplinary_status(expiry_date):
    today = get_today()
    if not expiry_date:
        return "NO EXPIRY"
    try:
        exp = datetime.strptime(str(expiry_date)[:10], "%Y-%m-%d").date()
        days = (exp - today).days
        if days < 0:
            return "EXPIRED"
        elif days <= 7:
            return "EXPIRING SOON"
        else:
            return "ACTIVE"
    except:
        return "UNKNOWN"

DEPARTMENTS = ["Human Resources","Finance","Information Technology","Operations",
               "Sales & Marketing","Administration","Legal","Procurement",
               "Customer Service","Engineering","Mechanical","Electrical",
               "General Services","Stores","Logistics","Management","Other"]
CONTRACT_TYPES = ["Permanent","Fixed-Term","Contract","Part-Time","Internship","Probation"]
STATUS_OPTIONS = ["active","inactive","suspended","terminated","on_leave"]
LEAVE_TYPES = ["Annual Leave","Sick Leave","Maternity Leave","Paternity Leave",
               "Compassionate Leave","Study Leave","Unpaid Leave","Other"]
APPROVAL_STATUS = ["Pending","Approved","Rejected","Cancelled"]
ISSUE_TYPES = ["Verbal Warning","Written Warning","First Warning","Final Warning",
               "Suspension","Misconduct","Insubordination","Absenteeism","Other"]
SEPARATION_TYPES = ["Resigned","Terminated","Contract Ended","Retired","Deceased","Other"]

# ====================== SIDEBAR ======================
st.sidebar.markdown(f"**Logged in as:** {st.session_state.username.upper()}")
if st.sidebar.button("🚪 Logout", use_container_width=True):
    for k in ["logged_in","user_role","username"]:
        st.session_state[k] = None if k != "logged_in" else False
    st.rerun()

st.sidebar.divider()

menu = st.sidebar.radio("📋 Menu", [
    "📊 Dashboard",
    "👤 Employee Database",
    "📄 Contract Alerts",
    "🏖️ Leave Tracker",
    "⚖️ Disciplinary Tracker",
    "💰 Payroll",
    "🚨 Alerts Dashboard",
    "📧 Notifications",
    "📊 Reports",
    "⚙️ Settings",
])


# ============================================================
# ========================= DASHBOARD ========================
# ============================================================
if menu == "📊 Dashboard":
    st.header("📊 HR Dashboard")
    today = get_today()
    employees = get_employees()

    # ---- Top KPI Cards ----
    total_emp  = len(employees) if not employees.empty else 0
    active_emp = len(employees[employees["status"] == "active"]) if not employees.empty else 0
    left_emp   = len(employees[employees["actual_end_date"].notna()]) if not employees.empty and "actual_end_date" in employees.columns else 0

    # Contract alerts counts
    expiring_soon_count = 0
    expired_count       = 0
    if not employees.empty and "contract_end" in employees.columns:
        for _, emp in employees.iterrows():
            cs = contract_status(emp.get("contract_end"), emp.get("actual_end_date"))
            if cs == "EXPIRING SOON":
                expiring_soon_count += 1
            elif cs == "EXPIRED":
                expired_count += 1

    # Disciplinary counts
    try:
        disc_df = pd.read_sql("SELECT * FROM disciplinary_tracker", conn)
        active_disc   = 0
        expiring_disc = 0
        for _, d in disc_df.iterrows():
            ds = disciplinary_status(d.get("expiry_date"))
            if ds == "ACTIVE":
                active_disc += 1
            elif ds == "EXPIRING SOON":
                expiring_disc += 1
    except:
        active_disc = expiring_disc = 0

    # Leave counts
    try:
        leave_df      = pd.read_sql("SELECT * FROM leave_tracker", conn)
        pending_leave = len(leave_df[leave_df["approval_status"] == "Pending"]) if not leave_df.empty else 0
        on_leave_now  = 0
        if not leave_df.empty:
            for _, lv in leave_df.iterrows():
                try:
                    s = datetime.strptime(str(lv["start_date"])[:10], "%Y-%m-%d").date()
                    e = datetime.strptime(str(lv["end_date"])[:10], "%Y-%m-%d").date()
                    if s <= today <= e and lv["approval_status"] == "Approved":
                        on_leave_now += 1
                except:
                    pass
    except:
        pending_leave = on_leave_now = 0

    # ---- ROW 1: Workforce Overview ----
    st.subheader("👥 Workforce Overview")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Employees", total_emp)
    c2.metric("Active", active_emp)
    c3.metric("Exited / Left", left_emp)
    c4.metric("On Leave Today", on_leave_now)
    c5.metric("Departments", employees["department"].nunique() if not employees.empty else 0)

    st.divider()

    # ---- ROW 2: Pending Issues ----
    st.subheader("🚨 Pending Issues")
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("⏳ Expiring Contracts (30 days)", expiring_soon_count,
              delta="Action needed" if expiring_soon_count > 0 else None,
              delta_color="inverse")
    p2.metric("❌ Expired Contracts", expired_count,
              delta="Urgent" if expired_count > 0 else None,
              delta_color="inverse")
    p3.metric("⚖️ Active Disciplinary Cases", active_disc)
    p4.metric("⚠️ Expiring Disciplinary Cases", expiring_disc,
              delta="Review soon" if expiring_disc > 0 else None,
              delta_color="inverse")
    p5.metric("📋 Leave Requests Pending", pending_leave,
              delta="Awaiting approval" if pending_leave > 0 else None,
              delta_color="inverse")

    st.divider()

    # ---- ROW 3: Department & Contract breakdown ----
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("🏢 Employees by Department")
        if not employees.empty:
            dept_summary = employees.groupby("department").agg(
                Total=("id","count"),
                Active=("status", lambda x: (x=="active").sum())
            ).reset_index().sort_values("Total", ascending=False)
            st.dataframe(dept_summary, use_container_width=True, hide_index=True)
        else:
            st.info("No data yet.")

    with col_right:
        st.subheader("📄 Contract Status Summary")
        if not employees.empty and "contract_end" in employees.columns:
            statuses = []
            for _, emp in employees.iterrows():
                statuses.append(contract_status(emp.get("contract_end"), emp.get("actual_end_date")))
            status_counts = pd.Series(statuses).value_counts().reset_index()
            status_counts.columns = ["Status","Count"]
            st.dataframe(status_counts, use_container_width=True, hide_index=True)
        else:
            st.info("No contract data yet.")

    st.divider()

    # ---- ROW 4: Contracts Expiring Soon list ----
    st.subheader("📋 Contracts Expiring in Next 30 Days")
    if not employees.empty and "contract_end" in employees.columns:
        expiring_list = []
        for _, emp in employees.iterrows():
            cs = contract_status(emp.get("contract_end"), emp.get("actual_end_date"))
            if cs == "EXPIRING SOON":
                try:
                    end_date = datetime.strptime(str(emp["contract_end"])[:10], "%Y-%m-%d").date()
                    days_left = (end_date - today).days
                    expiring_list.append({
                        "Employee ID": emp.get("employee_id","—"),
                        "Name": emp["name"],
                        "Position": emp.get("position","—"),
                        "Department": emp.get("department","—"),
                        "Contract End": str(emp["contract_end"])[:10],
                        "Days Remaining": days_left
                    })
                except:
                    pass
        if expiring_list:
            st.warning(f"⚠️ {len(expiring_list)} contract(s) expiring soon!")
            st.dataframe(pd.DataFrame(expiring_list).sort_values("Days Remaining"),
                         use_container_width=True, hide_index=True)
        else:
            st.success("✅ No contracts expiring in the next 30 days.")
    else:
        st.info("Add contract end dates to employees to see alerts here.")

    st.divider()

    # ---- ROW 5: Recent Leave Requests ----
    st.subheader("🏖️ Recent Leave Requests")
    try:
        recent_leave = pd.read_sql("""
            SELECT e.employee_id, e.name, l.leave_type, l.start_date, l.end_date,
                   l.days_taken, l.approval_status
            FROM leave_tracker l
            JOIN employees e ON l.employee_id = e.id
            ORDER BY l.created_at DESC LIMIT 10
        """, conn)
        if not recent_leave.empty:
            st.dataframe(recent_leave, use_container_width=True, hide_index=True)
        else:
            st.info("No leave requests recorded yet.")
    except:
        st.info("No leave data available.")

    st.divider()

    # ---- ROW 6: Recent Disciplinary Cases ----
    st.subheader("⚖️ Recent Disciplinary Cases")
    try:
        recent_disc = pd.read_sql("""
            SELECT e.employee_id, e.name, d.issue_date, d.issue_type,
                   d.action_taken, d.expiry_date, d.status
            FROM disciplinary_tracker d
            JOIN employees e ON d.employee_id = e.id
            ORDER BY d.created_at DESC LIMIT 10
        """, conn)
        if not recent_disc.empty:
            st.dataframe(recent_disc, use_container_width=True, hide_index=True)
        else:
            st.info("No disciplinary cases recorded yet.")
    except:
        st.info("No disciplinary data available.")


# ============================================================
# ====================== EMPLOYEE DATABASE ===================
# ============================================================
elif menu == "👤 Employee Database":
    st.header("👤 Employee Database")
    tab_list, tab_add, tab_edit, tab_delete, tab_export = st.tabs([
        "📋 All Employees","➕ Add Employee","✏️ Edit Employee","🗑️ Remove Employee","📥 Export"
    ])

    with tab_list:
        st.subheader("All Employees")
        employees = get_employees()
        if not employees.empty:
            col1,col2,col3,col4 = st.columns(4)
            col1.metric("Total Employees", len(employees))
            col2.metric("Active", len(employees[employees["status"]=="active"]))
            col3.metric("Non-Active", len(employees[employees["status"]!="active"]))
            col4.metric("Departments", employees["department"].nunique())
            st.divider()
        with st.expander("🔍 Filter Employees", expanded=False):
            f1,f2,f3 = st.columns(3)
            with f1: filter_dept = st.selectbox("Department", ["All"]+DEPARTMENTS)
            with f2: filter_status = st.selectbox("Status", ["All"]+STATUS_OPTIONS)
            with f3: filter_contract = st.selectbox("Contract Type", ["All"]+CONTRACT_TYPES)
            search_name = st.text_input("🔎 Search by name or employee ID","")
        if employees.empty:
            st.info("No employees found. Go to **Add Employee** to get started.")
        else:
            filtered = employees.copy()
            if filter_dept != "All":
                filtered = filtered[filtered["department"]==filter_dept]
            if filter_status != "All":
                filtered = filtered[filtered["status"]==filter_status]
            if filter_contract != "All":
                filtered = filtered[filtered["contract_type"]==filter_contract]
            if search_name:
                filtered = filtered[
                    filtered["name"].str.contains(search_name,case=False,na=False) |
                    filtered["employee_id"].astype(str).str.contains(search_name,case=False,na=False)
                ]
            display_cols = [c for c in ["employee_id","name","position","department","email",
                                         "phone","hire_date","contract_start","contract_end",
                                         "contract_type","status"] if c in filtered.columns]
            st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)
            st.caption(f"Showing {len(filtered)} of {len(employees)} employees")

            if not filtered.empty:
                with st.expander("👁️ View Full Profile"):
                    sel_name = st.selectbox("Select employee", filtered["name"])
                    emp_data = filtered[filtered["name"]==sel_name].iloc[0]
                    c1,c2 = st.columns(2)
                    with c1:
                        st.markdown("**Personal Details**")
                        st.write(f"🪪 **Employee ID:** {emp_data.get('employee_id','—')}")
                        st.write(f"👤 **Full Name:** {emp_data['name']}")
                        st.write(f"📧 **Email:** {emp_data.get('email','—')}")
                        st.write(f"📞 **Phone:** {emp_data.get('phone','—')}")
                        st.write(f"🏠 **Address:** {emp_data.get('address','—')}")
                        st.write(f"🆘 **Emergency Contact:** {emp_data.get('emergency_contact_name','—')} — {emp_data.get('emergency_contact_phone','—')}")
                    with c2:
                        st.markdown("**Employment Details**")
                        st.write(f"💼 **Position:** {emp_data.get('position','—')}")
                        st.write(f"🏢 **Department:** {emp_data.get('department','—')}")
                        st.write(f"📅 **Hire Date:** {emp_data.get('hire_date','—')}")
                        st.write(f"📅 **Contract Start:** {emp_data.get('contract_start','—')}")
                        st.write(f"📅 **Contract End:** {emp_data.get('contract_end','—')}")
                        st.write(f"📄 **Contract Type:** {emp_data.get('contract_type','—')}")
                        st.write(f"🟢 **Status:** {str(emp_data.get('status','—')).upper()}")
                        if emp_data.get("actual_end_date"):
                            st.write(f"🚪 **Actual End Date:** {emp_data.get('actual_end_date','—')}")
                            st.write(f"📝 **Separation Type:** {emp_data.get('separation_type','—')}")

    with tab_add:
        st.subheader("➕ Add New Employee")
        with st.form("add_employee_form", clear_on_submit=True):
            st.markdown("#### 👤 Personal Information")
            a1,a2 = st.columns(2)
            with a1:
                new_name        = st.text_input("Full Name *")
                new_email       = st.text_input("Email Address")
                new_phone       = st.text_input("Phone Number")
                new_national_id = st.text_input("National ID / Passport No.")
            with a2:
                new_address         = st.text_area("Residential Address", height=68)
                new_emergency_name  = st.text_input("Emergency Contact Name")
                new_emergency_phone = st.text_input("Emergency Contact Phone")
            st.divider()
            st.markdown("#### 💼 Employment Details")
            b1,b2 = st.columns(2)
            with b1:
                new_position       = st.text_input("Position / Job Title *")
                new_dept           = st.selectbox("Department *", DEPARTMENTS)
                new_hire_date      = st.date_input("Hire Date", value=get_today())
                new_contract_start = st.date_input("Contract Start Date", value=get_today())
            with b2:
                new_contract_end   = st.date_input("Contract End Date", value=get_today()+timedelta(days=365))
                new_contract       = st.selectbox("Contract Type", CONTRACT_TYPES)
                new_status         = st.selectbox("Status", STATUS_OPTIONS)
            st.markdown("#### 🚪 Separation (if applicable)")
            s1,s2 = st.columns(2)
            with s1:
                new_actual_end = st.date_input("Actual End Date (leave blank if still employed)",
                                               value=None, min_value=date(2000,1,1))
            with s2:
                new_separation = st.selectbox("Separation Type", ["None"]+SEPARATION_TYPES)
            new_notes = st.text_area("Notes / Remarks", height=60)
            submitted = st.form_submit_button("➕ Add Employee", use_container_width=True)
            if submitted:
                if not new_name or not new_position:
                    st.error("Full Name and Position are required.")
                else:
                    emp_id = generate_employee_id(new_dept)
                    actual_end = str(new_actual_end) if new_actual_end else None
                    sep_type   = new_separation if new_separation != "None" else None
                    try:
                        cursor.execute('''
                            INSERT INTO employees
                            (name, employee_id, position, department, email, phone, national_id,
                             hire_date, contract_start, contract_end, actual_end_date, separation_type,
                             contract_type, status, emergency_contact_name, emergency_contact_phone, address, notes)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ''', (new_name, emp_id, new_position, new_dept, new_email, new_phone,
                              new_national_id, str(new_hire_date), str(new_contract_start),
                              str(new_contract_end), actual_end, sep_type,
                              new_contract, new_status, new_emergency_name, new_emergency_phone,
                              new_address, new_notes))
                        conn.commit()
                        st.success(f"✅ **{new_name}** added with ID `{emp_id}`")
                        rules = pd.read_sql("SELECT * FROM alert_rules WHERE rule_type='new_employee' AND enabled=1",conn)
                        if not rules.empty:
                            plain = f"New employee added:\nName: {new_name}\nPosition: {new_position}\nDepartment: {new_dept}\nEmployee ID: {emp_id}"
                            html  = build_html_email("New Employee Added",[
                                ("Name",new_name),("Position",new_position),
                                ("Department",new_dept),("Employee ID",emp_id),
                                ("Contract End",str(new_contract_end))])
                            ok,msg = send_email(f"New Employee: {new_name}",plain,html_body=html)
                            if ok: st.info("📧 Notification sent.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    with tab_edit:
        st.subheader("✏️ Edit Employee")
        employees = get_employees()
        if employees.empty:
            st.info("No employees to edit.")
        else:
            sel_emp = st.selectbox("Select employee to edit", employees["name"], key="edit_sel")
            emp_row = employees[employees["name"]==sel_emp].iloc[0]
            with st.form("edit_employee_form"):
                e1,e2 = st.columns(2)
                with e1:
                    edit_name     = st.text_input("Full Name", value=emp_row["name"])
                    edit_email    = st.text_input("Email", value=emp_row.get("email","") or "")
                    edit_phone    = st.text_input("Phone", value=emp_row.get("phone","") or "")
                    edit_position = st.text_input("Position", value=emp_row.get("position","") or "")
                    try:
                        cs_val = datetime.strptime(str(emp_row.get("contract_start",""))[:10],"%Y-%m-%d").date() if emp_row.get("contract_start") else get_today()
                        edit_contract_start = st.date_input("Contract Start", value=cs_val)
                    except:
                        edit_contract_start = st.date_input("Contract Start", value=get_today())
                    try:
                        ce_val = datetime.strptime(str(emp_row.get("contract_end",""))[:10],"%Y-%m-%d").date() if emp_row.get("contract_end") else get_today()+timedelta(days=365)
                        edit_contract_end = st.date_input("Contract End", value=ce_val)
                    except:
                        edit_contract_end = st.date_input("Contract End", value=get_today()+timedelta(days=365))
                with e2:
                    edit_dept     = st.selectbox("Department", DEPARTMENTS, index=DEPARTMENTS.index(emp_row["department"]) if emp_row["department"] in DEPARTMENTS else 0)
                    edit_contract = st.selectbox("Contract Type", CONTRACT_TYPES, index=CONTRACT_TYPES.index(emp_row["contract_type"]) if emp_row.get("contract_type") in CONTRACT_TYPES else 0)
                    edit_status   = st.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(emp_row["status"]) if emp_row["status"] in STATUS_OPTIONS else 0)
                    edit_sep      = st.selectbox("Separation Type", ["None"]+SEPARATION_TYPES,
                                                 index=(["None"]+SEPARATION_TYPES).index(emp_row.get("separation_type","None")) if emp_row.get("separation_type") in SEPARATION_TYPES else 0)
                    try:
                        ae_val = datetime.strptime(str(emp_row.get("actual_end_date",""))[:10],"%Y-%m-%d").date() if emp_row.get("actual_end_date") else None
                        edit_actual_end = st.date_input("Actual End Date", value=ae_val, min_value=date(2000,1,1))
                    except:
                        edit_actual_end = st.date_input("Actual End Date", value=None, min_value=date(2000,1,1))
                edit_notes = st.text_area("Notes", value=emp_row.get("notes","") or "")
                if st.form_submit_button("💾 Save Changes"):
                    try:
                        actual_end = str(edit_actual_end) if edit_actual_end else None
                        sep_type   = edit_sep if edit_sep != "None" else None
                        cursor.execute('''
                            UPDATE employees SET name=?,email=?,phone=?,position=?,department=?,
                            contract_start=?,contract_end=?,actual_end_date=?,separation_type=?,
                            contract_type=?,status=?,notes=? WHERE id=?
                        ''', (edit_name,edit_email,edit_phone,edit_position,edit_dept,
                              str(edit_contract_start),str(edit_contract_end),actual_end,sep_type,
                              edit_contract,edit_status,edit_notes,int(emp_row["id"])))
                        conn.commit()
                        st.success("✅ Employee updated.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    with tab_delete:
        st.subheader("🗑️ Remove Employee")
        employees = get_employees()
        if employees.empty:
            st.info("No employees found.")
        else:
            del_emp = st.selectbox("Select employee to remove", employees["name"])
            st.warning(f"⚠️ Are you sure you want to remove **{del_emp}**? This cannot be undone.")
            if st.button("🗑️ Confirm Delete", type="primary"):
                eid = employees[employees["name"]==del_emp]["id"].iloc[0]
                cursor.execute("DELETE FROM employees WHERE id=?", (int(eid),))
                conn.commit()
                st.success(f"✅ {del_emp} removed.")
                st.rerun()

    with tab_export:
        st.subheader("📥 Export Employee Data")
        employees = get_employees()
        if employees.empty:
            st.info("No employees to export.")
        else:
            export_cols = [c for c in ["employee_id","name","position","department","email",
                                        "phone","hire_date","contract_start","contract_end",
                                        "actual_end_date","separation_type","contract_type","status"]
                           if c in employees.columns]
            export_df = employees[export_cols]
            col1,col2 = st.columns(2)
            with col1:
                xl = export_to_excel({"Employees":export_df},"employees")
                st.download_button("📥 Download Excel", xl, f"employees_{datetime.now().strftime('%Y%m%d')}.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True)
            with col2:
                csv = export_df.to_csv(index=False).encode("utf-8")
                st.download_button("📄 Download CSV", csv, f"employees_{datetime.now().strftime('%Y%m%d')}.csv",
                                   mime="text/csv", use_container_width=True)
            st.dataframe(export_df, use_container_width=True, hide_index=True)


# ============================================================
# ====================== CONTRACT ALERTS =====================
# ============================================================
elif menu == "📄 Contract Alerts":
    st.header("📄 Contract Alerts")
    employees = get_employees()
    today = get_today()
    threshold = int(get_setting("contract_alert_days","30"))

    st.info(f"Showing contracts expiring within **{threshold} days**. Change threshold in ⚙️ Settings → Payroll Defaults.")

    if employees.empty or "contract_end" not in employees.columns:
        st.warning("No employees or contract data found.")
    else:
        rows = []
        for _, emp in employees.iterrows():
            cs = contract_status(emp.get("contract_end"), emp.get("actual_end_date"), threshold)
            try:
                end_date = datetime.strptime(str(emp.get("contract_end",""))[:10],"%Y-%m-%d").date() if emp.get("contract_end") else None
                days_rem = (end_date - today).days if end_date else None
            except:
                end_date, days_rem = None, None
            rows.append({
                "Employee ID": emp.get("employee_id","—"),
                "Name": emp["name"],
                "Position": emp.get("position","—"),
                "Department": emp.get("department","—"),
                "Contract Start": str(emp.get("contract_start",""))[:10],
                "Contract End": str(emp.get("contract_end",""))[:10],
                "Actual End Date": str(emp.get("actual_end_date",""))[:10] if emp.get("actual_end_date") else "—",
                "Days Remaining": days_rem,
                "Status": cs
            })
        df = pd.DataFrame(rows)

        # Summary metrics
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total", len(df))
        c2.metric("Active", len(df[df["Status"]=="ACTIVE"]))
        c3.metric("⏳ Expiring Soon", len(df[df["Status"]=="EXPIRING SOON"]))
        c4.metric("❌ Expired", len(df[df["Status"]=="EXPIRED"]))

        st.divider()

        # Filter by status
        status_filter = st.selectbox("Filter by Status", ["All","ACTIVE","EXPIRING SOON","EXPIRED","LEFT","UNKNOWN"])
        display_df = df if status_filter == "All" else df[df["Status"]==status_filter]

        # Color code
        def highlight_status(val):
            colors = {"EXPIRING SOON":"background-color:#FFF3CD;color:#856404",
                      "EXPIRED":"background-color:#F8D7DA;color:#721c24",
                      "LEFT":"background-color:#E2E3E5;color:#383d41",
                      "ACTIVE":"background-color:#D4EDDA;color:#155724"}
            return colors.get(val,"")

        styled = display_df.style.applymap(highlight_status, subset=["Status"])
        st.dataframe(styled, use_container_width=True, hide_index=True)

        # Export
        xl = export_to_excel({"Contract Alerts": display_df}, "contract_alerts")
        st.download_button("📥 Export to Excel", xl, f"contract_alerts_{datetime.now().strftime('%Y%m%d')}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # Send email alert
        st.divider()
        if st.button("📧 Send Contract Expiry Alert Email"):
            expiring = df[df["Status"]=="EXPIRING SOON"]
            body = f"Contract Expiry Alert — {today}\n\n"
            body += "\n".join([f"  - {r['Name']} ({r['Department']}) — {r['Days Remaining']} days remaining" for _,r in expiring.iterrows()]) if not expiring.empty else "No expiring contracts."
            html = build_html_email("Contract Expiry Alert",
                                    [(r["Name"],f"{r['Department']} — {r['Days Remaining']} days") for _,r in expiring.iterrows()] or [("Status","No expiring contracts")])
            ok,msg = send_email("HR Alert: Contract Expiry",body,html_body=html)
            st.success(msg) if ok else st.error(msg)


# ============================================================
# ====================== LEAVE TRACKER =======================
# ============================================================
elif menu == "🏖️ Leave Tracker":
    st.header("🏖️ Leave Tracker")
    employees = get_employees()

    tab_list, tab_add, tab_approve, tab_export = st.tabs([
        "📋 All Leave Records","➕ Log Leave Request","✅ Approve / Reject","📥 Export"
    ])

    with tab_list:
        st.subheader("All Leave Records")
        try:
            leave_df = pd.read_sql("""
                SELECT l.id, e.employee_id, e.name, e.department, l.leave_type,
                       l.start_date, l.end_date, l.days_taken, l.approval_status, l.notes
                FROM leave_tracker l
                JOIN employees e ON l.employee_id = e.id
                ORDER BY l.created_at DESC
            """, conn)
            if leave_df.empty:
                st.info("No leave records found. Use **Log Leave Request** to add one.")
            else:
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Total Records", len(leave_df))
                c2.metric("Pending", len(leave_df[leave_df["approval_status"]=="Pending"]))
                c3.metric("Approved", len(leave_df[leave_df["approval_status"]=="Approved"]))
                c4.metric("Rejected", len(leave_df[leave_df["approval_status"]=="Rejected"]))
                st.divider()

                # Filters
                col1,col2,col3 = st.columns(3)
                with col1: f_status = st.selectbox("Approval Status",["All"]+APPROVAL_STATUS)
                with col2: f_type   = st.selectbox("Leave Type",["All"]+LEAVE_TYPES)
                with col3: f_search = st.text_input("Search by name","")

                filtered = leave_df.copy()
                if f_status != "All": filtered = filtered[filtered["approval_status"]==f_status]
                if f_type   != "All": filtered = filtered[filtered["leave_type"]==f_type]
                if f_search: filtered = filtered[filtered["name"].str.contains(f_search,case=False,na=False)]

                st.dataframe(filtered, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error: {e}")

    with tab_add:
        st.subheader("➕ Log New Leave Request")
        if employees.empty:
            st.warning("No employees found.")
        else:
            with st.form("leave_form", clear_on_submit=True):
                l1,l2 = st.columns(2)
                with l1:
                    emp_sel      = st.selectbox("Employee *", employees["name"])
                    leave_type   = st.selectbox("Leave Type *", LEAVE_TYPES)
                    start_date   = st.date_input("Start Date *", value=get_today())
                with l2:
                    end_date     = st.date_input("End Date *", value=get_today()+timedelta(days=1))
                    appr_status  = st.selectbox("Approval Status", APPROVAL_STATUS)
                leave_notes = st.text_area("Notes / Reason", height=80)
                if st.form_submit_button("➕ Save Leave Request", use_container_width=True):
                    if end_date < start_date:
                        st.error("End date must be after start date.")
                    else:
                        eid = employees[employees["name"]==emp_sel]["id"].iloc[0]
                        days = (end_date - start_date).days
                        try:
                            cursor.execute('''
                                INSERT INTO leave_tracker
                                (employee_id, leave_type, start_date, end_date, days_taken, approval_status, notes)
                                VALUES (?,?,?,?,?,?,?)
                            ''', (int(eid), leave_type, str(start_date), str(end_date), days, appr_status, leave_notes))
                            conn.commit()
                            st.success(f"✅ Leave request logged for **{emp_sel}** — {days} day(s)")
                        except Exception as e:
                            st.error(f"Error: {e}")

    with tab_approve:
        st.subheader("✅ Approve / Reject Leave Requests")
        try:
            pending = pd.read_sql("""
                SELECT l.id, e.name, l.leave_type, l.start_date, l.end_date,
                       l.days_taken, l.approval_status
                FROM leave_tracker l
                JOIN employees e ON l.employee_id = e.id
                WHERE l.approval_status = 'Pending'
                ORDER BY l.start_date
            """, conn)
            if pending.empty:
                st.success("✅ No pending leave requests.")
            else:
                st.warning(f"{len(pending)} pending request(s)")
                for _, row in pending.iterrows():
                    with st.expander(f"📋 {row['name']} — {row['leave_type']} ({row['start_date']} to {row['end_date']}, {row['days_taken']} days)"):
                        c1,c2 = st.columns(2)
                        with c1:
                            if st.button(f"✅ Approve", key=f"approve_{row['id']}"):
                                cursor.execute("UPDATE leave_tracker SET approval_status='Approved' WHERE id=?", (row['id'],))
                                conn.commit()
                                st.success("Approved!")
                                st.rerun()
                        with c2:
                            if st.button(f"❌ Reject", key=f"reject_{row['id']}"):
                                cursor.execute("UPDATE leave_tracker SET approval_status='Rejected' WHERE id=?", (row['id'],))
                                conn.commit()
                                st.warning("Rejected.")
                                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

    with tab_export:
        st.subheader("📥 Export Leave Records")
        try:
            export_df = pd.read_sql("""
                SELECT e.employee_id, e.name, e.department, l.leave_type,
                       l.start_date, l.end_date, l.days_taken, l.approval_status, l.notes
                FROM leave_tracker l
                JOIN employees e ON l.employee_id = e.id
                ORDER BY l.start_date DESC
            """, conn)
            if export_df.empty:
                st.info("No records to export.")
            else:
                xl = export_to_excel({"Leave Records": export_df}, "leave_tracker")
                st.download_button("📥 Download Excel", xl, f"leave_records_{datetime.now().strftime('%Y%m%d')}.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True)
                st.dataframe(export_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error: {e}")


# ============================================================
# =================== DISCIPLINARY TRACKER ===================
# ============================================================
elif menu == "⚖️ Disciplinary Tracker":
    st.header("⚖️ Disciplinary Tracker")
    employees = get_employees()

    tab_list, tab_add, tab_export = st.tabs([
        "📋 All Cases","➕ Log New Case","📥 Export"
    ])

    with tab_list:
        st.subheader("All Disciplinary Cases")
        try:
            disc_df = pd.read_sql("""
                SELECT d.id, e.employee_id, e.name, e.department, d.issue_date,
                       d.issue_type, d.description, d.action_taken, d.expiry_date, d.status
                FROM disciplinary_tracker d
                JOIN employees e ON d.employee_id = e.id
                ORDER BY d.created_at DESC
            """, conn)

            # Recalculate live status
            if not disc_df.empty:
                disc_df["Status (Live)"] = disc_df["expiry_date"].apply(disciplinary_status)

                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Total Cases", len(disc_df))
                c2.metric("⚖️ Active", len(disc_df[disc_df["Status (Live)"]=="ACTIVE"]))
                c3.metric("⚠️ Expiring Soon", len(disc_df[disc_df["Status (Live)"]=="EXPIRING SOON"]))
                c4.metric("✅ Expired", len(disc_df[disc_df["Status (Live)"]=="EXPIRED"]))
                st.divider()

                # Filter
                col1,col2 = st.columns(2)
                with col1: f_status = st.selectbox("Status",["All","ACTIVE","EXPIRING SOON","EXPIRED","NO EXPIRY"])
                with col2: f_search = st.text_input("Search by name","")

                filtered = disc_df.copy()
                if f_status != "All": filtered = filtered[filtered["Status (Live)"]==f_status]
                if f_search: filtered = filtered[filtered["name"].str.contains(f_search,case=False,na=False)]

                def highlight_disc(val):
                    colors = {"EXPIRING SOON":"background-color:#FFF3CD;color:#856404",
                              "ACTIVE":"background-color:#F8D7DA;color:#721c24",
                              "EXPIRED":"background-color:#D4EDDA;color:#155724"}
                    return colors.get(val,"")

                styled = filtered.style.applymap(highlight_disc, subset=["Status (Live)"])
                st.dataframe(styled, use_container_width=True, hide_index=True)
            else:
                st.info("No disciplinary cases recorded yet.")

        except Exception as e:
            st.error(f"Error: {e}")

    with tab_add:
        st.subheader("➕ Log New Disciplinary Case")
        if employees.empty:
            st.warning("No employees found.")
        else:
            with st.form("disc_form", clear_on_submit=True):
                d1,d2 = st.columns(2)
                with d1:
                    emp_sel     = st.selectbox("Employee *", employees["name"])
                    issue_date  = st.date_input("Issue Date *", value=get_today())
                    issue_type  = st.selectbox("Issue Type *", ISSUE_TYPES)
                with d2:
                    action_taken = st.text_input("Action Taken", placeholder="e.g. Written warning issued")
                    expiry_date  = st.date_input("Warning Expiry Date", value=get_today()+timedelta(days=90))
                description = st.text_area("Description / Details *", height=100)
                if st.form_submit_button("➕ Save Case", use_container_width=True):
                    if not description:
                        st.error("Description is required.")
                    else:
                        eid = employees[employees["name"]==emp_sel]["id"].iloc[0]
                        status = disciplinary_status(expiry_date)
                        try:
                            cursor.execute('''
                                INSERT INTO disciplinary_tracker
                                (employee_id, issue_date, issue_type, description, action_taken, expiry_date, status)
                                VALUES (?,?,?,?,?,?,?)
                            ''', (int(eid), str(issue_date), issue_type, description, action_taken, str(expiry_date), status))
                            conn.commit()
                            st.success(f"✅ Disciplinary case logged for **{emp_sel}**")
                        except Exception as e:
                            st.error(f"Error: {e}")

    with tab_export:
        st.subheader("📥 Export Disciplinary Records")
        try:
            export_df = pd.read_sql("""
                SELECT e.employee_id, e.name, e.department, d.issue_date,
                       d.issue_type, d.description, d.action_taken, d.expiry_date, d.status
                FROM disciplinary_tracker d
                JOIN employees e ON d.employee_id = e.id
                ORDER BY d.issue_date DESC
            """, conn)
            if export_df.empty:
                st.info("No records to export.")
            else:
                xl = export_to_excel({"Disciplinary Tracker": export_df}, "disciplinary")
                st.download_button("📥 Download Excel", xl, f"disciplinary_{datetime.now().strftime('%Y%m%d')}.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True)
                st.dataframe(export_df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error: {e}")


# ============================================================
# ====================== PAYROLL MODULE ======================
# ============================================================
elif menu == "💰 Payroll":
    st.header("💰 Payroll Management")
    tab1, tab2, tab3, tab4 = st.tabs(["Salary Settings","Run Payroll","Payroll History","Payslips"])
    employees = get_employees()

    with tab1:
        st.subheader("Set / Update Employee Salaries & Allowances")
        if employees.empty:
            st.warning("No employees yet.")
        else:
            emp_name = st.selectbox("Select Employee", employees["name"])
            emp_id   = employees[employees["name"]==emp_name]["id"].iloc[0]
            settings = pd.read_sql("SELECT * FROM payroll_settings WHERE employee_id = ?", conn, params=[emp_id])
            defaults = settings.iloc[0] if not settings.empty else pd.Series({
                "basic_salary":0.0,"housing_allowance":0.0,"transport_allowance":0.0,
                "other_allowance":0.0,"tax_rate":0.0,"pension_rate":0.0,"other_deduction":0.0})
            with st.form("salary_form"):
                col1,col2 = st.columns(2)
                with col1:
                    basic     = st.number_input("Basic Salary (ZMW)", value=float(defaults["basic_salary"]), min_value=0.0, step=100.0)
                    housing   = st.number_input("Housing Allowance",   value=float(defaults["housing_allowance"]), min_value=0.0, step=50.0)
                    transport = st.number_input("Transport Allowance", value=float(defaults["transport_allowance"]), min_value=0.0, step=50.0)
                with col2:
                    other_all    = st.number_input("Other Allowance",     value=float(defaults["other_allowance"]), min_value=0.0, step=50.0)
                    tax_rate     = st.number_input("Income Tax Rate (%)", value=float(defaults["tax_rate"])*100, min_value=0.0, max_value=50.0, step=0.5) / 100
                    pension_rate = st.number_input("Pension (%)",         value=float(defaults["pension_rate"])*100, min_value=0.0, max_value=20.0, step=0.5) / 100
                    other_ded    = st.number_input("Other Deduction (ZMW)", value=float(defaults["other_deduction"]), min_value=0.0, step=10.0)
                if st.form_submit_button("Save Salary Settings"):
                    cursor.execute('''
                        INSERT OR REPLACE INTO payroll_settings
                        (employee_id, basic_salary, housing_allowance, transport_allowance, other_allowance,
                         tax_rate, pension_rate, other_deduction, currency, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,'ZMW',date('now'))
                    ''', (emp_id,basic,housing,transport,other_all,tax_rate,pension_rate,other_ded))
                    conn.commit()
                    st.success(f"Salary settings saved for {emp_name}")

    with tab2:
        st.subheader("Process Monthly Payroll")
        year, month = get_current_period()
        col1,col2 = st.columns([1,3])
        with col1:
            sel_year  = st.number_input("Year",  min_value=2020, max_value=2035, value=year)
            sel_month = st.number_input("Month", min_value=1,    max_value=12,   value=month)
        try:
            run_exists = pd.read_sql("SELECT id, status FROM payroll_runs WHERE period_year=? AND period_month=?",
                                     conn, params=[sel_year, sel_month])
            if not run_exists.empty:
                st.info(f"Payroll for {sel_month}/{sel_year} — Status: **{run_exists['status'].iloc[0].upper()}**")

            if st.button("🔄 Load / Preview Payroll"):
                if employees.empty:
                    st.error("No employees.")
                else:
                    results = []
                    for _, emp in employees.iterrows():
                        sett = pd.read_sql("SELECT * FROM payroll_settings WHERE employee_id=?",conn,params=[emp["id"]])
                        if sett.empty:
                            results.append({"name":emp["name"],"status":"No salary settings","net_pay":0})
                            continue
                        s   = sett.iloc[0]
                        pay = calculate_pay(emp["id"],s["basic_salary"],s["housing_allowance"],
                                            s["transport_allowance"],s["other_allowance"],
                                            s["tax_rate"],s["pension_rate"],s["other_deduction"])
                        results.append({"employee_id":emp["id"],"name":emp["name"],
                                        "basic_salary":pay["basic_salary"],
                                        "gross_pay":pay["gross_pay"],"net_pay":pay["net_pay"],"status":"Ready"})
                    preview_df = pd.DataFrame(results)
                    st.session_state.payroll_preview     = preview_df
                    st.session_state.current_run_year    = sel_year
                    st.session_state.current_run_month   = sel_month
                    st.dataframe(preview_df.style.format({"basic_salary":"ZMW {:,.2f}","gross_pay":"ZMW {:,.2f}","net_pay":"ZMW {:,.2f}"}),
                                 use_container_width=True)
                    st.metric("Total Net Payroll", f"ZMW {preview_df['net_pay'].sum():,.2f}")

            if "payroll_preview" in st.session_state and st.button("💾 PROCESS Payroll"):
                try:
                    sy = st.session_state.get("current_run_year", sel_year)
                    sm = st.session_state.get("current_run_month", sel_month)
                    existing = pd.read_sql("SELECT id FROM payroll_runs WHERE period_year=? AND period_month=?",conn,params=[sy,sm])
                    if not existing.empty:
                        run_id = existing["id"].iloc[0]
                    else:
                        cursor.execute("INSERT INTO payroll_runs (period_year,period_month,run_date,status) VALUES (?,?,date('now'),'processed')",(sy,sm))
                        run_id = cursor.lastrowid
                        conn.commit()
                    preview = st.session_state.payroll_preview
                    total_net = 0
                    for _, row in preview.iterrows():
                        if row["status"] != "Ready": continue
                        eid  = int(row["employee_id"])
                        sett = pd.read_sql("SELECT * FROM payroll_settings WHERE employee_id=?",conn,params=[eid]).iloc[0]
                        pay  = calculate_pay(eid,sett["basic_salary"],sett["housing_allowance"],
                                             sett["transport_allowance"],sett["other_allowance"],
                                             sett["tax_rate"],sett["pension_rate"],sett["other_deduction"])
                        total_net += pay["net_pay"]
                        cursor.execute('''
                            INSERT INTO payroll_payments
                            (run_id,employee_id,basic_salary,allowances,gross_pay,tax,pension,other_deduction,net_pay,payment_date,status)
                            VALUES (?,?,?,?,?,?,?,?,?,date('now'),'pending')
                        ''', (run_id,eid,pay["basic_salary"],pay["allowances"],pay["gross_pay"],
                              pay["tax"],pay["pension"],pay["other_deduction"],pay["net_pay"]))
                    conn.commit()
                    st.success(f"✅ Payroll processed for {sm}/{sy}!")
                    st.balloons()
                    if "payroll_preview" in st.session_state:
                        del st.session_state.payroll_preview
                except Exception as e:
                    st.error(f"Error: {e}")
        except Exception as e:
            st.error(f"Error: {e}")

    with tab3:
        st.subheader("Payroll Run History")
        try:
            runs = pd.read_sql("""
                SELECT id, period_year || '-' || printf('%02d',period_month) AS period,
                       run_date, status FROM payroll_runs ORDER BY period_year DESC, period_month DESC
            """, conn)
            st.dataframe(runs, use_container_width=True)
            if not runs.empty:
                view_run = st.selectbox("View details", runs["id"],
                                        format_func=lambda x: runs[runs["id"]==x]["period"].values[0])
                if view_run:
                    details = pd.read_sql("""
                        SELECT e.name, p.basic_salary, p.gross_pay, p.net_pay, p.status
                        FROM payroll_payments p JOIN employees e ON p.employee_id=e.id WHERE p.run_id=?
                    """, conn, params=[view_run])
                    st.dataframe(details.style.format({"basic_salary":"ZMW {:,.2f}","gross_pay":"ZMW {:,.2f}","net_pay":"ZMW {:,.2f}"}),
                                 use_container_width=True)
        except Exception as e:
            st.error(f"Error: {e}")

    with tab4:
        st.subheader("Generate Payslips")
        try:
            runs = pd.read_sql("SELECT id, period_year || '-' || printf('%02d',period_month) AS period FROM payroll_runs ORDER BY period_year DESC, period_month DESC",conn)
            if runs.empty:
                st.info("No payroll runs available.")
            else:
                run_id = st.selectbox("Select Payroll Run", runs["id"],
                                      format_func=lambda x: runs[runs["id"]==x]["period"].values[0])
                if run_id:
                    payslips = pd.read_sql("""
                        SELECT e.name, e.position, e.department,
                               p.basic_salary, p.allowances, p.gross_pay,
                               p.tax, p.pension, p.other_deduction, p.net_pay,
                               pr.period_year || '-' || printf('%02d',pr.period_month) AS period
                        FROM payroll_payments p
                        JOIN employees e ON p.employee_id=e.id
                        JOIN payroll_runs pr ON p.run_id=pr.id
                        WHERE p.run_id=?
                    """, conn, params=[run_id])
                    if not payslips.empty:
                        emp_choice   = st.selectbox("Employee Payslip", payslips["name"])
                        slip         = payslips[payslips["name"]==emp_choice].iloc[0]
                        company_name = get_setting("company_name","Kaunda HRMS")
                        st.markdown(f"""
**{company_name} — Payslip {slip['period']}**  
**{slip['name']}** — {slip['position']} | {slip['department']}  

**Earnings**  
Basic Salary: ZMW {slip['basic_salary']:,.2f}  
Allowances:   ZMW {slip['allowances']:,.2f}  
**Gross Pay**: ZMW **{slip['gross_pay']:,.2f}**

**Deductions**  
PAYE/Tax:  ZMW {slip['tax']:,.2f}  
Pension:   ZMW {slip['pension']:,.2f}  
Other:     ZMW {slip['other_deduction']:,.2f}  

**Net Pay**: ZMW **{slip['net_pay']:,.2f}**
                        """)
                        xl = export_to_excel({"Payslips":payslips},f"payslips_{slip['period']}")
                        st.download_button("📥 Export All Payslips",xl,f"payslips_{slip['period']}.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        except Exception as e:
            st.error(f"Error: {e}")


# ============================================================
# ====================== ALERTS DASHBOARD ====================
# ============================================================
elif menu == "🚨 Alerts Dashboard":
    st.header("🚨 Alerts Dashboard")
    employees = get_employees()
    today = get_today()
    col1,col2,col3 = st.columns(3)

    with col1:
        st.subheader("📄 Contract Expiry")
        threshold = int(get_setting("contract_alert_days","30"))
        expiring = []
        if not employees.empty and "contract_end" in employees.columns:
            for _, emp in employees.iterrows():
                cs = contract_status(emp.get("contract_end"), emp.get("actual_end_date"), threshold)
                if cs == "EXPIRING SOON":
                    try:
                        end = datetime.strptime(str(emp["contract_end"])[:10],"%Y-%m-%d").date()
                        expiring.append({"Name":emp["name"],"Dept":emp["department"],"Days Left":(end-today).days})
                    except:
                        pass
        if expiring:
            st.warning(f"{len(expiring)} contract(s) expiring soon!")
            st.dataframe(pd.DataFrame(expiring),use_container_width=True,hide_index=True)
        else:
            st.success("✅ No contracts expiring soon.")

    with col2:
        st.subheader("⚖️ Active Disciplinary Cases")
        try:
            disc_df = pd.read_sql("""
                SELECT e.name, d.issue_type, d.expiry_date
                FROM disciplinary_tracker d JOIN employees e ON d.employee_id=e.id
            """, conn)
            active_cases = []
            for _, d in disc_df.iterrows():
                ds = disciplinary_status(d.get("expiry_date"))
                if ds in ["ACTIVE","EXPIRING SOON"]:
                    active_cases.append({"Name":d["name"],"Issue":d["issue_type"],"Status":ds})
            if active_cases:
                st.warning(f"{len(active_cases)} active disciplinary case(s)")
                st.dataframe(pd.DataFrame(active_cases),use_container_width=True,hide_index=True)
            else:
                st.success("✅ No active disciplinary cases.")
        except:
            st.info("No disciplinary data.")

    with col3:
        st.subheader("🏖️ Pending Leave Requests")
        try:
            pending = pd.read_sql("""
                SELECT e.name, l.leave_type, l.start_date, l.end_date
                FROM leave_tracker l JOIN employees e ON l.employee_id=e.id
                WHERE l.approval_status='Pending'
            """, conn)
            if not pending.empty:
                st.warning(f"{len(pending)} pending leave request(s)")
                st.dataframe(pending,use_container_width=True,hide_index=True)
            else:
                st.success("✅ No pending leave requests.")
        except:
            st.info("No leave data.")

    st.divider()
    st.subheader("📧 Send Alert Email Now")
    alert_type = st.selectbox("Alert Type",["Contract Expiry Summary","Disciplinary Summary","Leave Summary","Custom Alert"])
    if alert_type == "Custom Alert":
        custom_subject = st.text_input("Subject")
        custom_body    = st.text_area("Body", height=120)
        if st.button("📤 Send"):
            ok,msg = send_email(custom_subject, custom_body)
            st.success(msg) if ok else st.error(msg)
    else:
        if st.button(f"📤 Send {alert_type} Email"):
            if alert_type == "Contract Expiry Summary":
                body = f"Contract Expiry — {today}\n\n"
                body += "\n".join([f"  - {e['Name']} ({e['Dept']}) — {e['Days Left']} days" for e in expiring]) or "No expiring contracts."
                html = build_html_email("Contract Expiry",([(e["Name"],f"{e['Dept']} — {e['Days Left']}d") for e in expiring] or [("Status","No expiring contracts")]))
            elif alert_type == "Disciplinary Summary":
                body = f"Disciplinary Summary — {today}\n\nActive/Expiring cases:\n"
                try:
                    for _, d in disc_df.iterrows():
                        body += f"  - {d['name']} ({d['issue_type']})\n"
                except:
                    body += "  No data."
                html = build_html_email("Disciplinary Summary",[("Status","See attached report")])
            else:
                body = f"Leave Summary — {today}\n\n"
                try:
                    body += "\n".join([f"  - {r['name']} ({r['leave_type']}): {r['start_date']} to {r['end_date']}" for _,r in pending.iterrows()])
                except:
                    body += "No pending leave."
                html = build_html_email("Leave Summary",[("Status","See attached report")])
            ok,msg = send_email(f"HR Alert: {alert_type}", body, html_body=html)
            st.success(msg) if ok else st.error(msg)


# ============================================================
# ====================== NOTIFICATIONS =======================
# ============================================================
elif menu == "📧 Notifications":
    st.header("📧 Notifications Centre")
    tab_send, tab_rules, tab_log = st.tabs(["✉️ Send Notification","⚙️ Alert Rules","📋 Notification Log"])

    with tab_send:
        st.subheader("Send a Notification Email")
        employees = get_employees()
        notif_type = st.radio("Recipient",["Admin Email","Specific Employee","All Active Employees"],horizontal=True)
        with st.form("notification_form"):
            subject = st.text_input("Subject *")
            message = st.text_area("Message *", height=150)
            if notif_type == "Specific Employee":
                emp_sel = st.selectbox("Select Employee", employees["name"] if not employees.empty else ["No employees"])
            include_html = st.checkbox("Send as formatted HTML email", value=True)
            if st.form_submit_button("📤 Send Notification", use_container_width=True):
                if not subject or not message:
                    st.error("Subject and message are required.")
                else:
                    if notif_type == "Admin Email":
                        recipients = [get_setting("admin_email","")]
                    elif notif_type == "Specific Employee":
                        emp_email = employees[employees["name"]==emp_sel]["email"].values
                        recipients = [emp_email[0]] if len(emp_email)>0 and emp_email[0] else []
                    else:
                        recipients = [e for e in employees[employees["status"]=="active"]["email"].dropna().tolist() if e]
                    sent = failed = 0
                    for r in recipients:
                        html_body = build_html_email(subject,[("Message",message)]) if include_html else None
                        ok,_ = send_email(subject,message,recipient=r,html_body=html_body)
                        if ok: sent+=1
                        else: failed+=1
                    if sent>0:   st.success(f"✅ Sent to {sent} recipient(s).")
                    if failed>0: st.error(f"❌ Failed for {failed} recipient(s).")

    with tab_rules:
        st.subheader("⚙️ Automated Alert Rules")
        rules = pd.read_sql("SELECT * FROM alert_rules", conn)
        for _, rule in rules.iterrows():
            col1,col2,col3 = st.columns([3,1,1])
            with col1: st.write(f"**{rule['rule_name']}**  \n`{rule['rule_type']}`")
            with col2:
                if rule["threshold_days"]>0: st.write(f"⏰ {rule['threshold_days']} days")
            with col3:
                label = "✅ Enabled" if rule["enabled"] else "❌ Disabled"
                if st.button(label, key=f"toggle_{rule['id']}"):
                    cursor.execute("UPDATE alert_rules SET enabled=? WHERE id=?", (0 if rule["enabled"] else 1, rule["id"]))
                    conn.commit()
                    st.rerun()

    with tab_log:
        st.subheader("📋 Email Notification Log")
        try:
            log = pd.read_sql("SELECT id, sent_at, subject, recipient, status FROM notification_log ORDER BY id DESC LIMIT 100",conn)
            if log.empty:
                st.info("No notifications sent yet.")
            else:
                st.dataframe(log, use_container_width=True, hide_index=True)
                if st.button("🗑️ Clear Log"):
                    cursor.execute("DELETE FROM notification_log")
                    conn.commit()
                    st.success("Log cleared.")
                    st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")


# ============================================================
# ====================== REPORTS =============================
# ============================================================
elif menu == "📊 Reports":
    st.header("📊 Reports")
    employees = get_employees()
    if not employees.empty:
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total Employees", len(employees))
        c2.metric("Active", len(employees[employees["status"]=="active"]))
        c3.metric("Departments", employees["department"].nunique())
        c4.metric("Contract Types", employees["contract_type"].nunique())

        st.subheader("Department Summary")
        dept_summary = employees.groupby("department").agg(
            Total=("id","count"),
            Active=("status",lambda x: (x=="active").sum())
        ).reset_index()
        st.dataframe(dept_summary, use_container_width=True)

        st.subheader("Contract Type Breakdown")
        ct = employees["contract_type"].value_counts().reset_index()
        ct.columns = ["Contract Type","Count"]
        st.dataframe(ct, use_container_width=True)

        st.subheader("Leave Summary by Type")
        try:
            leave_summary = pd.read_sql("""
                SELECT leave_type, COUNT(*) AS Requests,
                       SUM(days_taken) AS Total_Days,
                       SUM(CASE WHEN approval_status='Approved' THEN 1 ELSE 0 END) AS Approved
                FROM leave_tracker GROUP BY leave_type
            """, conn)
            st.dataframe(leave_summary, use_container_width=True)
        except:
            pass

        st.subheader("Disciplinary Summary by Type")
        try:
            disc_summary = pd.read_sql("""
                SELECT issue_type, COUNT(*) AS Cases FROM disciplinary_tracker GROUP BY issue_type
            """, conn)
            st.dataframe(disc_summary, use_container_width=True)
        except:
            pass

        st.subheader("Payroll Summary")
        try:
            payroll_summary = pd.read_sql("""
                SELECT pr.period_year || '-' || printf('%02d',pr.period_month) AS period,
                       COUNT(pp.id) AS employees_paid, SUM(pp.net_pay) AS total_net_pay, pr.status
                FROM payroll_runs pr
                LEFT JOIN payroll_payments pp ON pr.id=pp.run_id
                GROUP BY pr.id ORDER BY pr.period_year DESC, pr.period_month DESC
            """, conn)
            if not payroll_summary.empty:
                st.dataframe(payroll_summary.style.format({"total_net_pay":"ZMW {:,.2f}"}),use_container_width=True)
        except:
            pass
    else:
        st.info("No employee data available yet.")


# ============================================================
# ======================== SETTINGS ==========================
# ============================================================
elif menu == "⚙️ Settings":
    st.header("⚙️ System Settings")
    tab_admin, tab_company, tab_email, tab_payroll_cfg, tab_security = st.tabs([
        "🔐 Admin Credentials","🏢 Company Info","📧 Email Configuration","💰 Payroll Defaults","🛡️ Security"
    ])

    with tab_admin:
        st.subheader("🔐 Change Admin Credentials")
        with st.form("admin_cred_form"):
            current_user = get_setting("admin_username","admin")
            current_pass = get_setting("admin_password","admin123")
            st.info(f"Current Username: **{current_user}**")
            new_username   = st.text_input("New Username")
            new_password   = st.text_input("New Password", type="password")
            confirm_pass   = st.text_input("Confirm Password", type="password")
            verify_current = st.text_input("Current Password (to confirm)", type="password")
            if st.form_submit_button("💾 Update Credentials", use_container_width=True):
                if verify_current != current_pass:
                    st.error("❌ Current password incorrect.")
                elif new_password and new_password != confirm_pass:
                    st.error("❌ Passwords do not match.")
                elif new_password and len(new_password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    if new_username: save_setting("admin_username", new_username)
                    if new_password: save_setting("admin_password", new_password)
                    st.success("✅ Credentials updated. Please log in again.")
                    st.session_state.logged_in = False
                    st.rerun()

    with tab_company:
        st.subheader("🏢 Company Information")
        with st.form("company_form"):
            company_name     = st.text_input("Company Name",     value=get_setting("company_name","Kaunda HRMS"))
            company_address  = st.text_area("Company Address",   value=get_setting("company_address","Lusaka, Zambia"), height=80)
            company_phone    = st.text_input("Company Phone",    value=get_setting("company_phone",""))
            company_email    = st.text_input("Company Email",    value=get_setting("company_email",""))
            company_website  = st.text_input("Website",          value=get_setting("company_website",""))
            company_tpin     = st.text_input("TPIN",             value=get_setting("company_tpin",""))
            company_napsa    = st.text_input("NAPSA No.",        value=get_setting("company_napsa",""))
            company_currency = st.selectbox("Default Currency",  ["ZMW","USD","ZAR","EUR","GBP"],
                                            index=["ZMW","USD","ZAR","EUR","GBP"].index(get_setting("default_currency","ZMW")))
            if st.form_submit_button("💾 Save", use_container_width=True):
                for k,v in [("company_name",company_name),("company_address",company_address),
                            ("company_phone",company_phone),("company_email",company_email),
                            ("company_website",company_website),("company_tpin",company_tpin),
                            ("company_napsa",company_napsa),("default_currency",company_currency)]:
                    save_setting(k,v)
                st.success("✅ Saved.")

    with tab_email:
        st.subheader("📧 Email / SMTP Configuration")
        with st.form("email_config_form"):
            col1,col2 = st.columns(2)
            with col1:
                smtp_host = st.text_input("SMTP Host", value=get_setting("smtp_host","smtp.gmail.com"))
                smtp_port = st.selectbox("SMTP Port",  ["587","465","25"],
                                         index=["587","465","25"].index(get_setting("smtp_port","587")))
                smtp_user = st.text_input("Email",     value=get_setting("smtp_user",""))
            with col2:
                smtp_pass   = st.text_input("App Password", type="password", value=get_setting("smtp_password",""))
                admin_email = st.text_input("Admin Recipient Email", value=get_setting("admin_email",""))
            st.markdown("**Gmail users:** Use an App Password. Enable 2FA first.")
            if st.form_submit_button("💾 Save Email Settings", use_container_width=True):
                for k,v in [("smtp_host",smtp_host),("smtp_port",smtp_port),
                            ("smtp_user",smtp_user),("smtp_password",smtp_pass),("admin_email",admin_email)]:
                    save_setting(k,v)
                st.success("✅ Email settings saved.")
        st.divider()
        st.subheader("🔬 Test Email")
        test_rec = st.text_input("Send test to", value=get_setting("admin_email",""))
        if st.button("📤 Send Test Email"):
            ok,msg = send_email("HRMS Test Email",
                                f"Test email from HRMS. Sent: {datetime.now().strftime('%d %b %Y %H:%M')}",
                                recipient=test_rec)
            st.success(msg) if ok else st.error(msg)

    with tab_payroll_cfg:
        st.subheader("💰 Payroll Defaults")
        with st.form("payroll_defaults_form"):
            col1,col2 = st.columns(2)
            with col1:
                default_tax     = st.number_input("Default PAYE Tax Rate (%)", value=float(get_setting("default_tax_rate","30")), min_value=0.0, max_value=60.0, step=0.5)
                default_pension = st.number_input("Default Pension Rate (%)",  value=float(get_setting("default_pension_rate","5")), min_value=0.0, max_value=20.0, step=0.5)
            with col2:
                default_napsa_emp  = st.number_input("NAPSA Employee (%)", value=float(get_setting("napsa_employee","5")), min_value=0.0, max_value=10.0, step=0.5)
                default_napsa_empr = st.number_input("NAPSA Employer (%)", value=float(get_setting("napsa_employer","5")), min_value=0.0, max_value=10.0, step=0.5)
            contract_alert_days = st.number_input("Contract Expiry Alert Threshold (days)",
                                                   value=int(get_setting("contract_alert_days","30")), min_value=1, max_value=180)
            if st.form_submit_button("💾 Save", use_container_width=True):
                for k,v in [("default_tax_rate",str(default_tax)),("default_pension_rate",str(default_pension)),
                            ("napsa_employee",str(default_napsa_emp)),("napsa_employer",str(default_napsa_empr)),
                            ("contract_alert_days",str(contract_alert_days))]:
                    save_setting(k,v)
                st.success("✅ Saved.")

    with tab_security:
        st.subheader("🛡️ Security Settings")
        with st.form("security_form"):
            auto_logout = st.selectbox("Auto Logout", ["Never","15 minutes","30 minutes","1 hour","2 hours"],
                                       index=["Never","15 minutes","30 minutes","1 hour","2 hours"].index(get_setting("auto_logout","Never")))
            require_strong = st.checkbox("Require Strong Passwords", value=get_setting("strong_password","0")=="1")
            if st.form_submit_button("💾 Save"):
                save_setting("auto_logout", auto_logout)
                save_setting("strong_password","1" if require_strong else "0")
                st.success("✅ Saved.")
        st.divider()
        st.subheader("System Info")
        c1,c2 = st.columns(2)
        with c1:
            st.metric("Total Employees", pd.read_sql("SELECT COUNT(*) AS c FROM employees",conn)["c"].iloc[0])
            st.metric("Payroll Runs",    pd.read_sql("SELECT COUNT(*) AS c FROM payroll_runs",conn)["c"].iloc[0])
            st.metric("Notifications",  pd.read_sql("SELECT COUNT(*) AS c FROM notification_log",conn)["c"].iloc[0])
        with c2:
            st.metric("Leave Records",       pd.read_sql("SELECT COUNT(*) AS c FROM leave_tracker",conn)["c"].iloc[0])
            st.metric("Disciplinary Cases",  pd.read_sql("SELECT COUNT(*) AS c FROM disciplinary_tracker",conn)["c"].iloc[0])
            st.metric("Company", get_setting("company_name","Kaunda HRMS"))

# ====================== FOOTER ======================
st.sidebar.divider()
st.sidebar.caption(f"🏢 {get_setting('company_name','Kaunda HRMS')}")
st.sidebar.caption("Data stored in hr_system.db")
st.sidebar.caption(f"🔐 {st.session_state.username.upper()}")
