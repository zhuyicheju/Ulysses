// Package rpc implements the JSON-RPC 2.0 client over stdio.
// It communicates with the Python child process via newline-delimited
// JSON messages on stdin/stdout.
package rpc

import "encoding/json"

// JSON-RPC 2.0 standard error codes and application-specific error codes.
// Values match the Python side defined in ulysses_ai/protocol.py.
const (
	// Standard JSON-RPC 2.0 error codes.
	ParseError     = -32700
	InvalidRequest = -32600
	MethodNotFound = -32601
	InvalidParams  = -32602
	InternalError  = -32603

	// Application-specific error codes (reserved range -32000 to -32099).
	RateLimitExceeded     = -32000
	ContextLengthExceeded = -32001
	AuthError             = -32002
	APITimeout            = -32003
	ModelNotAvailable     = -32004
)

// Request is a JSON-RPC 2.0 request.
// Matches Python's JSONRPCRequest in ulysses_ai/protocol.py.
type Request struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      int64           `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// Response is a JSON-RPC 2.0 success response.
// Matches Python's JSONRPCResponse in ulysses_ai/protocol.py.
type Response struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      int64           `json:"id"`
	Result  json.RawMessage `json:"result,omitempty"`
}

// Error is a JSON-RPC 2.0 error object.
// Matches Python's JSONRPCError in ulysses_ai/protocol.py.
type Error struct {
	Code    int             `json:"code"`
	Message string          `json:"message"`
	Data    json.RawMessage `json:"data,omitempty"`
}

// ErrorResponse is a JSON-RPC 2.0 error response.
// ID is a pointer to allow null for parse errors where the request id
// could not be determined.
// Matches Python's JSONRPCErrorResponse in ulysses_ai/protocol.py.
type ErrorResponse struct {
	JSONRPC string `json:"jsonrpc"`
	ID      *int64 `json:"id"`
	Error   Error  `json:"error"`
}

// Notification is a JSON-RPC 2.0 notification (no id field).
// Matches Python's JSONRPCNotification in ulysses_ai/protocol.py.
type Notification struct {
	JSONRPC string          `json:"jsonrpc"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}
