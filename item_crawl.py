# --- [TOP: imports & globals] ---
import os, re, time, random, json, hashlib, argparse
import urllib.parse as urlparse
from dataclasses import dataclass, asdict
from typing import List, Tuple, Set, Dict

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 저장 폴더
SAVE_DIR = "./data"
JSONL_DIR = os.path.join(SAVE_DIR, "jsonl")
IMAGE_DIR = os.path.join(SAVE_DIR, "image")  

# 사이트 기본 상수
BASE = "https://www.musinsa.com"
NUM_COLLECT = 2 # 세부카테고리별 수집 개수 for test

# 스크롤/대기
SCROLL_ROUNDS = 8
SCROLL_SLEEP = (0.9, 1.5)

# 전역 중복 방지 (상품 ID)
SEEN_IDS: Set[str] = set()

# 디렉토리 생성
os.makedirs(SAVE_DIR, exist_ok=True)
os.makedirs(JSONL_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

# ========= 데이터 모델 =========
@dataclass
class ItemRow:
    ### for mangagement
    product_id: str
    gender: str
    main_cat_id: str
    main_cat_name: str
    sub_cat_id: str
    sub_cat_name: str
    product_name: str
    item_url: str
    brand: str
    price: str
    color: List[str]
    img_dir: List[str]      
    img_url: List[str]       
    
    ### for recommendation
    style_id: str
    style_name: str
    texture_id: str    
    texture_name: str
    pattern_id: str
    pattern_name: str
    fit_id: str
    fit_name: str
    seasonality: str # 겨울로 고정

def save_jsonl(data, filename):
    # 확장자를 .jsonl로 변경
    if not filename.endswith(".jsonl"):
        filename = re.sub(r"\.json$", "", filename) + ".jsonl"
        
    path = os.path.join(JSONL_DIR, filename)
    
    # 리스트 데이터라면 한 줄씩 분리해서 저장
    if isinstance(data, list):
        items_to_write = data
    else:
        items_to_write = [data]

    # 'a' (append) 모드로 열어서 한 줄씩 쓰기
    with open(path, "a", encoding="utf-8") as f:
        for item in items_to_write:
            # 개행 문자(\n)를 붙여서 한 줄씩 저장
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    
    print(f"[INFO] Appended to JSONL -> {path} (+{len(items_to_write)} items)")

# ========= 드라이버 =========
def make_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1400,2200")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-plugins-discovery")
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(40)
    return driver

def build_category_url(gf: str, style_id: int, sub_cat_id: str=None) -> str:
    q = f"{BASE}/category/{main_cat_id}?gf={gf}&style={style_id}"
    if sub_cat_id:
        q += f"&category2Depth={sub_cat_id}"
    return q

def build_url(sub_cat_id: str, gf: str, style_id: int, texture_id: str, pattern_id: str, fit_id: str) -> str:
    q = f"{BASE}/category/{sub_cat_id}?gf={gf}&style={style_id}&attributeMaterial=1%{texture_id}&attributePattern=6%{pattern_id}&attributeFit=2%{fit_id}"
    return q

def extract_product_id(a_elem, href: str) -> str:
    pid = (a_elem.get_attribute("data-item-id") or "").strip()
    if pid:
        return pid
    m = re.search(r"/products/(\d+)", href)
    return m.group(1) if m else hashlib.md5(href.encode()).hexdigest()

# 아이템명에서 '상품 상세로 이동' 꼬리 제거 + 공백 정리
def _clean_item_name(txt: str) -> str:
    if not txt:
        return ""
    txt = re.sub(r"\s*(상품\s*상세(?:로)?\s*이동)\s*$", "", txt).strip()
    txt = re.sub(r"\s+", " ", txt)
    return txt

