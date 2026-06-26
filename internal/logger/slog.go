package logger

import (
	"context"
	"io"
	"log/slog"
	"os"
	"strings"
)

// slogAdapter wraps a *slog.Logger to satisfy the Logger interface.
type slogAdapter struct {
	inner *slog.Logger
}

// Ensure interface satisfaction at compile time.
var _ Logger = (*slogAdapter)(nil)

// New creates a Logger backed by slog.
//   - level: one of "debug", "info", "warn", "error" (case-insensitive).
//   - format: "json" or "text".
//   - output: the io.Writer to write to. If nil, os.Stderr is used.
func New(level string, format string, output io.Writer) (Logger, error) {
	if output == nil {
		output = os.Stderr
	}

	slogLevel := parseLevel(level)

	opts := &slog.HandlerOptions{
		Level: slogLevel,
		ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
			if a.Key == slog.TimeKey {
				// Format time as RFC3339 with milliseconds.
				t := a.Value.Time()
				a.Value = slog.StringValue(t.Format("2006-01-02T15:04:05.000Z07:00"))
			}
			return a
		},
	}

	var handler slog.Handler
	switch format {
	case "text":
		handler = slog.NewTextHandler(output, opts)
	default:
		handler = slog.NewJSONHandler(output, opts)
	}

	return &slogAdapter{inner: slog.New(handler)}, nil
}

// parseLevel converts a level string to a slog.Level.
// Unrecognized values default to info.
func parseLevel(s string) slog.Level {
	switch strings.ToLower(s) {
	case "debug":
		return slog.LevelDebug
	case "info":
		return slog.LevelInfo
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

func (l *slogAdapter) Debug(msg string, args ...any) {
	l.inner.Debug(msg, args...)
}

func (l *slogAdapter) Info(msg string, args ...any) {
	l.inner.Info(msg, args...)
}

func (l *slogAdapter) Warn(msg string, args ...any) {
	l.inner.Warn(msg, args...)
}

func (l *slogAdapter) Error(msg string, args ...any) {
	l.inner.Error(msg, args...)
}

func (l *slogAdapter) DebugContext(ctx context.Context, msg string, args ...any) {
	l.inner.DebugContext(ctx, msg, args...)
}

func (l *slogAdapter) InfoContext(ctx context.Context, msg string, args ...any) {
	l.inner.InfoContext(ctx, msg, args...)
}

func (l *slogAdapter) WarnContext(ctx context.Context, msg string, args ...any) {
	l.inner.WarnContext(ctx, msg, args...)
}

func (l *slogAdapter) ErrorContext(ctx context.Context, msg string, args ...any) {
	l.inner.ErrorContext(ctx, msg, args...)
}

func (l *slogAdapter) With(args ...any) Logger {
	return &slogAdapter{inner: l.inner.With(args...)}
}

func (l *slogAdapter) WithGroup(name string) Logger {
	return &slogAdapter{inner: l.inner.WithGroup(name)}
}
