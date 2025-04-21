import imaplib
import email
import os # 用于读取环境变量
import sqlite3
from email.header import decode_header
from bs4 import BeautifulSoup

# --- 配置信息 ---
# !!! 重要警告 !!!
# 在实际生产环境中，绝不能将敏感信息（如密码）硬编码在代码中。
# 本示例使用环境变量 EMAIL_PASSWORD，请确保在运行脚本前设置好此环境变量。

# 您的 IMAP 服务器地址和端口
# 示例：对于 Gmail 是 'imap.gmail.com', 端口 993
EMAIL_SERVER = 'imap.gmail.com' # <-- 请替换成您的服务器地址
EMAIL_PORT = 993

# 您的邮箱地址和密码
EMAIL_ADDRESS = '2095667048lj.gmail.com' # <-- 请替换成您的邮箱地址
# 从环境变量获取密码，更安全一些
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD') # <-- 请确保您设置了名为 EMAIL_PASSWORD 的环境变量

# 要连接的邮箱文件夹 (通常是 'INBOX')
MAILBOX = 'INBOX'

# --- 辅助函数：解码邮件头部信息 ---
def decode_mail_header(header):
    """解码邮件头部，处理编码问题"""
    decoded_parts = decode_header(header)
    decoded_string = ""
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            if encoding:
                try:
                    decoded_string += part.decode(encoding)
                except (LookupError, UnicodeDecodeError):
                    # 如果解码失败，尝试一些常见编码
                    try:
                         decoded_string += part.decode('utf-8', errors='ignore')
                    except:
                         decoded_string += part.decode('gbk', errors='ignore') # 尝试中文编码
            else:
                # 如果没有编码信息，假设是 ASCII 或 UTF-8
                try:
                     decoded_string += part.decode('utf-8', errors='ignore')
                except:
                     decoded_string += part.decode('ascii', errors='ignore')
        else:
            decoded_string += str(part)
    return decoded_string

# --- 改进后的函数：获取邮件正文 ---
def get_email_body_improved(msg):
    """
    尝试从邮件消息对象中提取纯文本正文。
    优先获取 text/plain 部分，如果不存在则尝试从 text/html 中提取文本。
    忽略附件。
    """
    html_body = None
    plain_body = None

    # 遍历邮件的所有部分 (包括嵌套的多部分)
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdisp = part.get('Content-Disposition')

            # 跳过附件和内嵌资源 (如图片)
            if cdisp and ('attachment' in cdisp or 'inline' in cdisp):
                continue

            # 获取内容
            if ctype == 'text/plain':
                try:
                    # 获取字符集，默认为 utf-8
                    charset = part.get_content_charset() or 'utf-8'
                    plain_body = part.get_payload(decode=True).decode(charset, errors='ignore')
                except Exception as e:
                    # print(f"Warning: Failed to decode text/plain part - {e}") # 可选的调试信息
                    pass # 解码失败则跳过
            elif ctype == 'text/html':
                 try:
                    charset = part.get_content_charset() or 'utf-8'
                    html_body = part.get_payload(decode=True).decode(charset, errors='ignore')
                 except Exception as e:
                     # print(f"Warning: Failed to decode text/html part - {e}") # 可选的调试信息
                     pass # 解码失败则跳过

        # 优先返回纯文本部分的内容
        if plain_body:
            return plain_body.strip()

        # 如果没有纯文本部分，尝试从 HTML 部分提取文本
        if html_body:
            try:
                # 使用 BeautifulSoup 提取 HTML 中的文本
                soup = BeautifulSoup(html_body, 'html.parser')

                # 移除不必要的元素，如 <script>, <style>
                for script_or_style in soup(["script", "style"]):
                    script_or_style.extract()

                # 获取所有文本内容，用换行符连接
                text = soup.get_text(separator='\n')

                # 清理多余的空行和空白
                text = os.linesep.join([s.strip() for s in text.splitlines() if s.strip()])

                return text.strip()
            except Exception as e:
                print(f"警告: 从 HTML 部分提取文本失败 - {e}")
                # 如果 Beautiful Soup 失败，可以返回原始 HTML 或空字符串，这里选择返回空
                return "" # 提取失败，返回空字符串

    # 如果不是 multipart 邮件，且是 text/plain 或 text/html
    elif msg.get_content_type() == 'text/plain':
         try:
             charset = msg.get_content_charset() or 'utf-8'
             return msg.get_payload(decode=True).decode(charset, errors='ignore').strip()
         except:
              return "" # 解码失败

    elif msg.get_content_type() == 'text/html':
         try:
             charset = msg.get_content_charset() or 'utf-8'
             html_body = msg.get_payload(decode=True).decode(charset, errors='ignore')
             # 使用 BeautifulSoup 提取文本
             soup = BeautifulSoup(html_body, 'html.parser')
             for script_or_style in soup(["script", "style"]):
                 script_or_style.extract()
             text = soup.get_text(separator='\n')
             text = os.linesep.join([s.strip() for s in text.splitlines() if s.strip()])
             return text.strip()
         except Exception as e:
             print(f"警告: 从 HTML 部分提取文本失败 - {e}")
             return "" # 提取失败

    # 如果邮件没有 text/plain 或 text/html 部分
    return ""