# ========= 상단 탭: 세부 카테고리 수집 (전체 제외) =========
def collect_subcategories(exclude_subcats, driver) -> List[Tuple[str, str]]:
    """
    탭 컨테이너(data-mds=TabText) 안의 2뎁스 세부카테고리만 수집.
    '전체' 및 data-category-id == main_cat_name_CODE(001) 제외.
    return: [(category_id, category_name)]
    """
    def _norm(s: str) -> str:
        s = (s or "").strip()
        return re.sub(r"\s+", " ", s)

    subs: List[Tuple[str, str]] = []

    try:
        # 탭 컨테이너가 렌더될 때까지 대기
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-mds="TabText"]'))
        )
        # 탭 컨테이너 내부의 카테고리 탭만 대상
        nodes = driver.find_elements(
            By.CSS_SELECTOR,
            '[data-mds="TabText"] [data-button-id="category"][data-category-id]'
        )
        for n in nodes:
            cid = (n.get_attribute("data-category-id") or "").strip()
            cname_full = (n.get_attribute("data-category-name") or "").strip()
            cname = cname_full.split("|")[-1] if "|" in cname_full else cname_full
            # 텍스트 백업
            if not cname:
                cname = _norm(n.text)
            cname = _norm(cname)

            # '전체'(텍스트) 제외 + '001'(루트 코드) 제외
            if not cid or cid == main_cat_id or cname == "전체":
                continue

            # 6자리 카테고리 ID만 허용
            if not re.fullmatch(r"\d{6}", cid):
                continue
            
            # ✅ 제외 목록 체크
            exclude_ids = exclude_subcats.get('ids', [])
            exclude_names = exclude_subcats.get('names', [])
            
            if cid in exclude_ids or cname in exclude_names:
                print(f"    🙅 제외: {cid} {cname}")
                continue

            subs.append((cid, cname))

    except Exception:
        pass

    # 중복 제거(순서 보존)
    uniq, seen = [], set()
    for cid, cname in subs:
        key = f"{cid}|{cname}"
        if key not in seen:
            seen.add(key); uniq.append((cid, cname))
    return uniq

def click_subcategory(driver, cat_id: str, timeout: float = 6.0) -> bool:
    """
    세부카테고리 탭(data-category-id=cat_id)을 클릭하고 활성화(aria-current=true)될 때까지 대기.
    반환: True(성공) / False(실패)
    """
    try:
        # 대상 탭 요소
        tab = driver.find_element(By.CSS_SELECTOR, f'[data-mds="TabText"] [data-button-id="category"][data-category-id="{cat_id}"]')
        # 스크롤해서 가시 영역으로
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tab)
        # 클릭 (오버레이 회피용 JS 클릭 우선)
        try:
            driver.execute_script("arguments[0].click();", tab)
        except:
            tab.click()

        # 활성화(aria-current=true)까지 대기
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, f'[data-mds="TabText"] [data-button-id="category"][data-category-id="{cat_id}"][aria-current="true"]')
            )
        )

        # 상품 그리드가 다시 채워질 때까지도 짧게 대기
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a.gtm-select-item[href*="/products/"]'))
        )
        return True
    except Exception:
        return False

# ========= 리스트: 브랜드/아이템명/URL 수집 =========
def collect_list_minimals_unique(driver, need: int):
    """
    (product_id, brand, item_name, product_url) 반환 (전역 SEEN_IDS로 중복 제외)
    """
    results, seen_local = [], set()
    rounds, last_cnt = 0, 0

    while len(results) < need and rounds < SCROLL_ROUNDS:
        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'a.gtm-select-item[href*="/products/"]'))
            )
        except: pass

        product_anchors = driver.find_elements(By.CSS_SELECTOR, 'a.gtm-select-item[href*="/products/"]')
        for a in product_anchors:
            href = (a.get_attribute("href") or "").split("?")[0]
            if "/products/" not in href:
                continue

            pid = extract_product_id(a, href)
            if pid in SEEN_IDS or pid in seen_local:
                continue

            # ----- 아이템명 -----
            item_name = ""
            try:
                item_name = a.find_element(By.CSS_SELECTOR, 'span[data-mds="Typography"]').text.strip()
                item_name = _clean_item_name(item_name)
            except: item_name = ""
            if not item_name:
                item_name = _clean_item_name((a.get_attribute("aria-label") or "").strip())
            if not item_name or item_name in ("상품상세로 이동", "상품 상세로 이동"):
                item_name = _clean_item_name((a.text or "").strip())
            if not item_name or item_name in ("상품상세로 이동", "상품 상세로 이동"):
                try:
                    card = a.find_element(By.XPATH, "./ancestor::*[self::li or self::div][1]")
                    img = card.find_element(By.CSS_SELECTOR, "img[alt]")
                    item_name = _clean_item_name((img.get_attribute("alt") or "").strip())
                except: pass

            # ----- 브랜드명 -----
            brand = ""
            try:
                card = a.find_element(By.XPATH, "./ancestor::*[self::li or self::div][1]")
                brand_span = card.find_element(By.CSS_SELECTOR, 'a[href*="/brand/"] span[data-mds="Typography"]')
                brand = brand_span.text.strip()
            except:
                brand = (a.get_attribute("data-brand-id") or a.get_attribute("data-item-brand") or "").strip()

            results.append((pid, brand, item_name, href))
            seen_local.add(pid)
            if len(results) >= need:
                break

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(*SCROLL_SLEEP))
        rounds += 1
        if len(results) == last_cnt:
            break
        last_cnt = len(results)

    return results[:need]



