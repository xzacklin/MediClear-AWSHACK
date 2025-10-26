#
# main.py
#
# This file defines the FastAPI server and all API endpoints.
#
import os
import json
from dotenv import load_dotenv

# --- LOAD ENV VARS FIRST ---
load_dotenv()
# --- END LOAD ENV ---

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from typing import Optional, List # <-- Import List

# Import our schemas and helper functions
from schemas import (
    RagQueryInput, RagQueryOutput,
    CreateCaseInput, CreateCaseOutput,
    InsurerDecisionInput # <-- ADD THIS LINE
)
from aws_services import retrieve_from_knowledge_base, invoke_claude_agent
import dynamo_helpers

# Get Knowledge Base IDs from environment
PROVIDER_KB_ID = os.getenv("PROVIDER_KB_ID")
INSURER_KB_ID = os.getenv("INSURER_KB_ID")

if not all([PROVIDER_KB_ID, INSURER_KB_ID]):
    print("Error: PROVIDER_KB_ID or INSURER_KB_ID is not set in .env file.")

app = FastAPI(
    title="Pre-Authorization RAG Agent",
    description="API for managing and analyzing medical pre-authorization cases using Bedrock RAG.",
    version="0.1.0"
)

# --- Global Exception Handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global exception handler caught: {exc}")
    # Print the full traceback
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"message": f"An unexpected server error occurred: {str(exc)}"},
    )

# --- API Endpoints ---

@app.get("/", summary="Check Server Status", tags=["Status"])
def get_status():
    """Check if the server is running."""
    return {"message": "Pre-Authorization RAG Agent is running. Go to /docs for API documentation."}


@app.post("/create-pre-auth", response_model=CreateCaseOutput, summary="Create and Analyze Pre-Auth Case", tags=["Cases"])
async def create_and_analyze_case(request: CreateCaseInput):
    """
    Runs the full pre-authorization process:
    1. Creates a new case in DynamoDB (Status: PENDING).
    2. Retrieves from Provider KB for clinical notes, *filtered by patient_id*.
    3. Retrieves from Insurer KB for policy rules.
    4. Sends *all relevant policy chunks* and *all* filtered clinical notes to the Claude agent.
    5. Updates the case in DynamoDB with the result.
    6. Returns the final analysis.
    """

    # --- Step 1: Create PENDING case in DynamoDB ---
    print(f"Creating new case for patient: {request.patient_id}")
    new_case = await run_in_threadpool(
        dynamo_helpers.create_new_case,
        patient_id=request.patient_id,
        provider_id=request.provider_id,
        procedure_code=request.procedure_code
    )
    case_id = new_case['case_id']

    try:
        # --- Step 2: Run RAG retrievals in parallel (in threadpool) ---
        print(f"[{case_id}] Running RAG retrievals...")
        policy_query = f"What are the medical necessity criteria for {request.procedure_code}?"
        # This query is simpler, as the filter will do the precise matching
        clinical_query = f"Clinical notes for patient {request.patient_id} related to {request.procedure_code}."

        # Create the exact metadata filter for the Provider KB
        clinical_filter = {
            "equals": {
                "key": "patient_id",
                "value": request.patient_id
            }
        }
        
        policy_rag_result = await run_in_threadpool(
            retrieve_from_knowledge_base, 
            kb_id=INSURER_KB_ID, 
            query=policy_query
        )
        clinical_rag_result = await run_in_threadpool(
            retrieve_from_knowledge_base, 
            kb_id=PROVIDER_KB_ID, 
            query=clinical_query,
            patient_filter=clinical_filter # <-- Pass the filter here
        )

        # Join ALL relevant policy chunks to get the full section
        if policy_rag_result.source_chunks:
            policy_context = "\n".join([chunk.text for chunk in policy_rag_result.source_chunks])
            print(f"[{case_id}] Using ALL policy chunks: {policy_context[:200]}...") # Log first 200 chars
        else:
            policy_context = "" # Handle case where no policy chunks are found

        # We concatenate all clinical chunks, as they are now guaranteed
        # to be *only* for the correct patient due to the metadata filter.
        clinical_context = "\n".join([chunk.text for chunk in clinical_rag_result.source_chunks])

        if not policy_context or not clinical_context:
            print(f"[{case_id}] Error: RAG queries returned no relevant context.")
            # Be more specific if policy is missing
            error_detail = "Could not find matching policy or clinical documents in Knowledge Bases."
            if not policy_context:
                error_detail = f"Could not find relevant policy section for procedure '{request.procedure_code}'."
            elif not clinical_context:
                 error_detail = f"Could not find clinical notes for patient '{request.patient_id}' related to procedure '{request.procedure_code}'."

            raise HTTPException(status_code=404, detail=error_detail)

        # --- Step 3: Invoke Agent for Analysis ---
        print(f"[{case_id}] Retrieval complete. Invoking agent for analysis...")

        analysis_json = await run_in_threadpool(
            invoke_claude_agent,
            policy_context=policy_context, # Pass the CLEAN context
            clinical_context=clinical_context,
            procedure_code=request.procedure_code
        )

        final_status = analysis_json.get("status", "AGENT_ERROR")

        analysis_payload = analysis_json.get("analysis", analysis_json)

        # --- Step 4: Update case in DynamoDB with final analysis ---
        print(f"[{case_id}] Analysis complete. Updating DynamoDB...")
        updated_item = await run_in_threadpool(
            dynamo_helpers.update_case_with_analysis,
            case_id=case_id,
            status=final_status,
            analysis_payload=analysis_payload,
            policy_context=policy_context, # Save the clean context
            clinical_context=clinical_context
        )

        print(f"[{case_id}] Process complete.")

        # Convert Decimals back to floats/ints for the API response
        return json.loads(json.dumps(updated_item, default=str))

    except Exception as e:
        # If anything fails, log the error to the case in DynamoDB
        print(f"[{case_id}] An error occurred: {e}")
        await run_in_threadpool(
            dynamo_helpers.update_case_with_analysis,
            case_id=case_id,
            status="SYSTEM_ERROR",
            analysis_payload={"error": str(e)},
            policy_context="",
            clinical_context=""
        )

        # Re-raise the exception so the user gets a 500 error
        raise


