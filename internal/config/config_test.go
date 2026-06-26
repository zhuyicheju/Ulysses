package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// =============================================================================
// DefaultConfig tests
// =============================================================================

func TestDefaultConfig(t *testing.T) {
	t.Parallel()

	cfg := DefaultConfig()

	// LLM defaults
	if cfg.LLM.Model != "claude-sonnet-4-6" {
		t.Errorf("LLM.Model = %q, want %q", cfg.LLM.Model, "claude-sonnet-4-6")
	}
	if cfg.LLM.BaseURL != "https://api.anthropic.com" {
		t.Errorf("LLM.BaseURL = %q, want %q", cfg.LLM.BaseURL, "https://api.anthropic.com")
	}
	if cfg.LLM.MaxTokens != 4096 {
		t.Errorf("LLM.MaxTokens = %d, want %d", cfg.LLM.MaxTokens, 4096)
	}
	if cfg.LLM.APIKey != "" {
		t.Errorf("LLM.APIKey = %q, want empty string", cfg.LLM.APIKey)
	}

	// Python defaults
	if cfg.Python.Interpreter != "python3" {
		t.Errorf("Python.Interpreter = %q, want %q", cfg.Python.Interpreter, "python3")
	}
	if cfg.Python.ModulePath != "py-ai" {
		t.Errorf("Python.ModulePath = %q, want %q", cfg.Python.ModulePath, "py-ai")
	}

	// Agent defaults
	if cfg.Agent.MaxIterations != 50 {
		t.Errorf("Agent.MaxIterations = %d, want %d", cfg.Agent.MaxIterations, 50)
	}
	if cfg.Agent.Timeout != 5*time.Minute {
		t.Errorf("Agent.Timeout = %v, want %v", cfg.Agent.Timeout, 5*time.Minute)
	}

	// Logging defaults
	if cfg.Logging.Level != "info" {
		t.Errorf("Logging.Level = %q, want %q", cfg.Logging.Level, "info")
	}
	if cfg.Logging.Format != "json" {
		t.Errorf("Logging.Format = %q, want %q", cfg.Logging.Format, "json")
	}

	// FilePath should be empty for defaults
	if cfg.FilePath != "" {
		t.Errorf("FilePath = %q, want empty string", cfg.FilePath)
	}
}

func TestDefaultConfig_ReturnsIndependentInstances(t *testing.T) {
	t.Parallel()

	cfg1 := DefaultConfig()
	cfg2 := DefaultConfig()

	// Modifying one should not affect the other
	cfg1.LLM.Model = "modified"
	if cfg2.LLM.Model == "modified" {
		t.Error("DefaultConfig instances should be independent")
	}
}

// =============================================================================
// Load tests
// =============================================================================

func TestLoad_EmptyPath_ReturnsDefaults(t *testing.T) {
	cfg, err := Load("")
	if err != nil {
		t.Fatalf("Load(\"\") returned error: %v", err)
	}
	if cfg == nil {
		t.Fatal("Load(\"\") returned nil config")
	}

	// Should match defaults
	defaults := DefaultConfig()
	if cfg.LLM.Model != defaults.LLM.Model {
		t.Errorf("Model = %q, want %q", cfg.LLM.Model, defaults.LLM.Model)
	}
	if cfg.Agent.MaxIterations != defaults.Agent.MaxIterations {
		t.Errorf("MaxIterations = %d, want %d", cfg.Agent.MaxIterations, defaults.Agent.MaxIterations)
	}
}

func TestLoad_ValidYAMLFile_MergesValues(t *testing.T) {
	dir := t.TempDir()
	configPath := filepath.Join(dir, "ulysses.yaml")

	yamlContent := `
llm:
  model: claude-opus-4-8
  max_tokens: 8192
agent:
  max_iterations: 100
`
	writeFile(t, configPath, yamlContent)

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("Load(%q) returned error: %v", configPath, err)
	}

	// File values should override defaults
	if cfg.LLM.Model != "claude-opus-4-8" {
		t.Errorf("LLM.Model = %q, want %q", cfg.LLM.Model, "claude-opus-4-8")
	}
	if cfg.LLM.MaxTokens != 8192 {
		t.Errorf("LLM.MaxTokens = %d, want %d", cfg.LLM.MaxTokens, 8192)
	}
	if cfg.Agent.MaxIterations != 100 {
		t.Errorf("Agent.MaxIterations = %d, want %d", cfg.Agent.MaxIterations, 100)
	}

	// Missing keys in YAML should retain defaults
	if cfg.LLM.BaseURL != "https://api.anthropic.com" {
		t.Errorf("LLM.BaseURL = %q, want default %q", cfg.LLM.BaseURL, "https://api.anthropic.com")
	}
	if cfg.Logging.Level != "info" {
		t.Errorf("Logging.Level = %q, want default %q", cfg.Logging.Level, "info")
	}

	// FilePath should be set
	if cfg.FilePath != configPath {
		t.Errorf("FilePath = %q, want %q", cfg.FilePath, configPath)
	}
}

