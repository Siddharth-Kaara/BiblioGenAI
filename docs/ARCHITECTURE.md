# Bibliotheca Chatbot API Architecture

## 1. System Overview

The Bibliotheca Chatbot API is a production-grade FastAPI application that processes natural language queries about library data. It integrates with PostgreSQL databases, uses **LangGraph** for agent orchestration, maintains conversation state with **RunnableWithMessageHistory**, and leverages Azure OpenAI's GPT-4o for natural language understanding and generation. It can produce visualizations as static PNG files served via URL.

### Key Features
- Natural language query processing for library data
- Multi-modal responses (text, tables, charts)
- Context-aware conversations with **integrated memory management**
- Integration with multiple PostgreSQL databases
- Dynamic visualization generation (using **Matplotlib/Seaborn**, saved as PNG files with URL access)
- Schema-first approach for accurate SQL generation
- **Graph-based agent execution for controlled workflow**
- Automatic query result limiting and pagination (handled by SQL Tool)
- **Hybrid final response formatting (Manual data extraction + LLM text generation)**
- Robust error handling with specific error types

### Target Users
- Library administrators and staff accessing via Flutter mobile app
- Users seeking insights about library data

## 2. Architecture Components

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   FastAPI API   │◄────►│ LangGraph App   │◄────►│ PostgreSQL DBs  │
└─────────────────┘      │ (w/ Memory)     │      └─────────────────┘
                           └───────┬─────────┘
                                   │ ▲
                   ┌───────────────▼─┴────────────┐
                   │ Tool Execution (via Nodes)   │
                   │                              │
                   │ ┌────────────┐ ┌────────────┐│
                   │ │  SQL Tool  │ │ Chart Tool ││
                   │ └────────────┘ └────────────┘│
                   │ ┌────────────┐               │
                   │ │ Summary Tool│              │
                   │ └────────────┘               │
                   └──────────────────────────────┘