# ========= 옵션: "컬러"만 안전하게 추출 =========
_COLOR_WORDS = [
    # 한글/영문 색상 키워드(대표적인 것들 + '라이트/다크' 수식 포함)
    "블랙","화이트","아이보리","베이지","브라운","그레이","라이트 그레이","차콜","네이비","블루","스카이","옐로우",
    "오렌지","레드","핑크","퍼플","보라","그린","카키","올리브","민트","버건디","크림","코코아","실버","골드",
    "라이트","라이트블루","라이트 핑크","다크","딥","샌드","모카","와인","탄","카멜","청록","청색","군청","연청","진청",
    # 영문
    "black","white","ivory","beige","brown","gray","grey","charcoal","navy","blue","sky","yellow","orange","red","pink",
    "purple","green","khaki","olive","mint","burgundy","cream","silver","gold","tan","camel","wine","sand","mocha","teal"
]
_SIZE_PATTERN = re.compile(
    r"^\s*(?:XXXS|XXS|XS|S|M|L|XL|XXL|XXXL|[\d]{2,3}|[2-5]XL|Free|FREE|F|사이즈|Size|size|cm|CM)\s*$"
)

def looks_like_color(text: str) -> bool:
    t = (text or "").strip()
    if not t: return False
    if _SIZE_PATTERN.match(t):
        return False
    # 색 단서가 하나라도 들어가면 컬러로 간주 (너무 빡세면 누락됨)
    for w in _COLOR_WORDS:
        if w.lower() in t.lower():
            return True
    # 색상칩 없는 '단색명'도 허용 (한글 1~10자)
    if re.search(r"[가-힣A-Za-z]{1,10}", t) and len(t) <= 20:
        return True
    return False

