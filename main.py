#
# main.py
#
# This file defines the FastAPI server and all API endpoints.
#
import os
import json
import boto3
from dotenv import load_dotenv

# --- LOAD ENV VARS FIRST ---
load_dotenv()
# --- END LOAD ENV ---

from fastapi import (
    FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect,
    UploadFile, File, Form
)
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from typing import Optional, List, Dict, Any
from fastapi.middleware.cors import CORSMiddleware
# Import our schemas and helper functions
from schemas import (
    RagQueryInput, RagQueryOutput,
    CreateCaseInput, CreateCaseOutput,
    InsurerDecisionInput
)
from aws_services import retrieve_from_knowledge_base, invoke_claude_agent
import dynamo_helpers

# Import the WebSocket manager
from websocket_manager import manager

# Get Knowledge Base IDs from environment
PROVIDER_KB_ID = os.getenv("PROVIDER_KB_ID")
INSURER_KB_ID = os.getenv("INSURER_KB_ID")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1") # Get region for boto3
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME") # For patient records

# --- BOTO3 Clients ---
# We initialize these clients with the region to avoid NoRegionError
sfn_client = boto3.client('stepfunctions', region_name=AWS_REGION)
s3_client = boto3.client('s3', region_name=AWS_REGION)
STEP_FUNCTION_ARN = os.getenv("STEP_FUNCTION_ARN")

if not all([PROVIDER_KB_ID, INSURER_KB_ID]):
    print("Error: PROVIDER_KB_ID or INSURER_KB_ID is not set in .env file.")

app = FastAPI(
    title="Pre-Authorization RAG Agent",
    description="API for managing and analyzing medical pre-authorization cases using Bedrock RAG.",
    version="0.1.0"
)
origins = [
    "http://localhost:5173", # Your frontend's address
    "http://localhost",
    "http://127.0.0.1",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods (GET, POST, etc.)
    allow_headers=["*"], # Allows all headers
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
    6. Broadcasts the result via WebSocket.
    7. Returns the final analysis.
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

        # Convert Decimals back to floats/ints for API and WebSocket
        final_case_data = json.loads(json.dumps(updated_item, default=str))

        # --- AGENTIC BROADCAST ---
        try:
            # Decide which channel to send the update to
            final_status = final_case_data.get("status")
            provider_channel = f"provider-{final_case_data.get('provider_id')}"
            
            if final_status == "MISSING_INFORMATION":
                # Push the "fix this" task to the doctor
                await manager.broadcast(provider_channel, final_case_data)
                
            elif final_status == "APPROVED_READY":
                # Push the "review this" task to the insurer queue
                await manager.broadcast("insurer-queue", final_case_data)
                # Also notify the doctor that it's ready
                await manager.broadcast(provider_channel, final_case_data)
                
        except Exception as e:
            # Don't fail the HTTP request if WebSocket fails
            print(f"[{case_id}] FAILED to broadcast WebSocket update: {e}")
        # --- END BROADCAST ---

        return final_case_data

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


# --- NEW ENDPOINTS FOR INSURER DASHBOARD ---

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
    which updates the case in DynamoDB and notifies the doctor.
    """
    try:
        updated_item = await run_in_threadpool(
            dynamo_helpers.update_case_decision,
            case_id=request.case_id,
            final_status=request.decision,
            insurer_notes=request.notes
        )
        
        # --- AGENTIC BROADCAST (Close the loop) ---
        try:
            # Send the final decision back to the doctor
            provider_channel = f"provider-{updated_item.get('provider_id')}"
            await manager.broadcast(provider_channel, updated_item)
        except Exception as e:
            # Don't fail the HTTP request if WebSocket fails
            print(f"[{updated_item.get('case_id')}] FAILED to broadcast decision: {e}")
        # --- END BROADCAST ---

        return updated_item
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- NEW ENDPOINT FOR S3 UPLOAD ---

@app.post("/upload-patient-record", summary="Upload Patient PDF to S3", tags=["Patients"])
async def upload_patient_record(
    patient_id: str = Form(...),
    patient_file: UploadFile = File(...)
):
    """
    Uploads a patient's PDF record to the S3 bucket for the Knowledge Base.
    Also uploads the required .metadata.json file.
    """
    if not S3_BUCKET_NAME:
        raise HTTPException(status_code=500, detail="S3_BUCKET_NAME is not configured.")

    # 1. Upload the PDF
    pdf_filename = f"{patient_id}_{patient_file.filename}"
    try:
        s3_client.upload_fileobj(
            patient_file.file,
            S3_BUCKET_NAME,
            pdf_filename
        )
        print(f"Successfully uploaded file: {pdf_filename}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload PDF: {e}")

    # 2. Upload the Metadata file (CRITICAL)
    metadata_filename = f"{pdf_filename}.metadata.json"
    metadata_content = {
        "metadataAttributes": {
            "patient_id": patient_id
        }
    }
    
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=metadata_filename,
            Body=json.dumps(metadata_content),
            ContentType='application/json'
        )
        print(f"Successfully uploaded metadata: {metadata_filename}")
    except Exception as e:
        # Don't leave an orphaned PDF
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=pdf_filename)
        raise HTTPException(status_code=500, detail=f"Failed to upload metadata: {e}")

    return {"status": "success", "filename": pdf_filename}


# --- TEST ENDPOINTS ---

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


# --- WEBSOCKET ENDPOINT ---

@app.websocket("/ws/{channel_id}")
async def websocket_endpoint(websocket: WebSocket, channel_id: str):
    """
    Main WebSocket connection endpoint.
    Clients connect here and "subscribe" to a channel.
    
    - Doctors should connect to: "provider-{provider_id}" (e.g., "provider-doctor@example.com")
    - Insurers should connect to: "insurer-queue"
    """
    await manager.connect(channel_id, websocket)
    try:
        while True:
            # Keep the connection alive
            # In a real app, you might receive pings/pongs
            await websocket.receive_text() 
    except WebSocketDisconnect:
        manager.disconnect(channel_id, websocket)
    except Exception as e:
        print(f"WebSocket Error: {e}")
        manager.disconnect(channel_id, websocket)