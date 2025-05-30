# Bibliotheca Chatbot API

A production-grade FastAPI chatbot API that integrates with PostgreSQL databases and uses **LangGraph** and Azure OpenAI's GPT-4o to answer user queries related to library data.

## Features

- Natural language query processing for library data
- Multi-modal responses (text, tables, charts)
- Context-aware conversations with **integrated memory via LangGraph & RunnableWithMessageHistory**
- Integration with multiple PostgreSQL databases
- Dynamic visualization generation (using **Matplotlib/Seaborn**, saved as PNG files with URL access)
- Schema-first approach for accurate SQL generation
- **Graph-based agent execution for controlled, reliable workflow (Resolver -> Tools -> Final Response)**
- **Agent directly generates final response structure (text + data flags)**
- Automatic result limiting (max 50 rows per query in SQL tool)
- Robust error handling with specific error types
- **Strict guardrails and nuanced handling of analytical queries**

## Architecture

This project uses a **LangGraph-based agent architecture** with:

- FastAPI for API endpoints
- **LangGraph** for agent orchestration and state management (using separate nodes for resolving and other tools)
- **RunnableWithMessageHistory** for seamless memory integration
- Azure OpenAI GPT-4o as the LLM
- SQLAlchemy for database interactions
- **Matplotlib & Seaborn** for chart generation (saving PNG files)
- Predefined schema definitions for reliable SQL generation
- **Agent generates final response structure directly via tool binding** (No separate formatter LLM call)

See `docs/ARCHITECTURE.md` for detailed diagrams and component descriptions.

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL database(s)
- Azure OpenAI API key and endpoint

### Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd bibliotheca-api
```

2. Create a virtual environment:

```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On Unix/macOS
source venv/bin/activate
```

3. Install Python dependencies:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file:

```bash
cp .env.example .env
```

6. Edit the `.env` file with your configuration:
   - Add your Azure OpenAI configuration (API key, endpoint, deployment name)
   - Configure database connections
   - Set other environment variables as needed

### Database Schema

The application uses a schema-first approach with predefined schema definitions in `app/db/schema_definitions.py`. This file contains detailed information about all databases, tables, columns, relationships, and example queries. The LLM uses this information to generate accurate SQL queries.

When the application starts, it can validate the schema definitions against the actual database structure if `VALIDATE_SCHEMA_ON_STARTUP=true` in your `.env` file.

### SQL Generation Best Practices

The SQL generation is optimized with the following best practices:
- Specific column selection instead of SELECT *
- Appropriate filtering with WHERE clauses
- Automatic result limiting (max 100 rows)
- Metadata for truncated results
- Aggregation with GROUP BY for summarizing data
- Proper sorting with ORDER BY
- COUNT(*) for counting records
- Clear error messages for database errors

### Database Connection via SSH Tunnel

If your database is in a VPC or otherwise not directly accessible, you can use an SSH tunnel to connect to it:

1. Create an SSH tunnel to forward the remote database port to your local machine:
   ```bash
   ssh -L 5433:loadtesting-db.cpuebrabtehq.eu-north-1.rds.amazonaws.com:5432 -i JUNTO-KEYPAIR-DEV-QA.pem ec2-user@13.60.89.207
   ```

2. Configure your `.env` file to connect to the local forwarded port:
   ```
   DATABASE_URLS=device_management=postgresql://postgres:YOUR_ACTUAL_PASSWORD@localhost:5433/device_management,report_management=postgresql://postgres:YOUR_ACTUAL_PASSWORD@localhost:5433/report_management,organization_management=postgresql://postgres:YOUR_ACTUAL_PASSWORD@localhost:5433/organization_management
   ```
   
   Note: Replace `YOUR_ACTUAL_PASSWORD` with the actual PostgreSQL password.

3. The application will connect to localhost:5433, which forwards to your remote database.

### Running the API

Development mode:

```bash
uvicorn app.main:app --reload
```

Production mode:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API Endpoints

### POST /api/v1/chat

Process a chat message and return a response. Manages conversation state via `session_id`.

**Request:**

```bash
curl -X POST "http://127.0.0.1:8000/chat" \
-H "Content-Type: application/json" \
-d '{
  "organization_id": "your-org-uuid",
  "message": "Compare total borrow activity between Argyle Branch and Main Library last 30 days",
  "session_id": "user-session-12345"
}'
```

**Success Response (Example with Table):**

```json
{
  "status": "success",
  "data": {
    "text": "Over the last 30 days, Branch A had 150 borrows, while Branch B had 220 borrows.",
    "tables": [
      {
        "columns": ["Branch Name", "Total Borrows"],
        "rows": [
          ["Branch A", 150],
          ["Branch B", 220]
        ]
      }
    ],
    "visualizations": null
  },
  "error": null,
  "timestamp": "2024-07-30T10:00:00Z"
}
```

**Error Response:** (Structure similar, codes might change e.g., `GRAPH_EXECUTION_ERROR`)
```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "GRAPH_EXECUTION_ERROR",
    "message": "An error occurred while processing your request: ...",
    "details": { ... }
  },
  "timestamp": "..."
}
```

### GET /api/v1/health

Check API health status.

**Response:**

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "dependencies": {
    "database": "connected",
    "azure_openai": "available"
  },
  "uptime": 3600
}
```

