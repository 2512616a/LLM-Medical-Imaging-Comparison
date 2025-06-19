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
    调用API让AI回答题目
    """
    question = question_data.get('question', '')
    correct_answer = question_data.get('answer', '')
    
    # 如果题目为空，直接返回错误
    if not question.strip():
        print(f"[警告] 题目内容为空，跳过API调用")
        return False, "题目为空", None
    
    url = "https://api.siliconflow.cn/v1/chat/completions"
    
    # 修改提示词，要求AI回答选择题
    prompt = """
    你是一个专业的医学专家，请仔细分析下面的选择题并给出正确答案。

    要求：
    1. 仔细阅读题目和所有选项
    2. 基于你的医学知识分析每个选项
    3. 给出你认为正确的答案选项（A、B、C、D或E）
    4. 简要说明选择该答案的理由

    请按以下JSON格式回答：
    {
      "selected_answer": "你选择的答案字母",
      "reasoning": "选择该答案的简要理由"
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
            ai_answer = json_data.get("selected_answer", "").strip()
            reasoning = json_data.get("reasoning", "").strip()
            
            # 构建完整的结果
            complete_result = {
                "question": question,
                "correct_answer": correct_answer,
                "ai_answer": ai_answer,
                "reasoning": reasoning,
                "is_correct": ai_answer.upper() == correct_answer.upper(),
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
    question_data, output_dir, api_key, index, total, progress_bar, key_status, failed_questions, processed_questions, result_lock = args
    
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
        
        # 获取目标文件路径
        output_file = os.path.join(output_dir, f"question_{index+1:04d}.json")
        
        # 确保目标目录存在
        os.makedirs(output_dir, exist_ok=True)
        
        # 将AI回答写入JSON文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(ai_result)
        
        # 记录处理的题目
        result_data = json.loads(ai_result)
        with result_lock:
            processed_questions.append({
                "index": index + 1,
                "question_preview": question_preview,
                "correct_answer": result_data["correct_answer"],
                "ai_answer": result_data["ai_answer"],
                "is_correct": result_data["is_correct"],
                "output_file": output_file,
                "time": time.strftime("%Y-%m-%d %H:%M:%S")
            })
        
        print(f"[保存] 题目 {index+1} 已处理，AI回答保存到 {output_file}")
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

def generate_reports(output_dir, processed_questions, failed_questions, total_elapsed, 
                    total_questions, processed_count, success_count, error_count, key_usage_count):
    """
    生成准确率统计报告和错题汇总报告（Markdown格式）
    """
    try:
        # 计算统计数据
        correct_answers = sum(1 for q in processed_questions if q["is_correct"])
        total_answers = len(processed_questions)
        accuracy = (correct_answers / total_answers * 100) if total_answers > 0 else 0
        wrong_answers = total_answers - correct_answers
        
        # 生成准确率统计报告（Markdown格式）
        accuracy_report_file = os.path.join(output_dir, f"accuracy_report_{time.strftime('%Y%m%d_%H%M%S')}.md")
        
        with open(accuracy_report_file, 'w', encoding='utf-8') as f:
            f.write("# AI题库测试准确率报告\n\n")
            f.write(f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("## 基本统计\n\n")
            f.write(f"| 统计项目 | 数值 |\n")
            f.write(f"|---------|------|\n")
            f.write(f"| 总题目数 | {total_questions} |\n")
            f.write(f"| 成功处理题目数 | {processed_count} |\n")
            f.write(f"| 成功生成AI回答数 | {success_count} |\n")
            f.write(f"| 处理失败数 | {error_count} |\n")
            f.write(f"| 总处理时间 | {total_elapsed:.2f} 秒 |\n")
            if processed_count > 0:
                f.write(f"| 平均每题处理时间 | {total_elapsed/processed_count:.2f} 秒 |\n")
                f.write(f"| 实际吞吐量 | {processed_count/total_elapsed:.2f} 题目/秒 |\n")
            
            f.write("\n## 准确率统计\n\n")
            f.write(f"| 准确率指标 | 数值 | 百分比 |\n")
            f.write(f"|-----------|------|--------|\n")
            f.write(f"| AI答对题目 | {correct_answers}/{total_answers} | {accuracy:.2f}% |\n")
            f.write(f"| AI答错题目 | {wrong_answers}/{total_answers} | {(wrong_answers / total_answers * 100):.2f}% |\n")
            
            if processed_questions:
                f.write("\n## 题目详细统计\n\n")
                f.write("| 题目编号 | 题目预览 | 正确答案 | AI答案 | 是否正确 | 处理时间 |\n")
                f.write("|---------|---------|---------|--------|---------|----------|\n")
                
                for q in processed_questions:
                    status = "✅" if q["is_correct"] else "❌"
                    preview = q["question_preview"][:50] + "..." if len(q["question_preview"]) > 50 else q["question_preview"]
                    f.write(f"| {q['index']} | {preview} | {q['correct_answer']} | {q['ai_answer']} | {status} | {q['time']} |\n")
            
            f.write("\n## API密钥使用统计\n\n")
            f.write("| 密钥编号 | 使用次数 |\n")
            f.write("|---------|----------|\n")
            for key, count in key_usage_count.items():
                f.write(f"| {key[:8]}... | {count} |\n")
        
        print(f"[信息] 准确率统计报告已保存到: {accuracy_report_file}")
        
        # 生成错题汇总报告（Markdown格式）
        if processed_questions:
            wrong_questions = [q for q in processed_questions if not q["is_correct"]]
            
            if wrong_questions:
                wrong_questions_report_file = os.path.join(output_dir, f"wrong_questions_summary_{time.strftime('%Y%m%d_%H%M%S')}.md")
                
                with open(wrong_questions_report_file, 'w', encoding='utf-8') as f:
                    f.write("# AI错题汇总报告\n\n")
                    f.write(f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    f.write(f"**错题统计**: 共 {len(wrong_questions)} 道题目\n")
                    f.write(f"**错误率**: {(len(wrong_questions) / len(processed_questions) * 100):.2f}%\n\n")
                    
                    f.write("## 错题详情\n\n")
                    
                    for i, q in enumerate(wrong_questions, 1):
                        f.write(f"### 错题 {i} (原题目编号: {q['index']})\n\n")
                        
                        # 读取完整题目内容
                        try:
                            question_file = q["output_file"]
                            if os.path.exists(question_file):
                                with open(question_file, 'r', encoding='utf-8') as qf:
                                    question_data = json.load(qf)
                                    full_question = question_data.get("question", "题目内容读取失败")
                                    ai_reasoning = question_data.get("reasoning", "推理过程读取失败")
                            else:
                                full_question = q["question_preview"]
                                ai_reasoning = "文件不存在，无法读取推理过程"
                        except Exception as e:
                            full_question = q["question_preview"]
                            ai_reasoning = f"读取推理过程时出错: {e}"
                        
                        f.write(f"**题目内容**:\n```\n{full_question}\n```\n\n")
                        f.write(f"**正确答案**: {q['correct_answer']}\n\n")
                        f.write(f"**AI答案**: {q['ai_answer']}\n\n")
                        f.write(f"**AI推理过程**:\n```\n{ai_reasoning}\n```\n\n")
                        f.write(f"**处理时间**: {q['time']}\n\n")
                        f.write("---\n\n")
                
                print(f"[信息] 错题汇总报告已保存到: {wrong_questions_report_file}")
            else:
                print(f"[信息] 没有错题，无需生成错题汇总报告")
        
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
            correct_count = sum(1 for q in processed_questions if q["is_correct"])
        
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
            
            accuracy = (correct_count / processed_count * 100) if processed_count > 0 else 0
            
            print(f"[进度] 已处理: {completed}/{total_questions} 题目 ({completed/total_questions*100:.1f}%)")
            print(f"[进度] 已完成题目: {processed_count} 道")
            print(f"[准确率] AI答对: {correct_count}/{processed_count} 道 ({accuracy:.1f}%)")
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
    并发处理题库中的所有题目，让AI回答
    """
    print(f"[信息] 开始处理题库: {question_file}")
    print(f"[信息] AI回答保存目录: {output_dir}")
    
    # 设置失败题目记录目录
    fail_dir = "D:\\try\\20\\fail_questions"
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
    
    # 使用指定的线程数，受API密钥数量和题目数量限制
    num_workers = min(max_workers, len(api_keys), len(questions))
    print(f"[信息] 将使用 {num_workers} 个并发线程 (请求的并发数: {max_workers})")
    
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
                     progress_bar, key_status, failed_questions, processed_questions, result_lock))
    
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
    
    # 合并所有AI回答到一个数组
    try:
        all_answer_files = glob.glob(os.path.join(output_dir, "question_*.json"))
        
        if all_answer_files:
            combined_data = []
            for answer_file in sorted(all_answer_files):
                try:
                    with open(answer_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        combined_data.append(data)
                except Exception as e:
                    print(f"[警告] 读取回答文件 {answer_file} 时出错: {e}")
            
            combined_file = os.path.join(output_dir, f"all_answers_{time.strftime('%Y%m%d_%H%M%S')}.json")
            with open(combined_file, 'w', encoding='utf-8') as f:
                json.dump(combined_data, f, ensure_ascii=False, indent=2)
            print(f"[信息] 已合并所有AI回答到: {combined_file}")
            
            # 计算准确率统计
            correct_answers = sum(1 for data in combined_data if data.get("is_correct", False))
            total_answers = len(combined_data)
            accuracy = (correct_answers / total_answers * 100) if total_answers > 0 else 0
            
            print(f"[统计] AI整体准确率: {correct_answers}/{total_answers} ({accuracy:.1f}%)")
            
    except Exception as e:
        print(f"[错误] 合并回答文件时出错: {e}")
    
    # 生成准确率统计和错题汇总报告
    generate_reports(output_dir, processed_questions, failed_questions, total_elapsed, len(questions), 
                    processed_count, success_count, error_count, key_usage_count)
    
    # 清除控制台并显示最终结果
    clear_console()
    
    print(f"\n[统计] 处理完成!")
    print(f"[统计] 总题目数: {len(questions)}")
    print(f"[统计] 成功处理: {processed_count}")
    print(f"[统计] 成功生成AI回答: {success_count} 道")
    print(f"[统计] AI回答保存位置: {output_dir}")
    print(f"[统计] 处理失败: {error_count}")
    if error_count > 0:
        print(f"[统计] 失败题目记录保存到: {fail_dir}")
    print(f"[统计] 总处理时间: {total_elapsed:.2f} 秒")
    if processed_count > 0:
        print(f"[统计] 平均每题处理时间: {total_elapsed/processed_count:.2f} 秒")
        print(f"[统计] 实际吞吐量: {processed_count/total_elapsed:.2f} 题目/秒")
    
    # 显示准确率统计
    if processed_questions:
        correct_answers = sum(1 for q in processed_questions if q["is_correct"])
        total_answers = len(processed_questions)
        accuracy = (correct_answers / total_answers * 100) if total_answers > 0 else 0
        print(f"\n[准确率统计]")
        print(f"[准确率] AI答对题目: {correct_answers}/{total_answers}")
        print(f"[准确率] 整体准确率: {accuracy:.2f}%")
        
        # 显示错题数量
        wrong_answers = total_answers - correct_answers
        print(f"[准确率] AI答错题目: {wrong_answers}/{total_answers}")
        print(f"[准确率] 错误率: {(wrong_answers / total_answers * 100):.2f}%")
    
    # 显示每个密钥的使用次数
    print("\n[密钥使用统计]")
    for key, count in key_usage_count.items():
        print(f"  - 密钥 {key[:8]}...: 使用了 {count} 次")

if __name__ == "__main__":
    print(f"[开始] 程序启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print("AI题库处理程序")
    print("="*60)
    
    # 获取用户输入的题库JSON文件路径
    while True:
        question_file = input("\n请输入题库JSON文件的完整路径: ").strip()
        
        # 如果用户输入为空，使用默认路径
        if not question_file:
            question_file = "D:\\try\\20\\题库.json"
            print(f"[信息] 使用默认题库路径: {question_file}")
        
        # 验证文件是否存在
        if os.path.exists(question_file):
            if question_file.lower().endswith('.json'):
                print(f"[信息] 题库文件验证成功: {question_file}")
                break
            else:
                print("[错误] 文件不是JSON格式，请重新输入")
        else:
            print(f"[错误] 文件不存在: {question_file}")
            print("请检查路径是否正确，或按回车使用默认路径")
    
    # 询问用户是否自定义输出目录
    output_choice = input("\n是否自定义AI回答保存目录？(y/n，回车默认为n): ").strip().lower()
    
    if output_choice in ['y', 'yes']:
        while True:
            output_directory = input("请输入AI回答保存目录的完整路径: ").strip()
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
        output_directory = os.path.join(question_dir, "ai_answers")
        print(f"[信息] 使用默认输出目录: {output_directory}")
    
    # 询问用户设置并发数量
    while True:
        concurrent_input = input("\n请输入并发处理数量 (回车默认为100，建议1-200): ").strip()
        
        if not concurrent_input:
            max_workers = 100
            print(f"[信息] 使用默认并发数量: {max_workers}")
            break
        
        try:
            max_workers = int(concurrent_input)
            if max_workers <= 0:
                print("[错误] 并发数量必须大于0")
                continue
            elif max_workers > 500:
                print("[警告] 并发数量过大可能导致系统不稳定，建议不超过200")
                confirm = input("是否继续使用此数量？(y/n): ").strip().lower()
                if confirm not in ['y', 'yes']:
                    continue
            
            print(f"[信息] 并发数量设置为: {max_workers}")
            break
            
        except ValueError:
            print("[错误] 请输入有效的数字")
    
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
    print(f"[配置] AI回答保存目录: {output_directory}")
    print(f"[配置] API密钥数量: {len(api_keys)}")
    print(f"[配置] 并发线程数: {max_workers}")
    
    # 最终确认
    confirm = input("\n确认开始处理？(y/n，回车默认为y): ").strip().lower()
    if confirm in ['n', 'no']:
        print("[信息] 用户取消处理，程序退出")
        sys.exit(0)
    
    print("\n" + "="*60)
    print("开始处理题库")
    print("="*60)
    
    # 处理题目
    process_questions(question_file, output_directory, api_keys, max_workers=max_workers)
    print(f"\n[结束] 程序结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
