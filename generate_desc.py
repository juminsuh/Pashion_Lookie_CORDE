from openai import OpenAI
import os
import json
from dotenv import load_dotenv

load_dotenv('.env', override=True)
API_KEY = os.getenv("OPENAI_API_KEY")

def extract_json(data):
    return {
        'img_url': data.get('img_url', "")[0],
        'category': data.get('sub_cat_name', ""),
        'style': data.get('style_name', "정보 없음"),
        'texture': data.get('texture_name', "정보 없음"),
        'pattern': data.get('pattern_name', "정보 없음"),
        'fit': data.get('fit_name', "정보 없음"),
        'seasonality': data.get('seasonality', "정보 없음")
    }

def gpt(input_json):
    client = OpenAI(api_key= API_KEY)
    text_info = {k:v for k, v in input_json.items() if k!="img_url"}
    user_text = f"아이템 정보: {json.dumps(text_info, ensure_ascii=False)}"
    response = client.chat.completions.create(
        model="gpt-4o",
        temperature=0,  # remove randomness
        
        # 3-shot: 오버피팅될 수 있으므로 2-3 shot이 적당
        messages=[{
            "role": "system",
            "content": 
'''너는 패션 아이템 묘사 전문가야. 이미지와 정보를 결합해 TPO 매칭용 [특징; TPO] 요약을 작성해.

다음에 주의해서 작성해:
1. 색상 정보를 반드시 구체적으로 포함해 (예: 차콜, 다크 네이비, 아이보리 등).
2. 재질과 패턴, 핏을 단순 나열하지 말고 이미지에서 보이는 질감을 상세히 묘사해.
3. TPO는 3가지 이상의 구체적인 상황(장소나 활동)을 포함해.
4. "면 소재"라고만 하지 말고 "탄탄한 코튼", "부드러운 니트" 등 형용사를 활용해.
5. 반드시 [특징; TPO] 형식을 지키고 한 문장으로 끝내.'''
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": '아이템 정보: {"category": "긴소매 티셔츠", "style": "스트릿", "texture": "니트", "pattern": "로고/그래픽", "fit": "오버사이즈", "seasonality": "봄/가을"}'},
                {"type": "image_url", "image_url": {"url": "https://image.msscdn.net/thumbnails/images/prd_img/20240811/4317499/detail_4317499_17312946342666_500.jpg"}}
                ]
        },
        {
            "role": "assistant",
            "content": "화이트 로고 그래픽 포인트, 차콜/블랙 오버사이즈 스트릿 니트; 힙한 카페 방문, 겨울철 가벼운 친구 모임, 데일리 스트릿 룩"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": input_json["img_url"]}}
            ]
        }
                
            ]     
    )
    desc = response.choices[0].message.content.strip() 
    print(desc)
    return desc

def main(jsonl_dir):
    file_name = os.path.basename(jsonl_dir)
    fname = os.path.splitext(file_name)[0]
    output_dir = f"./{fname}_desc.jsonl"
    
    processed_ids = set()
    with open(jsonl_dir, 'r', encoding='utf-8') as f_in, \
            open(output_dir, 'a', encoding='utf-8') as f_out:
            
            for i, line in enumerate(f_in):
                try:
                    data = json.loads(line)
                    p_id = data.get('product_id') # 고유 ID 추출
                    
                    if p_id in processed_ids:
                        continue
                    
                    input_json = extract_json(data)
                    print(f"input_json: {input_json}")
                    desc = gpt(input_json)
                    
                    result = {
                        "product_id": p_id,
                        "description": desc
                    }
                    
                    f_out.write(json.dumps(result, ensure_ascii=False) + '\n')
                    processed_ids.add(p_id)
                    
                    if (i + 1) % 10 == 0:
                        print(f"{i + 1}번째 데이터 처리 중...")
                        
                except Exception as e:
                    print(f"오류 발생 (라인 {i+1}): {e}")
                    continue
    
if __name__ == "__main__":
    jsonl_dir = "./test.jsonl"
    main(jsonl_dir=jsonl_dir)