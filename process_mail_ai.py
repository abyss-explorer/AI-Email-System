import sqlite3
import os
import google.generativeai as genai
from datetime import datetime
# 如果您之前添加了列出模型的代码，请现在删除或注释掉它

# --- 配置信息 ---
DATABASE_FILE = 'emails.db' # 数据库文件名
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# --- AI 模型配置 ---
# 从上次成功的列表中选择一个模型名称
# 例如：models/gemini-pro, models/gemini-1.5-pro-latest, models/gemini-1.5-flash-latest
# 请替换成您实际能用的模型名称
AI_MODEL_NAME = 'models/gemini-1.5-flash-latest' # <-- 请替换为您选择并验证可用的模型名称

# --- AI 提示词 ---
# 使用之前设计好的提示词模板
CLASSIFICATION_PROMPT_TEMPLATE = """
请根据以下邮件内容，将其分类为以下之一：工作、个人、广告、垃圾邮件。请提供分类理由。

邮件内容：
{email_body}

输出格式：
分类：[分类结果]
理由：[简要理由说明]
"""

SUMMARY_PROMPT_TEMPLATE = """
请为以下邮件生成一段简洁的摘要，保留关键信息，长度控制在50-100字。

邮件内容：
{email_body}

摘要：
""" # 在末尾添加 "摘要：" 方便后续解析

REPLY_PROMPT_TEMPLATE = """
请根据以下邮件内容，生成一段礼貌且专业的回复草稿：

邮件内容：
{email_body}

回复建议：
""" # 在末尾添加 "回复建议：" 方便后续解析


# --- 数据库操作函数 ---
# 修改函数以获取多封未处理邮件
def get_unprocessed_emails(db_file, limit=None):
    """从数据库获取未进行 AI 分类的邮件列表"""
    conn = None
    emails_data = []
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 查询 classification 字段为空或为 'AI处理失败' 的邮件 (可以根据需要调整 WHERE 条件)
        query = '''
            SELECT id, subject, sender, date, body
            FROM emails
            WHERE classification IS NULL OR classification = '' OR classification = 'AI处理失败'
        '''
        if limit is not None:
            query += f' LIMIT {limit}' # 添加 limit 子句如果需要限制数量

        cursor.execute(query)
        rows = cursor.fetchall() # 获取所有符合条件的行

        for row in rows:
             # 将查询结果映射到字典列表
            emails_data.append({
                'id': row[0],
                'subject': row[1],
                'sender': row[2],
                'date': row[3],
                'body': row[4]
            })

    except sqlite3.Error as e:
        print(f"数据库错误（获取未处理邮件列表）: {e}")
    finally:
        if conn:
            conn.close()

    return emails_data

# 修改函数以更新所有 AI 结果字段
def update_email_ai_results(db_file, email_id, classification, classification_reason, summary, reply_suggestion):
    """更新邮件的 AI 处理结果到数据库"""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        processed_time = datetime.now().isoformat() # 获取当前时间字符串

        cursor.execute('''
            UPDATE emails
            SET classification = ?,
                classification_reason = ?,
                summary = ?,
                reply_suggestion = ?,
                ai_processed_at = ?
            WHERE id = ?
        ''', (classification, classification_reason, summary, reply_suggestion, processed_time, email_id))

        conn.commit()
        #print(f"成功更新邮件 ID {email_id} 的 AI 处理结果。") # 调试时可以 uncomment

    except sqlite3.Error as e:
        print(f"数据库错误（更新 AI 结果）: {e}")
    finally:
        if conn:
            conn.close()

# --- AI 处理函数 ---
# 添加函数用于摘要和回复建议

def call_ai_model(prompt):
    """通用函数：调用 AI 模型生成内容"""
    if not GOOGLE_API_KEY:
        # print("错误：未设置 GOOGLE_API_KEY 环境变量。") # 在主程序检查即可，避免重复打印
        return None

    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel(AI_MODEL_NAME) # 使用上面定义的模型名称

        # 调用 AI 模型生成内容
        response = model.generate_content(prompt)

        # 检查响应是否被阻断或发生错误
        if not hasattr(response, 'text'):
            # 打印更多错误信息，例如 blockage reason
            # print("AI 响应没有文本内容。原始响应对象:", response)
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback.block_reason:
                 return f"Prompt Blocked: {response.prompt_feedback.block_reason.name}"
            if hasattr(response, 'candidates') and response.candidates:
                 candidate = response.candidates[0]
                 if candidate.finish_reason:
                     return f"Generation Failed: {candidate.finish_reason.name}"
            return "AI响应异常或被屏蔽" # 通用错误信息


        return response.text.strip() # 返回提取出的文本内容

    except Exception as e:
        # print(f"调用 AI 模型失败: {e}") # 在调用处处理错误并记录
        return f"调用 AI 模型失败: {e}"


