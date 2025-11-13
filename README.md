<img width="1009" height="478" alt="Screenshot 2025-11-12 at 8 30 32 PM" src="https://github.com/user-attachments/assets/f3360108-8161-4d48-a7cc-8d075cacff26" />
MediClear

MediClear is a FastAPI-based application developed during a hackathon to streamline medical note processing, simplify patient data retrieval, and provide structured insights using AI-powered prompts. The project integrates AWS services, DynamoDB, and real-time WebSocket communication to support a responsive and reliable medical documentation workflow.

Features
AI-Driven Medical Note Processing

Converts unstructured medical notes into structured, query-ready data using a prompt-driven workflow.

Uses customizable system and user prompts for medical summarization, extraction, or classification.

AWS-Backed Data Storage

Stores processed notes and metadata in DynamoDB.

Encapsulates DynamoDB interactions in dedicated helper modules to keep logic maintainable.

Secure Backend API

FastAPI server with clearly defined schemas, validation, and routing.

Modular API design for extensibility.

Real-Time WebSocket Updates

WebSocket manager supports live notifications to connected clients.

Enables streaming results or real-time message updates.

Clean, Modular Codebase

Separated modules for prompts, AWS helpers, schemas, and WebSocket logic.

Simplifies future expansion such as adding authentication, analytics, or UI integration.

Project Structure
.
├── aws_services.py          # AWS DynamoDB helper utilities
├── dynamo_helpers.py        # CRUD and record-management abstractions
├── main.py                  # FastAPI application entrypoint
├── prompts.py               # System and user prompts for AI processing
├── schemas.py               # Pydantic models for request/response validation
├── websocket_manager.py     # WebSocket connection manager for real-time updates
├── requirements.txt         # Project dependencies
├── jordan_smith_notes.txt.metadata.json   # Example metadata file
├── sarah_chen_notes.txt.metadata.json    # Example metadata file

Architecture

The high-level architecture of MediClear is shown below.

flowchart LR
    subgraph Client
        UI[Web / Mobile Client]
    end

    subgraph Backend[FastAPI Backend]
        MAIN[main.py\nFastAPI App]
        WS[websocket_manager.py\nWebSocket Manager]
        PROMPTS[prompts.py\nPrompt Logic]
        SCHEMAS[schemas.py\nPydantic Schemas]
        AWSHELP[aws_services.py / dynamo_helpers.py\nDynamoDB Helpers]
    end

    subgraph AWS[AWS Cloud]
        DDB[(DynamoDB\nNotes / Metadata)]
    end

    UI <-- HTTP/JSON --> MAIN
    UI <-- WebSocket --> WS

    MAIN --> SCHEMAS
    MAIN --> PROMPTS
    MAIN --> AWSHELP
    WS --> AWSHELP
    AWSHELP --> DDB


Flow Summary

The client sends medical notes or related requests to the FastAPI backend over HTTP.

main.py validates incoming data using models from schemas.py and routes the request.

prompts.py provides the system and user prompts used to drive AI-based processing.

aws_services.py and dynamo_helpers.py handle storage and retrieval of processed notes and metadata in DynamoDB.

websocket_manager.py manages WebSocket connections, enabling real-time updates back to connected clients.

Requirements

Dependencies are listed in requirements.txt.

requirements


Example:

fastapi
uvicorn[standard]
boto3
pydantic
python-dotenv


To install:

pip install -r requirements.txt

Running the Application

Ensure you have your AWS credentials configured locally or stored in environment variables.

Start the FastAPI server:

uvicorn main:app --reload


Access the automatic API documentation:

Swagger UI: http://localhost:8000/docs

ReDoc: http://localhost:8000/redoc

Environment Variables

Use a .env file or system environment variables for:

AWS credentials

DynamoDB table name(s)

Any additional prompt or configuration overrides

Example .env:

AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-west-2
DYNAMO_TABLE_NAME=MediClearNotes

How It Works
1. Client Sends Medical Note

A user or system uploads a raw medical note or text payload.

2. FastAPI Receives and Validates

Request data is validated through Pydantic models defined in schemas.py.

3. Prompt Engine Processes the Note

prompts.py contains the system and user prompts that structure and guide the AI’s response.

4. DynamoDB Stores Processed Output

aws_services.py and dynamo_helpers.py insert or update medical note entries.

5. WebSocket Sends Real-Time Updates

If a frontend is connected, processed results can be pushed immediately via websocket_manager.py.

Example Input Metadata Files

The repository includes example metadata files used for testing or demonstration:

jordan_smith_notes.txt.metadata.json

sarah_chen_notes.txt.metadata.json

Example structure:

{
  "metadataAttributes": {
    "patient_id": "JS-10293"
  }
}

{
  "metadataAttributes": {
    "patient_id": "SC-44556"
  }
}


These illustrate how patient metadata can be attached to associated notes.

Future Improvements

Add user authentication and role-based access control for clinical environments.

Integrate vector search or embeddings for enhanced retrieval.

Add a frontend dashboard for providers or admins.

Provide version-controlled prompt templates for different medical specialties.

License

This project was created for a hackathon and may be freely extended or modified. Add your preferred license if needed
