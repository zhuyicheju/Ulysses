// Package config provides configuration loading from YAML files
// with environment variable overrides (ULYSSES_ prefix).
package config

import (
	"fmt"
	"os"
	"strings"
	"time"

	"dario.cat/mergo"
	"github.com/caarlos0/env/v11"
	"gopkg.in/yaml.v3"
)

// Config holds all configuration for the Ulysses agent runtime.
// Values are loaded from a YAML file and can be overridden by
// environment variables with the ULYSSES_ prefix.
type Config struct {
	// FilePath is the path to the YAML file that was loaded (empty if defaults only).
	FilePath string `yaml:"-" env:"-"`

	LLM     LLMConfig     `yaml:"llm"`
	Python  PythonConfig  `yaml:"python"`
	Agent   AgentConfig   `yaml:"agent"`
	Logging LoggingConfig `yaml:"logging"`
}

// LLMConfig holds configuration for the LLM backend connection.
type LLMConfig struct {
	Model     string `yaml:"model"`
	BaseURL   string `yaml:"base_url"`
	APIKey    string `yaml:"api_key"`
	MaxTokens int    `yaml:"max_tokens"`
}

// PythonConfig holds configuration for the Python child process.
type PythonConfig struct {
	Interpreter string `yaml:"interpreter"`
	ModulePath  string `yaml:"module_path"`
}

// AgentConfig holds configuration for the agent runtime.
type AgentConfig struct {
	MaxIterations int           `yaml:"max_iterations"`
	Timeout       time.Duration `yaml:"timeout"`
}

// LoggingConfig holds configuration for structured logging.
type LoggingConfig struct {
	Level  string `yaml:"level"`
	Format string `yaml:"format"`
}

// DefaultConfig returns a Config with sensible defaults.
func DefaultConfig() *Config {
	return &Config{
		LLM: LLMConfig{
			Model:     "claude-sonnet-4-6",
			BaseURL:   "https://api.anthropic.com",
			MaxTokens: 4096,
		},
		Python: PythonConfig{
			Interpreter: "python3",
			ModulePath:  "py-ai",
		},
		Agent: AgentConfig{
			MaxIterations: 50,
			Timeout:       5 * time.Minute,
		},
		Logging: LoggingConfig{
			Level:  "info",
			Format: "json",
		},
	}
}

// Load reads configuration from a YAML file and applies environment
// variable overrides. If configPath is empty, it looks for "ulysses.yaml"
// in the current directory and common parent directories.
func Load(configPath string) (*Config, error) {
	cfg := DefaultConfig()

	if configPath != "" {
		if err := loadYAML(configPath, cfg); err != nil {
			return nil, fmt.Errorf("loading config file %s: %w", configPath, err)
		}
		cfg.FilePath = configPath
	}

	_ = env.ParseWithOptions(cfg, env.Options{Prefix: "ULYSSES_"})

	return cfg, nil
}

// MustLoad calls Load and panics on error. Intended for use in main
// where a missing or invalid config is a fatal startup error.
func MustLoad(configPath string) *Config {
	cfg, err := Load(configPath)
	if err != nil {
		panic(fmt.Sprintf("failed to load config: %v", err))
	}
	return cfg
}

// loadYAML reads and decodes a YAML config file, applying values on
// top of the existing config (which already contains defaults).
func loadYAML(path string, cfg *Config) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("reading file: %w", err)
	}

	// Use a separate decode to preserve defaults for missing keys.
	var fileCfg Config
	if err := yaml.Unmarshal(data, &fileCfg); err != nil {
		return fmt.Errorf("parsing yaml: %w", err)
	}

	// Merge: only override non-zero values from file.
	return mergeConfig(cfg, &fileCfg)
}

// mergeConfig copies non-zero values from src to dst.
func mergeConfig(dst, src *Config) error {
	return mergo.Merge(dst, src, mergo.WithOverride)
}

// LoadDotEnv reads a .env file and sets environment variables.
// It does NOT override existing environment variables.
// The path parameter is optional; if empty, looks for ".env" in cwd.
func LoadDotEnv(path string) error {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil // no .env file is not an error
		}
		return fmt.Errorf("reading .env file: %w", err)
	}

	lines := strings.Split(string(data), "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)

		// Skip empty lines and comments.
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		// Parse KEY=VALUE.
		parts := strings.SplitN(line, "=", 2)
		if len(parts) != 2 {
			continue // malformed line, skip
		}

		key := strings.TrimSpace(parts[0])
		value := strings.TrimSpace(parts[1])

		// Remove optional surrounding quotes.
		value = strings.Trim(value, `"'`)

		if key == "" {
			continue
		}

		// Only set if not already set in environment.
		if _, exists := os.LookupEnv(key); !exists {
			os.Setenv(key, value)
		}
	}

	return nil
}
