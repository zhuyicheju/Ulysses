# Ulysses Agent Runtime - Build System
# ============================================================================
# Supports parallel builds: make -j$(nproc)

# Project paths
GO_MODULE       := github.com/zhuyicheju/ulysses
GO_ENTRY        := ./cmd/ulysses
BIN_DIR         := bin
BINARY          := $(BIN_DIR)/ulysses
PY_DIR          := py-ai

# Auto-detect conda environment prefix
CONDA_EXE       := $(shell command -v conda 2>/dev/null)
CONDA_ENV       := ulysses
CONDA_PREFIX    := $(shell $(CONDA_EXE) env list 2>/dev/null | grep -E '^$(CONDA_ENV)[[:space:]]' | awk '{print $$NF}')
PYTHON          := $(CONDA_PREFIX)/bin/python
PIP_INSTALL     := $(PYTHON) -m pip install -q

# Build info (injected via ldflags)
GIT_COMMIT      := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIME      := $(shell date -u "+%Y-%m-%dT%H:%M:%SZ")
LDFLAGS         := -s -w -X main.gitCommit=$(GIT_COMMIT) -X main.buildTime=$(BUILD_TIME)

.DEFAULT_GOAL := build

# ---------------------------------------------------------------------------
# Primary targets (all support -j)
# ---------------------------------------------------------------------------

.PHONY: build
build: $(BINARY) py-deps
	@echo "Build complete: $(BINARY)"

.PHONY: test
test: test-go test-py
	@echo "All tests passed"

.PHONY: lint
lint: lint-go lint-py
	@echo "Lint complete"

.PHONY: run
run: build
	@echo "Starting Ulysses..."
	./$(BINARY)

# ---------------------------------------------------------------------------
# Go targets
# ---------------------------------------------------------------------------

$(BIN_DIR):
	@mkdir -p $(BIN_DIR)

$(BINARY): $(BIN_DIR)
	@echo "Building Go binary..."
	go build -ldflags "$(LDFLAGS)" -o $(BINARY) $(GO_ENTRY)

.PHONY: test-go
test-go:
	@echo "Running Go tests..."
	go test -race -count=1 ./...

.PHONY: lint-go
lint-go:
	@if command -v golangci-lint >/dev/null 2>&1; then \
		echo "Running golangci-lint..."; \
		golangci-lint run ./...; \
	else \
		echo "golangci-lint not found - running go vet instead"; \
		go vet ./...; \
	fi

# ---------------------------------------------------------------------------
# Python targets (via conda environment)
# ---------------------------------------------------------------------------

.PHONY: py-deps
py-deps:
	@echo "Installing Python dependencies..."
	$(PIP_INSTALL) --no-build-isolation -e $(PY_DIR)
	$(PIP_INSTALL) -r $(PY_DIR)/requirements-dev.txt

.PHONY: test-py
test-py: py-deps
	@echo "Running Python tests..."
	cd $(PY_DIR) && $(PYTHON) -m pytest -v

.PHONY: lint-py
lint-py: py-deps
	@echo "Running ruff..."
	cd $(PY_DIR) && $(PYTHON) -m ruff check src/ tests/

.PHONY: fmt-py
fmt-py: py-deps
	@echo "Formatting Python code..."
	cd $(PY_DIR) && $(PYTHON) -m ruff format src/ tests/

# ---------------------------------------------------------------------------
# Utility targets
# ---------------------------------------------------------------------------

.PHONY: clean
clean:
	@echo "Cleaning..."
	rm -rf $(BIN_DIR)
	rm -rf $(PY_DIR)/*.egg-info $(PY_DIR)/build $(PY_DIR)/dist
	find $(PY_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	rm -rf $(PY_DIR)/.pytest_cache
	@echo "Clean complete"

.PHONY: info
info:
	@echo "Go module:    $(GO_MODULE)"
	@echo "Go entry:     $(GO_ENTRY)"
	@echo "Binary:       $(BINARY)"
	@echo "Git commit:   $(GIT_COMMIT)"
	@echo "Build time:   $(BUILD_TIME)"
	@echo "Conda env:    $(CONDA_ENV)"
	@echo "Conda prefix: $(CONDA_PREFIX)"

.PHONY: help
help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Primary targets (all safe for make -j):"
	@echo "  build   - Build Go binary and verify Python dependencies"
	@echo "  test    - Run Go tests and Python tests"
	@echo "  lint    - Run golangci-lint and ruff"
	@echo "  run     - Build and run Ulysses with default config"
	@echo ""
	@echo "Utility targets:"
	@echo "  clean   - Remove build artifacts"
	@echo "  info    - Print build information"
	@echo "  fmt-py  - Format Python code with ruff"
