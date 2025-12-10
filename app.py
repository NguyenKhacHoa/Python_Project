import io
import os
import json
import re
import ast
import platform
import html  # [QUAN TRỌNG] Thư viện để xử lý ký tự đặc biệt
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, flash
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import MySQLdb.cursors

# Thư viện AI
import google.generativeai as genai

# Thư viện PDF
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

app = Flask(__name__)

# --- 1. CẤU HÌNH HỆ THỐNG ---
app.config['SECRET_KEY'] = 'dev-secret-key-super-secure'

# Cấu hình Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'hoa590472@gmail.com'
app.config['MAIL_PASSWORD'] = 'ojkn zxql fwab snjp'
app.config['MAIL_DEFAULT_SENDER'] = ('System', 'hoa590472@gmail.com')

mail = Mail(app)
s = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# Cấu hình MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'code_reviewer_db'

mysql = MySQL(app)

# Cấu hình AI Gemini
genai.configure(api_key='AIzaSyCP2hq_x9hmdYP0imEnFcIEZEltU5xQ1yo')
model = genai.GenerativeModel('gemini-2.5-flash')


# --- 2. HÀM HỖ TRỢ: TÌM FONT TIẾNG VIỆT ---
def register_vietnamese_font():
    """Tự động tìm và load font Arial để hiển thị tiếng Việt"""
    font_name = 'Helvetica'  # Font mặc định an toàn

    # Danh sách nơi có thể tìm thấy font
    possible_paths = [
        "arial.ttf",  # Ưu tiên tìm ngay cạnh file app.py
        os.path.join(os.getcwd(), "arial.ttf"),
        r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    ]

    font_path = None
    for path in possible_paths:
        if os.path.exists(path):
            font_path = path
            break

    if font_path:
        try:
            pdfmetrics.registerFont(TTFont('VietnameseFont', font_path))
            return 'VietnameseFont'
        except Exception as e:
            print(f"⚠️ Không load được font {font_path}: {e}")

    return font_name


# --- 3. PHÂN TÍCH TĨNH (AST) ---
def analyze_static_issues(source_code):
    issues = []
    deduction = 0
    try:
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_name = node.name
                args_count = len(node.args.args)
                if args_count > 5:
                    issues.append({
                        "msg": f"Hàm '{func_name}' có tới {args_count} tham số. Khó bảo trì.",
                        "category": "Code Smell (High)"
                    })
                    deduction += 25
                func_lines = len(node.body)
                if func_lines > 15:
                    issues.append({
                        "msg": f"Hàm '{func_name}' dài {func_lines} dòng. Vi phạm SRP.",
                        "category": "Code Smell (Medium)"
                    })
                    deduction += 15
    except SyntaxError as e:
        return [{"msg": f"Lỗi cú pháp dòng {e.lineno}: {e.msg}", "category": "Syntax Error"}], 100
    except Exception:
        pass
    return issues, deduction