# --- 数据库配置 ---
DATABASE_FILE = 'emails.db' # 数据库文件名，会创建在脚本所在的目录下

# --- 数据库操作函数 ---
def create_database_and_table(db_file):
    """创建一个SQLite数据库文件和emails表，如果它们不存在的话"""
    conn = None
    try:
        # 连接到数据库（如果文件不存在会自动创建）
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        print(f"数据库连接成功: {db_file}")

        # 创建 emails 表
        # id: IMAP UID (TEXT, 主键，唯一标识一封邮件)
        # subject: 邮件主题 (TEXT)
        # sender: 发件人 (TEXT)
        # date: 日期 (TEXT)
        # body: 提取的纯文本正文 (TEXT)
        # raw_email: 原始邮件内容 bytes (BLOB)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS emails (
                id TEXT PRIMARY KEY,
                subject TEXT,
                sender TEXT,
                date TEXT,
                body TEXT,
                raw_email BLOB,
                -- 新增字段用于存储 AI 结果
                classification TEXT,
                classification_reason TEXT, -- 用于存储分类理由
                summary TEXT,              -- 用于存储摘要
                reply_suggestion TEXT,     -- 用于存储回复建议
                ai_processed_at TEXT       -- 记录AI处理时间或状态
            )
        ''')
        conn.commit() # 提交更改
        print("数据表 'emails' 创建或已存在。")

    except sqlite3.Error as e:
        print(f"数据库错误（创建表）: {e}")
    finally:
        # 确保关闭连接
        if conn:
            conn.close()
            # print("数据库连接关闭。") # 如果需要，可以在这里加日志

def insert_email_data(db_file, email_data):
    """
    将一封邮件的数据插入到emails表中。
    如果邮件ID已存在，则跳过插入。
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 准备数据
        # 使用 .get() 方法从字典安全获取数据，避免 KeyError
        email_id = email_data.get('id')
        subject = email_data.get('subject')
        sender = email_data.get('from')
        date = email_data.get('date')
        # 存储完整的提取出的正文
        body = email_data.get('full_body', '') # 如果 full_body 不存在则给空字符串
        raw_email = email_data.get('raw_email')

        if not email_id:
             print("警告：邮件数据缺少 ID，无法插入数据库。")
             return

        # 检查是否已存在相同的 ID，避免重复插入
        cursor.execute('SELECT id FROM emails WHERE id = ?', (email_id,))
        if cursor.fetchone() is not None:
            # print(f"邮件 ID {email_id} 已存在，跳过插入。") # 调试时可以 uncomment
            return # 如果已存在，则直接返回，不进行插入

        # 插入数据
        cursor.execute('''
            INSERT INTO emails (id, subject, sender, date, body, raw_email)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (email_id, subject, sender, date, body, raw_email))

        conn.commit() # 提交更改
        # print(f"成功插入邮件 ID: {email_id}") # 调试时可以 uncomment

    except sqlite3.Error as e:
        print(f"数据库插入错误: {e}")
    finally:
        if conn:
            conn.close()
            # print("数据库连接关闭。") # 如果需要，可以在这里加日志