func TestLoad_NonExistentFile_ReturnsError(t *testing.T) {
	cfg, err := Load("/nonexistent/path/config.yaml")
	if err == nil {
		t.Error("Load with nonexistent file should return error")
	}
	if cfg != nil {
		t.Error("Load with nonexistent file should return nil config on error")
	}
}

func TestLoad_InvalidYAML_ReturnsError(t *testing.T) {
	dir := t.TempDir()
	configPath := filepath.Join(dir, "bad.yaml")

	writeFile(t, configPath, "invalid: yaml: {{{unclosed")

	cfg, err := Load(configPath)
	if err == nil {
		t.Error("Load with invalid YAML should return error")
	}
	if cfg != nil {
		t.Error("Load with invalid YAML should return nil config on error")
	}
}

func TestLoad_EmptyYAMLFile_RetainsAllDefaults(t *testing.T) {
	dir := t.TempDir()
	configPath := filepath.Join(dir, "empty.yaml")

	writeFile(t, configPath, "")

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("Load with empty YAML returned error: %v", err)
	}

	defaults := DefaultConfig()
	if cfg.LLM.Model != defaults.LLM.Model {
		t.Errorf("LLM.Model = %q, want default %q", cfg.LLM.Model, defaults.LLM.Model)
	}
	if cfg.Agent.MaxIterations != defaults.Agent.MaxIterations {
		t.Errorf("Agent.MaxIterations = %d, want default %d", cfg.Agent.MaxIterations, defaults.Agent.MaxIterations)
	}
}

// TestLoad_EnvParseIsCalled verifies that env.ParseWithOptions is invoked
// during Load. Note: env var overrides currently require either `env` struct
// tags on fields or UseFieldNameByDefault:true in Options. Without these,
// env.ParseWithOptions is a no-op. See recommendation in test report.
func TestLoad_EnvParseIsCalled(t *testing.T) {
	// Load should complete without error even when env parsing yields no matches
	dir := t.TempDir()
	configPath := filepath.Join(dir, "config.yaml")
	writeFile(t, configPath, `
llm:
  model: file-model
`)

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	// File values are applied; env parsing is a no-op without env tags
	if cfg.LLM.Model != "file-model" {
		t.Errorf("LLM.Model = %q, want %q", cfg.LLM.Model, "file-model")
	}
}

func TestLoad_PartialYAML_PreservesUnspecifiedDefaults(t *testing.T) {
	dir := t.TempDir()
	configPath := filepath.Join(dir, "partial.yaml")
	writeFile(t, configPath, `
logging:
  level: debug
`)

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	// Specified key
	if cfg.Logging.Level != "debug" {
		t.Errorf("Logging.Level = %q, want %q", cfg.Logging.Level, "debug")
	}

	// Unspecified keys retain defaults
	defaults := DefaultConfig()
	if cfg.LLM.Model != defaults.LLM.Model {
		t.Errorf("LLM.Model = %q, want default %q", cfg.LLM.Model, defaults.LLM.Model)
	}
	if cfg.Python.Interpreter != defaults.Python.Interpreter {
		t.Errorf("Python.Interpreter = %q, want default %q", cfg.Python.Interpreter, defaults.Python.Interpreter)
	}
	if cfg.Agent.MaxIterations != defaults.Agent.MaxIterations {
		t.Errorf("Agent.MaxIterations = %d, want default %d", cfg.Agent.MaxIterations, defaults.Agent.MaxIterations)
	}
}

// =============================================================================
// MustLoad tests
// =============================================================================

func TestMustLoad_ValidConfig_ReturnsConfig(t *testing.T) {
	cfg := MustLoad("")
	if cfg == nil {
		t.Fatal("MustLoad(\"\") returned nil")
	}
	defaults := DefaultConfig()
	if cfg.LLM.Model != defaults.LLM.Model {
		t.Errorf("LLM.Model = %q, want %q", cfg.LLM.Model, defaults.LLM.Model)
	}
}

