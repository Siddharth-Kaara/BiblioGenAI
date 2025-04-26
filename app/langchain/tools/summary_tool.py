import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain.prompts import PromptTemplate
from langchain.tools import BaseTool
from langchain_openai import AzureChatOpenAI
from sqlalchemy import text
from langchain_core.output_parsers import StrOutputParser

from app.core.config import settings
from app.db.connection import get_db_engine
from app.langchain.tools.sql_tool import SQLQueryTool

logger = logging.getLogger(__name__)

class SummarySynthesizerTool(BaseTool):
    """Tool for synthesizing high-level summaries from data."""
    
    name: str = "summary_synthesizer"
    description: str = """
    Creates high-level summaries and insights from data.
    Use this tool for complex queries requiring analysis across multiple dimensions.
    Input should be a description of the summary or analysis needed.
    """
    
    organization_id: str
    
    def _decompose_query(self, query: str) -> List[str]:
        """Decompose a complex query into subqueries using LLM."""
        # Create an Azure OpenAI instance
        llm = AzureChatOpenAI(
            openai_api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            openai_api_version=settings.AZURE_OPENAI_API_VERSION,
            deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            model_name=settings.LLM_MODEL_NAME,
            temperature=0.1,
        )
        
        # Create prompt template
        template = """
        You are a data analyst. Given the following high-level query or analysis request,
        break it down into 2-5 specific, atomic subqueries that need to be executed to gather the necessary data.

        Context Provided in Query: The input query may contain already resolved entity names and IDs (e.g., '...for Main Library (ID: uuid-...)'). If IDs are provided, formulate subqueries that use these specific IDs for filtering or joining.

        Database Schema Hints:
        - The main hierarchy table is named "hierarchyCaches".
        - The main event data table is named "5".
        - Joins often happen between "5"."hierarchyId" and "hierarchyCaches"."id".

        High-level Query (potentially with context): {query}

        Format your response as a JSON array of strings, each representing a specific subquery description suitable for the sql_query tool.
        Example if query contains resolved IDs: ["Retrieve borrow count for hierarchy ID 'uuid-for-main' last 30 days", "Retrieve borrow count for hierarchy ID 'uuid-for-argyle' last 30 days"]
        Example if no IDs provided: ["Count active hierarchies by type", "Count subscriptions by type"]

        Return ONLY the JSON array without any explanation or comments.
        """
        
        prompt = PromptTemplate(
            input_variables=["query"],
            template=template,
        )
        
        # Create an LCEL chain for decomposition
        decompose_chain = prompt | llm | StrOutputParser()
        
        # Generate subqueries
        subqueries_str = decompose_chain.invoke({"query": query})
        
        # Clean and parse the JSON
        subqueries_str = subqueries_str.strip()
        if subqueries_str.startswith("```json"):
            subqueries_str = subqueries_str[7:]
        if subqueries_str.endswith("```"):
            subqueries_str = subqueries_str[:-3]
        
        try:
            subqueries = json.loads(subqueries_str.strip())
            if not isinstance(subqueries, list):
                raise ValueError("Subqueries must be a list")
            return subqueries
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing subqueries JSON: {str(e)}")
            logger.debug(f"Raw subqueries string: {subqueries_str}")
            # Fallback: return the original query
            return [query]
    
    def _execute_subqueries(self, subqueries: List[str]) -> List[Tuple[str, Dict]]:
        """Execute each subquery and collect results."""
        results = []
        
        # Create SQL tool, passing only organization_id
        sql_tool = SQLQueryTool(organization_id=self.organization_id)
        
        for subquery in subqueries:
            try:
                # Execute organization-scoped SQL query for each subquery
                subquery_result_str = sql_tool._run(subquery)
                try:
                    # Parse the JSON string result from sql_tool
                    subquery_result_dict = json.loads(subquery_result_str)
                except json.JSONDecodeError:
                    logger.error(f"Failed to decode JSON from subquery result for '{subquery}'")
                    # Use a placeholder if parsing fails, maybe just the text part?
                    subquery_result_dict = {"table": {"columns": ["Error"], "rows": [["Failed to parse SQL tool output"]]}, "text": subquery_result_str}

                # Add the parsed dictionary result (which should contain the 'table' key)
                results.append((subquery, subquery_result_dict))

            except Exception as e:
                logger.error(f"Error executing subquery '{subquery}' for org {self.organization_id}: {str(e)}")
                # Ensure the fallback structure matches what _synthesize_results expects
                results.append((subquery, {"table": {"columns": ["Error"], "rows": [[str(e)]]}, "text": f"Error: {str(e)}"}))
        
        return results
    
    def _synthesize_results(self, query: str, subquery_results: List[Tuple[str, Dict]]) -> str:
        """Synthesize subquery results into a coherent summary."""
        # Create an Azure OpenAI instance
        llm = AzureChatOpenAI(
            openai_api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            openai_api_version=settings.AZURE_OPENAI_API_VERSION,
            deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            model_name=settings.LLM_MODEL_NAME,
            temperature=0.3,
        )
        
        # Convert results to string format, accessing the 'table' within the dict
        results_str = ""
        for subquery, result_dict in subquery_results:
            results_str += f"Subquery: {subquery}\n"
            table_data = result_dict.get("table", {})
            limited_rows = table_data.get("rows", [])[:5]
            results_str += f"Results (showing up to 5 rows): {json.dumps({"columns": table_data.get("columns", []), "rows": limited_rows}, indent=2)}\n"
            results_str += f"Total rows in original result: {len(table_data.get("rows", []))}\n\n"
        
        # Create prompt template
        template = """
        You are a data analyst. Given the following high-level query and results from subqueries,
        synthesize a coherent, insightful summary that addresses the original question.
        
        Original Query: {query}
        
        Subquery Results:
        {results}
        
        Provide a comprehensive summary that:
        1. Directly answers the original query
        2. Highlights key insights, patterns, and trends
        3. Mentions any notable outliers or anomalies
        4. Uses specific numbers and percentages when relevant
        5. Is written in a professional, concise style
        
        Your summary:
        """
        
        prompt = PromptTemplate(
            input_variables=["query", "results"],
            template=template,
        )
        
        # Create an LCEL chain for synthesis
        synthesis_chain = prompt | llm | StrOutputParser()
        
        # Generate summary
        summary = synthesis_chain.invoke({"query": query, "results": results_str})
        
        return summary.strip()
    
    def _run(self, query: str) -> Dict[str, str]:
        """Run the tool to generate a summary string."""
        logger.info(f"Executing summary synthesizer tool for org {self.organization_id}")
        
        # Decompose the query
        subqueries = self._decompose_query(query)
        logger.info(f"Decomposed query into {len(subqueries)} subqueries")
        
        # Execute subqueries
        subquery_results = self._execute_subqueries(subqueries)
        
        # Synthesize results
        summary = self._synthesize_results(query, subquery_results)
        logger.info("Successfully generated summary")
        
        # Return standardized output format
        return {"text": summary}
    
    async def _arun(self, query: str) -> Dict[str, str]:
        """Run the tool asynchronously."""
        # For now, just call the synchronous version
        # In a truly async implementation, _decompose_query, _execute_subqueries, _synthesize_results might be async
        return self._run(query)