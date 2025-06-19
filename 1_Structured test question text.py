import pandas as pd
import json
import re

def process_cancer_excel_to_json(excel_path, output_path=None):
    """
    处理癌症评测Excel文件，转换为JSON格式
    
    Args:
        excel_path: Excel文件路径（现在也支持CSV文件）
        output_path: 输出JSON文件路径，如果为None则返回JSON字符串
    """
    try:
        # 读取CSV文件（原来是Excel文件）
        df = pd.read_csv(excel_path, encoding='utf-8')
        
        # 打印列名以便调试
        print("Excel文件的列名:", df.columns.tolist())
        print("文件行数:", len(df))
        
        # 获取列名（第一列是问题，第二列是选项，第三列是答案）
        question_col = df.columns[0]
        options_col = df.columns[1]
        answer_col = df.columns[2]
        
        print(f"问题列: {question_col}")
        print(f"选项列: {options_col}")
        print(f"答案列: {answer_col}")
        
        json_data = []
        
        for index, row in df.iterrows():
            question_text = str(row[question_col]).strip()
            options_text = str(row[options_col]).strip()
            answer_text = str(row[answer_col]).strip()
            
            # 跳过空行或无效行
            if pd.isna(row[question_col]) or pd.isna(row[options_col]) or question_text == 'nan' or options_text == 'nan':
                continue
            
            # 直接从第三列获取答案
            answer = answer_text if not pd.isna(row[answer_col]) and answer_text != 'nan' else ""
            
            # 构建完整的问题文本
            full_question = f"{index + 1}、{question_text}\n{options_text}"
            
            # 如果没有找到答案，设置为空字符串
            if not answer:
                print(f"警告：第{index + 1}行未找到答案，请手动检查")
                answer = ""
            
            json_item = {
                "question": full_question,
                "answer": answer
            }
            
            json_data.append(json_item)
            
            # 打印前几行以便检查
            if index < 3:
                print(f"\n第{index + 1}行处理结果:")
                print(f"问题: {question_text[:50]}...")
                print(f"选项: {options_text[:50]}...")
                print(f"答案: {answer}")
        
        # 输出JSON
        json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
        
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(json_str)
            print(f"\n成功将{len(json_data)}条记录保存到 {output_path}")
        
        return json_str
        
    except Exception as e:
        print(f"处理文件时出错: {str(e)}")
        return None

def main():
    # CSV文件路径（原来是Excel文件路径）
    excel_file = r"F:\test_with_annotations.csv"
    
    # 输出JSON文件路径
    output_file = "cancer_questions.json"
    
    print("开始处理CSV文件...")
    result = process_cancer_excel_to_json(excel_file, output_file)
    
    if result:
        print("\n处理完成！")
        print("\n前100个字符预览:")
        print(result[:500] + "...")
    else:
        print("处理失败！")

if __name__ == "__main__":
    main()
