# test_imdb_graphql.py
import requests
import time

def get_imdb_plot_graphql(imdb_id):
    url = "https://api.graphql.imdb.com/"
    
    # Questa è la query esatta che usa IMDb per recuperare la trama "short"
    query = {
        "query": """
        query GetPlot($id: ID!) {
          title(id: $id) {
            plot {
              plotText {
                plainText
              }
            }
          }
        }
        """,
        "variables": {"id": imdb_id}
    }
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "X-Imdb-User-Language": "it-IT"
    }

    try:
        r = requests.post(url, json=query, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data['data']['title']['plot']['plotText']['plainText']
    except:
        return None

if __name__ == "__main__":
    start = time.time()
    plot = get_imdb_plot_graphql("tt18925334")
    print(f"TEMPO: {time.time() - start:.2f}s")
    print(f"TRAMA: {plot}")