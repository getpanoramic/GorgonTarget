import urllib.parse

# ...

@app.get("/api/v3/series/lookup")
async def series_lookup(term: str = Query(...), api_key: str = Depends(get_medusa_key)):
    # 1. Decode URL parameters safely (e.g., "Black%20Mirror" -> "Black Mirror")
    clean_term = urllib.parse.unquote(term)
    
    # 2. Extract TVDB ID format if passed explicitly as 'tvdb:12345'
    query_term = clean_term.split(":")[-1] if clean_term.startswith("tvdb:") else clean_term
    
    print(f"[GorgonTarget] Processing lookup request for term: '{query_term}'")
    
    try:
        res = await async_client.get(
            "/api/v2/series/lookup", 
            params={"q": query_term, "indexer": "tvdb"}, 
            headers=medusa_headers(api_key)
        )
        
        if res.status_code != 200: 
            print(f"[GorgonTarget] Downstream Medusa lookup failed with status: {res.status_code} - {res.text}")
            return []
            
        return [{
            "title": item.get("title"),
            "tvdbId": item.get("ids", {}).get("tvdb"),
            "overview": item.get("overview"),
            "year": item.get("year", 0),
            "remotePoster": item.get("image", "")
        } for item in res.json()]
        
    except Exception as e:
        print(f"[GorgonTarget] Internal exception during lookup translation: {str(e)}")
        return []
