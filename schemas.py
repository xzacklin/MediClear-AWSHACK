from pydantic import BaseModel
from typing import List, Optional

# This defines what a 'source chunk' looks like
class SourceChunk(BaseModel):
    text: str
    location: Optional[str] = None # e.g., "s3://my-bucket/insurance_policy.pdf"
    score: Optional[float] = None

# This is the data we expect to get back from our RAG query
class RagQueryOutput(BaseModel):
    generated_text: str
    source_chunks: List[SourceChunk]

# This is the data we'll send IN to our new API endpoint
class RagQueryInput(BaseModel):
    query: str
