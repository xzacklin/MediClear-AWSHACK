import boto3
import os
import json
from schemas import RagQueryOutput, SourceChunk # Import our new data models

# --- Bedrock Client Initialization ---
# We'll get credentials from environment variables (loaded in main.py)
# Note: We use 'bedrock-agent-runtime' for RAG queries, not 'bedrock'
try:
    session = boto3.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION")
    )
    bedrock_agent_runtime = session.client('bedrock-agent-runtime')
    
    # We also need the regular bedrock client for later (Step 3)
    bedrock_runtime = session.client('bedrock-runtime')

except Exception as e:
    print(f"Error initializing Boto3 clients: {e}")
    # Handle error appropriately, maybe raise it
    bedrock_agent_runtime = None
    bedrock_runtime = None

def query_knowledge_base(kb_id: str, query: str) -> RagQueryOutput:
    """
    Queries a specific Bedrock Knowledge Base and returns a structured response.
    """
    if not bedrock_agent_runtime:
        raise ValueError("Boto3 client 'bedrock-agent-runtime' is not initialized.")

    try:
        # The key API call
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': query
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': kb_id,
                    # Use the default model configured in your KB settings
                    'modelArn': os.getenv("CLAUDE_MODEL_ID") 
                }
            }
        )
        
        # Parse the response
        generated_text = response['output']['text']
        citations = response.get('citations', [])
        
        source_chunks = []
        for citation in citations:
            retrieved_refs = citation.get('retrievedReferences', [])
            for ref in retrieved_refs:
                source_chunks.append(SourceChunk(
                    text=ref['content']['text'],
                    location=ref['location']['s3Location']['uri'],
                    score=ref.get('score') # Add score if available
                ))
        
        return RagQueryOutput(
            generated_text=generated_text,
            source_chunks=source_chunks
        )

    except Exception as e:
        print(f"Error querying Knowledge Base {kb_id}: {e}")
        # In a real app, you'd return an HTTP error
        return RagQueryOutput(
            generated_text=f"Error: {e}",
            source_chunks=[]
        )

# --- We will add the Claude 'invoke_model' function here in the next step ---