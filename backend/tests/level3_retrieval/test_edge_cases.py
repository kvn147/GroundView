import asyncio
import os
import sys

# Ensure the project root directory is in the path so we can import 'backend.xyz'
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backend.agents.agent_healthcare import retrieve_evidence as hc_retrieve
from backend.agents.agent_immigration import retrieve_evidence as imm_retrieve
from backend.agents.agent_crime import retrieve_evidence as cr_retrieve
from backend.agents.agent_economy import retrieve_evidence as ec_retrieve
from backend.agents.agent_education import retrieve_evidence as ed_retrieve

async def main():
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Error: OPENROUTER_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    print("Testing Edge Cases on All Agents...\n")
    
    # Claims that cross the boundary between Healthcare and Immigration
    edge_cases = [
        "Undocumented immigrants are placing a massive financial strain on emergency rooms in border states.",
        "Foreign-born nurses are essential to filling the current labor shortage in the US healthcare system.",
        "Recent visa restrictions are preventing international medical graduates from completing their residencies in the United States."
    ]

    for i, claim in enumerate(edge_cases, 1):
        print(f"==================================================")
        print(f"EDGE CASE {i}:\n\"{claim}\"")
        print(f"==================================================\n")
        
        # Test Healthcare Agent
        print("--- [HEALTHCARE AGENT RESPONSE] ---")
        try:
            hc_evidence = await hc_retrieve(claim)
            print(hc_evidence)
        except Exception as e:
            print(f"Healthcare agent failed: {e}")
            
        print("\n\n--- [IMMIGRATION AGENT RESPONSE] ---")
        # Test Immigration Agent
        try:
            imm_evidence = await imm_retrieve(claim)
            print(imm_evidence)
        except Exception as e:
            print(f"Immigration agent failed: {e}")
            
        print("\n\n--- [CRIME AGENT RESPONSE] ---")
        try:
            cr_evidence = await cr_retrieve(claim)
            print(cr_evidence)
        except Exception as e:
            print(f"Crime agent failed: {e}")
            
        print("\n\n--- [ECONOMY AGENT RESPONSE] ---")
        try:
            ec_evidence = await ec_retrieve(claim)
            print(ec_evidence)
        except Exception as e:
            print(f"Economy agent failed: {e}")
            
        print("\n\n--- [EDUCATION AGENT RESPONSE] ---")
        try:
            ed_evidence = await ed_retrieve(claim)
            print(ed_evidence)
        except Exception as e:
            print(f"Education agent failed: {e}")
            
        print("\n\n")

if __name__ == "__main__":
    asyncio.run(main())