## Error Handling

The API uses structured error responses. See `docs/ARCHITECTURE.md` for details on graph-related error handling.

## Project Structure

```
/bibliotheca-api
  /app
    /api
      __init__.py
      chat.py
      health.py
    /core
      __init__.py
      config.py
      logging.py
    /db
      __init__.py
      connection.py
      schema_definitions.py
    /langchain
      __init__.py
      agent.py  # Contains LangGraph implementation
      memory.py # Contains get_session_history for RunnableWithMessageHistory
      /tools
        __init__.py
        sql_tool.py
        chart_tool.py
        summary_tool.py
    /schemas
      __init__.py
      chat.py
    main.py
  /static            # Serves static files (e.g., generated charts)
    /charts
  /logs
  /docs
    ARCHITECTURE.md
  .env.example
  requirements.txt
  README.md
```

## Development

### Adding New Tools

1. Create a new tool class in `app/langchain/tools/` inheriting `BaseTool`.
2. Implement `_run` / `_arun`. Ensure output is structured (e.g., `dict` or basic types) and ideally JSON-serializable. Dictionaries from tools will be JSON stringified before being added to `ToolMessage`.
3. Add the tool instance to the list returned by `get_tools` in `app/langchain/agent.py`.
4. Update `SYSTEM_PROMPT_TEMPLATE` in `app/langchain/agent.py` to describe the new tool and when the agent node should decide to use it.
5. If the tool needs to run *before* others (like the resolver), you might need to adjust the `should_continue` logic and potentially add a dedicated node in the LangGraph setup.

### Modifying Schema Definitions

1. Update the schema definitions in `app/db/schema_definitions.py` to match your database structure
2. The schema definitions should include:
   - Database descriptions
   - Table definitions with descriptions
   - Detailed column information (name, type, keys, etc.)
   - Example SQL queries for common operations
3. Restart the application with `VALIDATE_SCHEMA_ON_STARTUP=true` to verify your changes

### Adding New Databases

1. Add the database connection string to the `.env` file using the format:
   ```
   DATABASE_URLS=db1=postgresql://user:pass@host:port/db1,db2=postgresql://user:pass@host:port/db2
   ```
2. Add the database schema definition to `app/db/schema_definitions.py`

## Production Considerations

- **Memory:** The default `ChatMessageHistory` is in-memory only. For production, switch to a persistent store like `RedisChatMessageHistory` or a database-backed history in `app/langchain/memory.py`. Update `get_session_history` accordingly.
- **Matplotlib Backend:** Ensure the deployment environment uses a non-interactive backend like 'Agg' (set via code or `MPLBACKEND` env var).
- **Scalability:** Consider potential bottlenecks in tool execution or LLM calls under load.
- **Error Monitoring:** Implement robust monitoring and alerting for API errors and graph execution failures.
- **Prompt Engineering:** The reliability and behavior of the agent heavily depend on the quality and clarity of the system prompts. Continuous refinement might be needed.
- Row limiting is handled by the `SQLQueryTool`.

## License

[Specify license here]