def extract_colors(driver) -> List[str]:
    """
    무신사 상세페이지 '컬러' 드롭다운에서 색상명 추출
    실제 DOM 구조에 맞춰 개선된 버전
    """
    import time, random, re
    colors: List[str] = []

    def _clean(txt: str) -> str:
        if not txt: return ""
        txt = re.sub(r"\s*\(.*?\)\s*$", "", (txt or "").strip())  # (품절) 등 꼬리 제거
        txt = re.sub(r"\s+", " ", txt)
        return txt

    def _grab_colors_from_dropdown() -> List[str]:
        """열린 드롭다운에서 색상 추출"""
        found = []
        
        try:
            # 1️⃣ data-state="open"인 드롭다운 메뉴 찾기
            open_menu = driver.find_element(
                By.CSS_SELECTOR, 
                '[data-mds="StaticDropdownMenuContent"][data-state="open"]'
            )
            
            # 2️⃣ 메뉴 내부의 모든 옵션 아이템 찾기
            # data-mds="StaticDropdownMenuItem" 또는 role="option"
            option_items = open_menu.find_elements(
                By.CSS_SELECTOR,
                '[data-mds="StaticDropdownMenuItem"], [role="option"]'
            )
            
            print(f"    [DEBUG] Found {len(option_items)} option items")
            
            for item in option_items:
                try:
                    # 방법 1: data-button-name 속성에서 추출
                    color_name = item.get_attribute("data-button-name")
                    if color_name and color_name not in ["none", ""]:
                        cleaned = _clean(color_name)
                        if cleaned and looks_like_color(cleaned):
                            found.append(cleaned)
                            print(f"    [DEBUG] Color from data-button-name: {cleaned}")
                            continue
                    
                    # 방법 2: aria-label에서 추출
                    aria_label = item.get_attribute("aria-label")
                    if aria_label:
                        cleaned = _clean(aria_label)
                        if cleaned and looks_like_color(cleaned):
                            found.append(cleaned)
                            print(f"    [DEBUG] Color from aria-label: {cleaned}")
                            continue
                    
                    # 방법 3: 내부 텍스트에서 추출
                    # span이나 div 안의 텍스트 찾기
                    text_elements = item.find_elements(
                        By.CSS_SELECTOR,
                        'span[data-mds="Typography"], div[class*="text"], span'
                    )
                    for txt_el in text_elements:
                        text = _clean(txt_el.text)
                        if text and looks_like_color(text):
                            found.append(text)
                            print(f"    [DEBUG] Color from text: {text}")
                            break
                    
                    # 방법 4: 전체 텍스트 내용
                    if not found or len(found) == 0:
                        full_text = _clean(item.text)
                        if full_text and looks_like_color(full_text):
                            found.append(full_text)
                            print(f"    [DEBUG] Color from full text: {full_text}")
                            
                except Exception as e:
                    print(f"    [DEBUG] Error extracting from item: {e}")
                    continue
                    
        except Exception as e:
            print(f"    [DEBUG] Error finding dropdown: {e}")
            
        return found

    # Step 1: 이미 열려있는지 확인
    try:
        existing_menu = driver.find_element(
            By.CSS_SELECTOR,
            '[data-mds="StaticDropdownMenuContent"][data-state="open"]'
        )
        if existing_menu:
            print("    [DEBUG] Dropdown already open")
            colors = _grab_colors_from_dropdown()
    except:
        print("    [DEBUG] Dropdown not open, will try to open it")

    # Step 2: 열려있지 않으면 클릭해서 열기
    if not colors:
        print("    [DEBUG] Attempting to open color dropdown...")
        
        # 우선순위 1: '컬러' 드롭다운 트리거 (가장 정확)
        selectors_to_try = [
            # 가장 구체적인 선택자부터
            'div[data-section-name*="컬러"] input[data-mds="DropdownTriggerInput"]',
            'div[data-section-name*="color"] input[data-mds="DropdownTriggerInput"]',
            '[data-button-name*="컬러"] input[data-mds="DropdownTriggerInput"]',
            'input[data-mds="DropdownTriggerInput"][placeholder*="컬러"]',
            'input[data-mds="DropdownTriggerInput"][placeholder*="color"]',
        ]
        
        clicked = False
        for selector in selectors_to_try:
            try:
                triggers = driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"    [DEBUG] Found {len(triggers)} triggers with selector: {selector}")
                
                for trigger in triggers:
                    try:
                        # 화면에 보이도록 스크롤
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center', behavior:'instant'});", 
                            trigger
                        )
                        time.sleep(0.3)
                        
                        # 클릭 시도
                        try:
                            driver.execute_script("arguments[0].click();", trigger)
                        except:
                            trigger.click()
                        
                        time.sleep(0.8)  # 드롭다운이 열릴 시간
                        
                        # 드롭다운이 열렸는지 확인
                        try:
                            driver.find_element(
                                By.CSS_SELECTOR,
                                '[data-mds="StaticDropdownMenuContent"][data-state="open"]'
                            )
                            print(f"    [DEBUG] Successfully opened dropdown!")
                            clicked = True
                            break
                        except:
                            print(f"    [DEBUG] Click didn't open dropdown, trying next...")
                            continue
                            
                    except Exception as e:
                        print(f"    [DEBUG] Failed to click trigger: {e}")
                        continue
                
                if clicked:
                    break
                    
            except Exception as e:
                print(f"    [DEBUG] Selector {selector} failed: {e}")
                continue
        
        # 클릭 성공했으면 다시 추출 시도
        if clicked:
            time.sleep(0.5)
            colors = _grab_colors_from_dropdown()

    # Step 3: 여전히 못 찾았으면 XPath로 시도
    if not colors:
        print("    [DEBUG] Trying XPath approach...")
        try:
            xpath_triggers = driver.find_elements(
                By.XPATH,
                "//div[contains(text(),'컬러')]//ancestor::div[1]//input | "
                "//label[contains(text(),'컬러')]//following-sibling::input | "
                "//span[contains(text(),'컬러')]//ancestor::div[contains(@class,'select') or contains(@class,'dropdown')]//input"
            )
            
            print(f"    [DEBUG] Found {len(xpath_triggers)} triggers via XPath")
            
            for trigger in xpath_triggers:
                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});", 
                        trigger
                    )
                    time.sleep(0.3)
                    driver.execute_script("arguments[0].click();", trigger)
                    time.sleep(0.8)
                    
                    colors = _grab_colors_from_dropdown()
                    if colors:
                        break
                except:
                    continue
                    
        except Exception as e:
            print(f"    [DEBUG] XPath approach failed: {e}")

    # 정리: 중복 제거
    uniq, seen = [], set()
    for c in colors:
        if c and not _SIZE_PATTERN.match(c) and c not in seen:
            seen.add(c)
            uniq.append(c)
    
    print(f"    [DEBUG] Final colors extracted: {uniq}")
    return uniq

