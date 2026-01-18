from fastapi import FastAPI
from pydantic import BaseModel
import time

from persona import PERSONA_MAP
from recommender import load_metadata, load_faiss_index, retrieve
from utils import parse_tpo, clip_embed, generate_reason

app = FastAPI(title="Fashion Demo API")

CATEGORY_ORDER = ["상의", "하의", "아우터", "가방", "신발"]
SESSIONS = {}

# ---------- Session Utils ----------

def get_session(session_id: str):
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "persona": None,
            "negative": {},
            "parsed_tpo": [],
            "selected_items": [],
            "current_step": CATEGORY_ORDER[0],
            "created_at": time.time()
        }
    return SESSIONS[session_id]

# ---------- Request Models ----------

class PersonaReq(BaseModel):
    session_id: str
    persona_id: str

class NegativeReq(BaseModel):
    session_id: str
    fit: list[str]
    pattern: list[str]
    price_threshold: int

class TPOReq(BaseModel):
    session_id: str
    tpo_text: str

# ---------- APIs ----------

@app.post("/step/persona")
def select_persona(req: PersonaReq):
    state = get_session(req.session_id)
    persona = PERSONA_MAP.get(req.persona_id)
    if not persona:
        return {"status": "error", "message": "persona not found"}
    state["persona"] = persona
    return {"status": "success", "persona": persona}

@app.post("/step/negative")
def save_negative(req: NegativeReq):
    state = get_session(req.session_id)
    negative = {
        "fit": req.fit,
        "pattern": req.pattern,
        "price": req.price_threshold
    }
    state["negative"] = negative
    return {"status": "success", "negative": negative}

@app.post("/step/tpo")
def save_tpo(req: TPOReq):
    state = get_session(req.session_id)
    parsed = parse_tpo(req.tpo_text)
    state["parsed_tpo"] = parsed
    return {"status": "parsing_done", "parsed_tpo": parsed}

@app.get("/step/recommend")
def recommend(session_id: str):
    state = get_session(session_id)
    
    category = state["current_step"]
    db_path = f"./db/{category}" 
    metadata = load_metadata(db_path)
    index = load_faiss_index(db_path)

    context = (
        state["persona"]["선호 스타일"] + " " +
        state["persona"]["선호하는 아이템 특징"] + " " +
        " ".join(state["parsed_tpo"]) + " " +
        " ".join(state["selected_items"])
    )
    query_emb = clip_embed(context)

    items = retrieve(
        metadata=metadata,
        index=index,
        query_emb=query_emb,
        category=category,
        negative=state.get("negative", {})
    )

    return {
        "category": category,
        "items": [
            {
                "item_id": it["product_id"],
                "image": it["image_url"],
                "description": it["description"], 
                "reason": generate_reason(it["description"], context)
            } for it in items
        ]
    }

class SelectReqWithInfo(BaseModel):
    session_id: str
    item_id: str
    main_cat_name: str
    name: str
    image_url: str

@app.post("/step/select")
def select_item(req: SelectReqWithInfo):
    state = get_session(req.session_id)
    state["selected_items"].append({
        "item_id": req.item_id,
        "main_cat_name": req.main_cat_name,
        "name": req.name,
        "image_url": req.image_url
    })

    idx = CATEGORY_ORDER.index(state["current_step"])
    if idx + 1 < len(CATEGORY_ORDER):
        state["current_step"] = CATEGORY_ORDER[idx + 1]
        return {
            "status": "selected",
            "is_finished": False,
            "next_category": state["current_step"]
        }
    else:
        return {
            "status": "selected",
            "is_finished": True,
            "next_category": None
        }

@app.get("/lookbook")
def lookbook(session_id: str):
    state = get_session(session_id)
    return {
        "user_persona": state["persona"],
        "final_lookbook": [
            {
                "main_cat_name": item["main_cat_name"],
                "name": item["name"],
                "image_url": item["image_url"]
            } for item in state["selected_items"]
        ],
        "message": "당신의 코디가 완성되었습니다!"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
