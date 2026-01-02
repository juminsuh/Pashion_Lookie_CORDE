import os
import random

# 유의미한 조합 정의 (스타일: [(소재, 패턴, 핏), ...])
meaningful_combos = {
    1: [("5E3", "5E898", "5E90"), ("5E3", "5E893", "5E88"), ("5E10", "5E116", "5E88"), ("5E17", "5E118", "5E90")], # 캐주얼
    2: [("5E3", "5E898", "5E90"), ("5E29", "5E893", "5E90"), ("5E17", "5E898", "5E90")], # 스트릿
    4: [("5E3", "5E893", "5E88"), ("5E3", "5E118", "5E88"), ("5E29", "5E893", "5E88")], # 워크웨어
    5: [("5E43", "5E118", "5E88"), ("5E3", "5E116", "5E88"), ("5E10", "5E893", "5E87")], # 프레피
    12: [("5E43", "5E893", "5E87"), ("5E17", "5E893", "5E88"), ("5E10", "5E893", "5E88")] # 시크
}

commands = []
for s_id, filters in meaningful_combos.items():
    for t_id, p_id, f_id in filters:
        # 실행 명령어
        cmd = f"python item_crawl.py --style_id {s_id} --texture_id {t_id} --pattern_id {p_id} --fit_id {f_id}"
        commands.append(cmd)
        
        # 랜덤 sleep 추가 (5~10초 사이)
        wait_time = random.randint(5, 10)
        commands.append(f"echo 'Wait for {wait_time} seconds...'")
        commands.append(f"sleep {wait_time}")

# 쉘 스크립트 저장
with open("run.sh", "w", encoding="utf-8") as f:
    f.write("#!/bin/bash\n\n")
    f.write("echo 'Starting Optimized Musinsa Crawling...'\n\n")
    for c in commands:
        f.write(c + "\n")

print(f"✅ 유의미한 조합과 sleep이 포함된 'run.sh' 파일이 생성되었습니다.")
