# Sources

Source-of-truth document for L3 agent allowlists. Each domain agent's
`ALLOWED_SOURCES` frozenset must match the corresponding section here.
The L3 base class normalizes case/punctuation but enforces exact-name
matching against the allowlist — see `backend/agents/base.py`.

Topic-expansion discipline: a new topic earns a slot only if it has at
least three authoritative sources distinct from `Universal Fact
Checkers` and from every other topic's allowlist. See
`backend/app/level2b_routing/topics.py` for the rule.

## Universal Fact Checkers (Priority)
- PolitiFact
- FactCheck.org
- Snopes
- Associated Press Fact Check
- Reuters Fact Check
- Washington Post Fact Checker

## Healthcare
- BLS (Bureau of Labor Statistics) for healthcare economic/employment data.
- CDC, NIH, WHO for medical and epidemiological data.
- KFF for health policy data.
- CMS (Centers for Medicare & Medicaid Services) for Medicare/Medicaid policy and spending.
- AHRQ (Agency for Healthcare Research and Quality) for healthcare quality and outcomes data.
- Commonwealth Fund for health policy research.

## Immigration
- USCIS (U.S. Citizenship and Immigration Services) for immigration statistics and policy data.
- Migration Policy Institute for research and analysis on immigration policy.
- Pew Research Center for data on immigration trends and public opinion.
- The United Nations High Commissioner for Refugees (UNHCR) for information on refugees and asylum seekers.
- BLS (Bureau of Labor Statistics) for employment data related to immigration.
- Customs and Border Protection for border-related data and statistics.
- ICE (Immigration and Customs Enforcement) for deportation and enforcement data.
- DHS Office of Immigration Statistics for the authoritative immigration dataset.
- EOIR (Executive Office for Immigration Review) for immigration court statistics.
- Cato Institute for peer-reviewed immigration data (right-of-center peer to MPI).

## Crime
- The Bureau of Justice Statistics (BJS)
- The FBI Uniform Crime Reporting (UCR) Program
- The National Institute of Justice (NIJ)
- Pew Research Center for data on crime trends and public opinion.
- The Sentencing Project for data on incarceration and sentencing.
- National Center for State Courts for state-level court data.
- Vera Institute of Justice for criminal justice research.

## Economy
- The Bureau of Economic Analysis (BEA)
- The Federal Reserve Economic Data (FRED)
- The U.S. Census Bureau
- The Bureau of Labor Statistics (BLS)
- The Organization for Economic Co-operation and Development (OECD)
- CBO (Congressional Budget Office) for fiscal projections.
- IMF (International Monetary Fund) for global economic data.
- Treasury Department for federal fiscal/debt data.
- Tax Policy Center for tax-policy analysis.

## Education
- The National Center for Education Statistics (NCES)
- The Bureau of Labor Statistics (BLS)
- The U.S. Census Bureau
- The Pew Research Center for data on education trends and public opinion.
- Department of Education for federal education policy.
- Brookings Institution (Brown Center on Education Policy) for education research.

## Legal/Political
Distinct from Crime: this domain covers specific legal proceedings
against public figures, not aggregate offense statistics.

- DOJ (Department of Justice) for federal prosecutions and press releases.
- U.S. Courts for federal court records.
- PACER for federal court docket records.
- Federal Election Commission for campaign-finance and political-figure legal records.
- Office of Inspector General for executive-branch investigations.
- Congressional Research Service for nonpartisan legislative/legal analysis.
- Supreme Court of the United States for SCOTUS rulings.

## Elections
- Federal Election Commission for federal campaign-finance and election data.
- U.S. Election Assistance Commission for federal election administration data.
- Brennan Center for Justice for voting-rights and election-administration research.
- Cook Political Report for nonpartisan election analysis.
- MIT Election Lab for election data and academic research.
- Ballotpedia for ballot/candidate reference data.
- National Association of Secretaries of State for state-level election administration.

## Foreign Policy
- State Department for U.S. diplomatic policy.
- Department of Defense for military deployments and operations.
- CIA World Factbook for country-level reference data.
- Council on Foreign Relations for foreign-policy research.
- SIPRI (Stockholm International Peace Research Institute) for arms/conflict data.
- NATO for alliance data and statements.
- RAND Corporation for defense and foreign-policy research.
- Congressional Research Service for nonpartisan foreign-policy analysis.
