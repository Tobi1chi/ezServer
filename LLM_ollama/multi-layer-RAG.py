import chromadb
from chromadb.utils import embedding_functions
import json
import requests
from typing import List, Dict, Any, Optional
import os
import uuid

# Configuration matching run_ollama.py
OLLAMA_URL = "http://127.0.0.1:11434"
EMBEDDING_MODEL = "qwen2.5:7b" # Using a model likely to be present, or user can change

class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    def __init__(self, model_name: str = EMBEDDING_MODEL, base_url: str = OLLAMA_URL):
        self.model_name = model_name
        self.base_url = base_url

    def __call__(self, input: List[str]) -> List[List[float]]:
        embeddings = []
        for text in input:
            try:
                response = requests.post(
                    f"{self.base_url}/api/embeddings",
                    json={
                        "model": self.model_name,
                        "prompt": text
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    embeddings.append(data["embedding"])
                else:
                    print(f"Error getting embedding: {response.text}")
                    # Fallback or error handling
                    embeddings.append([0.0] * 768) # Assuming 768 dim, this is bad but prevents crash
            except Exception as e:
                print(f"Connection error to Ollama: {e}")
                embeddings.append([0.0] * 768)
        return embeddings

class SimpleRAG:
    def __init__(self, collection_name: str = "flight_logs", persistence_path: str = "./chroma_db"):
        """
        Initialize the RAG system with ChromaDB.
        """
        # Initialize persistent client
        self.client = chromadb.PersistentClient(path=persistence_path)
        
        # Use custom Ollama embedding function
        # If Ollama is not running or model missing, this might fail during usage
        self.embedding_fn = OllamaEmbeddingFunction()
        
        # Get or create collection
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedding_fn
        )

    def add_logs(self, logs: List[str], metadatas: Optional[List[Dict]] = None):
        """
        Add log entries to the database.
        """
        if not logs:
            return

        ids = [str(uuid.uuid4()) for _ in logs]
        if metadatas is None:
            metadatas = [{"source": "flightlog"} for _ in logs]

        print(f"Adding {len(logs)} documents to ChromaDB...")
        self.collection.add(
            documents=logs,
            metadatas=metadatas,
            ids=ids
        )
        print("Done.")

    def query(self, query_text: str, n_results: int = 5) -> Dict[str, Any]:
        """
        Query the database for relevant logs.
        """
        print(f"Querying: {query_text}")
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        return results

def load_flight_logs(file_path: str) -> List[str]:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return []

if __name__ == "__main__":
    # Example usage
    rag = SimpleRAG()
    
    # Load data from existing json
    log_file = "../Flightlog_Latest.json" # Adjust path as needed
    if os.path.exists(log_file):
        logs = load_flight_logs(log_file)
        if logs:
            # Check if collection is empty to avoid duplicate adds for this demo
            if rag.collection.count() == 0:
                rag.add_logs(logs)
            else:
                print(f"Collection already has {rag.collection.count()} documents.")
        
        # Test Query
        test_query = "Who connected to the server?"
        results = rag.query(test_query)
        
        print("\nSearch Results:")
        for i, doc in enumerate(results['documents'][0]):
            print(f"{i+1}. {doc}")
    else:
        print(f"File {log_file} not found.")
