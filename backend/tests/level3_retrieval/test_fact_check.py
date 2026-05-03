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

from backend.agents.base_agent import run_domain_agent

async def main():
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Error: OPENROUTER_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please set it in your .env file", file=sys.stderr)
        sys.exit(1)

    print("Testing Universal Fact Check Override...")
    
    # Test claim that is famously fact-checked by PolitiFact/FactCheck.org
    claim = "Barack Obama was born in Kenya."
    
    print(f"\nClaim: {claim}\n")
    print("Retrieving evidence (this should be fast if fact-checked)...\n")
    
    try:
        # We can route it to any domain, like 'crime', but the fact checker should intercept it first.
        evidence = await run_domain_agent(
            domain="crime",
            specialty_desc="criminal justice",
            source_examples="(like BJS)",
            claim=claim
        )
        print("=== RETRIEVED EVIDENCE ===")
        print(evidence)
        print("==========================")
        
        # Verify that it overrode the standard retrieval
        if "### Universal Fact Check Verification" in evidence:
            print("\n✅ SUCCESS: The Universal Fact Check correctly overrode the standard retrieval.")
        else:
            print("\n❌ FAILURE: The Universal Fact Check did not override the standard retrieval.")
            sys.exit(1)
            
    except Exception as e:
        print(f"Failed to retrieve evidence: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
