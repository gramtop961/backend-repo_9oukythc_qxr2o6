"""
Database Schemas for VibeHunt

Each Pydantic model maps to a MongoDB collection with the lowercase class name.
- Post -> "post"
- Comment -> "comment"
- Vote -> "vote"
"""

from pydantic import BaseModel, Field
from typing import Optional

class Post(BaseModel):
    title: str = Field(..., description="Idea title")
    tagline: str = Field(..., description="Short one-line description")
    maker: Optional[str] = Field(None, description="Creator name or handle")
    url: Optional[str] = Field(None, description="Link to more info (optional)")
    votes_count: int = Field(0, ge=0, description="Cached total votes")
    comments_count: int = Field(0, ge=0, description="Cached total comments")

class Comment(BaseModel):
    post_id: str = Field(..., description="Target post id as string")
    author: Optional[str] = Field(None, description="Comment author (optional)")
    content: str = Field(..., description="Comment text")
    device_id: Optional[str] = Field(None, description="Client device id for simple identity")

class Vote(BaseModel):
    post_id: str = Field(..., description="Target post id as string")
    device_id: str = Field(..., description="Client device id for idempotent toggle")
