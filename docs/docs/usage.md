---
sidebar_position: 4
---

# Usage

Learn how to use MCP Jupyter effectively with your AI assistant.

## Basic Usage

### Creating a New Notebook

Ask your AI assistant to create a notebook:

```
"Create a new notebook called data_analysis.ipynb"
```

The AI will:
1. Create the notebook file
2. Start a kernel
3. Be ready for your commands

### Working with Existing Notebooks

```
"Open the notebook experiments/model_training.ipynb"
```

Your AI assistant will connect to the existing notebook and preserve all current state.

## Example Workflows

### Data Analysis Workflow

Here's a typical data analysis session:

```python
# You: Load the sales data
# AI: *loads data and shows preview*

# You: "I see there are missing values. Handle them appropriately"
# AI: *analyzes data types and fills missing values*

# You: Manually explore specific columns
df['revenue'].describe()

# You: "Create visualizations for the quarterly trends"
# AI: *generates comprehensive visualizations*
```

### Machine Learning Workflow

```python
# You: "Load the iris dataset and prepare it for classification"
# AI loads data, does train-test split

# You manually inspect the data
X_train.shape, y_train.value_counts()

# You: "Try different classifiers and compare their performance"
# AI implements multiple models with cross-validation

# If a package is missing, AI will see the error and install it
# automatically, then retry the operation
```

### Package Management

The AI assistant handles package installation seamlessly:

```python
# You: "Create a word cloud from this text"
# AI attempts to import wordcloud
# Sees ImportError
# Installs the package: !pip install wordcloud
# Retries and creates the visualization
```

## Advanced Features

### State Preservation

All variables remain available throughout your session:

```python
# Cell 1 (executed by you)
data = load_large_dataset()
model = train_complex_model(data)

# Cell 2 (AI continues with your objects)
# AI can access 'data' and 'model' directly
# "Evaluate the model and show feature importance"
```

### Error Handling

The AI can see and respond to errors:

```python
# You write code with an error
result = data.groupby('category').mean()  # Error: 'data' not defined

# AI sees the error and can:
# - Suggest loading the data first
# - Check available variables
# - Provide the correct code
```

### Collaborative Exploration

Switch seamlessly between manual and AI work:

```python
# You: Start exploring
df.head()
df.info()

# You: "Continue exploring this dataset and find interesting patterns"
# AI: Performs statistical analysis, creates visualizations

# You: Notice something interesting in the AI's output
subset = df[df['category'] == 'electronics']
subset['profit_margin'].hist()

# You: "Investigate why electronics have this distribution"
# AI: Continues analysis focusing on your discovery
```

## Best Practices

### 1. Clear Instructions

Be specific about what you want:
- ❌ "Analyze the data"
- ✅ "Perform exploratory data analysis focusing on customer segments and seasonal patterns"

### 2. Iterative Refinement

Work iteratively with the AI:
```
1. "Load and preview the customer data"
2. Review the output
3. "Focus on customers from the last quarter"
4. "Now segment them by purchase frequency"
```

### 3. State Management

- Keep important variables in the global namespace
- Use descriptive variable names
- Periodically check available variables with `dir()` or `locals()`

### 4. Error Recovery

When errors occur:
- Let the AI see and handle the error
- Provide context if needed
- The AI will install packages or fix issues automatically

## Demo Example

![MCP Jupyter Demo](/demos/goose-demo.png)

[View the generated notebook →](https://github.com/squareup/mcp-jupyter/blob/main/demos/demo.ipynb)

## Tips and Tricks

1. **Use Markdown cells**: Ask the AI to document its analysis
2. **Save checkpoints**: Periodically save important state
3. **Combine approaches**: Use AI for boilerplate, manually tune details
4. **Leverage errors**: Let errors guide package installation
5. **Incremental development**: Build complex analyses step by step

## Next Steps

- [Development Guide →](/docs/development)