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

from backend.agents.agent_immigration import retrieve_evidence

async def main():
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Error: OPENROUTER_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please set it in your .env file", file=sys.stderr)
        sys.exit(1)

    print("Testing Immigration Agent with OpenRouter...")
    
    # Test claim
    claim = "The number of people obtaining lawful permanent resident status in the United States increased significantly from 2020 to 2022."
    
    print(f"\nClaim: {claim}\n")
    print("Retrieving evidence (this may take a few seconds)...\n")
    
    try:
        evidence = await retrieve_evidence(claim)
        print("=== RETRIEVED EVIDENCE ===")
        print(evidence)
        print("==========================")
    except Exception as e:
        print(f"Failed to retrieve evidence: {e}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
