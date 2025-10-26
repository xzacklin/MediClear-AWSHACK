from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv # New import
import os # New import
from schemas import RagQueryInput, RagQueryOutput # New import
from aws_services import query_knowledge_base # New import

# --- Configuration ---
# Load environment variables from .env file
# This line looks for a file named '.env' in the same directory
load_dotenv()

# Get Knowledge Base IDs from environment
PROVIDER_KB_ID = os.getenv("PROVIDER_KB_ID")
INSURER_KB_ID = os.getenv("INSURER_KB_ID")

if not PROVIDER_KB_ID or not INSURER_KB_ID:
    print("WARNING: PROVIDER_KB_ID or INSURER_KB_ID is not set in .env file.")
    # In a real app, you would raise a proper startup error
    # For the hackathon, this print warning is fine.

# --- FastAPI App ---
app = FastAPI(
    title="Pre-Authorization RAG Agent",
    description="API for automating healthcare pre-authorization checks with AWS Bedrock.",
    version="0.1.0"
)

@app.get("/", tags=["Root"])
async def read_root():
    """
    Root endpoint to check if the server is running.
    """
    return {"message": "Pre-Authorization RAG Agent is running. Go to /docs for API documentation."}


# --- NEW ENDPOINTS ---

@app.post("/query/provider", tags=["RAG Query"], response_model=RagQueryOutput)
async def query_provider_kb(request: RagQueryInput):
    """
    Query the PROVIDER (e.g., clinical notes) Knowledge Base.
    """
    if not PROVIDER_KB_ID:
        raise HTTPException(status_code=500, detail="PROVIDER_KB_ID is not configured in your .env file.")
    
    # This calls the function from aws_services.py
    return query_knowledge_base(kb_id=PROVIDER_KB_ID, query=request.query)


@app.post("/query/insurer", tags=["RAG Query"], response_model=RagQueryOutput)
async def query_insurer_kb(request: RagQueryInput):
    """
    Query the INSURER (e.g., policy docs) Knowledge Base.
    """
    if not INSURER_KB_ID:
        raise HTTPException(status_code=500, detail="INSURER_KB_ID is not configured in your .env file.")
        
    # This calls the function from aws_services.py
    return query_knowledge_base(kb_id=INSURER_KB_ID, query=request.query)


# --- We will add the main '/analyze' endpoint in the next step ---
