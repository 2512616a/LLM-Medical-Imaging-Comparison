import os
import requests
import glob
from pathlib import Path
import time
import concurrent.futures
import random
import threading
from tqdm import tqdm
import shutil
import json
import sys

def load_api_keys(key_file):
    """
    从文件中加载API密钥列表
    """
    print(f"[信息] 正在从 {key_file} 加载API密钥")
    keys = []
    try:
        with open(key_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # 提取所有以sk-开头的字符串
            import re
            keys = re.findall(r'"sk-[a-zA-Z0-9]+"', content)
            # 去除引号
            keys = [key.strip('"') for key in keys]
        print(f"[信息] 成功加载 {len(keys)} 个API密钥")
        return keys
    except Exception as e:
        print(f"[错误] 加载API密钥失败: {e}")
        return ["sk-axcmjwcwfeigofmpqbqjghoczpknqfklxeewdebezshrpmmm"]  # 返回默认密钥

def load_questions(question_file):
    """
    从JSON文件中加载题库
    """
    print(f"[信息] 正在从 {question_file} 加载题库")
    try:
        with open(question_file, 'r', encoding='utf-8') as f:
            questions = json.load(f)
        print(f"[信息] 成功加载 {len(questions)} 道题目")
        return questions
    except Exception as e:
        print(f"[错误] 加载题库失败: {e}")
        return []

def get_answer_from_ai(question_data, api_key):
    """
    调用API让AI判断题目是否与指定的医学影像学方向相关
    """
    question = question_data.get('question', '')
    correct_answer = question_data.get('answer', '')
    
    # 如果题目为空，直接返回错误
    if not question.strip():
        print(f"[警告] 题目内容为空，跳过API调用")
        return False, "题目为空", None
    
    url = "https://api.siliconflow.cn/v1/chat/completions"
    
    # 修改提示词，要求AI判断题目是否与指定的医学影像学方向相关
    prompt = """
    你是一个专业的医学影像学专家，请仔细分析下面的医学题目，判断这道题目是否与以下医学影像学方向相关：

    目标方向：
    1. X线影像学（包括普通X线、数字化X线、胸片、骨片等）
    2. CT影像学（计算机断层扫描）
    3. MRI影像学（磁共振成像）
    4. 超声影像学（超声检查、彩超等）
    5. 核医学影像学（PET、SPECT、同位素扫描等）

    要求：
    1. 仔细阅读题目内容和选项
    2. 判断题目是否与上述5个方向中的任意一个相关
    3. 如果相关，请明确指出是哪个方向（只能选择一个最主要的方向）
    4. 如果不相关或无法确定，请返回"不相关"

    请按以下JSON格式回答：
    {
      "category": "X线/CT/MRI/超声/核医学/不相关",
      "reasoning": "判断的简要理由"
    }

    只输出JSON格式，不要添加其他解释。
    """
    
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": question
            }
        ],
        "stream": False,
        "max_tokens": 1000,
        "temperature": 0.1,
        "top_p": 0.9,
        "response_format": {"type": "json_object"}
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        print(f"[调试] 发送API请求...")
        response = requests.post(url, json=payload, headers=headers)
        
        print(f"[调试] API响应状态码: {response.status_code}")
        response.raise_for_status()
        result = response.json()
        
        # 提取API返回的内容
        ai_response = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        print(f"[调试] AI回答长度: {len(ai_response)} 字符")
        
        # 验证JSON格式是否正确
        try:
            json_data = json.loads(ai_response)
            category = json_data.get("category", "").strip()
            reasoning = json_data.get("reasoning", "").strip()
            
            # 构建完整的结果，保持原有格式并添加category字段
            complete_result = {
                "question": question,
                "answer": correct_answer,
                "category": category,
                "reasoning": reasoning,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            return True, None, json.dumps(complete_result, ensure_ascii=False, indent=2)
            
        except json.JSONDecodeError as e:
            print(f"[警告] AI回答不是有效的JSON格式: {e}")
            return False, f"AI返回的内容不是有效的JSON格式: {e}", None
        
    except Exception as e:
        print(f"[错误] API调用出错: {e}")
        return False, str(e), None

def process_single_question(args):
    """
    处理单个题目，让AI回答
    """
    question_data, output_dir, api_key, index, total, progress_bar, key_status, failed_questions, processed_questions, result_lock, category_results = args
    
    # 更新当前密钥状态
    key_id = api_key[:8]
    question_preview = question_data.get('question', '')[:50] + "..." if len(question_data.get('question', '')) > 50 else question_data.get('question', '')
    
    with result_lock:
        key_status[key_id] = f"处理题目 {index+1}"
    
    error_info = None
    
    try:
        # 调用API让AI回答题目
        success, error, ai_result = get_answer_from_ai(question_data, api_key)
        
        if not success:
            raise Exception(f"API调用失败: {error}")
        
        # 解析AI返回的结果
        result_data = json.loads(ai_result)
        category = result_data.get("category", "不相关")
        reasoning = result_data.get("reasoning", "")
        
        # 根据分类结果保存到对应的列表中
        with result_lock:
            if category in ["X线", "CT", "MRI", "超声", "核医学"]:
                # 保持原有的题目格式
                original_format_question = {
                    "question": question_data.get("question", ""),
                    "answer": question_data.get("answer", "")
                }
                # 添加到对应分类的结果中
                if category not in category_results:
                    category_results[category] = []
                category_results[category].append(original_format_question)
                
                # 记录处理的题目
                processed_questions.append({
                    "index": index + 1,
                    "question_preview": question_preview,
                    "original_answer": result_data["answer"],
                    "category": category,
                    "reasoning": reasoning,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S")
                })
        
        print(f"[分类] 题目 {index+1} 分类为: {category}")
        result = (True, True, 0, None, None)  # 处理成功，保存成功
            
    except Exception as e:
        error_info = f"题目处理错误: {str(e)}"
        # 将失败题目记录
        with result_lock:
            failed_questions.append({
                "index": index + 1,
                "question": question_data,
                "error": error_info,
                "time": time.strftime("%Y-%m-%d %H:%M:%S")
            })
        result = (False, False, 0, index+1, error_info)  # 处理失败
        
        # 更新密钥状态，包含错误信息
        with result_lock:
            key_status[key_id] = f"题目{index+1}: 失败 - {str(e)[:30]}..."
    
    # 更新进度条
    progress_bar.update(1)
    
    # 5秒后将密钥状态设为空闲
    def clear_status():
        time.sleep(5)
        with result_lock:
            key_status[key_id] = "空闲"
    
    threading.Thread(target=clear_status, daemon=True).start()
    
    return result

def clear_console():
    """清除控制台内容"""
    os.system('cls' if os.name == 'nt' else 'clear')

def save_category_files(output_dir, category_results):
    """
    保存分类结果到5个JSON文件
    """
    categories = ["X线", "CT", "MRI", "超声", "核医学"]
    saved_files = []
    
    for category in categories:
        questions = category_results.get(category, [])
        if questions:  # 只有当该分类有题目时才创建文件
            filename = f"{category}_questions.json"
            filepath = os.path.join(output_dir, filename)
            
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(questions, f, ensure_ascii=False, indent=2)
                print(f"[保存] {category}相关题目已保存到: {filepath} (共{len(questions)}道题目)")
                saved_files.append((category, filepath, len(questions)))
            except Exception as e:
                print(f"[错误] 保存{category}题目文件时出错: {e}")
        else:
            print(f"[信息] {category}分类中没有相关题目，跳过文件创建")
    
    return saved_files

def generate_reports(output_dir, processed_questions, failed_questions, total_elapsed, 
                    total_questions, processed_count, success_count, error_count, key_usage_count, category_results):
    """
    生成医学影像学分类统计报告（Markdown格式）
    """
    try:
        # 计算各分类统计
        category_stats = {}
        for category, questions in category_results.items():
            category_stats[category] = len(questions)
        
        # 生成分类报告（Markdown格式）
        report_file = os.path.join(output_dir, f"classification_report_{time.strftime('%Y%m%d_%H%M%S')}.md")
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("# AI题库医学影像学分类报告\n\n")
            f.write(f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("## 基本统计\n\n")
            f.write(f"| 统计项目 | 数值 |\n")
            f.write(f"|---------|------|\n")
            f.write(f"| 总题目数 | {total_questions} |\n")
            f.write(f"| 成功处理题目数 | {processed_count} |\n")
            f.write(f"| 成功分类题目数 | {success_count} |\n")
            f.write(f"| 处理失败数 | {error_count} |\n")
            f.write(f"| 总处理时间 | {total_elapsed:.2f} 秒 |\n")
            if processed_count > 0:
                f.write(f"| 平均每题处理时间 | {total_elapsed/processed_count:.2f} 秒 |\n")
                f.write(f"| 实际吞吐量 | {processed_count/total_elapsed:.2f} 题目/秒 |\n")
            
            f.write("\n## 医学影像学分类分布统计\n\n")
            f.write(f"| 影像学分类 | 题目数量 | 占比 |\n")
            f.write(f"|---------|---------|------|\n")
            
            # 按数量排序显示分类
            sorted_categories = sorted(category_stats.items(), key=lambda x: x[1], reverse=True)
            total_classified = sum(category_stats.values())
            
            for category, count in sorted_categories:
                percentage = (count / total_classified * 100) if total_classified > 0 else 0
                f.write(f"| {category} | {count} | {percentage:.1f}% |\n")
            
            # 添加不相关题目的统计
            unrelated_count = total_questions - total_classified - error_count
            if unrelated_count > 0:
                unrelated_percentage = (unrelated_count / total_questions * 100) if total_questions > 0 else 0
                f.write(f"| 不相关题目 | {unrelated_count} | {unrelated_percentage:.1f}% |\n")
            
            if processed_questions:
                f.write("\n## 题目详细分类结果\n\n")
                f.write("| 题目编号 | 题目预览 | 原答案 | 分类结果 | 处理时间 |\n")
                f.write("|---------|---------|--------|----------|----------|\n")
                
                for q in processed_questions:
                    preview = q["question_preview"][:50] + "..." if len(q["question_preview"]) > 50 else q["question_preview"]
                    f.write(f"| {q['index']} | {preview} | {q['original_answer']} | {q['category']} | {q['time']} |\n")
            
            f.write("\n## API密钥使用统计\n\n")
            f.write("| 密钥编号 | 使用次数 |\n")
            f.write("|---------|----------|\n")
            for key, count in key_usage_count.items():
                f.write(f"| {key[:8]}... | {count} |\n")
        
        print(f"[信息] 医学影像学分类报告已保存到: {report_file}")
        
        # 生成处理失败题目报告（如果有的话）
        if failed_questions:
            failed_report_file = os.path.join(output_dir, f"failed_questions_report_{time.strftime('%Y%m%d_%H%M%S')}.md")
            
            with open(failed_report_file, 'w', encoding='utf-8') as f:
                f.write("# 处理失败题目报告\n\n")
                f.write(f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                f.write(f"**失败题目统计**: 共 {len(failed_questions)} 道题目\n\n")
                
                f.write("## 失败题目详情\n\n")
                
                for i, q in enumerate(failed_questions, 1):
                    f.write(f"### 失败题目 {i} (原题目编号: {q['index']})\n\n")
                    f.write(f"**错误信息**: {q['error']}\n\n")
                    f.write(f"**处理时间**: {q['time']}\n\n")
                    
                    question_content = q['question'].get('question', '题目内容获取失败')
                    f.write(f"**题目内容**:\n```\n{question_content}\n```\n\n")
                    f.write("---\n\n")
            
            print(f"[信息] 处理失败题目报告已保存到: {failed_report_file}")
        
    except Exception as e:
        print(f"[错误] 生成报告时出错: {e}")

def display_status(key_status, total_questions, start_time, progress_bar, result_lock, processed_questions):
    """
    定期显示处理状态，保持进度条在底部
    """
    while not progress_bar.disable:
        # 计算已经过去的时间
        elapsed_time = time.time() - start_time
        
        # 计算完成百分比
        with result_lock:
            completed = progress_bar.n
            processed_count = len(processed_questions)
        
        if completed > 0:
            # 估计剩余时间
            remaining_questions = total_questions - completed
            avg_time_per_question = elapsed_time / completed
            estimated_remaining_time = remaining_questions * avg_time_per_question
            
            # 格式化时间
            def format_time(seconds):
                hours, remainder = divmod(seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                return f"{int(hours)}小时{int(minutes)}分钟{int(seconds)}秒"
            
            # 清除控制台并重新显示状态
            clear_console()
            
            print(f"[进度] 已处理: {completed}/{total_questions} 题目 ({completed/total_questions*100:.1f}%)")
            print(f"[进度] 已完成分类: {processed_count} 道")
            print(f"[时间] 已用时间: {format_time(elapsed_time)}")
            print(f"[时间] 预计剩余: {format_time(estimated_remaining_time)}")
            print("\n[密钥状态]")
            
            with result_lock:
                for key, status in key_status.items():
                    print(f"  - 密钥 {key}: {status}")
            
            # 重新显示进度条
            progress_bar.refresh()
        
        # 等待一段时间后再次更新
        time.sleep(2)

def process_questions(question_file, output_dir, api_keys, max_workers=100):
    """
    并发处理题库中的所有题目，让AI分类医学影像学方向
    """
    print(f"[信息] 开始处理题库: {question_file}")
    print(f"[信息] 医学影像学分类结果保存目录: {output_dir}")
    
    # 设置失败题目记录目录
    fail_dir = "D:\\try\\2\\fail_questions"
    print(f"[信息] 失败题目记录目录: {fail_dir}")
    
    # 确保目标目录存在
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(fail_dir, exist_ok=True)
    
    # 加载题库
    questions = load_questions(question_file)
    if not questions:
        print("[错误] 题库为空或加载失败")
        return
    
    print(f"[信息] 找到 {len(questions)} 道题目")
    
    # 使用指定的线程数，最多100个
    num_workers = min(max_workers, len(api_keys), len(questions))
    print(f"[信息] 将使用 {num_workers} 个并发线程")
    
    # 只使用前num_workers个API密钥
    used_api_keys = api_keys[:num_workers]
    
    # 创建密钥状态字典和使用计数字典
    key_status = {key[:8]: "空闲" for key in used_api_keys}
    key_usage_count = {key: 0 for key in used_api_keys}
    
    # 创建线程锁，用于同步更新状态
    result_lock = threading.Lock()
    
    # 创建进度条
    progress_bar = tqdm(total=len(questions), desc="处理进度", unit="题目", 
                        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]")
    
    # 记录开始时间
    start_time = time.time()
    
    # 创建失败题目列表和处理题目列表
    failed_questions = []
    processed_questions = []
    category_results = {}  # 用于存储各分类的题目
    
    # 启动状态显示线程
    status_thread = threading.Thread(
        target=display_status, 
        args=(key_status, len(questions), start_time, progress_bar, result_lock, processed_questions)
    )
    status_thread.daemon = True
    status_thread.start()
    
    # 准备任务参数 - 每个题目分配一个API密钥（循环使用）
    tasks = []
    for i, question_data in enumerate(questions):
        # 为每个题目分配一个API密钥（循环使用）
        api_key = used_api_keys[i % len(used_api_keys)]
        # 增加该密钥的使用计数
        key_usage_count[api_key] += 1
        
        tasks.append((question_data, output_dir, api_key, i, len(questions), 
                     progress_bar, key_status, failed_questions, processed_questions, result_lock, category_results))
    
    processed_count = 0
    success_count = 0
    error_count = 0
    
    # 使用线程池并发处理题目
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        # 提交所有任务
        future_to_task = {executor.submit(process_single_question, task): task for task in tasks}
        
        # 处理结果
        for future in concurrent.futures.as_completed(future_to_task):
            try:
                processed, saved, _, failed_question, error_info = future.result()
                with result_lock:
                    if processed:
                        processed_count += 1
                        if saved:
                            success_count += 1
                    else:
                        error_count += 1
            except Exception as e:
                with result_lock:
                    error_count += 1
    
    # 关闭进度条
    progress_bar.close()
    
    # 计算总处理时间
    total_elapsed = time.time() - start_time
    
    # 保存分类结果到5个JSON文件
    saved_files = save_category_files(output_dir, category_results)
    
    # 保存失败题目列表到JSON文件
    if failed_questions:
        fail_log_file = os.path.join(fail_dir, f"failed_questions_{time.strftime('%Y%m%d_%H%M%S')}.json")
        try:
            with open(fail_log_file, 'w', encoding='utf-8') as f:
                json.dump(failed_questions, f, ensure_ascii=False, indent=2)
            print(f"[信息] 已保存失败题目列表到: {fail_log_file}")
        except Exception as e:
            print(f"[错误] 保存失败题目列表时出错: {e}")
    
    # 保存处理成功的题目列表到JSON文件
    if processed_questions:
        processed_log_file = os.path.join(output_dir, f"processed_questions_{time.strftime('%Y%m%d_%H%M%S')}.json")
        try:
            with open(processed_log_file, 'w', encoding='utf-8') as f:
                json.dump(processed_questions, f, ensure_ascii=False, indent=2)
            print(f"[信息] 已保存处理成功题目列表到: {processed_log_file}")
        except Exception as e:
            print(f"[错误] 保存处理成功题目列表时出错: {e}")
    
    # 生成准确率统计和错题汇总报告
    generate_reports(output_dir, processed_questions, failed_questions, total_elapsed, len(questions), 
                    processed_count, success_count, error_count, key_usage_count, category_results)
    
    # 清除控制台并显示最终结果
    clear_console()
    
    print(f"\n[统计] 处理完成!")
    print(f"[统计] 总题目数: {len(questions)}")
    print(f"[统计] 成功处理: {processed_count}")
    print(f"[统计] 成功分类: {success_count} 道")
    print(f"[统计] 处理失败: {error_count}")
    if error_count > 0:
        print(f"[统计] 失败题目记录保存到: {fail_dir}")
    print(f"[统计] 总处理时间: {total_elapsed:.2f} 秒")
    if processed_count > 0:
        print(f"[统计] 平均每题处理时间: {total_elapsed/processed_count:.2f} 秒")
        print(f"[统计] 实际吞吐量: {processed_count/total_elapsed:.2f} 题目/秒")
    
    # 显示医学影像学分类分布统计
    if category_results:
        print(f"\n[医学影像学分类分布统计]")
        categories = ["X线", "CT", "MRI", "超声", "核医学"]
        total_classified = sum(len(questions) for questions in category_results.values())
        
        for category in categories:
            count = len(category_results.get(category, []))
            percentage = (count / total_classified * 100) if total_classified > 0 else 0
            print(f"[分类] {category}: {count} 道题目 ({percentage:.1f}%)")
    
    # 显示保存的文件信息
    print(f"\n[文件保存统计]")
    for category, filepath, count in saved_files:
        print(f"[文件] {category}相关题目: {filepath} (共{count}道题目)")
    
    # 显示每个密钥的使用次数
    print("\n[密钥使用统计]")
    for key, count in key_usage_count.items():
        print(f"  - 密钥 {key[:8]}...: 使用了 {count} 次")

if __name__ == "__main__":
    print(f"[开始] 程序启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print("AI题库医学影像学分类程序")
    print("="*60)
    
    # 设置固定的题库文件路径
    question_file = r"D:\try\2\medical_questions.json"
    print(f"[信息] 使用题库文件: {question_file}")
    
    # 验证文件是否存在
    if not os.path.exists(question_file):
        print(f"[错误] 题库文件不存在: {question_file}")
        print("请确保文件路径正确")
        sys.exit(1)
    
    if not question_file.lower().endswith('.json'):
        print("[错误] 文件不是JSON格式")
        sys.exit(1)
    
    print(f"[信息] 题库文件验证成功: {question_file}")
    
    # 询问用户是否自定义输出目录
    output_choice = input("\n是否自定义医学影像学分类结果保存目录？(y/n，回车默认为n): ").strip().lower()
    
    if output_choice in ['y', 'yes']:
        while True:
            output_directory = input("请输入医学影像学分类结果保存目录的完整路径: ").strip()
            if not output_directory:
                print("[错误] 输出目录不能为空")
                continue
            
            try:
                # 尝试创建目录以验证路径有效性
                os.makedirs(output_directory, exist_ok=True)
                print(f"[信息] 输出目录设置成功: {output_directory}")
                break
            except Exception as e:
                print(f"[错误] 无法创建输出目录: {e}")
    else:
        # 基于题库文件路径创建默认输出目录
        question_dir = os.path.dirname(question_file)
        output_directory = os.path.join(question_dir, "medical_classification_results")
        print(f"[信息] 使用默认输出目录: {output_directory}")
    
    # 加载API密钥
    key_file = "D:\\try\\2\\614.md"
    print(f"\n[信息] 正在加载API密钥文件: {key_file}")
    api_keys = load_api_keys(key_file)
    
    if not api_keys:
        print("[错误] 无法加载API密钥，程序退出")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("配置信息确认")
    print("="*60)
    print(f"[配置] 题库文件: {question_file}")
    print(f"[配置] 医学影像学分类结果保存目录: {output_directory}")
    print(f"[配置] API密钥数量: {len(api_keys)}")
    print(f"[配置] 并发线程数: 100")
    print(f"[配置] 分类目标: X线、CT、MRI、超声、核医学")
    
    # 最终确认
    confirm = input("\n确认开始医学影像学分类处理？(y/n，回车默认为y): ").strip().lower()
    if confirm in ['n', 'no']:
        print("[信息] 用户取消处理，程序退出")
        sys.exit(0)
    
    print("\n" + "="*60)
    print("开始医学影像学分类处理")
    print("="*60)
    
    # 处理题目
    process_questions(question_file, output_directory, api_keys, max_workers=100)
    print(f"\n[结束] 程序结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