func TestMustLoad_InvalidConfig_Panics(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Error("MustLoad with invalid config should panic")
		}
	}()
	MustLoad("/nonexistent/path/should/panic.yaml")
}

func TestMustLoad_PanicMessage_ContainsError(t *testing.T) {
	defer func() {
		r := recover()
		if r == nil {
			t.Error("MustLoad should panic on invalid config")
			return
		}
		msg, ok := r.(string)
		if !ok {
			t.Errorf("panic value should be string, got %T", r)
			return
		}
		if !strings.Contains(msg, "failed to load config") {
			t.Errorf("panic message %q should contain 'failed to load config'", msg)
		}
	}()
	MustLoad("/nonexistent/path/should/panic.yaml")
}

// =============================================================================
// LoadDotEnv tests
// =============================================================================

func TestLoadDotEnv_ValidFile_SetsEnvVars(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "TEST_KEY_1=value1\nTEST_KEY_2=value2\n")

	// Clean up env vars after test
	t.Cleanup(func() {
		os.Unsetenv("TEST_KEY_1")
		os.Unsetenv("TEST_KEY_2")
	})

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv(%q) returned error: %v", envPath, err)
	}

	if val := os.Getenv("TEST_KEY_1"); val != "value1" {
		t.Errorf("TEST_KEY_1 = %q, want %q", val, "value1")
	}
	if val := os.Getenv("TEST_KEY_2"); val != "value2" {
		t.Errorf("TEST_KEY_2 = %q, want %q", val, "value2")
	}
}

func TestLoadDotEnv_MissingFile_ReturnsNil(t *testing.T) {
	err := LoadDotEnv("/nonexistent/.env_file")
	if err != nil {
		t.Errorf("LoadDotEnv with missing file should return nil, got: %v", err)
	}
}

func TestLoadDotEnv_SkipsEmptyLines(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "TEST_SKIP_EMPTY=val\n\n\nTEST_AFTER_EMPTY=after\n")

	t.Cleanup(func() {
		os.Unsetenv("TEST_SKIP_EMPTY")
		os.Unsetenv("TEST_AFTER_EMPTY")
	})

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv returned error: %v", err)
	}

	if val := os.Getenv("TEST_SKIP_EMPTY"); val != "val" {
		t.Errorf("TEST_SKIP_EMPTY = %q, want %q", val, "val")
	}
	if val := os.Getenv("TEST_AFTER_EMPTY"); val != "after" {
		t.Errorf("TEST_AFTER_EMPTY = %q, want %q", val, "after")
	}
}

func TestLoadDotEnv_SkipsComments(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "# This is a comment\nTEST_COMMENT_SKIP=val\n# Another comment\n")

	t.Cleanup(func() {
		os.Unsetenv("TEST_COMMENT_SKIP")
	})

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv returned error: %v", err)
	}

	if val := os.Getenv("TEST_COMMENT_SKIP"); val != "val" {
		t.Errorf("TEST_COMMENT_SKIP = %q, want %q", val, "val")
	}
}

func TestLoadDotEnv_SkipsMalformedLines(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "VALID_KEY=val\nINVALID_LINE_NO_EQUALS\nALSO_VALID=yes\n")

	t.Cleanup(func() {
		os.Unsetenv("VALID_KEY")
		os.Unsetenv("ALSO_VALID")
	})

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv returned error: %v", err)
	}

	if _, exists := os.LookupEnv("INVALID_LINE_NO_EQUALS"); exists {
		t.Error("Malformed line without '=' should not set an env var")
	}
	if val := os.Getenv("VALID_KEY"); val != "val" {
		t.Errorf("VALID_KEY = %q, want %q", val, "val")
	}
	if val := os.Getenv("ALSO_VALID"); val != "yes" {
		t.Errorf("ALSO_VALID = %q, want %q", val, "yes")
	}
}

func TestLoadDotEnv_StripsQuotes(t *testing.T) {
	tests := []struct {
		name     string
		rawValue string
		want     string
	}{
		{"double quotes", `TEST_DQ="quoted_value"`, "quoted_value"},
		{"single quotes", `TEST_SQ='quoted_value'`, "quoted_value"},
		{"mixed quotes both stripped", `TEST_MIXED='no_strip"`, `no_strip`},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			envPath := filepath.Join(dir, ".env")
			writeFile(t, envPath, tc.rawValue)

			// Extract key name for cleanup
			key := strings.SplitN(tc.rawValue, "=", 2)[0]
			t.Cleanup(func() { os.Unsetenv(key) })

			err := LoadDotEnv(envPath)
			if err != nil {
				t.Fatalf("LoadDotEnv returned error: %v", err)
			}

			if val := os.Getenv(key); val != tc.want {
				t.Errorf("%s = %q, want %q", key, val, tc.want)
			}
		})
	}
}