# --- 修改 fetch_latest_emails 函数 ---
# 添加 db_file 参数
def fetch_latest_emails(server, port, address, password, mailbox='INBOX', num_emails=5, db_file=DATABASE_FILE):
    """
    连接到IMAP服务器，获取最近的邮件，并将其存储到数据库。
    同时返回获取到的邮件概要信息列表用于显示。
    """
    # ... (函数开始部分的配置检查和连接、登录、选择文件夹代码不变) ...
    if not password:
        print("错误：未设置 EMAIL_PASSWORD 环境变量。请在运行脚本前设置它。")
        return [] # 返回空列表

    messages_for_display = [] # 用于存储要返回显示的信息列表
    mail = None

    try:
        print(f"尝试连接到 {server}:{port} ...")
        mail = imaplib.IMAP4_SSL(server, port)
        print("连接成功。")
        mail.login(address, password)
        print(f"成功登录为 {address}")
        status, message_count_data = mail.select(mailbox)
        if status != 'OK':
            print(f"错误：无法选择邮箱文件夹 '{mailbox}' - {message_count_data[0].decode()}")
            return [] # 返回空列表
        message_count = int(message_count_data[0])
        print(f"已选择文件夹 '{mailbox}'，共 {message_count} 封邮件。")

        if message_count == 0:
            print("文件夹中没有邮件。")
            return [] # 返回空列表

        # 搜索邮件 (这里仍然搜索所有邮件以便演示插入，实际应用可以只搜索新邮件)
        status, data = mail.search(None, 'ALL') # 搜索所有邮件
        if status != 'OK':
            print(f"错误：搜索邮件失败 - {data}")
            return [] # 返回空列表

        email_ids = data[0].split()
        if not email_ids:
             print("搜索结果为空，没有找到符合条件的邮件。")
             return [] # 返回空列表

        # 获取最新的 num_emails 封邮件的ID
        latest_email_ids = email_ids[-num_emails:]
        print(f"正在获取最近的 {len(latest_email_ids)} 封邮件详情并存储到数据库...")

        # 遍历邮件ID，获取邮件内容并存储到数据库
        inserted_count = 0
        for email_id_bytes in latest_email_ids: # 邮件ID是bytes类型
            email_id = email_id_bytes.decode() # 转换为字符串作为数据库主键

            # 为了避免重复插入，先检查数据库中是否已存在
            # 注意：更高效的方式是在获取ID列表后，一次性查询数据库中已存在的ID
            # 但为了简单演示，这里在循环中逐个检查和插入
            conn_check = None
            try:
                conn_check = sqlite3.connect(db_file)
                cursor_check = conn_check.cursor()
                cursor_check.execute('SELECT id FROM emails WHERE id = ?', (email_id,))
                if cursor_check.fetchone() is not None:
                    # print(f"邮件 ID {email_id} 已存在，跳过处理。") # 调试时可以 uncomment
                    continue # 如果已存在则跳过当前循环，处理下一封
            except sqlite3.Error as e:
                 print(f"数据库检查邮件 ID {email_id} 存在性失败: {e}")
                 continue # 数据库检查失败也跳过当前邮件
            finally:
                if conn_check:
                     conn_check.close()


            # 如果 ID 不存在，则继续获取邮件详情并插入
            status, msg_data = mail.fetch(email_id_bytes, '(RFC822)') # fetch需要bytes ID
            if status != 'OK':
                print(f"错误：获取邮件 ID {email_id} 失败 - {msg_data}")
                continue # 获取失败，跳过

            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            # 解码头部信息和获取正文
            subject = decode_mail_header(msg.get('Subject', '无主题'))
            sender = decode_mail_header(msg.get('From', '无发件人'))
            date = msg.get('Date', '无日期')
            body = get_email_body_improved(msg) # 使用改进后的函数获取正文

            # 准备要插入数据库的数据字典
            email_data_to_save = {
                'id': email_id, # 字符串ID
                'subject': subject,
                'from': sender,
                'date': date,
                'full_body': body, # 存储提取出的正文
                'raw_email': raw_email # 存储原始 bytes 内容
            }

            # 将数据插入数据库
            insert_email_data(db_file, email_data_to_save)
            inserted_count += 1 # 计数成功插入的数量

            # 同时，将概要信息添加到返回列表中用于立即显示
            messages_for_display.append({
                'id': email_id,
                'subject': subject,
                'from': sender,
                'date': date,
                'body_snippet': body[:500] + '...' if len(body) > 500 else body # 截取片段用于显示
            })


    except imaplib.IMAP4.error as e:
        print(f"IMAP 错误: {e}")
    except Exception as e:
        print(f"发生了一个意外错误: {e}")
    finally:
        # 确保连接关闭
        if mail:
            try:
                mail.logout()
                print("已从 IMAP 服务器登出。")
            except Exception as e:
                print(f"登出时发生错误: {e}")

    print(f"完成邮件获取和数据库存储过程。成功处理并尝试插入 {len(latest_email_ids)} 封邮件，其中 {inserted_count} 封是新插入的。")
    return messages_for_display # 返回用于显示的信息列表