def classify_email_with_ai(email_body):
    """使用 AI 模型对邮件正文进行分类和提供理由"""
    prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(email_body=email_body)
    ai_response_text = call_ai_model(prompt)

    classification = "AI处理失败"
    reason = ai_response_text if ai_response_text.startswith("调用 AI 模型失败") or ai_response_text.startswith("Prompt Blocked") or ai_response_text == "AI响应异常或被屏蔽" else "无法解析AI输出"

    if ai_response_text and not (ai_response_text.startswith("调用 AI 模型失败") or ai_response_text.startswith("Prompt Blocked") or ai_response_text == "AI响应异常或被屏蔽"):
        # 尝试解析输出格式 (分类和理由)
        lines = ai_response_text.split('\n')
        for line in lines:
            if line.startswith('分类：'):
                classification = line.replace('分类：', '').strip()
            elif line.startswith('理由：'):
                reason = line.replace('理由：', '').strip()
            if classification != "AI处理失败" and reason != "无法解析AI输出":
                break # 如果找到分类和理由，就停止查找

    return classification, reason

def summarize_email_with_ai(email_body):
    """使用 AI 模型对邮件正文生成摘要"""
    prompt = SUMMARY_PROMPT_TEMPLATE.format(email_body=email_body)
    ai_response_text = call_ai_model(prompt)

    summary = ai_response_text if ai_response_text and not (ai_response_text.startswith("调用 AI 模型失败") or ai_response_text.startswith("Prompt Blocked") or ai_response_text == "AI响应异常或被屏蔽") else "AI摘要失败"

    # 如果响应文本以 "摘要：" 开头，则去除前缀
    if summary.startswith("摘要："):
        summary = summary.replace("摘要：", "").strip()

    return summary

def suggest_reply_with_ai(email_body):
    """使用 AI 模型为邮件正文生成回复建议"""
    prompt = REPLY_PROMPT_TEMPLATE.format(email_body=email_body)
    ai_response_text = call_ai_model(prompt)

    reply_suggestion = ai_response_text if ai_response_text and not (ai_response_text.startswith("调用 AI 模型失败") or ai_response_text.startswith("Prompt Blocked") or ai_response_text == "AI响应异常或被屏蔽") else "AI回复建议失败"

    # 如果响应文本以 "回复建议：" 开头，则去除前缀
    if reply_suggestion.startswith("回复建议："):
        reply_suggestion = reply_suggestion.replace("回复建议：", "").strip()

    return reply_suggestion

# --- 数据库查看函数 ---
def view_emails_in_db(db_file, limit=10):
    """连接到数据库并打印 emails 表中的邮件概要和 AI 结果"""
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        print(f"\n--- 数据库 {db_file} 中的邮件数据 (最近 {limit} 条) ---")

        # 查询邮件数据，包括 AI 结果
        # 仅选择部分重要字段打印，避免输出过长
        # ORDER BY id DESC 通常能获取到最近的邮件，因为 IMAP ID 递增
        cursor.execute(f'''
            SELECT id, subject, sender, classification, summary, reply_suggestion, ai_processed_at
            FROM emails
            ORDER BY id DESC
            LIMIT {limit}
        ''')

        rows = cursor.fetchall() # 获取所有符合条件的行
        # 获取列名，用于打印头部
        column_names = [description[0] for description in cursor.description]

        if not rows:
            print("数据表中没有邮件记录。")
            return

        # 打印表头
        # print(" | ".join(column_names)) # 简单的头部，可能不对齐
        # 为了更好的对齐，可以考虑更复杂的格式化，但简单起见先用这个

        # 打印每一行数据
        # 简单格式化每一列数据，避免过长，并处理 None 值和换行符
        for i, row in enumerate(rows):
            print("-" * 60) # 行分隔线
            print(f"记录 {i+1}:")
            for col_name, item in zip(column_names, row):
                 formatted_item = "NULL" if item is None else str(item)
                 # 对较长的字段进行截断并处理换行符
                 if col_name in ['body', 'raw_email', 'summary', 'reply_suggestion']:
                      display_length = 100 # 控制片段长度
                      formatted_item = formatted_item.replace('\n', '\\n').replace('\r', '\\r') # 将换行符可视化
                      if len(formatted_item) > display_length + 3:
                           formatted_item = formatted_item[:display_length] + '...'


                 print(f"  {col_name}: {formatted_item}")

        print("-" * 60) # 结束分隔线


    except sqlite3.Error as e:
        print(f"数据库读取错误: {e}")
    finally:
        if conn:
            conn.close()

