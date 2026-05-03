import asyncio
from judge import calculate_confidence

async def run_test():
    claim = "The national crime rate decreased in 2022 compared to 2021."
    evidence_items = [
        {"source": "FBI", "text": "According to the FBI's Uniform Crime Reporting program, violent crime decreased by 1.7% in 2022, while property crime increased by 7.1%. Overall national crime rates showed a slight decline."},
        {"source": "Pew Research", "text": "Pew Research Center analysis of federal data indicates a drop in the national violent crime rate in 2022, though public perception of crime remains high."}
    ]
    
    result = await calculate_confidence(claim, evidence_items)
    print("Test Result:", result)

if __name__ == "__main__":
    asyncio.run(run_test())