# ========= 상세: 가격/이미지들/컬러 =========
def download_images(
    img_urls: List[str],
    gender: str,
    category_name: str,
    subcategory_name: str,
    style_name: str,
    texture_name: str,
    pattern_name: str,
    fit_name: str,
    item_idx: int
) -> List[str]:
    """
    이미지들을 무신사/image/[카테고리]_[세부카테고리]_[스타일][번호]/ 아래에 저장
    파일명은 01.jpg, 02.jpg … 순번
    """
    saved_paths = []

    def _clean_name(x: str) -> str:
        x = (x or "").strip()
        x = re.sub(r"[\\/:*?\"<>|]", "_", x)   # 금지문자 → "_"
        x = re.sub(r"\s+", " ", x)             # 공백 정리
        return x

    cat = _clean_name(category_name)
    sub = _clean_name(subcategory_name)
    pat = _clean_name(pattern_name)

    # ✅ 폴더명: [카테고리]_[세부카테고리]_[스타일][아이템번호]
    folder_name1 = f"{style_name}_{texture_name}_{pat}_{fit_name}"
    folder_name2 = f"{sub}_{item_idx:02d}"
    DETAIL_DIR = os.path.join(IMAGE_DIR, gender, cat)
    folder1 = os.path.join(DETAIL_DIR, folder_name1)
    folder2 = os.path.join(folder1, folder_name2)
    os.makedirs(folder2, exist_ok=True)

    headers = {"User-Agent": "Mozilla/5.0"}
    print(f"💬 image_urls: {img_urls}")
    for idx, url in enumerate(img_urls, start=1):
        try:
            ext = ".jpg"
            m = re.search(r"\.(jpg|jpeg|png|webp)(?:\?|$)", url, re.I)
            if m:
                ext = "." + m.group(1).lower()

            filepath = os.path.join(folder2, f"{idx:02d}{ext}")

            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(r.content)
                saved_paths.append(filepath)
                print("✅ Images are downloaded!")
        except Exception as e:
            print(f"[WARN] image download failed: {url} ({e})")

    return saved_paths


