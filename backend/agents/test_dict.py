from judge import SOURCE_METRICS

print("Total Sources Loaded:", len(SOURCE_METRICS))
print("Fox News Digital:", SOURCE_METRICS.get("Fox News Digital"))
print("New York Times (News):", SOURCE_METRICS.get("New York Times (News)"))
print("PolitiFact:", SOURCE_METRICS.get("PolitiFact"))
print("Default:", SOURCE_METRICS.get("Default"))
