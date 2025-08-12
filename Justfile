# Run all CI checks locally (matches GitHub Actions)
ci: test lint format
    @echo "✅ All CI checks passed!"

# Run tests (matches: uv run pytest tests)
test:
    @echo "🧪 Running tests..."
    uv run pytest tests

# Run linting (matches: uvx ruff check)  
lint:
    @echo "🔍 Running linter..."
    uvx ruff check

# Run format check and fix (matches: uvx ruff format --check but also fixes)
format:
    @echo "🎨 Checking and fixing formatting..."
    uvx ruff format