def parse_detail(driver, url: str) -> Tuple[str, List[str], List[str], str]:
    """
    상세: 가격(원가), 색상(컬러만), 모든 섬네일 이미지 URL, product_id 반환
    """
    driver.get(url)
    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'img'))
        )
    except: pass
    time.sleep(0.6)

    # product_id 재추출(보수)
    m = re.search(r"/products/(\d+)", url)
    product_id = m.group(1) if m else hashlib.md5(url.encode()).hexdigest()

    # 1) 가격(원가)
    price_original = ""
    try:
        els = driver.find_elements(By.CSS_SELECTOR, ".line-through, del, s")
        texts = [e.text.strip() for e in els if (e.text or "").strip()]
        for t in texts:
            if re.search(r"\d[\d,]*\s*원", t):
                price_original = t; break
        if not price_original and texts:
            price_original = texts[0]
    except: pass

    # 2) 이미지 썸네일들 (요구: 제공된 컨테이너 내 이미지 전부)
    #    기본 선택자: div.sc-366fl4-2 ... 내부의 img[alt^="Thumbnail"]
    #    폴백: 썸네일/상세 패턴이 들어간 모든 썸네일 이미지
    image_urls = []
    try:
        thumbs = driver.find_elements(By.CSS_SELECTOR, 'div[class*="sc-366fl4-2"] img[alt^="Thumbnail"]')
        image_urls = [(im.get_attribute("src") or "").strip() for im in thumbs]
        image_urls = [u for u in image_urls if u]
    except: image_urls = []
    if not image_urls:
        imgs = driver.find_elements(By.CSS_SELECTOR, 'img')
        for im in imgs:
            src = (im.get_attribute("src") or "").strip()
            if not src: continue
            # 무신사 썸네일/상세 이미지 패턴 필터
            if "image.msscdn.net/thumbnails" in src or "goods_img" in src or "prd_img" in src:
                image_urls.append(src)

    # 3) 컬러 옵션(컬러만)
    colors = extract_colors(driver)  # 사이즈 필터링 반영

    # 정리: 중복 제거
    def dedup(seq):
        out, seen = [], set()
        for x in seq:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    image_urls = dedup(image_urls)
    colors = dedup(colors)

    return price_original, colors, image_urls, product_id

# ========= 실행 파이프라인 =========
def run_one_category(sub_cat_id: str, gf: str, style_id: int, texture_id: str, pattern_id: str, fit_id: str, gender: str, style_name: str,
                     sub_cat_name: str, texture_name: str, pattern_name: str, fit_name: str, NUM_COLLECT: int = 10, headless=True) -> List[Dict]:
    driver = make_driver(headless=headless)
    items: List[Dict] = []
    try:
        # 1) 세부 카테고리 탭이 있는 페이지를 먼저 오픈 (cat_id 포함/비포함 모두 허용)
        url = build_url(sub_cat_id, gf, style_id, texture_id, pattern_id, fit_id)  # ← cat_id 없이 상단 탭 보장
        print("[OPEN LIST]", url)
        driver.get(url)

        # 탭들이 보일 때까지
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-mds="TabText"]'))
        )

        # 2) 목표 세부 카테고리 탭을 클릭해서 확정
        if sub_cat_id:
            ok = click_subcategory(driver, sub_cat_id)
            if not ok:
                print("❌ 세부 카테고리 탭 클릭 실패")
                # 실패 시 URL 파라미터로 다시 진입 (폴백), 그 후 다시 클릭 시도
                driver.get(build_category_url(gf, style_id, sub_cat_id))
                WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'a.gtm-select-item[href*="/products/"]'))
                )
                re_ok = click_subcategory(driver, sub_cat_id)
                if not re_ok:
                    print("❌❌ 정말 실패")

        # 3) 이제 리스트 수집
        minimal = collect_list_minimals_unique(driver, need=NUM_COLLECT)

        for idx, (_, brand, item_name, href) in enumerate(minimal, start=1):
            price_o, colors, img_urls, pid2 = parse_detail(driver, href)
            SEEN_IDS.add(pid2)

            saved_paths = download_images(
                img_urls,
                gender=gender,
                category_name=main_cat_name,
                subcategory_name=sub_cat_name,
                style_name=style_name,
                texture_name=texture_name,
                pattern_name=pattern_name,
                fit_name=fit_name,
                item_idx=idx
            )

            row = ItemRow(
                product_id=pid2,
                gender=gender,
                main_cat_id=main_cat_id,
                main_cat_name=main_cat_name,
                sub_cat_id=sub_cat_id,
                sub_cat_name=sub_cat_name,
                product_name=item_name,
                item_url=href,
                brand=brand,
                price=price_o,
                color=colors,
                img_dir=saved_paths,
                img_url=img_urls,
                style_id=style_id,
                style_name=style_name,
                texture_id=texture_id,   
                texture_name=texture_name,
                pattern_id=pattern_id,
                pattern_name=pattern_name,
                fit_id=fit_id,
                fit_name=fit_name,
                seasonality="겨울" # 겨울로 고정
            )
            items.append(asdict(row))
    finally:
        driver.quit()
    return items


