#
# schemas.py
#
# This file contains all Pydantic models for API request/response validation.
#
from pydantic import BaseModel
from typing import List, Optional, Dict, Any # <-- Import 'Any'

# --- RAG Query Models ---

class SourceChunk(BaseModel):
    text: str
    location: Optional[str] = None
    score: Optional[float] = 0.0

class RagQueryOutput(BaseModel):
    generated_text: str
    source_chunks: List[SourceChunk]

class RagQueryInput(BaseModel):
    query: str

# --- Pre-Auth Case Models ---

class CreateCaseInput(BaseModel):
    """
    Data needed to start a new pre-auth case.
    """
    patient_id: str
    provider_id: str
    procedure_code: str # e.g., "CPT 73721 (MRI Left Knee)"

class CaseAnalysisDetail(BaseModel):
    """
    The structure for a single line-item in the agent's analysis.
    """
    met: bool
    evidence: str
    policy_reference: str

class CreateCaseOutput(BaseModel):
    """
    The final response after a case is created and analyzed.
    This is what is stored in DynamoDB.
    """
    case_id: str
    patient_id: str
    provider_id: str
    procedure_code: str
    status: str
    created_at: str
    last_updated: str
    
    # --- THIS IS THE FIX ---
    # We are changing 'Dict[str, CaseAnalysisDetail]' to 'Dict[str, Any]'.
    # This tells Pydantic that 'analysis' can be ANY object,
    # including our '{"error": "..."}' object.
    analysis: Optional[Dict[str, Any]] = None
    # --- END FIX ---
    
    policy_context: Optional[str] = None
    clinical_context: Optional[str] = None