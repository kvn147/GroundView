## Domains
We will set up the domains that can be used for claims.
- Healthcare
- Immigration
- Crime
- Economy
- Education

'router.py' will pick a agent for the claim to retrieve data, if it is not sure, it will pick 'other'. 

The agents will retreive data from a set of sources, 'sources.py'
The agents output markdown of the data they retreive from the set sources.