# --- 4. ROUTES: AUTHENTICATION ---
@app.route('/')
def index():
    if 'loggedin' in session: return redirect(url_for('home'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    msg = ''
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
            account = cursor.fetchone()
            if account and check_password_hash(account['password_hash'], password):
                session['loggedin'] = True
                session['id'] = account['user_id']
                session['username'] = account['username']
                session['role'] = account['role']
                return redirect(url_for('home'))
            else:
                msg = '❌ Sai tài khoản hoặc mật khẩu!'
        except Exception as e:
            msg = f'⚠️ Lỗi DB: {str(e)}'
    return render_template('login.html', msg=msg)


@app.route('/register', methods=['GET', 'POST'])
def register():
    msg = ''
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        try:
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute('SELECT * FROM users WHERE username = %s OR email = %s', (username, email))
            account = cursor.fetchone()
            if account:
                msg = '⚠️ Tài khoản đã tồn tại!'
            else:
                hashed = generate_password_hash(password)
                cursor.execute('INSERT INTO users (username, email, password_hash, role) VALUES (%s, %s, %s, %s)',
                               (username, email, hashed, 'user'))
                mysql.connection.commit()
                msg = '✅ Đăng ký thành công! Hãy đăng nhập.'
                return redirect(url_for('login'))
        except Exception as e:
            msg = f'⚠️ Lỗi DB: {str(e)}'
    return render_template('register.html', msg=msg)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- 5. MAIN APP ---
@app.route('/home')
def home():
    if 'loggedin' not in session: return redirect(url_for('login'))
    history = []
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM reviews WHERE user_id = %s ORDER BY created_at DESC LIMIT 5', (session['id'],))
        history = cursor.fetchall()
        cursor.close()
    except:
        pass
    return render_template('home.html', username=session['username'], role=session['role'], history=history)


@app.route('/api/analyze', methods=['POST'])
def analyze_code():
    if 'loggedin' not in session: return jsonify({'error': 'Unauthorized'}), 401
    data = request.json
    code = data.get('code', '')
    if not code.strip(): return jsonify({'error': 'Empty code'}), 400

    static_risks, static_deduction = analyze_static_issues(code)
    if static_risks and static_risks[0]['category'] == 'Syntax Error':
        result = {
            "summary": "Lỗi cú pháp Python, không thể phân tích tiếp.",
            "score": 0, "security_issues": 0, "risks": static_risks, "suggested_fix": code
        }
        save_review_to_db(code, result)
        return jsonify(result)

    prompt = f"""
    Bạn là Code Reviewer. Output JSON only:
    {{
        "summary": "Tóm tắt tiếng Việt", "score": (0-100), "security_issues": (int),
        "risks": [{{"msg": "...", "category": "Security/Logic"}}], "suggested_fix": "code"
    }}
    Code: {code}
    """
    try:
        response = model.generate_content(prompt)
        ai_text = re.sub(r'^```json\s*|^```\s*|```$', '', response.text.strip(), flags=re.MULTILINE)
        start, end = ai_text.find('{'), ai_text.rfind('}') + 1
        result = json.loads(ai_text[start:end])

        result['risks'] = static_risks + result.get('risks', [])
        result['score'] = max(0, result.get('score', 80) - static_deduction)
        if static_risks: result['summary'] += f" (Có {len(static_risks)} vấn đề cấu trúc)."

        save_review_to_db(code, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({
            "summary": "Lỗi AI, hiển thị kết quả phân tích tĩnh.",
            "score": max(0, 100 - static_deduction),
            "security_issues": 0, "risks": static_risks, "suggested_fix": code
        })


def save_review_to_db(code, result):
    try:
        cursor = mysql.connection.cursor()
        risks_json = json.dumps(result.get("risks", []), ensure_ascii=False)
        cursor.execute('''
                       INSERT INTO reviews (user_id, input_code, ai_summary, score, security_issues, bugs_count,
                                            risks_detail)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ''', (session['id'], code, result.get("summary", ""), result.get("score", 0),
                             result.get("security_issues", 0), len(result.get("risks", [])), risks_json))
        mysql.connection.commit()
        cursor.close()
    except Exception as e:
        print(f"DB Error: {e}")


# --- 6. ROUTES: HISTORY & EXPORT (ĐÃ FIX HTML) ---
@app.route('/history')
def history_page():
    if 'loggedin' not in session: return redirect(url_for('login'))
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM reviews WHERE user_id = %s ORDER BY created_at DESC', (session['id'],))
        reviews = cursor.fetchall()
        cursor.close()
        return render_template('history.html', username=session['username'], role=session['role'], reviews=reviews)
    except:
        return "Lỗi DB", 500


@app.route('/api/review/<int:review_id>')
def get_review_detail(review_id):
    if 'loggedin' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM reviews WHERE review_id = %s AND user_id = %s', (review_id, session['id']))
        review = cursor.fetchone()
        if review:
            try:
                review['risks_detail'] = json.loads(review['risks_detail'])
            except:
                review['risks_detail'] = []
            return jsonify(review)
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Hàm tạo PDF (Đã fix font và ký tự đặc biệt)
def generate_pdf_response(data, filename):
    try:
        my_font = register_vietnamese_font()
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        elements = []
        styles = getSampleStyleSheet()

        style_title = ParagraphStyle('VN_Title', parent=styles['Heading1'], fontName=my_font, fontSize=18,
                                     textColor=colors.HexColor('#4f46e5'), spaceAfter=15, alignment=1)
        style_normal = ParagraphStyle('VN_Normal', parent=styles['Normal'], fontName=my_font, fontSize=10, leading=14)
        style_code = ParagraphStyle('Code', parent=styles['Normal'], fontName=my_font, fontSize=9,
                                    backColor=colors.whitesmoke, borderPadding=8)

        summary = str(data.get('ai_summary') or 'Không có nội dung')
        score = data.get('score', 0)
        input_code = str(data.get('input_code') or '')
        created_at = str(data.get('created_at', datetime.now()))

        risks = []
        if data.get('risks_detail'):
            try:
                raw = data['risks_detail']
                if isinstance(raw, bytes): raw = raw.decode('utf-8')
                risks = json.loads(raw)
            except:
                pass

        elements.append(Paragraph("BÁO CÁO PHÂN TÍCH CODE", style_title))
        elements.append(Paragraph(f"Ngày tạo: {created_at}", style_normal))
        elements.append(Spacer(1, 15))

        # Dùng html.escape để xử lý ký tự < > trong nội dung
        safe_summary = html.escape(summary)

        tbl_data = [
            [Paragraph('<b>Tiêu chí</b>', style_normal), Paragraph('<b>Kết quả</b>', style_normal)],
            ['Điểm số', f"{score}/100"],
            ['Số vấn đề', str(len(risks))],
            ['Tóm tắt', Paragraph(safe_summary, style_normal)]
        ]
        t = Table(tbl_data, colWidths=[1.5 * inch, 4.5 * inch])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#eef2ff')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dddddd')),
            ('FONTNAME', (0, 0), (-1, -1), my_font),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]))
        elements.append(t)
        elements.append(Spacer(1, 20))

        elements.append(Paragraph("Chi Tiết Vấn Đề:", styles['Heading2']))
        if risks:
            for i, r in enumerate(risks, 1):
                # FIX: Xử lý an toàn nếu risk là string hoặc dict
                if isinstance(r, dict):
                    msg = str(r.get('msg') or str(r))
                    cat = str(r.get('category') or 'Issue')
                else:
                    msg = str(r)
                    cat = 'Issue'

                safe_msg = html.escape(msg)
                elements.append(Paragraph(f"{i}. <b>[{cat}]</b>: {safe_msg}", style_normal))
                elements.append(Spacer(1, 5))
        else:
            elements.append(Paragraph("Không tìm thấy lỗi nghiêm trọng.", style_normal))

        elements.append(Spacer(1, 15))
        elements.append(Paragraph("Source Code:", styles['Heading2']))

        # FIX code
        safe_code = html.escape(input_code)
        fmt_code = safe_code.replace('\n', '<br/>').replace(' ', '&nbsp;')
        elements.append(Paragraph(fmt_code, style_code))

        doc.build(elements)
        buffer.seek(0)
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')
    except Exception as e:
        print(f"PDF ERROR: {e}")
        return jsonify({"error": str(e)}), 500


