#
# aws_services.py
#
# This file handles all Bedrock API calls.
#
import os
import json
import boto3
from dotenv import load_dotenv
from typing import Optional, Dict, Any # Import Optional, Dict, Any

# Import our Pydantic models and the new agent prompt
from schemas import RagQueryOutput, SourceChunk 
from prompts import PRE_AUTH_SYSTEM_PROMPT

# --- LOAD ENV VARS ---
load_dotenv()

# --- ENV VARS ---
AWS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_TOKEN = os.getenv("AWS_SESSION_TOKEN")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# This is the ARN for our AGENT model (Haiku)
AGENT_MODEL_ARN = os.getenv("CLAUDE_MODEL_ID", "").strip()


# --- BOTO3 CLIENTS ---
try:
    if not all([AWS_KEY, AWS_SECRET, AWS_TOKEN, AWS_REGION, AGENT_MODEL_ARN]):
        raise EnvironmentError(
            "Missing one or more required environment variables. "
            "Check your .env file for: "
            "AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN, AWS_REGION, CLAUDE_MODEL_ID"
        )

    session = boto3.Session(
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET,
        aws_session_token=AWS_TOKEN,
        region_name=AWS_REGION,
    )

    # RAG (Knowledge Base) client
    bedrock_agent_runtime = session.client("bedrock-agent-runtime")
    
    # Direct model calls (for the agent) client
    bedrock_runtime = session.client("bedrock-runtime")

    print("Boto3 clients initialized successfully.")
except Exception as e:
    print(f"Error initializing Boto3 clients: {e}")
    bedrock_agent_runtime = None
    bedrock_runtime = None


# --- RAG RETRIEVAL (with Metadata Filter support) ---
def retrieve_from_knowledge_base(
    kb_id: str, 
    query: str,
    patient_filter: Optional[Dict[str, Any]] = None # <-- Accepts filter
) -> RagQueryOutput:
    """
    Retrieves relevant text chunks from a Bedrock Knowledge Base
    using the 'retrieve' API.
    
    Can optionally filter by metadata (e.g., for a specific patient_id).
    """
    if not bedrock_agent_runtime:
        raise ValueError("Boto3 client 'bedrock-agent-runtime' is not initialized.")

    print(f"RAG: Retrieving from KB {kb_id} with query: {query}")
    
    # Start with the default configuration
    retrieval_config = {
        'vectorSearchConfiguration': {
            'numberOfResults': 5 
        }
    }
    
    # If a filter is provided, add it to the configuration
    if patient_filter:
        print(f"RAG: Applying metadata filter: {patient_filter}")
        retrieval_config['vectorSearchConfiguration']['filter'] = patient_filter

    try:
        # The key API call.
        response = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={
                'text': query
            },
            retrievalConfiguration=retrieval_config # <-- Use the new config
        )

        retrieval_results = response.get('retrievalResults', [])
        
        source_chunks = []
        for result in retrieval_results:
            source_chunks.append(SourceChunk(
                text=result['content']['text'],
                location=result['location']['s3Location']['uri'],
                score=result.get('score', 0.0)
            ))

        return RagQueryOutput(
            generated_text="", # This field is not used
            source_chunks=source_chunks
        )

    except Exception as e:
        print(f"Error retrieving from Knowledge Base {kb_id}: {e}")
        return RagQueryOutput(
            generated_text=f"An error occurred while retrieving from the Knowledge Base: {e}",
            source_chunks=[]
        )


# --- AGENT INVOCATION (This function is updated) ---

def invoke_claude_agent(
    policy_context: str, 
    clinical_context: str, 
    procedure_code: str
) -> dict:
    """
    Calls the Claude Haiku model directly (the "agent") with the
    RAG context to perform the final JSON analysis.
    """
    if not bedrock_runtime:
        raise ValueError("Boto3 client 'bedrock-runtime' is not initialized.")

    # We dynamically insert the procedure code into the system prompt
    # to "anchor" the agent to the correct task.
    system_prompt = PRE_AUTH_SYSTEM_PROMPT.replace("{procedure_code}", procedure_code)

    # Construct the user prompt with the retrieved context
    user_prompt = f"""
    Here is the information. Please perform the pre-authorization analysis.

    <Insurer_Policy_Criteria>
    {policy_context}
    </Insurer_Policy_Criteria>

    <Patient_Clinical_Data>
    {clinical_context}
    </Patient_Clinical_Data>
    """
    
    # Construct the request body for the Bedrock Messages API (for Claude 3)
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": system_prompt, # <-- Pass the new dynamic prompt
        "messages": [
            {
                "role": "user",
                "content": user_prompt
            }
        ]
    })
    
    # Initialize cleaned_text here for the except block
    cleaned_text = ""
    agent_output_text = ""
    
    try:
        print(f"AGENT: Invoking agent with model: {AGENT_MODEL_ARN}")
        
        response = bedrock_runtime.invoke_model(
            body=body,
            modelId=AGENT_MODEL_ARN,
            contentType='application/json',
            accept='application/json'
        )
        
        response_body = json.loads(response.get('body').read())
        agent_output_text = response_body.get("content")[0].get("text")
        
        print(f"Agent raw output: {agent_output_text}")
        
        # --- NEW FIX: Robustly find the JSON object ---
        # Find the first '{' and last '}' to isolate the JSON object
        first_brace = agent_output_text.find('{')
        last_brace = agent_output_text.rfind('}')
        
        if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
            # If no JSON object is found, raise an error
            raise json.JSONDecodeError("No valid JSON object found in agent output", agent_output_text, 0)

        cleaned_text = agent_output_text[first_brace:last_brace+1]
        # --- END FIX ---

        print(f"Agent CLEANED output: {cleaned_text}")
        
        # Parse the cleaned, valid JSON string
        return json.loads(cleaned_text)

    except json.JSONDecodeError as json_e:
        print(f"Error: Agent did not return valid JSON. {json_e}")
        # Log the text that *failed* to parse
        print(f"Failed to parse: {cleaned_text}") 
        print(f"Raw output was: {agent_output_text}")
        return {"status": "AGENT_ERROR", "analysis": {"error": "Agent failed to produce valid JSON output."}}
    except Exception as e:
        print(f"Error invoking model {AGENT_MODEL_ARN}: {e}")
        return {"status": "AGENT_ERROR", "analysis": {"error": f"Error invoking agent model: {e}"}}