# --- 主程序执行部分 ---
if __name__ == "__main__":
    print("--- AI 邮件系统 - 邮件获取模块演示 ---")

    # 在运行此脚本之前，请确保已设置 EMAIL_SERVER, EMAIL_ADDRESS
    # 并且最重要的是，设置了 EMAIL_PASSWORD 环境变量。
    #
    # 在终端中运行脚本的示例 (请替换为您的实际信息)：
    # export EMAIL_SERVER='imap.gmail.com'
    # export EMAIL_PORT=993 # 或您的服务器端口
    # export EMAIL_ADDRESS='your_email@example.com'
    # export EMAIL_PASSWORD='您的应用专用密码或邮箱密码' # !!! 注意安全 !!!
    # python fetch_mail.py
    #
    # 或者，您可以在脚本运行前手动设置环境变量（仅对当前终端会话有效）：
    # import os
    # os.environ['EMAIL_SERVER'] = 'imap.gmail.com'
    # os.environ['EMAIL_PORT'] = '993' # 注意环境变量是字符串
    # os.environ['EMAIL_ADDRESS'] = 'your_email@example.com'
    # os.environ['EMAIL_PASSWORD'] = '您的应用专用密码或邮箱密码' # !!! 注意安全 !!!

    # 再次从环境变量获取配置（如果上面没设置，这里可能还是 None 或默认值）
    # 使用 os.getenv 比 os.environ.get 更简洁
    server = os.getenv('EMAIL_SERVER', 'imap.gmail.com')
    port = int(os.getenv('EMAIL_PORT', 993)) # 端口通常是数字，转为 int
    address = os.getenv('EMAIL_ADDRESS', '2095667048lj@gmail.com')
    password = os.getenv('EMAIL_PASSWORD')


    # 定义数据库文件名
    DATABASE_FILE = 'emails.db'


    if address == 'your_email@example.com' or not password or server == 'your_imap_server.com':
         # ... (配置不完整提示不变) ...
         print("\n*** 配置不完整 ***")
         print("请确保已设置 EMAIL_SERVER, EMAIL_ADDRESS 和 EMAIL_PASSWORD 环境变量。")
         print("例如：export EMAIL_SERVER='imap.gmail.com' && export EMAIL_ADDRESS='your_email@example.com' && export EMAIL_PASSWORD='您的密码'")
         print("*****************\n")
    else:
        print(f"配置信息：\n  服务器: {server}\n  邮箱: {address}\n  端口: {port}")

        # 1. 创建数据库和表（每次运行都调用，如果已存在则不做任何事）
        create_database_and_table(DATABASE_FILE)

        # 2. 调用获取邮件函数，将数据库文件名传递进去
        # fetch_latest_emails 函数现在会负责将获取到的邮件存储到数据库
        # 同时返回用于此处显示的概要信息列表
        messages_info_to_print = fetch_latest_emails(
            server, port, address, password,
            mailbox='INBOX', # 可以改为 MAILBOX 变量
            num_emails=5, # 您可以调整获取的数量
            db_file=DATABASE_FILE # 将数据库文件名传递给函数
        )

        # 3. 打印获取到的邮件概要信息
        if messages_info_to_print:
             print(f"\n最近获取到的 {len(messages_info_to_print)} 封邮件概要信息 (已尝试存储到数据库 {DATABASE_FILE})：")
             for i, email_info in enumerate(messages_info_to_print):
                 print("-" * 30)
                 print(f"邮件 {i+1} (ID: {email_info['id']}):")
                 print(f"发件人: {email_info['from']}")
                 print(f"主题: {email_info['subject']}")
                 print(f"日期: {email_info['date']}")
                 print(f"正文片段: {email_info['body_snippet']}") # 使用函数返回的片段
        else:
             print(f"\n未能获取到新的邮件或所有获取到的邮件都已存在于数据库 {DATABASE_FILE} 中。")
             # 可选：添加查询数据库总邮件数量的代码
             conn = None
             try:
                 conn = sqlite3.connect(DATABASE_FILE)
                 cursor = conn.cursor()
                 cursor.execute('SELECT COUNT(*) FROM emails')
                 count = cursor.fetchone()[0]
                 print(f"目前数据库 {DATABASE_FILE} 中共有 {count} 封邮件记录。")
             except sqlite3.Error as e:
                 print(f"查询数据库邮件数量失败: {e}")
             finally:
                 if conn:
                     conn.close()