# [ĐÃ FIX TRIỆT ĐỂ LỖI HTML]
@app.route('/api/history/export/html/<int:review_id>')
def export_html_history(review_id):
    if 'loggedin' not in session: return redirect(url_for('login'))
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM reviews WHERE review_id = %s', (review_id,))
        review = cursor.fetchone()
        if not review: return "Not Found", 404

        risks = []
        try:
            raw_risks = review['risks_detail']
            if isinstance(raw_risks, bytes): raw_risks = raw_risks.decode('utf-8')
            risks = json.loads(raw_risks)
        except:
            risks = []

        # 1. Chuyển thành string an toàn và escape ký tự đặc biệt
        input_code = html.escape(str(review['input_code'] or ''))
        summary = html.escape(str(review['ai_summary'] or ''))

        # 2. Tạo danh sách lỗi HTML một cách an toàn
        risks_html = ""
        for r in risks:
            # Kiểm tra kiểu dữ liệu để tránh crash
            if isinstance(r, dict):
                cat = str(r.get("category") or "Warn")
                msg = str(r.get("msg") or "")
            else:
                cat = "Issue"
                msg = str(r)

            # Escape từng phần tử
            safe_cat = html.escape(cat)
            safe_msg = html.escape(msg)
            risks_html += f'<li><b>[{safe_cat}]</b> {safe_msg}</li>'

        # 3. Tạo nội dung HTML (đổi tên biến để không trùng với module html)
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Báo cáo #{review['review_id']}</title>
        </head>
        <body style="font-family:sans-serif; padding:40px;">
            <h1 style="color:#4f46e5">Báo cáo #{review['review_id']}</h1>
            <p>Ngày: {review['created_at']}</p>
            <div style="background:#f3f4f6; padding:20px; border-radius:8px;">
                <h2>Điểm số: {review['score']}/100</h2>
                <p><b>Tóm tắt:</b> {summary}</p>
            </div>
            <h3>Chi tiết lỗi:</h3>
            <ul>{risks_html}</ul>
            <h3>Code:</h3>
            <pre style="background:#1f2937; color:#fff; padding:15px; overflow-x:auto;">{input_code}</pre>
        </body></html>
        """

        # Trả về file
        return send_file(
            io.BytesIO(html_content.encode('utf-8')),
            as_attachment=True,
            download_name=f"Report_{review_id}.html",
            mimetype='text/html'
        )
    except Exception as e:
        print(f"HTML EXPORT ERROR: {e}")
        return f"<h1>Lỗi xuất HTML: {str(e)}</h1>", 500


@app.route('/api/export/pdf', methods=['POST', 'GET'])
def export_pdf_home():
    if 'loggedin' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM reviews WHERE user_id = %s ORDER BY created_at DESC LIMIT 1', (session['id'],))
        review = cursor.fetchone()
        if not review: return jsonify({"error": "No data"}), 404
        return generate_pdf_response(review, "Latest_Report.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/history/export/pdf/<int:review_id>')
def export_pdf_history(review_id):
    if 'loggedin' not in session: return redirect(url_for('login'))
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM reviews WHERE review_id = %s AND user_id = %s', (review_id, session['id']))
        review = cursor.fetchone()
        if not review: return "Not Found", 404
        return generate_pdf_response(review, f"History_{review_id}.pdf")
    except Exception as e:
        return str(e), 500


# --- 7. QUÊN MẬT KHẨU & CÀI ĐẶT & ADMIN ---

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    msg = ''
    if request.method == 'POST':
        email = request.form['email']
        try:
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
            user = cursor.fetchone()
            if user:
                token = s.dumps(email, salt='email-confirm')
                link = url_for('reset_password', token=token, _external=True)
                msg_mail = Message('Khoi phuc mat khau', recipients=[email])
                msg_mail.body = f'Link: {link}'
                mail.send(msg_mail)
                msg = '✅ Đã gửi mail!'
            else:
                msg = '⚠️ Email không tồn tại.'
        except Exception as e:
            msg = f'Lỗi: {str(e)}'
    return render_template('forgot_password.html', msg=msg)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=1800)
    except:
        return '<h1>Link hết hạn!</h1>'
    if request.method == 'POST':
        hashed = generate_password_hash(request.form['password'])
        cursor = mysql.connection.cursor()
        cursor.execute('UPDATE users SET password_hash = %s WHERE email = %s', (hashed, email))
        mysql.connection.commit()
        return redirect(url_for('login'))
    return render_template('reset_password.html')


@app.route('/settings')
def settings():
    if 'loggedin' not in session: return redirect(url_for('login'))
    return render_template('settings.html', username=session['username'], role=session['role'])


@app.route('/settings/change-password', methods=['POST'])
def change_password():
    if 'loggedin' not in session: return redirect(url_for('login'))
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT * FROM users WHERE user_id = %s', (session['id'],))
    user = cursor.fetchone()
    if check_password_hash(user['password_hash'], request.form['current_password']):
        new_hashed = generate_password_hash(request.form['new_password'])
        cursor.execute('UPDATE users SET password_hash = %s WHERE user_id = %s', (new_hashed, session['id']))
        mysql.connection.commit()
        return redirect(url_for('settings', msg='pass_ok'))
    return redirect(url_for('settings', msg='pass_fail'))


@app.route('/settings/clear-history', methods=['POST'])
def clear_history():
    if 'loggedin' not in session: return redirect(url_for('login'))
    try:
        cursor = mysql.connection.cursor()
        cursor.execute('DELETE FROM reviews WHERE user_id = %s', (session['id'],))
        mysql.connection.commit()
        return redirect(url_for('settings', msg='history_cleared'))
    except:
        return redirect(url_for('settings', msg='error'))


# --- ADMIN ROUTES ---
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'loggedin' not in session or session.get('role') != 'admin':
            flash('Unauthorized', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)

    return decorated_function


@app.route('/admin')
@admin_required
def admin_dashboard():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT COUNT(*) as total FROM users")
    t_users = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM reviews")
    t_reviews = cursor.fetchone()['total']
    cursor.execute("SELECT COUNT(*) as total FROM reviews WHERE score < 50")
    h_risk = cursor.fetchone()['total']

    search = request.args.get('q', '').strip()
    sql = "SELECT u.*, MAX(r.created_at) as last_active, COUNT(r.review_id) as review_count FROM users u LEFT JOIN reviews r ON u.user_id = r.user_id"
    params = ()
    if search:
        sql += " WHERE u.username LIKE %s OR u.email LIKE %s"
        params = (f"%{search}%", f"%{search}%")
    sql += " GROUP BY u.user_id"
    cursor.execute(sql, params)
    users = cursor.fetchall()
    return render_template('admin.html', username=session['username'], role=session['role'],
                           stats={'total_users': t_users, 'total_reviews': t_reviews, 'high_risk': h_risk},
                           users=users, search_query=search)


@app.route('/admin/user/<int:user_id>')
@admin_required
def admin_view_history(user_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    target = cursor.fetchone()
    if not target: return redirect(url_for('admin_dashboard'))
    cursor.execute("SELECT * FROM reviews WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    return render_template('admin_history.html', admin_name=session['username'], target_user=target,
                           reviews=cursor.fetchall())


@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == session['id']: return redirect(url_for('admin_dashboard'))
    cursor = mysql.connection.cursor()
    cursor.execute("DELETE FROM reviews WHERE user_id = %s", (user_id,))
    cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
    mysql.connection.commit()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/toggle_role/<int:user_id>', methods=['POST'])
@admin_required
def admin_toggle_role(user_id):
    if user_id == session['id']: return redirect(url_for('admin_dashboard'))
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT role FROM users WHERE user_id = %s", (user_id,))
    u = cursor.fetchone()
    if u:
        new_r = 'user' if u['role'] == 'admin' else 'admin'
        cursor.execute("UPDATE users SET role = %s WHERE user_id = %s", (new_r, user_id))
        mysql.connection.commit()
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reset_pass/<int:user_id>', methods=['POST'])
@admin_required
def admin_reset_pass(user_id):
    hashed = generate_password_hash("123456")
    cursor = mysql.connection.cursor()
    cursor.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (hashed, user_id))
    mysql.connection.commit()
    return redirect(url_for('admin_dashboard'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)   