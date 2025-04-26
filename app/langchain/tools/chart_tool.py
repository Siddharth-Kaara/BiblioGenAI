import base64
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
import matplotlib
matplotlib.use('Agg') # Use Agg backend for non-interactive environments (important for servers)
import matplotlib.pyplot as plt
import seaborn as sns
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain.tools import BaseTool
from langchain_openai import AzureChatOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

# Set a default Seaborn style
sns.set_theme(style="whitegrid")

class ChartRendererTool(BaseTool):
    """Tool for generating chart visualizations using Matplotlib/Seaborn."""
    
    name: str = "chart_renderer"
    description: str = """
    Generates charts and visualizations from data using Matplotlib/Seaborn.
    Use this tool when you need to create a bar chart, pie chart, line chart, scatter plot, etc.
    Input should be a dictionary with chart metadata and data to visualize.
    """
    
    def _generate_chart_metadata(self, query: str, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate chart metadata from query and data using LLM."""
        logger.debug("Generating chart metadata...")
        if not data:
            logger.error("No data provided to _generate_chart_metadata")
            raise ValueError("No data provided for chart generation")
        
        # Convert data to string format
        data_str = json.dumps(data[:10], indent=2)  # Limit to 10 rows for LLM
        
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
        You are a data visualization expert. Given the following data and a query, determine the best chart type
        and provide metadata needed to create the visualization using Matplotlib/Seaborn.
        
        Data (sample):
        {data}
        
        Query: {query}
        
        Respond with a JSON object with the following structure:
        {{
            "chart_type": "bar|pie|line|scatter",
            "title": "Chart title",
            "x_column": "Name of column for x-axis (or categories/labels for pie)",
            "y_column": "Name of column for y-axis (or values/sizes for pie)",
            "color_column": "Optional column for color differentiation (hue)",
            "description": "Brief description of what the chart shows"
        }}
        
        Return ONLY the JSON object without any explanation.
        """
        
        prompt = PromptTemplate(
            input_variables=["data", "query"],
            template=template,
        )
        
        # Create a chain for metadata generation
        metadata_chain = LLMChain(llm=llm, prompt=prompt)
        
        # Generate metadata
        logger.debug("Invoking LLM chain for chart metadata...")
        metadata_str = metadata_chain.run(
            data=data_str,
            query=query,
        )
        logger.debug(f"Raw metadata string from LLM: {metadata_str}")
        
        # Clean and parse the JSON
        metadata_str = metadata_str.strip().removeprefix("```json").removesuffix("```").strip()
        
        try:
            metadata = json.loads(metadata_str)
            logger.debug(f"Successfully parsed chart metadata: {metadata}")
            return metadata
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing chart metadata JSON: {str(e)}", exc_info=True)
            logger.debug(f"Problematic raw metadata string: {metadata_str}")
            raise ValueError(f"Invalid chart metadata format: {str(e)}")
    
    def _create_dataframe(self, data: List[Dict[str, Any]]) -> pd.DataFrame:
        """Create pandas DataFrame from list of dictionaries."""
        logger.debug("Creating pandas DataFrame...")
        try:
            df = pd.DataFrame(data)
            logger.debug(f"DataFrame created successfully with shape {df.shape}")
            return df
        except Exception as e:
            logger.error(f"Error creating DataFrame: {e}", exc_info=True)
            raise ValueError(f"Could not create DataFrame from provided data: {e}")
    
    def _render_bar_chart(self, ax: plt.Axes, df: pd.DataFrame, metadata: Dict[str, Any]):
        """Render a bar chart using Seaborn on the provided Axes."""
        x_col_meta = metadata.get("x_column") # Seaborn typically uses x/y based on plot type
        y_col_meta = metadata.get("y_column")
        hue_col_meta = metadata.get("color_column") # Hue for color

        actual_cols = df.columns.tolist()
        x_col = x_col_meta if x_col_meta in actual_cols else actual_cols[0] if len(actual_cols) > 0 else None
        y_col = y_col_meta if y_col_meta in actual_cols else actual_cols[1] if len(actual_cols) > 1 else None
        hue_col = hue_col_meta if hue_col_meta and hue_col_meta in actual_cols else None

        # Get color mapping from metadata if provided
        color_mapping = metadata.get("color_mapping")
        palette = None
        if isinstance(color_mapping, dict) and color_mapping:
            # Ensure mapping keys exist in the x-column data for bar chart
            valid_mapping = {k: v for k, v in color_mapping.items() if k in df[x_col].unique()}
            if valid_mapping:
                palette = valid_mapping
                logger.debug(f"Using provided color mapping (palette): {palette}")
            else:
                logger.warning("Provided color_mapping keys do not match data categories. Using default palette.")

        if x_col != x_col_meta or y_col != y_col_meta:
             logger.warning(f"Metadata columns ('{x_col_meta}', '{y_col_meta}') invalid. Falling back to ('{x_col}', '{y_col}').")

        if not x_col or not y_col:
            raise ValueError("Could not determine valid x and y columns for bar chart")

        logger.debug(f"Rendering bar chart with x='{x_col}', y='{y_col}', hue='{hue_col}', palette='{bool(palette)}'") # Log if palette used
        try:
            # Use the palette if available
            sns.barplot(data=df, x=x_col, y=y_col, hue=hue_col, ax=ax, errorbar=None, palette=palette)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
        except Exception as e:
            logger.error(f"Error rendering bar chart with Seaborn: {e}", exc_info=True)
            raise ValueError(f"Failed to render bar chart: {e}")
    
    def _render_pie_chart(self, ax: plt.Axes, df: pd.DataFrame, metadata: Dict[str, Any]):
        """Render a pie chart using Matplotlib on the provided Axes."""
        labels_col_meta = metadata.get("x_column") # Map x -> labels
        values_col_meta = metadata.get("y_column") # Map y -> values

        # Get color mapping from metadata if provided
        color_mapping = metadata.get("color_mapping")
        colors = None
        if isinstance(color_mapping, dict) and color_mapping:
            # For pie charts, create a list of colors in the order of the labels
            ordered_colors = [color_mapping.get(label) for label in df[labels_col_meta]]
            # Filter out None values if some labels weren't in the mapping
            if any(c is not None for c in ordered_colors):
                # Use mapped colors where available, None otherwise (matplotlib will default)
                colors = [c if c is not None else None for c in ordered_colors]
                logger.debug(f"Using provided colors for pie chart segments (partial matches allowed).")
            else:
                logger.warning("Provided color_mapping keys do not match data labels. Using default colors.")

        actual_cols = df.columns.tolist()
        labels_col = labels_col_meta if labels_col_meta in actual_cols else actual_cols[0] if len(actual_cols) > 0 else None
        values_col = values_col_meta if values_col_meta in actual_cols else actual_cols[1] if len(actual_cols) > 1 else None

        if labels_col != labels_col_meta or values_col != values_col_meta:
             logger.warning(f"Metadata columns ('{labels_col_meta}', '{values_col_meta}') invalid. Falling back to ('{labels_col}', '{values_col}').")

        if not labels_col or not values_col:
            raise ValueError("Could not determine valid labels and values columns for pie chart")
        
        # Handle potential non-numeric data in values column
        try:
            pie_data = pd.to_numeric(df[values_col], errors='coerce').fillna(0)
            if (pie_data < 0).any():
                 logger.warning(f"Pie chart values column '{values_col}' contains negative values. Taking absolute values.")
                 pie_data = pie_data.abs()
        except KeyError:
             raise ValueError(f"Values column '{values_col}' not found for pie chart.")
        except Exception as e:
             logger.error(f"Error processing pie chart values: {e}", exc_info=True)
             raise ValueError(f"Invalid data in values column '{values_col}' for pie chart.")

        logger.debug(f"Rendering pie chart with labels='{labels_col}', values='{values_col}', colors='{bool(colors)}'")
        try:
            # Pass the colors list to ax.pie
            wedges, texts, autotexts = ax.pie(pie_data, labels=df[labels_col], autopct='%1.1f%%', startangle=90, colors=colors)
            # ax.axis('equal') # Equal aspect ratio ensures that pie is drawn as a circle.
            plt.setp(autotexts, size=8, weight="bold", color="white") # Improve autopct visibility
        except Exception as e:
            logger.error(f"Error rendering pie chart with Matplotlib: {e}", exc_info=True)
            raise ValueError(f"Failed to render pie chart: {e}")
    
    def _render_line_chart(self, ax: plt.Axes, df: pd.DataFrame, metadata: Dict[str, Any]):
        """Render a line chart using Seaborn on the provided Axes."""
        x_col_meta = metadata.get("x_column")
        y_col_meta = metadata.get("y_column")
        hue_col_meta = metadata.get("color_column")

        # Get color mapping from metadata if provided (used if hue_col is set)
        color_mapping = metadata.get("color_mapping")
        palette = None
        if isinstance(color_mapping, dict) and color_mapping and hue_col_meta:
             # Ensure mapping keys exist in the hue column data
             valid_mapping = {k: v for k, v in color_mapping.items() if k in df[hue_col_meta].unique()}
             if valid_mapping:
                 palette = valid_mapping
                 logger.debug(f"Using provided color mapping (palette) for hue: {palette}")
             else:
                 logger.warning(f"Provided color_mapping keys do not match hue categories ('{hue_col_meta}'). Using default palette.")

        actual_cols = df.columns.tolist()
        x_col = x_col_meta if x_col_meta in actual_cols else actual_cols[0] if len(actual_cols) > 0 else None
        y_col = y_col_meta if y_col_meta in actual_cols else actual_cols[1] if len(actual_cols) > 1 else None
        hue_col = hue_col_meta if hue_col_meta and hue_col_meta in actual_cols else None

        if x_col != x_col_meta or y_col != y_col_meta:
             logger.warning(f"Metadata columns ('{x_col_meta}', '{y_col_meta}') invalid. Falling back to ('{x_col}', '{y_col}').")

        if not x_col or not y_col:
            raise ValueError("Could not determine valid x and y columns for line chart")

        logger.debug(f"Rendering line chart with x='{x_col}', y='{y_col}', hue='{hue_col}', palette='{bool(palette)}'")
        try:
            # Convert x_col to numeric or datetime if possible for better plotting
            try:
                df[x_col] = pd.to_datetime(df[x_col], errors='ignore')
            except Exception: pass # Ignore if conversion fails
            try:
                df[x_col] = pd.to_numeric(df[x_col], errors='ignore')
            except Exception: pass 
            
            # Pass palette to lineplot
            sns.lineplot(data=df, x=x_col, y=y_col, hue=hue_col, marker='o', ax=ax, palette=palette)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
        except Exception as e:
            logger.error(f"Error rendering line chart with Seaborn: {e}", exc_info=True)
            raise ValueError(f"Failed to render line chart: {e}")
    
    def _render_scatter_chart(self, ax: plt.Axes, df: pd.DataFrame, metadata: Dict[str, Any]):
        """Render a scatter chart using Seaborn on the provided Axes."""
        x_col_meta = metadata.get("x_column")
        y_col_meta = metadata.get("y_column")
        hue_col_meta = metadata.get("color_column") # Use hue for color

        # Get color mapping from metadata if provided (used if hue_col is set)
        color_mapping = metadata.get("color_mapping")
        palette = None
        if isinstance(color_mapping, dict) and color_mapping and hue_col_meta:
             # Ensure mapping keys exist in the hue column data
             valid_mapping = {k: v for k, v in color_mapping.items() if k in df[hue_col_meta].unique()}
             if valid_mapping:
                 palette = valid_mapping
                 logger.debug(f"Using provided color mapping (palette) for hue: {palette}")
             else:
                 logger.warning(f"Provided color_mapping keys do not match hue categories ('{hue_col_meta}'). Using default palette.")

        actual_cols = df.columns.tolist()
        x_col = x_col_meta if x_col_meta in actual_cols else actual_cols[0] if len(actual_cols) > 0 else None
        y_col = y_col_meta if y_col_meta in actual_cols else actual_cols[1] if len(actual_cols) > 1 else None
        hue_col = hue_col_meta if hue_col_meta and hue_col_meta in actual_cols else None

        if x_col != x_col_meta or y_col != y_col_meta:
             logger.warning(f"Metadata columns ('{x_col_meta}', '{y_col_meta}') invalid. Falling back to ('{x_col}', '{y_col}').")

        if not x_col or not y_col:
            raise ValueError("Could not determine valid x and y columns for scatter chart")

        logger.debug(f"Rendering scatter chart with x='{x_col}', y='{y_col}', hue='{hue_col}', palette='{bool(palette)}'")
        try:
            # Pass palette to scatterplot
            sns.scatterplot(data=df, x=x_col, y=y_col, hue=hue_col, ax=ax, palette=palette)
            ax.set_xlabel(x_col)
            ax.set_ylabel(y_col)
        except Exception as e:
            logger.error(f"Error rendering scatter chart with Seaborn: {e}", exc_info=True)
            raise ValueError(f"Failed to render scatter chart: {e}")
    
    def _run(
        self,
        query: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generates a chart using Matplotlib/Seaborn, saves it, and returns metadata including the URL."""
        logger.info("Executing chart renderer tool (Matplotlib/Seaborn)")
        
        visualization_output = None
        text_output = "Chart generation initiated."
        processed_data_list: List[Dict[str, Any]] = []
        fig = None # Define fig here to ensure it's available in finally block

        try:
            # --- Validation and Data Conversion (remains mostly the same) ---
            if not data: raise ValueError("Data is required for chart generation.")
            if not isinstance(data, dict): raise ValueError(f"Invalid format for 'data'. Expected Dict.")
            if "columns" not in data or "rows" not in data: raise ValueError("Invalid 'data' format. Must contain 'columns' and 'rows'.")
            
            columns = data['columns']
            rows = data['rows']
            processed_data_list = [dict(zip(columns, row)) for row in rows]
            logger.debug(f"Converted data to List[Dict]. Num items: {len(processed_data_list)}")
            # --- End Validation --- 

            # --- Generate Metadata (remains mostly the same) ---
            if not metadata:
                metadata = self._generate_chart_metadata(query or "Chart from data", processed_data_list)
                logger.debug(f"Generated chart metadata: {metadata}")
            else:
                logger.debug(f"Using provided metadata: {metadata}")

            df = self._create_dataframe(processed_data_list)

            # --- Select and Call Rendering Function --- 
            chart_type = metadata.get("chart_type", "bar").lower()
            logger.debug(f"Selected chart type: {chart_type}")
            title = metadata.get("title", f"{chart_type.capitalize()} Chart")
            description = metadata.get("description", f"Generated {chart_type} chart.")

            # Create a new figure and axes for each plot
            fig, ax = plt.subplots(figsize=(10, 6)) # Adjust figsize as needed
            ax.set_title(title)

            if chart_type == "bar":
                self._render_bar_chart(ax, df, metadata)
            elif chart_type == "pie":
                self._render_pie_chart(ax, df, metadata)
            elif chart_type == "line":
                self._render_line_chart(ax, df, metadata)
            elif chart_type == "scatter":
                self._render_scatter_chart(ax, df, metadata)
            else:
                raise ValueError(f"Unsupported chart type: {chart_type}")

            # --- Final Adjustments and Saving --- 
            logger.debug("Adjusting layout and saving figure...")
            try:
                # Improve layout and handle potentially long x-axis labels
                plt.xticks(rotation=45, ha='right') # Rotate labels
                plt.tight_layout() # Adjust layout to prevent overlap

                save_dir = Path("static/charts")
                save_dir.mkdir(parents=True, exist_ok=True)
                filename = f"chart_{uuid.uuid4()}.png"
                filepath = save_dir / filename
                image_url = f"/static/charts/{filename}"

                # Save the figure to a PNG file
                fig.savefig(str(filepath), format='png', bbox_inches='tight') 
                logger.info(f"Chart saved successfully to {filepath}")
                
                # Prepare output with image URL
                visualization_output = {
                    "type": chart_type,
                    "image_url": image_url,
                    "title": title,
                    "metadata": metadata,
                }
                text_output = description
                logger.info(f"Chart generated successfully, URL: {image_url}")

            except Exception as save_err:
                 logger.error(f"Failed during figure saving: {save_err}", exc_info=True)
                 raise ValueError(f"Failed to save image file: {save_err}") from save_err

        except Exception as e:
            logger.error(f"Chart renderer tool failed: {str(e)}", exc_info=True)
            text_output = f"Failed to generate chart. Error: {str(e)}"
            visualization_output = None
        finally:
            # IMPORTANT: Close the figure to release memory
            if fig is not None:
                plt.close(fig)
                logger.debug("Closed Matplotlib figure.")

        # Return structured output
        return {
            "visualization": visualization_output,
            "text": text_output,
        }

    async def _arun(
        self,
        query: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Asynchronous version of _run."""
        logger.debug("Chart renderer _arun called, invoking _run...")
        try:
            return self._run(query, data, metadata)
        except Exception as e:
             # Log the error specifically from _arun context if needed
            logger.error(f"Error during async chart rendering (_arun): {str(e)}", exc_info=True)
             # Re-package the error similar to how _run does
            return {
                "visualization": None,
                "text": f"Failed to generate chart during async execution. Error: {str(e)}",
            }

# Optional: Define a Pydantic model for stricter input validation if desired
# from pydantic import BaseModel, Field
# class ChartRendererInput(BaseModel):
#     query: Optional[str] = Field(default=None, description="User query or description")
#     data: Dict[str, Any] = Field(description="Data in SQL Tool format {'columns': [...], 'rows': [[...]]}")
#     metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional chart metadata")

# class ChartRendererTool(BaseTool):
#     name: str = "chart_renderer"
#     description: str = "..."
#     args_schema: Type[BaseModel] = ChartRendererInput
#     # ... rest of the class, _run would receive validated args ...