```

### Core Components

#### 1. FastAPI Layer
- Handles HTTP requests and responses (`/chat`, `/health`)
- Manages API routing and input/output validation using Pydantic schemas (`app/schemas/`)
- Invokes the LangGraph application (`process_chat_message` in `app/langchain/agent.py`)

#### 2. LangGraph Application Layer (`app/langchain/agent.py`)
- **Stateful Agent Graph:** Orchestrates the workflow using `langgraph.StateGraph`. The state (`AgentState`) includes the message history.
- **Agent Node:** Calls the LLM (`AzureChatOpenAI`) bound with tools to decide the next action (call a tool or respond). Guided by `SYSTEM_PROMPT_TEMPLATE`.
- **Tool Node:** Executes the selected tool (`SQLQueryTool`, `ChartRendererTool`, `SummarySynthesizerTool`) using `langgraph.prebuilt.ToolExecutor`. Handles tool exceptions and formats output as `ToolMessage`.
- **Conditional Edges:** Route the flow between the agent and tool nodes based on the LLM's decision, ending when the agent provides a final response. Checks for `ToolMessage` to route back to agent.
- **Memory Integration:** Uses `langchain_core.runnables.history.RunnableWithMessageHistory` to automatically manage conversation history persistence (using `app/langchain/memory.py`). Session management is handled via `session_id` in the request configuration.
- **Final Response Formatting:** Uses a hybrid approach in `process_chat_message`. Structured data (`table`, `visualization`) is manually extracted from the final message history. A separate, final LLM call generates the natural language `text` response, using the extracted data as context.

#### 3. Tool Suite (`app/langchain/tools/`)
- **SQLQueryTool**: Generates and executes SQL queries against PostgreSQL using predefined schema definitions. Returns structured data (`{"columns": ..., "rows": ...}`). Implements automatic row limiting (default 50 rows).
- **ChartRendererTool**: Creates visualizations (bar, pie, line, scatter charts) using **Matplotlib and Seaborn**. Saves charts as PNG files in `/static/charts/`. Returns visualization info (`{"type": ..., "image_url": ..., "title": ..., "metadata": ...}`). Includes validation for axis column names provided by LLM metadata, falling back to default DataFrame columns if necessary.
- **SummarySynthesizerTool**: Generates natural language summaries or performs complex analysis based on input text or data. Returns a text string.

#### 4. Database Layer (`app/db/`)
- Connects to multiple PostgreSQL databases using SQLAlchemy (`connection.py`).
- Includes predefined schema definitions (`schema_definitions.py`) used by `SQLQueryTool`.

## 3. API Endpoints

### POST /api/v1/chat
Processes user chat messages using the LangGraph application and returns multi-modal responses.

**Request:**
```json
{
  "user_id": "string",
  "message": "string",
  "session_id": "string (optional, for conversation continuity)"
  // chat_history is managed server-side via session_id
}
```

**Response:**
```json
{
  "status": "success|error",
  "data": {
    "text": "string (explanatory text)",
    "table": { // Compact table format
      "columns": ["col1", "col2"],
      "rows": [ ["val1", "val2"], ["val3", "val4"] ]
     } | null,
    "visualization": {
      "type": "bar|pie|line|scatter",
      "image_url": "string (URL path to the generated PNG, e.g., /static/charts/chart_uuid.png)"
    } | null
  },
  "error": {
    "code": "ERROR_CODE (e.g., GRAPH_EXECUTION_ERROR)",
    "message": "Error description",
    "details": {}
  } | null,
  "timestamp": "ISO datetime"
}
```

### GET /api/v1/health
Returns API health status.

**Response:**
```json
{
  "status": "healthy|degraded|unhealthy",
  "version": "string",
  "dependencies": {
    "database": "connected|disconnected",
    "azure_openai": "available|unavailable"
  }
}
```

## 4. Database Connection

- Multiple PostgreSQL databases accessed via SSH tunnel to a bastion host:
  - device_management: Contains device-related data and metrics
  - report_management: Stores reporting and analytics information
  - organization_management: Manages organizational structure and user relationships
- Connection to localhost:5433, which is forwarded to the remote database
- Connection pooling with SQLAlchemy
- Environment-based configuration
- Schema-first approach with predefined database definitions
- Optional validation of schema definitions against actual database structure

### SSH Tunnel Configuration
The application connects to databases that are in a private VPC through an SSH tunnel:
1. An SSH tunnel is established to forward the remote PostgreSQL port (5432) to local port 5433
2. The application connects to localhost:5433, which forwards to the remote database
3. This approach provides security without exposing the database directly to the internet

```bash
# Example SSH tunnel command
ssh -L 5433:loadtesting-db.cpuebrabtehq.eu-north-1.rds.amazonaws.com:5432 -i JUNTO-KEYPAIR-DEV-QA.pem ec2-user@13.60.89.207
```

## 5. LangGraph Implementation Details

### Agent State (`AgentState` in `agent.py`)
A `TypedDict` managing the conversation flow:
- `messages`: Sequence of `BaseMessage` objects (history).
- `final_text`, `final_table`, `final_visualization`: Fields populated based on the graph's final output (extracted in `process_chat_message`).

### Graph Structure (`create_graph_app` in `agent.py`)
- **Nodes:** `agent`, `tools`
- **Entry Point:** `agent`
- **Edges:**
    - `agent` -> `tools` (if tool call decided by LLM)
    - `agent` -> `END` (if final answer decided by LLM)
    - `tools` -> `agent` (after tool execution returns `FunctionMessage`)

### Memory (`RunnableWithMessageHistory` in `agent.py`)
- Wraps the compiled graph (`app.compile()`).
- Uses `app.langchain.memory.get_session_history` to fetch/create `ChatMessageHistory` based on `session_id` passed in config.
- Automatically saves user (`HumanMessage`) and AI (`AIMessage`, `FunctionMessage`) messages to the history store based on graph flow.
- Input key: `messages`, History key: `messages`.

### System Prompt (`SYSTEM_PROMPT_TEMPLATE` in `agent.py`)
- Guides the `agent` node LLM.
- Focuses on *decision-making* (which tool to use, or whether to respond directly).
- Includes descriptions and names of available tools dynamically formatted into the prompt.

### Tool Definitions (`app/langchain/tools/`)
- Tools return structured data (`dict` for SQL/Chart, `str` for Summary).
- The `tool_node` formats tool outputs into `ToolMessage` objects, serializing dictionaries to JSON strings for the message content.

### Final Output Processing (`process_chat_message` in `agent.py`)
- Invokes the graph with memory using `graph_with_memory.ainvoke`.
- Manually iterates backwards through the final message list (`final_state['messages']`) to find the most recent `ToolMessage` from `sql_query` and `chart_renderer`. Parses their JSON content to extract structured `table` and `visualization` data. Extraction stops once `visualization` data is found to prioritize it over the preceding table data.
- Calls a final LLM formatter with the full message history and the extracted structured data as context.
- Uses the LLM's output (constrained to generate only text via structured output) as the final `text` response.
- Combines the manually extracted `table` and `visualization` data with the LLM-generated `text` into the final API response structure defined in `app/schemas/chat.py`.

## 6. Security Considerations

- Authentication using API keys or JWT
- User filtering for database queries
- Input validation and sanitization
- Rate limiting to prevent abuse
- SQL injection prevention

## 7. Performance Optimization

- Async operations used in LangGraph and FastAPI.
- Tool execution (DB queries, chart rendering via Matplotlib/Seaborn) remains a potential bottleneck. Matplotlib rendering is CPU-bound.
- Caching compiled graphs per `user_id` in `agent.py` avoids re-compilation.
- **Memory Scalability:** Current `ChatMessageHistory` is in-memory; replace with persistent store (e.g., Redis) in `app/langchain/memory.py` for production.
- **Hybrid Response Formatting Latency:** Adds an extra LLM call at the end.

## 8. Error Handling

**Structured Error Response:**
```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": {}
  },
  "timestamp": "ISO datetime"
}
```

**Error Categories:**
- Authentication errors (401, 403)
- Input validation errors (400)
- Resource not found errors (404)
- Database errors (500)
- Azure LLM service errors (503)
- Rate limiting errors (429)
- Context length exceeded errors

**Specific Error Codes:**
- AGENT_ERROR: General agent processing errors
- CONTEXT_LENGTH_EXCEEDED: Response too large for model context window
- DATABASE_ERROR: Database connection or query execution errors
- OPENAI_API_ERROR: Azure OpenAI API errors

## 9. Example Queries and Responses

### Example 1: Data Query with Text Response

**Query:** "How many books were borrowed from Branch A last week?"

**Response:**
```json
{
  "status": "success",
  "data": {
    "text": "Branch A had 143 book borrowings last week, which is a 12% increase from the previous week.",
    "table": null,
    "visualization": null
  },
  "error": null,
  "timestamp": "2023-05-15T14:22:33Z"
}
```

### Example 2: Chart Generation

**Query:** "Create a bar chart of footfall by hour for Branch B yesterday"

**Response:**
```json
{
  "status": "success",
  "data": {
    "text": "Here's the chart showing hourly footfall for Branch B yesterday.",
    "table": null,
    "visualization": {
      "type": "bar",
      "image_url": "/static/charts/chart_some_uuid.png"
    }
  },
  "error": null,
  "timestamp": "2023-05-15T14:25:12Z"
}
```

### Example 3: Table Response
**Query:** "Show active ORG hierarchies"
**Response:**
```json
{
  "status": "success",
  "data": {
    "text": "Here is the data you requested:",
    "table": {
      "columns": ["ID", "Name", "Type"],
      "rows": [
        ["abc", "Org1", "ORG"],
        ["def", "Org2", "ORG"]
      ]
     },
    "visualization": null
  },
  "error": null,
  "timestamp": "2023-05-15T14:30:45Z"
}
```

### Example 4: Error Response for Context Length Exceeded

**Query:** "Show me all data from all tables"

**Response:**
```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "CONTEXT_LENGTH_EXCEEDED",
    "message": "Your query returned too much data. Please be more specific or add additional filters.",
    "details": {
      "suggestion": "Try asking about a specific hierarchy, type, or add date/time constraints."
    }
  },
  "timestamp": "2023-05-15T14:35:22Z"
}
```

## 10. Project File Structure

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
      security.py
      logging.py
    /db
      __init__.py
      connection.py
      schema_definitions.py
    /langchain
      __init__.py
      agent.py
      memory.py
      /tools
        __init__.py
        sql_tool.py
        chart_tool.py
        summary_tool.py
    /schemas
      __init__.py
      chat.py
      errors.py
    main.py
  /static            # Added for serving chart images
    /charts
  /tests
    /unit
    /integration
    /e2e
  /docs
    ARCHITECTURE.md
  .env.example
  requirements.txt
  README.md
  Dockerfile
```

## 11. Implementation Plan

1. Set up project structure and dependencies
2. Implement database connections with SQLAlchemy
3. Create FastAPI endpoints with schema validation
4. Define comprehensive schema definitions
5. Build LangGraph tools one by one
6. Create detailed system prompt for agent
7. Configure agent with tools and memory
8. Implement error handling and logging
9. Add authentication and security
10. Optimize performance
11. Write tests
12. Create deployment configuration

## 12. Production Deployment Considerations

- Containerization with Docker
- Scaling with Kubernetes or AWS ECS
- CI/CD pipeline with GitHub Actions
- Monitoring with Prometheus/Grafana
- Log aggregation with ELK stack
- Backup and disaster recovery plan
- Resource management for large queries
- Error monitoring and alerting
- **Persistent Memory Store (e.g., Redis) is essential.**
- **Matplotlib Backend:** Ensure the deployment environment uses a non-interactive backend like 'Agg' (set via `matplotlib.use('Agg')` in code or `MPLBACKEND` environment variable).