@app.get("/get-case-status/{case_id}", response_model=CreateCaseOutput, summary="Get Case Status", tags=["Cases"])
async def get_case_status(case_id: str):
    """
    Retrieves the full details and analysis results for a specific case by its ID.
    """
    try:
        case_item = await run_in_threadpool(dynamo_helpers.get_case, case_id=case_id)
        return case_item
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- THIS IS THE NEW ENDPOINT ---
@app.get("/get-cases-by-patient/{patient_id}", response_model=List[CreateCaseOutput], summary="Get Cases by Patient ID", tags=["Cases"])
async def get_cases_by_patient(patient_id: str):
    """
    Retrieves a list of all cases associated with a specific patient_id.
    
    This requires a 'patient_id-index' GSI on the DynamoDB table.
    """
    try:
        case_list = await run_in_threadpool(dynamo_helpers.get_cases_by_patient_id, patient_id=patient_id)
        if not case_list:
            # Return an empty list, which is valid, but good to know
            print(f"No cases found for patient: {patient_id}")
        return case_list
    except Exception as e:
        # This will catch errors from dynamo_helpers, e.g., if the GSI is missing
        print(f"Error querying for patient_id {patient_id}: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred while querying for patient cases: {e}")
# --- END NEW ENDPOINT ---


@app.post("/query/provider", response_model=RagQueryOutput, summary="Query Provider KB (Test)", tags=["RAG Query"])
async def query_provider_kb_endpoint(request: RagQueryInput):
    """
    (Test Endpoint) **Retrieves** from the Provider Knowledge Base directly.
    The 'generated_text' will be empty.
    """
    if not PROVIDER_KB_ID:
        raise HTTPException(status_code=500, detail="PROVIDER_KB_ID is not configured.")

    response = await run_in_threadpool(retrieve_from_knowledge_base, kb_id=PROVIDER_KB_ID, query=request.query)
    return response


@app.post("/query/insurer", response_model=RagQueryOutput, summary="Query Insurer KB (Test)", tags=["RAG Query"])
async def query_insurer_kb_endpoint(request: RagQueryInput):
    """
    (Test Endpoint) **Retrieves** from the Insurer Knowledge Base directly.
    The 'generated_text' will be empty.
    """
    if not INSURER_KB_ID:
        raise HTTPException(status_code=500, detail="INSURER_KB_ID is not configured.")

    response = await run_in_threadpool(retrieve_from_knowledge_base, kb_id=INSURER_KB_ID, query=request.query)
    return response

@app.get("/get-cases-by-status/{status}", response_model=List[CreateCaseOutput], summary="Get Cases by Status (for Insurer)", tags=["Insurer"])
async def get_cases_by_status_endpoint(status: str):
    """
    Retrieves a list of all cases with a specific status.
    (e.g., 'APPROVED_READY' for the insurer work queue)
    
    This requires the 'status-index' GSI on the DynamoDB table.
    """
    try:
        case_list = await run_in_threadpool(dynamo_helpers.get_cases_by_status, status=status)
        return case_list
    except Exception as e:
        print(f"Error querying for status {status}: {e}")
        raise HTTPException(status_code=500, detail=f"An error occurred while querying for cases: {e}")

@app.post("/submit-decision", response_model=CreateCaseOutput, summary="Submit Final Insurer Decision", tags=["Insurer"])
async def submit_insurer_decision(request: InsurerDecisionInput):
    """
    Allows an insurer to submit a final 'APPROVED' or 'DENIED' decision,
    which updates the case in DynamoDB.
    """
    try:
        updated_item = await run_in_threadpool(
            dynamo_helpers.update_case_decision,
            case_id=request.case_id,
            final_status=request.decision,
            insurer_notes=request.notes
        )
        return updated_item
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))