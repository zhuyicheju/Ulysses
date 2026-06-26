// Ulysses — a runtime system for long-horizon code agents.
//
// Entry point for the Ulysses CLI. Starts the agent runtime,
// manages the Python LLM bridge, and provides subcommands for
// chat, run, config, and version.
package main

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/zhuyicheju/ulysses/internal/config"
	"github.com/zhuyicheju/ulysses/internal/logger"
)

var (
	configPath  string
	envFilePath string
	cfg         *config.Config
	log         logger.Logger
)

var rootCmd = &cobra.Command{
	Use:   "ulysses",
	Short: "Ulysses — long-horizon code agent runtime",
	Long: `Ulysses is a runtime system for long-horizon code agents.
It orchestrates LLM interactions through a Python bridge,
with deterministic engineering infrastructure wrapping
probabilistic LLM calls.`,
	PersistentPreRunE: func(cmd *cobra.Command, args []string) error {
		// Load .env before config so env vars are available for overrides.
		_ = config.LoadDotEnv(envFilePath)

		var err error
		cfg, err = config.Load(configPath)
		if err != nil {
			return fmt.Errorf("loading config: %w", err)
		}

		log, err = logger.New(cfg.Logging.Level, cfg.Logging.Format, os.Stderr)
		if err != nil {
			return fmt.Errorf("creating logger: %w", err)
		}
		return nil
	},
	Run: func(cmd *cobra.Command, args []string) {
		log.Info("starting Ulysses")
	},
}

var versionCmd = &cobra.Command{
	Use:   "version",
	Short: "Print version information",
	Long:  "Print the Ulysses version including Git commit and build time.",
	Run: func(cmd *cobra.Command, args []string) {
		printVersion()
	},
}

var configCmd = &cobra.Command{
	Use:   "config",
	Short: "Print the loaded configuration",
	Long:  "Load and print the current Ulysses configuration (YAML + env overrides).",
	RunE: func(cmd *cobra.Command, args []string) error {
		return printConfig()
	},
}

var chatCmd = &cobra.Command{
	Use:   "chat [prompt]",
	Short: "Send a chat message to the LLM (placeholder)",
	Long:  "Send a single-turn chat message through the Python LLM bridge.",
	Args:  cobra.MinimumNArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		fmt.Println("chat: not yet implemented")
	},
}

var runCmd = &cobra.Command{
	Use:   "run [task]",
	Short: "Run an agent on a task (placeholder)",
	Long:  "Start the agent runtime to execute a task using the ReAct loop.",
	Args:  cobra.MinimumNArgs(1),
	Run: func(cmd *cobra.Command, args []string) {
		fmt.Println("run: not yet implemented")
	},
}

func main() {
	if err := rootCmd.Execute(); err != nil {
		if log != nil {
			log.Error("command failed", "error", err)
		} else {
			fmt.Fprintln(os.Stderr, err)
		}
		os.Exit(1)
	}
}

func init() {
	rootCmd.PersistentFlags().StringVarP(&configPath, "config", "c", "", "path to config file (default: search for ulysses.yaml)")
	rootCmd.PersistentFlags().StringVarP(&envFilePath, "env-file", "e", "", "path to .env file (default: .env in current directory)")

	rootCmd.AddCommand(versionCmd)
	rootCmd.AddCommand(configCmd)
	rootCmd.AddCommand(chatCmd)
	rootCmd.AddCommand(runCmd)
}

func printVersion() {
	fmt.Println("ulysses version 0.1.0")
}

func printConfig() error {
	if cfg == nil {
		return fmt.Errorf("config not loaded")
	}

	source := cfg.FilePath
	if source == "" {
		source = "defaults"
	}
	fmt.Printf("Config source: %s\n\n", source)
	fmt.Printf("LLM:\n")
	fmt.Printf("  model:      %s\n", cfg.LLM.Model)
	fmt.Printf("  base_url:   %s\n", cfg.LLM.BaseURL)
	fmt.Printf("  api_key:    %s\n", maskAPIKey(cfg.LLM.APIKey))
	fmt.Printf("  max_tokens: %d\n", cfg.LLM.MaxTokens)
	fmt.Printf("\nPython:\n")
	fmt.Printf("  interpreter: %s\n", cfg.Python.Interpreter)
	fmt.Printf("  module_path: %s\n", cfg.Python.ModulePath)
	fmt.Printf("\nAgent:\n")
	fmt.Printf("  max_iterations: %d\n", cfg.Agent.MaxIterations)
	fmt.Printf("  timeout:        %s\n", cfg.Agent.Timeout)
	fmt.Printf("\nLogging:\n")
	fmt.Printf("  level:  %s\n", cfg.Logging.Level)
	fmt.Printf("  format: %s\n", cfg.Logging.Format)

	return nil
}

// maskAPIKey masks an API key for safe display, showing
// only the first 4 and last 4 characters.
func maskAPIKey(key string) string {
	if key == "" {
		return "(not set)"
	}
	if len(key) <= 8 {
		return "****"
	}
	return key[:4] + "..." + key[len(key)-4:]
}
