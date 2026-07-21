# Creating a RAG assistant

The RAG assistant stores documents, chunks, metadata, and Ollama-generated embeddings
in the project's dedicated PostgreSQL database using the pgvector extension.

## Setting up pgvector

The RAG assistant uses Ollama embeddings. Start Ollama and pull the configured
model before creating or querying the database:

```sh
ollama pull embeddinggemma
```

`OLLAMA_EMBEDDING_MODEL` and `OLLAMA_EMBEDDING_BASE_URL` control the shared
embedding model and Ollama endpoint. `RAG_EMBEDDING_DIMENSIONS` must match the
configured model; `embeddinggemma` currently produces 768-dimensional vectors.
Indexing and retrieval must always use the same embedding model.

Start the dedicated PostgreSQL/pgvector container:

```sh
docker compose up -d postgres
```

The service creates the `vector` extension plus the `rag_documents` and
`rag_chunks` tables during startup. To import every supported PDF, DOCX, TXT, or
Markdown file from `./data`, run:

```sh
uv run python scripts/import_rag_documents.py
```

Documents can also be managed from the Vue **RAG Documents** page or through:

```text
GET    /rag/documents
POST   /rag/documents        multipart field: file
DELETE /rag/documents/{id}
```

## Configuring the RAG assistant

To create a RAG assistant:

1. Configure `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, and `RAG_SEARCH_K` if the defaults do not fit your documents.
2. Update the `database_search_func` function description to accurately describe what the purpose and contents of your database is.
3. Open [`rag_assistant.py` file](../src/agents/rag_assistant.py) and update the agent's instructions to describe what the assistant's specialty is and what knowledge it has access to, for example:

   ```python
   instructions = f"""
       You are a helpful HR assistant with the ability to search a database containing information on our company's policies, benefits and handbook.
       Today's date is {current_date}.

       NOTE: THE USER CAN'T SEE THE TOOL RESPONSE.

       A few things to remember:
       - If you have access to multiple databases, gather information from a diverse range of sources before crafting your response.
       - Please include the source of the information used in your response.
       - Use a friendly but professional tone when replying.
       - Only use information from the database. Do not use information from outside sources.
       """
   ```

4. Open [`streamlit_app.py` file](../src/streamlit_app.py) and update the agent's welcome message:

   ```python
   WELCOME = """Hello! I'm your AI-powered HR assistant, here to help you navigate company policies, the employee handbook, and benefits. Ask me anything!""
   ```

5. Run the application and test your RAG assistant.