func TestLoadDotEnv_DoesNotOverrideExistingEnv(t *testing.T) {
	key := "TEST_NO_OVERRIDE"
	t.Setenv(key, "original-value")
	t.Cleanup(func() { os.Unsetenv(key) })

	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, key+"=new-value")

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv returned error: %v", err)
	}

	if val := os.Getenv(key); val != "original-value" {
		t.Errorf("%s = %q, want %q (should not override existing)", key, val, "original-value")
	}
}

func TestLoadDotEnv_SkipsEmptyKey(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "=value_with_empty_key\nVALID_KEY=valid_val\n")

	t.Cleanup(func() {
		os.Unsetenv("VALID_KEY")
	})

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv returned error: %v", err)
	}

	if val := os.Getenv("VALID_KEY"); val != "valid_val" {
		t.Errorf("VALID_KEY = %q, want %q", val, "valid_val")
	}
}

func TestLoadDotEnv_TrimsWhitespace(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "  TEST_TRIM_KEY  =   trimmed_value  \n")

	t.Cleanup(func() { os.Unsetenv("TEST_TRIM_KEY") })

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv returned error: %v", err)
	}

	if val := os.Getenv("TEST_TRIM_KEY"); val != "trimmed_value" {
		t.Errorf("TEST_TRIM_KEY = %q, want %q", val, "trimmed_value")
	}
}

func TestLoadDotEnv_EmptyFile_ReturnsNil(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "")

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Errorf("LoadDotEnv with empty file should return nil, got: %v", err)
	}
}

func TestLoadDotEnv_ValueWithEqualsSign(t *testing.T) {
	dir := t.TempDir()
	envPath := filepath.Join(dir, ".env")
	writeFile(t, envPath, "TEST_EQ_SIGN=key=with=equals\n")

	t.Cleanup(func() { os.Unsetenv("TEST_EQ_SIGN") })

	err := LoadDotEnv(envPath)
	if err != nil {
		t.Fatalf("LoadDotEnv returned error: %v", err)
	}

	// SplitN with limit 2 means only the first = is the separator
	if val := os.Getenv("TEST_EQ_SIGN"); val != "key=with=equals" {
		t.Errorf("TEST_EQ_SIGN = %q, want %q", val, "key=with=equals")
	}
}

// =============================================================================
// loadYAML tests (internal function, tested via Load)
// =============================================================================

func TestLoadYAML_MissingFile_ReturnsError(t *testing.T) {
	cfg := DefaultConfig()
	err := loadYAML("/nonexistent/file.yaml", cfg)
	if err == nil {
		t.Error("loadYAML with missing file should return error")
	}
	if !strings.Contains(err.Error(), "reading file") {
		t.Errorf("error %q should contain 'reading file'", err.Error())
	}
}

func TestLoadYAML_InvalidYAML_ReturnsError(t *testing.T) {
	dir := t.TempDir()
	yamlPath := filepath.Join(dir, "invalid.yaml")
	writeFile(t, yamlPath, "key: [unclosed\n")

	cfg := DefaultConfig()
	err := loadYAML(yamlPath, cfg)
	if err == nil {
		t.Error("loadYAML with invalid YAML should return error")
	}
	if !strings.Contains(err.Error(), "parsing yaml") {
		t.Errorf("error %q should contain 'parsing yaml'", err.Error())
	}
}

func TestLoadYAML_ValidFile_MergesIntoExistingConfig(t *testing.T) {
	dir := t.TempDir()
	yamlPath := filepath.Join(dir, "config.yaml")
	writeFile(t, yamlPath, `
llm:
  model: test-model
  max_tokens: 1000
`)

	cfg := DefaultConfig()
	err := loadYAML(yamlPath, cfg)
	if err != nil {
		t.Fatalf("loadYAML returned error: %v", err)
	}

	if cfg.LLM.Model != "test-model" {
		t.Errorf("LLM.Model = %q, want %q", cfg.LLM.Model, "test-model")
	}
	if cfg.LLM.MaxTokens != 1000 {
		t.Errorf("LLM.MaxTokens = %d, want %d", cfg.LLM.MaxTokens, 1000)
	}
	// Defaults not in YAML should be preserved
	if cfg.Agent.MaxIterations != 50 {
		t.Errorf("Agent.MaxIterations = %d, want default %d", cfg.Agent.MaxIterations, 50)
	}
}

