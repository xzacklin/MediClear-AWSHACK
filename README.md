#MediClear - AWS Hackathon**
#Project Description**
This project is a FastAPI backend designed to automate medical pre-authorization requests. It functions as an analysis agent that uses AWS Bedrock and a Retrieval-Augmented Generation (RAG) pipeline to compare patient clinical notes against insurer policy criteria.

The system ingests a request, retrieves relevant documents from two separate Bedrock Knowledge Bases (one for provider notes, one for insurer policy), and uses a language model to perform a detailed analysis. The result is a structured JSON object that determines if the request is approved, needs more information, or is denied, based on the evidence.

The API also supports a real-time workflow using WebSockets to notify front-end applications (e.g., a provider's dashboard or an insurer's work queue) of case status changes.

**#Core Features
**Automated RAG Analysis: Runs a full RAG pipeline for each request, retrieving from separate insurer and provider knowledge bases.

Metadata Filtering: Securely retrieves patient data by using metadata filters (patient_id) on the provider Knowledge Base.

Structured JSON Output: Uses a Claude 3 Haiku agent with a specific system prompt to generate a consistent, parsable JSON analysis.

Real-Time Notifications: Employs WebSockets to broadcast case updates to subscribed provider and insurer channels.

Case Management Workflow: Provides API endpoints for creating new cases, fetching cases by ID, patient, or status, and allowing insurers to submit a final decision.

Data Ingestion: Includes an S3 upload endpoint to add new patient records and their required metadata files to the Bedrock Knowledge Base.

**Technology Stack**
-Backend Framework: FastAPI
-ASGI Server: Uvicorn
-AWS SDK: Boto3
-Data Validation: Pydantic
-Configuration: Python-dotenv
-AWS Services Used:
  Amazon Bedrock: For Knowledge Bases (RAG) and Claude 3 Haiku model invocation.
  Amazon DynamoDB: As the primary database for storing case data.
  Amazon S3: For storing patient documents that act as the data source for the provider Knowledge Base.

**How It Works**
-A provider submits a new case via POST /create-pre-auth with a patient_id, provider_id, and procedure_code.
-A new case item is created in DynamoDB with a PENDING status.
-The system queries two Bedrock Knowledge Bases in parallel:
-Insurer KB: Retrieves policy criteria related to the procedure_code.
-Provider KB: Retrieves clinical notes, using a metadata filter for the specific patient_id.
-The text from both retrievals is concatenated and passed as context to the Claude 3 Haiku agent.
-The agent analyzes the context against the rules in prompts.py and generates a JSON object with a final status: APPROVED_READY, MISSING_INFORMATION, or AI_DENIED.
-The case in DynamoDB is updated with this JSON analysis and the new status.
-A WebSocket message containing the full case update is broadcast to the relevant channels (e.g., provider-{provider_id} and/or insurer-queue).
-An insurer can later fetch cases in the APPROVED_READY queue and submit a final APPROVED or DENIED decision via POST /submit-decision.

**AWS Prerequisites**
This application will not run without the following AWS resources configured:
DynamoDB Table: A table (name defined in .env) with case_id as the primary key. This table MUST have two Global Secondary Indexes (GSIs):
  An index named patient_id-index with patient_id as its partition key.
  An index named status-index with status as its partition key.
Bedrock Knowledge Bases:
  An Insurer KB (ID set as INSURER_KB_ID) containing policy documents.
  A Provider KB (ID set as PROVIDER_KB_ID) containing patient clinical notes. This KB's data source (S3) must be configured to use metadata       files (e.g., filename.pdf.metadata.json) containing a patient_id attribute.
Bedrock Model Access: You must have access to the Claude 3 Haiku model (or other model, specified by CLAUDE_MODEL_ID) in the specified AWS region.
S3 Bucket: An S3 bucket (name set as S3_BUCKET_NAME) that serves as the data source for the Provider KB.

****Setup and Installation**
Clone the repository.
Create and activate a Python virtual environment:
python -m venv venv
source venv/bin/activate
# On Windows: venv\Scripts\activate
Install the required dependencies:

Bash

pip install -r requirements.txt
Configuration
Create a .env file in the root of the project and add the following environment variables.

# AWS Credentials
AWS_ACCESS_KEY_ID=YOUR_AWS_ACCESS_KEY
AWS_SECRET_ACCESS_KEY=YOUR_AWS_SECRET_KEY
AWS_SESSION_TOKEN=YOUR_AWS_SESSION_TOKEN
AWS_REGION=us-east-1

# DynamoDB
DYNAMO_TABLE_NAME=your-dynamo-table-name

# Bedrock
PROVIDER_KB_ID=YOUR_PROVIDER_KB_ID
INSURER_KB_ID=YOUR_INSURER_KB_ID
CLAUDE_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0

# S3
S3_BUCKET_NAME=your-kb-s3-bucket-name

# Step Functions (if used)
STEP_FUNCTION_ARN=YOUR_STEP_FUNCTION_ARN
Running the Server
Run the application using Uvicorn:

Bash

uvicorn main:app --reload
The API will be available at http://127.0.0.1:8000. You can access the auto-generated documentation at http://1227.0.0.1:8000/docs.

Key API Endpoints
POST /create-pre-auth: Creates and analyzes a new pre-authorization case.

GET /get-case-status/{case_id}: Retrieves the full details and analysis for a specific case.

GET /get-cases-by-patient/{patient_id}: Lists all cases associated with a specific patient.

GET /get-cases-by-status/{status}: Lists cases by status (e.g., APPROVED_READY for the insurer queue).

POST /submit-decision: Allows an insurer to submit a final APPROVED or DENIED decision.

POST /upload-patient-record: Uploads a patient document and its metadata file to S3 for the Knowledge Base.

WEBSOCKET /ws/{channel_id}: The WebSocket endpoint for real-time client connections.
