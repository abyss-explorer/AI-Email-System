# app.py

from flask import Flask, render_template, url_for, abort # <-- 添加 url_for 和 abort
import sqlite3
import os

app = Flask(__name__)

# --- 数据库配置 ---
DATABASE_FILE = 'emails.db'


# --- 数据库读取函数 (用于网页显示) ---
def get_emails_for_display(db_file=DATABASE_FILE, limit=20):
    """从数据库获取邮件数据用于网页显示"""
    conn = None
    emails_data = []
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 查询需要显示的字段，例如 ID, 主题, 发件人, 日期, AI分类, 摘要等
        # 按 ID 倒序排序，获取最近的邮件
        cursor.execute(f'''
            SELECT id, subject, sender, date, classification, summary, reply_suggestion, ai_processed_at
            FROM emails
            ORDER BY id DESC
            LIMIT {limit} -- 限制获取的数量，避免一次加载太多
        ''')

        rows = cursor.fetchall() # 获取所有符合条件的行
        # 获取列名，用于将查询结果映射到字典
        column_names = [description[0] for description in cursor.description]

        for row in rows:
             # 将每一行数据转换为字典，字段名作为键
            email_dict = {}
            for i, col_name in enumerate(column_names):
                 email_dict[col_name] = row[i]
            emails_data.append(email_dict)


    except sqlite3.Error as e:
        print(f"数据库读取错误（用于显示）: {e}")
        # 在生产环境中，您可能需要将错误记录到日志或向用户显示错误信息
        return [] # 出错时返回空列表
    finally:
        # 确保关闭数据库连接
        if conn:
            conn.close()

    return emails_data

# 新增函数：根据 ID 获取单个邮件数据
def get_email_by_id(db_file, email_id):
    """从数据库获取指定ID的邮件数据"""
    conn = None
    email_data = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 查询所有需要显示的字段（包括完整正文和原始邮件）
        cursor.execute('''
            SELECT id, subject, sender, date, body, raw_email, classification, classification_reason, summary, reply_suggestion, ai_processed_at
            FROM emails
            WHERE id = ? -- 使用 ? 作为占位符，防止 SQL 注入
        ''', (email_id,)) # 将 email_id 作为参数传递给 execute

        row = cursor.fetchone() # 获取单行结果
        if row:
            # 将查询结果映射到字典，以便在模板中通过名称访问
            column_names = [description[0] for description in cursor.description]
            email_data = dict(zip(column_names, row))

    except sqlite3.Error as e:
        print(f"数据库读取错误（获取单个邮件）: {e}")
        return None # 出错时返回 None
    finally:
        # 确保关闭数据库连接
        if conn:
            conn.close()

    return email_data


# --- 数据库写入/更新函数 ---
def update_email_classification_in_db(db_file, email_id, new_classification):
    """更新数据库中指定邮件的用户修正分类"""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 更新 classification 字段，并可以选择更新 ai_processed_at 或添加一个用户更新时间戳
        # 这里我们更新 classification 和 ai_processed_at（表示最近一次被修改的时间）
        cursor.execute('''
            UPDATE emails
            SET classification = ?,
                ai_processed_at = ? -- 记录用户修正的时间
            WHERE id = ?
        ''', (new_classification, datetime.now().isoformat(), email_id))

        conn.commit() # 提交更改
        print(f"成功更新邮件 ID: {email_id} 的分类为 {new_classification}") # 后端日志

    except sqlite3.Error as e:
        print(f"数据库错误（更新分类）: {e}")
        # 在生产环境中，需要更完善的错误处理和日志记录
        return False # 指示更新失败
    finally:
        if conn:
            conn.close()
        return True # 指示更新成功


# --- 路由和视图函数 ---
# 列表页路由保持不变
@app.route('/')
def index():
    """当访问根URL时，渲染 index.html 模板并传递邮件数据列表"""
    all_emails = get_emails_for_display(DATABASE_FILE, limit=10) # 获取最近 10 封邮件
    data_to_pass = {
        'page_title': '邮件列表',
        'system_name': 'AI 邮件处理系统',
        'emails': all_emails
    }
    # render_template 默认会使得 url_for 在模板中可用
    return render_template('index.html', **data_to_pass)

# 新增邮件详情页路由
# <email_id> 部分是一个变量占位符，它会捕获URL中对应部分的值，并作为字符串传递给视图函数
@app.route('/email/<email_id>')
def show_email_detail(email_id):
    """显示单个邮件的详细信息"""
    # 1. 从数据库获取指定ID的邮件数据
    email_data = get_email_by_id(DATABASE_FILE, email_id)

    # 2. 检查是否找到了邮件
    if email_data is None:
        # 如果数据库中没有找到对应ID的邮件，返回404错误页面
        abort(404)

    # 3. 定义要传递给详情模板的数据
    data_to_pass = {
        # 截取主题作为页面标题，避免太长
        'page_title': email_data.get('subject', '无主题邮件')[:50] + ('...' if len(email_data.get('subject', '')) > 50 else ''),
        'email': email_data # 将单个邮件数据字典传递给模板，模板中变量名为 'email'
    }

    # 4. 渲染 email_detail.html 模板并传递数据
    return render_template('email_detail.html', **data_to_pass)

# 接收来自详情页表单的 POST 请求
@app.route('/update_classification/<email_id>', methods=['POST'])
def update_classification(email_id):
    # 1. 从接收到的 POST 表单数据中获取用户选择的新分类值
    # request.form 是一个字典，包含了表单中所有通过 POST 发送的数据
    # new_classification 是我们在模板中给单选按钮组设置的 name
    new_classification = request.form.get('new_classification')

    # 2. （可选但推荐）验证接收到的分类值是否有效
    valid_classifications = ['工作', '个人', '广告', '垃圾邮件', '其他'] # 需要与模板中的选项一致
    if not new_classification or new_classification not in valid_classifications:
        # 如果接收到的值无效，可以打印警告或向用户显示错误信息
        print(f"警告：接收到邮件 ID {email_id} 的无效分类修正值: {new_classification}")
        # 对于无效输入，通常不进行更新，并重定向回详情页
        return redirect(url_for('show_email_detail', email_id=email_id))

    # 3. 调用数据库更新函数
    success = update_email_classification_in_db(DATABASE_FILE, email_id, new_classification)

    # 4. 更新完成后，重定向用户回邮件详情页面
    # 重定向是处理 POST 请求后的标准做法，可以避免用户刷新页面时重复提交表单
    return redirect(url_for('show_email_detail', email_id=email_id))

    # 如果数据库更新失败，也可以选择重定向到一个错误页面或在详情页显示错误信息
    # 例如: if success: return redirect(...) else: return render_template('error.html', ...)



# 运行应用
if __name__ == '__main__':

    # debug=True 可以在开发过程中提供详细的错误信息
    # port=XXXX 指定一个不同的端口号
    # **请使用您之前成功运行应用的端口号**
    app.run(debug=True, port=5001) # <-- 替换为您的实际端口号
