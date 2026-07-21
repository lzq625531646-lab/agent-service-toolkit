# Creating a RAG assistant

You can build a RAG assistant using a Chroma database.

## Setting up Chroma

The RAG assistant uses Ollama embeddings. Start Ollama and pull the configured
model before creating or querying the database:

```sh
ollama pull embeddinggemma
```

`OLLAMA_EMBEDDING_MODEL`, `OLLAMA_EMBEDDING_BASE_URL`, and `CHROMA_DB_PATH`
control the shared embedding model, Ollama endpoint, and persisted Chroma path.
Indexing and retrieval must always use the same embedding model.

To create a Chroma database:

1. Add the data you want to use to a folder, i.e. `./data`, Word and PDF files are currently supported.
2. Open [`create_chroma_db.py` file](../scripts/create_chroma_db.py) and set the folder_path variable to the path to your data i.e. `./data`.
3. You can change the database name, chunk size and overlap size.
4. Assuming you have already followed the [Quickstart](../README.md#quickstart) and activated the virtual environment, to create the database run:

   ```sh
   uv run python scripts/create_chroma_db.py
   ```

5. If successful, a Chroma db will be created in the repository root directory.

## Configuring the RAG assistant

To create a RAG assistant:

1. Set `CHROMA_DB_PATH` if the generated database is not located at `./chroma_db`.
2. Modify the amount of documents returned, currently set to 5.
3. Update the `database_search_func` function description to accurately describe what the purpose and contents of your database is.
4. Open [`rag_assistant.py` file](../src/agents/rag_assistant.py) and update the agent's instuctions to describe what the assistant's speciality is and what knowledge it has access to, for example:

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

5. Open [`streamlit_app.py` file](../src/streamlit_app.py) and update the agent's welcome message:

   ```python
   WELCOME = """Hello! I'm your AI-powered HR assistant, here to help you navigate company policies, the employee handbook, and benefits. Ask me anything!""
   ```

6. Run the application and test your RAG assistant.