def run_all(
    gender: str, 
    style_id:str, 
    texture_id: str,
    pattern_id: str,
    fit_id: str,
    NUM_COLLECT: int = 10, 
    headless=True) -> List[Dict]:
    """
    gender: '남' or '여' (공용 제외)  → 무신사 파라미터는 'M'/'F'
    style_id: 1~15
    각 세부 카테고리(‘전체’ 제외)를 순회하며 수집
    """
    gf_map = {"남": "M", "여": "F"}
    gf = gf_map[gender]
    
    if main_cat_id == "001":
        exclude_subcats = {
            'ids': ['001001', '001008', '001011'],
            'names': ['반소매 티셔츠', '기타 상의', '민소매 티셔츠']
        }
    style_name_map = {1:"캐주얼", 2:"스트릿", 4:"워크웨어", 5:"프레피",
                    9:"걸리시", 12:"시크"}
    texture_name_map = {"5E3": "면", "5E17": "폴리에스테르", 
                  "5E43": "울", "5E29": "나일론", "5E10": "니트"}
    pattern_name_map = {"5E898": "로고/그래픽", "5E893": "단색", 
                  "5E116": "스트라이프", "5E118": "체크"}
    fit_name_map = {"5E90": "오버사이즈", "5E88": "레귤러", "5E87": "슬림"}
    
    style_name = style_name_map[style_id]
    texture_name = texture_name_map[texture_id]
    pattern_name = pattern_name_map[pattern_id]
    fit_name = fit_name_map[fit_id]
    
    # 세부 카테고리 목록 얻기 위해 상위 페이지 한 번 열기
    driver = make_driver(headless=headless)
    subcats = []
    try:
        url = build_category_url(gf, style_id)
        print("[OPEN main_cat_name TABS]", url)
        driver.get(url)
        subcats = collect_subcategories(exclude_subcats, driver)  # [('001010','긴소매 티셔츠'), ...]  '전체' 제외됨
    finally:
        driver.quit()

    if not subcats:
        print("[WARN] 세부 카테고리를 찾지 못해 상위 카테고리에서 직접 수집합니다.")
        subcats = [(None, main_cat_name)]  # fallback

    all_items: List[Dict] = []
    for sub_cat_id, sub_cat_name in subcats:
        try:
            cat_items = run_one_category(sub_cat_id, gf, style_id, texture_id, pattern_id, fit_id, gender, style_name, sub_cat_name, texture_name, pattern_name, fit_name, NUM_COLLECT=NUM_COLLECT, headless=headless)
            all_items.extend(cat_items)
        except Exception as e:
            print(f"[WARN] category {sub_cat_id}/{sub_cat_name} failed: {e}")
    return all_items

def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--main_cat_id', type=str, default='001', help="ID of main category")
    parser.add_argument('--main_cat_name', type=str, default='상의', help="Name of main category")
    parser.add_argument('--style_id', type=int, default=1)
    parser.add_argument('--texture_id', type=str, default="5E3")
    parser.add_argument('--pattern_id', type=str, default="5E898")
    parser.add_argument('--fit_id', type=str, default="5E90")

    args = parser.parse_args()
    return args

if __name__ == "__main__":
    data_all = []
    args = parse_arguments()
    main_cat_id = args.main_cat_id
    main_cat_name = args.main_cat_name
    style_id = args.style_id
    texture_id = args.texture_id
    pattern_id = args.pattern_id
    fit_id = args.fit_id

    for gender in ["남", "여"]:   # ✅ 공용 제외
        items = run_all(
            gender=gender, 
            style_id=style_id,
            texture_id=texture_id,
            pattern_id=pattern_id,
            fit_id=fit_id,
            NUM_COLLECT=NUM_COLLECT, 
            headless=True)
        # 성별별 JSON 저장
        fname = f"{gender}_{main_cat_name}_{NUM_COLLECT}.json"
        save_jsonl(items, fname)
        data_all.extend(items)