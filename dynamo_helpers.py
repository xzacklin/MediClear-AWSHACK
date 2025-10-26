#
# dynamo_helpers.py
#
# This file handles all communication with the DynamoDB table.
#
import os
import boto3
import uuid
import json
from decimal import Decimal
from datetime import datetime, timezone
from dotenv import load_dotenv
from typing import List # <-- Import List
from boto3.dynamodb.conditions import Key # <-- Import Key

# --- LOAD ENV VARS ---
load_dotenv()

# --- ENV VARS ---
DYNAMO_TABLE_NAME = os.getenv("DYNAMO_TABLE_NAME")
AWS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_TOKEN = os.getenv("AWS_SESSION_TOKEN")
AWS_REGION = os.getenv("AWS_REGION")

# --- BOTO3 CLIENT ---
try:
    if not DYNAMO_TABLE_NAME:
        raise EnvironmentError("DYNAMO_TABLE_NAME is not set in .env file")

    session = boto3.Session(
        aws_access_key_id=AWS_KEY,
        aws_secret_access_key=AWS_SECRET,
        aws_session_token=AWS_TOKEN,
        region_name=AWS_REGION,
    )
    dynamodb = session.resource("dynamodb")
    table = dynamodb.Table(DYNAMO_TABLE_NAME)
    print("DynamoDB client and table initialized successfully.")
except Exception as e:
    print(f"Error initializing DynamoDB client: {e}")
    table = None

# Helper class to convert Python floats to DynamoDB Decimals
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, float):
            return Decimal(str(obj))
        return super(DecimalEncoder, self).default(obj)

def create_new_case(patient_id: str, provider_id: str, procedure_code: str) -> dict:
    """
    Creates a new case in DynamoDB with status 'PENDING'.
    """
    if not table:
        raise ValueError("DynamoDB table is not initialized.")
        
    case_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    
    item = {
        'case_id': case_id,
        'patient_id': patient_id,
        'provider_id': provider_id,
        'procedure_code': procedure_code,
        'status': 'PENDING',
        'created_at': timestamp,
        'last_updated': timestamp,
        'analysis': None,
        'policy_context': None,
        'clinical_context': None
    }
    
    try:
        table.put_item(Item=item)
        print(f"Created new case in DynamoDB with case_id: {case_id}")
        return item
    except Exception as e:
        print(f"Error creating case in DynamoDB: {e}")
        raise

# --- THIS FUNCTION IS UPDATED ---
def update_case_with_analysis(
    case_id: str, 
    status: str, 
    analysis_payload: dict, # Renamed from analysis_json
    policy_context: str, 
    clinical_context: str
) -> dict:
    """
    Updates an existing case with the RAG context and the agent's final analysis.
    """
    if not table:
        raise ValueError("DynamoDB table is not initialized.")

    timestamp = datetime.now(timezone.utc).isoformat()
    
    # Convert all floats in the analysis_payload JSON to Decimals for DynamoDB
    analysis_decimal = json.loads(json.dumps(analysis_payload), parse_float=Decimal)
    
    try:
        response = table.update_item(
            Key={'case_id': case_id},
            UpdateExpression=(
                "SET #s = :s, #a = :a, #pc = :pc, #cc = :cc, last_updated = :lu"
            ),
            ExpressionAttributeNames={
                '#s': 'status',
                '#a': 'analysis',
                '#pc': 'policy_context',
                '#cc': 'clinical_context',
            },
            ExpressionAttributeValues={
                ':s': status,
                ':a': analysis_decimal, # This now saves the correct, unwrapped object
                ':pc': policy_context,
                ':cc': clinical_context,
                ':lu': timestamp
            },
            ReturnValues="ALL_NEW"
        )
        print(f"Successfully updated case: {case_id} with status: {status}")
        return response.get('Attributes')
    except Exception as e:
        print(f"Error updating case {case_id} in DynamoDB: {e}")
        raise
# --- END UPDATE ---

def get_case(case_id: str) -> dict:
    """
    Retrieves a single case from DynamoDB by its ID.
    """
    if not table:
        raise ValueError("DynamoDB table is not initialized.")
        
    try:
        response = table.get_item(
            Key={'case_id': case_id}
        )
        item = response.get('Item')
        if not item:
            raise ValueError(f"Case {case_id} not found.")
        
        # Convert Decimals back to floats/ints for JSON response
        item = json.loads(json.dumps(item, cls=DecimalEncoder), parse_float=float)
        return item
        
    except Exception as e:
        print(f"Error getting case {case_id}: {e}")
        raise

# --- THIS IS THE NEW FUNCTION ---
def get_cases_by_patient_id(patient_id: str) -> List[dict]:
    """
    Retrieves a list of cases for a specific patient_id.
    
    *** NOTE: This function requires a Global Secondary Index (GSI) ***
    *** on the DynamoDB table. The GSI must:                     ***
    *** - Have an Index name (e.g., 'patient_id-index')         ***
    *** - Use 'patient_id' as its Partition Key (HASH)          ***
    """
    if not table:
        raise ValueError("DynamoDB table is not initialized.")
        
    # We will assume the GSI is named 'patient_id-index'
    # This must be created in your DynamoDB console.
    GSI_NAME = 'patient_id-index' 
        
    try:
        response = table.query(
            IndexName=GSI_NAME,
            KeyConditionExpression=Key('patient_id').eq(patient_id)
        )
        items = response.get('Items', [])
        
        # Convert Decimals back to floats/ints for JSON response
        result_items = []
        for item in items:
            result_items.append(
                json.loads(json.dumps(item, cls=DecimalEncoder), parse_float=float)
            )
            
        print(f"Found {len(result_items)} cases for patient_id: {patient_id}")
        return result_items
        
    except Exception as e:
        # This will often fail if the GSI 'patient_id-index' doesn't exist
        print(f"Error querying cases for patient_id {patient_id}: {e}")
        print("Please ensure a GSI with IndexName='patient_id-index' and PartitionKey='patient_id' exists.")
        raise
# --- END NEW FUNCTION ---