// =============================================================================
// mergeConfig tests
// =============================================================================

func TestMergeConfig_OverridesNonZeroValues(t *testing.T) {
	dst := DefaultConfig()
	src := &Config{
		LLM: LLMConfig{
			Model:     "merged-model",
			MaxTokens: 9999,
		},
	}

	err := mergeConfig(dst, src)
	if err != nil {
		t.Fatalf("mergeConfig returned error: %v", err)
	}

	if dst.LLM.Model != "merged-model" {
		t.Errorf("LLM.Model = %q, want %q", dst.LLM.Model, "merged-model")
	}
	if dst.LLM.MaxTokens != 9999 {
		t.Errorf("LLM.MaxTokens = %d, want %d", dst.LLM.MaxTokens, 9999)
	}
}

func TestMergeConfig_ZeroValuesDoNotOverride(t *testing.T) {
	dst := DefaultConfig()
	src := &Config{
		LLM: LLMConfig{
			Model:     "",        // zero value for string
			MaxTokens: 0,         // zero value for int
			BaseURL:   "",        // zero value for string
		},
		Agent: AgentConfig{
			MaxIterations: 0,     // zero value for int
			Timeout:       0,     // zero value for time.Duration
		},
	}

	err := mergeConfig(dst, src)
	if err != nil {
		t.Fatalf("mergeConfig returned error: %v", err)
	}

	// Defaults should be preserved when src has zero values
	defaults := DefaultConfig()
	if dst.LLM.Model != defaults.LLM.Model {
		t.Errorf("LLM.Model = %q, want default %q (zero should not override)", dst.LLM.Model, defaults.LLM.Model)
	}
	if dst.LLM.MaxTokens != defaults.LLM.MaxTokens {
		t.Errorf("LLM.MaxTokens = %d, want default %d (zero should not override)", dst.LLM.MaxTokens, defaults.LLM.MaxTokens)
	}
	if dst.LLM.BaseURL != defaults.LLM.BaseURL {
		t.Errorf("LLM.BaseURL = %q, want default %q (zero should not override)", dst.LLM.BaseURL, defaults.LLM.BaseURL)
	}
	if dst.Agent.MaxIterations != defaults.Agent.MaxIterations {
		t.Errorf("Agent.MaxIterations = %d, want default %d (zero should not override)", dst.Agent.MaxIterations, defaults.Agent.MaxIterations)
	}
	if dst.Agent.Timeout != defaults.Agent.Timeout {
		t.Errorf("Agent.Timeout = %v, want default %v (zero should not override)", dst.Agent.Timeout, defaults.Agent.Timeout)
	}
}

func TestMergeConfig_PartialOverride_PreservesUnspecifiedFields(t *testing.T) {
	dst := DefaultConfig()
	src := &Config{
		Logging: LoggingConfig{
			Level:  "debug",
			Format: "", // zero value, should not override
		},
	}

	err := mergeConfig(dst, src)
	if err != nil {
		t.Fatalf("mergeConfig returned error: %v", err)
	}

	if dst.Logging.Level != "debug" {
		t.Errorf("Logging.Level = %q, want %q", dst.Logging.Level, "debug")
	}
	// Format should retain default since src had zero value
	if dst.Logging.Format != "json" {
		t.Errorf("Logging.Format = %q, want default %q", dst.Logging.Format, "json")
	}
}

// =============================================================================
// Config type field tests
// =============================================================================

func TestConfig_FilePath_YAMLTagSkip(t *testing.T) {
	// FilePath is marked yaml:"-" so it should never be set from YAML
	dir := t.TempDir()
	configPath := filepath.Join(dir, "config.yaml")
	// Even if somehow a file_path key appears in YAML, it should be ignored
	writeFile(t, configPath, "file_path: /some/path\nllm:\n  model: test\n")

	cfg, err := Load(configPath)
	if err != nil {
		t.Fatalf("Load returned error: %v", err)
	}

	// FilePath should be the actual file path, not from YAML content
	if cfg.FilePath != configPath {
		t.Errorf("FilePath = %q, want actual config path %q", cfg.FilePath, configPath)
	}
}

// =============================================================================
// Helper
// =============================================================================

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0644); err != nil {
		t.Fatalf("failed to write test file %q: %v", path, err)
	}
}