# --- 主程序执行部分 ---
if __name__ == "__main__":
    print("--- AI 邮件系统 - AI 处理模块演示 ---")

    if not GOOGLE_API_KEY:
        print("\n*** AI 配置不完整 ***")
        print("请设置 GOOGLE_API_KEY 环境变量。")
        print("例如：export GOOGLE_API_KEY='您的API Key'")
        print("*****************\n")
    elif AI_MODEL_NAME == 'models/your-chosen-model': # 提醒用户替换模型名称
         print(f"\n*** AI 模型配置不完整 ***")
         print(f"请修改脚本中的 AI_MODEL_NAME = '{AI_MODEL_NAME}' 为您实际可用的模型名称。")
         print("可以运行之前的列出模型代码来查看列表。")
         print("*****************\n")
    else:
        # 1. 从数据库获取未处理的邮件列表
        # 您可以设置 limit=10 来限制每次处理的数量，方便测试
        print(f"从数据库 {DATABASE_FILE} 获取未处理的邮件...")
        emails_to_process = get_unprocessed_emails(DATABASE_FILE)

        if emails_to_process:
            print(f"获取到 {len(emails_to_process)} 封未处理的邮件，开始进行 AI 处理...")

            processed_count = 0
            error_count = 0

            # 遍历邮件列表，逐个进行 AI 处理
            for email_data in emails_to_process:
                email_id = email_data['id']
                email_body = email_data['body']
                email_subject = email_data['subject'] # 可以用于日志或调试

                print(f"\n--- 处理邮件 ID: {email_id}, 主题: {email_subject} ---")

                # 检查邮件正文是否为空，空邮件不进行AI处理
                if not email_body or email_body.strip() == "":
                    print(f"邮件 ID {email_id} 正文为空，跳过 AI 处理。")
                    update_email_ai_results(
                        DATABASE_FILE,
                        email_id,
                        "无正文", # 分类标记为无正文
                        "邮件正文为空，跳过AI处理。",
                        "", # 摘要为空
                        "" # 回复建议为空
                    )
                    processed_count += 1 # 也算作已处理，只是结果特殊
                    continue # 跳到下一封邮件

                try:
                    # 2. 依次调用 AI 模型进行分类、摘要和回复建议
                    # 每次调用都处理潜在的API错误
                    classification, reason = classify_email_with_ai(email_body)
                    print(f"  分类结果: {classification}")

                    summary = summarize_email_with_ai(email_body)
                    print(f"  摘要结果: {summary[:100] + '...' if len(summary) > 100 else summary}") # 打印摘要片段

                    reply_suggestion = suggest_reply_with_ai(email_body)
                    print(f"  回复建议片段: {reply_suggestion[:100] + '...' if len(reply_suggestion) > 100 else reply_suggestion}") # 打印建议片段

                    # 3. 将所有 AI 结果更新回数据库
                    update_email_ai_results(
                        DATABASE_FILE,
                        email_id,
                        classification,
                        reason,
                        summary,
                        reply_suggestion
                    )
                    print(f"  邮件 ID {email_id} 的 AI 结果已保存到数据库。")
                    processed_count += 1

                except Exception as e:
                    # 处理在单个邮件处理过程中发生的任何意外错误
                    print(f"处理邮件 ID {email_id} 时发生意外错误: {e}")
                    error_count += 1
                    # 可选：将错误状态记录到数据库
                    update_email_ai_results(
                        DATABASE_FILE,
                        email_id,
                        "内部错误", # 标记分类为内部错误
                        f"处理时发生意外错误: {e}",
                        "", "", # 摘要和建议为空
                    )


            print(f"\n--- AI 处理完成 ---")
            print(f"总共处理了 {len(emails_to_process)} 封邮件。成功处理 {processed_count} 封，处理时发生错误 {error_count} 封。")


        else:
            print(f"数据库 {DATABASE_FILE} 中没有找到未进行 AI 分类的邮件。")
            print("请先运行 fetch_mail.py 获取一些邮件，或检查是否有 AI 处理失败的邮件需要重试。")



