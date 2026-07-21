import math
import re

import numexpr
from langchain_core.tools import BaseTool, tool

from rag import rag_store


def calculator_func(expression: str) -> str:
    """Calculates a math expression using numexpr.

    Useful for when you need to answer questions about math using numexpr.
    This tool is only for math questions and nothing else. Only input
    math expressions.

    Args:
        expression (str): A valid numexpr formatted math expression.

    Returns:
        str: The result of the math expression.
    """

    try:
        local_dict = {"pi": math.pi, "e": math.e}
        output = str(
            numexpr.evaluate(
                expression.strip(),
                global_dict={},  # restrict access to globals
                local_dict=local_dict,  # add common mathematical functions
            )
        )
        return re.sub(r"^\[|\]$", "", output)
    except Exception as e:
        raise ValueError(
            f'calculator("{expression}") raised error: {e}.'
            " Please try again with a valid numerical expression"
        )


calculator: BaseTool = tool(calculator_func)
calculator.name = "Calculator"




def profile_func(name:str) -> dict[str,str]:
    """
    Retrieve detailed personal information based on the user's name
    """
    return {
        "name": name,
        "gender":"male",
        "lover":"binx",
        "balance":"2310000"
    }

profile: BaseTool = tool(profile_func)
profile.name = "profile"



# Format retrieved documents
def format_contexts(docs):
    return "\n\n".join(doc.page_content for doc in docs)


async def database_search_func(query: str) -> str:
    """Searches the pgvector RAG knowledge base for relevant document chunks."""
    documents = await rag_store.similarity_search(query)

    # Format the documents into a string
    context_str = format_contexts(documents)

    return context_str


database_search: BaseTool = tool(database_search_func)
database_search.name = "Database_Search"  # Update name with the purpose of your database
