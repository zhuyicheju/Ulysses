// Package logger provides structured logging using slog.
// It defines a Logger interface that all internal packages depend on,
// along with an slog-based implementation.
package logger

import "context"

// Logger is the interface for structured logging throughout Ulysses.
// Every internal package depends on this interface, not on slog directly,
// so the logging implementation can be swapped without changing consumers.
type Logger interface {
	// Debug logs at debug level.
	Debug(msg string, args ...any)
	// Info logs at info level.
	Info(msg string, args ...any)
	// Warn logs at warn level.
	Warn(msg string, args ...any)
	// Error logs at error level.
	Error(msg string, args ...any)

	// DebugContext logs at debug level with a context.
	DebugContext(ctx context.Context, msg string, args ...any)
	// InfoContext logs at info level with a context.
	InfoContext(ctx context.Context, msg string, args ...any)
	// WarnContext logs at warn level with a context.
	WarnContext(ctx context.Context, msg string, args ...any)
	// ErrorContext logs at error level with a context.
	ErrorContext(ctx context.Context, msg string, args ...any)

	// With returns a child logger with the given key-value pairs
	// pre-attached to every log line.
	With(args ...any) Logger

	// WithGroup returns a child logger that groups subsequent attributes
	// under the given namespace.
	WithGroup(name string) Logger
}
