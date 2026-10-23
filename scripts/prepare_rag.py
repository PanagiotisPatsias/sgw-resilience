from app.config import Settings
from app.container import Container

if __name__ == "__main__":
    container = Container(Settings())
    container.retriever.prepare()
    print("Hybrid retrieval index and model cache prepared.")
