import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document, get_documents
from bson import ObjectId

app = FastAPI(title="VibeHunt API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Utilities ----------

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


def serialize(doc: dict) -> dict:
    if not doc:
        return doc
    d = {**doc}
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # ensure datetime -> isoformat
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# ---------- Schemas (API layer) ----------

class PostCreate(BaseModel):
    title: str
    tagline: str
    maker: Optional[str] = None
    url: Optional[str] = None

class VoteToggle(BaseModel):
    device_id: str = Field(..., description="Client device id for idempotency")

class CommentCreate(BaseModel):
    content: str
    author: Optional[str] = None
    device_id: Optional[str] = None


# ---------- Seed Data ----------

def seed_posts():
    if db is None:
        return
    count = db["post"].count_documents({})
    if count > 0:
        return
    samples = [
        {
            "title": "Auto-SaaS Genie",
            "tagline": "AI that builds and ships micro-SaaS from a prompt.",
            "maker": "@vibe-wizard",
            "url": "https://example.com/genie",
            "votes_count": 28,
            "comments_count": 6,
            "created_at": datetime.now(timezone.utc) - timedelta(days=25),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=2),
        },
        {
            "title": "Recurring Notion Shop",
            "tagline": "Turn any Notion template into a paid subscription.",
            "maker": "@opsmith",
            "url": "https://example.com/notion-shop",
            "votes_count": 41,
            "comments_count": 9,
            "created_at": datetime.now(timezone.utc) - timedelta(days=5),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=1),
        },
        {
            "title": "Tweet-to-Product",
            "tagline": "Scrape your best tweets and spin them into a paid course + app.",
            "maker": "@shipdaily",
            "url": "https://example.com/tweet-product",
            "votes_count": 12,
            "comments_count": 2,
            "created_at": datetime.now(timezone.utc) - timedelta(days=2),
            "updated_at": datetime.now(timezone.utc) - timedelta(hours=12),
        },
        {
            "title": "API to Airtable Cashflow",
            "tagline": "One-click Stripe analytics in Airtable with churn & MRR.",
            "maker": "@revenuebits",
            "url": "https://example.com/cashflow",
            "votes_count": 33,
            "comments_count": 4,
            "created_at": datetime.now(timezone.utc) - timedelta(days=15),
            "updated_at": datetime.now(timezone.utc) - timedelta(days=6),
        },
    ]
    if samples:
        db["post"].insert_many(samples)

    # Create some votes tied to a demo device so toggle logic works
    demo_posts = list(db["post"].find({}).limit(2))
    for p in demo_posts:
        db["vote"].insert_one({
            "post_id": p["_id"],
            "device_id": "demo-device",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })


@app.on_event("startup")
async def on_start():
    try:
        seed_posts()
    except Exception:
        pass


# ---------- Basic ----------

@app.get("/")
def root():
    return {"name": "VibeHunt API", "status": "ok"}

@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Connected"
            response["collections"] = db.list_collection_names()
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:80]}"
    return response


# ---------- Posts listing with filters/sorts ----------

@app.get("/api/posts")
def list_posts(range: str = "all", sort: str = "votes"):
    if db is None:
        return []

    # Time filter
    now = datetime.now(timezone.utc)
    query = {}
    if range == "week":
        query["created_at"] = {"$gte": now - timedelta(days=7)}
    elif range == "month":
        query["created_at"] = {"$gte": now - timedelta(days=30)}

    # Sorting
    if sort == "comments":
        sort_key = ("comments_count", -1)
    elif sort == "latest":
        sort_key = ("created_at", -1)
    else:
        sort_key = ("votes_count", -1)

    items = list(db["post"].find(query).sort([sort_key, ("created_at", -1)]) )
    return [serialize(p) for p in items]


@app.get("/api/posts/{post_id}")
def get_post(post_id: str):
    p = db["post"].find_one({"_id": oid(post_id)})
    if not p:
        raise HTTPException(404, "Post not found")
    return serialize(p)


@app.post("/api/posts")
def create_post(data: PostCreate):
    if db is None:
        raise HTTPException(500, "Database not available")
    doc = {
        "title": data.title.strip(),
        "tagline": data.tagline.strip(),
        "maker": (data.maker or "").strip() or None,
        "url": (data.url or "").strip() or None,
        "votes_count": 0,
        "comments_count": 0,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    res = db["post"].insert_one(doc)
    doc["_id"] = res.inserted_id
    return serialize(doc)


# ---------- Voting (toggle) ----------

@app.post("/api/posts/{post_id}/vote")
def toggle_vote(post_id: str, payload: VoteToggle):
    if db is None:
        raise HTTPException(500, "Database not available")

    pid = oid(post_id)
    post = db["post"].find_one({"_id": pid})
    if not post:
        raise HTTPException(404, "Post not found")

    existing = db["vote"].find_one({"post_id": pid, "device_id": payload.device_id})
    voted = False
    if existing:
        # unvote
        db["vote"].delete_one({"_id": existing["_id"]})
        db["post"].update_one({"_id": pid}, {"$inc": {"votes_count": -1}, "$set": {"updated_at": datetime.now(timezone.utc)}})
        voted = False
    else:
        # vote
        db["vote"].insert_one({
            "post_id": pid,
            "device_id": payload.device_id,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        })
        db["post"].update_one({"_id": pid}, {"$inc": {"votes_count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}})
        voted = True

    post = db["post"].find_one({"_id": pid})
    return {"voted": voted, "votes": post.get("votes_count", 0)}


# ---------- Comments ----------

@app.get("/api/posts/{post_id}/comments")
def list_comments(post_id: str):
    pid = oid(post_id)
    items = list(db["comment"].find({"post_id": pid}).sort([("created_at", -1)]))
    return [serialize(c) for c in items]


@app.post("/api/posts/{post_id}/comments")
def add_comment(post_id: str, payload: CommentCreate):
    pid = oid(post_id)
    if not db["post"].find_one({"_id": pid}):
        raise HTTPException(404, "Post not found")

    doc = {
        "post_id": pid,
        "author": (payload.author or "").strip() or None,
        "content": payload.content.strip(),
        "device_id": (payload.device_id or None),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    res = db["comment"].insert_one(doc)
    db["post"].update_one({"_id": pid}, {"$inc": {"comments_count": 1}, "$set": {"updated_at": datetime.now(timezone.utc)}})

    doc["_id"] = res.inserted_id
    return serialize(doc)
