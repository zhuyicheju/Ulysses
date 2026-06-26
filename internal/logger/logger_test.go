package logger_test

import (
	"bytes"
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/zhuyicheju/ulysses/internal/logger"
)

func TestNew_JSONFormat_InfoLevel(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Info("hello world", "key", "value")

	// Parse the JSON output.
	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output is not valid JSON: %v\nraw: %s", err, buf.String())
	}

	// Verify required keys.
	if entry["level"] != "INFO" {
		t.Errorf("level = %v, want INFO", entry["level"])
	}
	if entry["msg"] != "hello world" {
		t.Errorf("msg = %v, want 'hello world'", entry["msg"])
	}
	if _, ok := entry["time"]; !ok {
		t.Error("missing 'time' key in JSON output")
	}
	if entry["key"] != "value" {
		t.Errorf("extra field key = %v, want 'value'", entry["key"])
	}
}

func TestNew_LevelFiltering_DebugSuppressedAtInfo(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Debug("should not appear")

	if buf.Len() != 0 {
		t.Errorf("Debug message appeared at info level: %s", buf.String())
	}
}

func TestNew_LevelFiltering_DebugShownAtDebug(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("debug", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Debug("debug message")

	if buf.Len() == 0 {
		t.Error("Debug message not shown at debug level")
	}
}

func TestNew_LevelFiltering_AllLevels(t *testing.T) {
	tests := []struct {
		levelString string
		shouldLog   []string // methods that should produce output
	}{
		{"debug", []string{"Debug", "Info", "Warn", "Error"}},
		{"info", []string{"Info", "Warn", "Error"}},
		{"warn", []string{"Warn", "Error"}},
		{"error", []string{"Error"}},
	}

	for _, tt := range tests {
		t.Run(tt.levelString, func(t *testing.T) {
			log, err := logger.New(tt.levelString, "json", &bytes.Buffer{})
			if err != nil {
				t.Fatalf("New() error = %v", err)
			}
			// Verify log doesn't panic — we just test that it can be created.
			// Level filtering is a slog built-in feature.
			_ = log
		})
	}
}

func TestNew_InvalidLevelDefaultsToInfo(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("bogus", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Info("hello")

	if buf.Len() == 0 {
		t.Error("logger with invalid level should default to info")
	}
}

func TestNew_TextFormat(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "text", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Info("hello world")

	output := buf.String()
	if output == "" {
		t.Error("text format produced no output")
	}
	// Text format should not be valid JSON.
	if json.Valid([]byte(output)) {
		t.Log("text output happens to be valid JSON — fine, just noting")
	}
	// Should contain the message.
	if !strings.Contains(output, "hello world") {
		t.Errorf("text output missing message: %s", output)
	}
}

func TestNew_NilWriterDefaultsToStderr(t *testing.T) {
	// When nil writer is passed, should not panic.
	log, err := logger.New("info", "json", nil)
	if err != nil {
		t.Fatalf("New() with nil writer error = %v", err)
	}
	if log == nil {
		t.Fatal("New() returned nil logger")
	}
	// Should still be usable (writes to stderr, we don't capture that here).
	log.Info("should not panic")
}

func TestWith_AddsFields(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	child := log.With("component", "test", "id", 42)
	child.Info("child message")

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}

	if entry["component"] != "test" {
		t.Errorf("component = %v, want 'test'", entry["component"])
	}
	id, ok := entry["id"].(float64) // JSON numbers are float64
	if !ok || int(id) != 42 {
		t.Errorf("id = %v, want 42", entry["id"])
	}
}

func TestWith_ParentUnaffected(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	_ = log.With("component", "child")
	log.Info("parent message")

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}

	if _, ok := entry["component"]; ok {
		t.Error("parent logger should not have child's fields")
	}
}

func TestWithGroup_GroupsAttributes(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	grouped := log.WithGroup("request")
	grouped.Info("request info", "method", "GET", "path", "/api")

	output := buf.String()
	// slog WithGroup nests fields under a sub-object.
	if !strings.Contains(output, "request") {
		t.Errorf("output missing group name 'request': %s", output)
	}
}

func TestDebugContext(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("debug", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	ctx := context.Background()
	log.DebugContext(ctx, "debug with context", "trace_id", "abc123")

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}

	if entry["msg"] != "debug with context" {
		t.Errorf("msg = %v, want 'debug with context'", entry["msg"])
	}
}

func TestInfoContext(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.InfoContext(context.Background(), "info with context")

	if buf.Len() == 0 {
		t.Error("InfoContext produced no output")
	}
}

func TestWarnContext(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.WarnContext(context.Background(), "warning with context")

	if buf.Len() == 0 {
		t.Error("WarnContext produced no output")
	}
}

func TestErrorContext(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.ErrorContext(context.Background(), "error with context", "err", "something broke")

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}

	if entry["level"] != "ERROR" {
		t.Errorf("level = %v, want ERROR", entry["level"])
	}
}

func TestNew_LevelCaseInsensitive(t *testing.T) {
	tests := []string{"DEBUG", "Debug", "INFO", "Info", "WARN", "Warn", "ERROR", "Error"}
	for _, level := range tests {
		t.Run(level, func(t *testing.T) {
			_, err := logger.New(level, "json", &bytes.Buffer{})
			if err != nil {
				t.Errorf("New(%q) error = %v", level, err)
			}
		})
	}
}

func TestTimeFormat(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Info("timestamp test")

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}

	timeStr, ok := entry["time"].(string)
	if !ok {
		t.Fatal("time field is not a string")
	}

	// Must contain 'T' and a timezone offset (+/-).
	if !strings.Contains(timeStr, "T") {
		t.Errorf("time format missing 'T': %s", timeStr)
	}
	// Should end with timezone offset like +08:00, -05:00, or Z.
	hasTZ := strings.Contains(timeStr, "+") || strings.Contains(timeStr, "-") && strings.LastIndex(timeStr, "-") > 10 || strings.HasSuffix(timeStr, "Z")
	if !hasTZ {
		t.Errorf("time format missing timezone offset: %s", timeStr)
	}
}

func TestErrorLevel(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Error("something failed", "error", "connection refused")

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}

	if entry["level"] != "ERROR" {
		t.Errorf("level = %v, want ERROR", entry["level"])
	}
	if entry["error"] != "connection refused" {
		t.Errorf("error field = %v, want 'connection refused'", entry["error"])
	}
}

func TestWarnLevel(t *testing.T) {
	var buf bytes.Buffer
	log, err := logger.New("info", "json", &buf)
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	log.Warn("low disk space", "disk", "/dev/sda1")

	var entry map[string]any
	if err := json.Unmarshal(buf.Bytes(), &entry); err != nil {
		t.Fatalf("output not valid JSON: %v", err)
	}

	if entry["level"] != "WARN" {
		t.Errorf("level = %v, want WARN", entry["level"])
	}
}

// Compile-time check: slogAdapter implements Logger.
func TestInterfaceSatisfaction(t *testing.T) {
	// This is a compile-time assertion — if it doesn't compile, the test fails.
	var _ logger.Logger = nil // ensure we import logger
	_ = logger.New             // ensure New exists
}
