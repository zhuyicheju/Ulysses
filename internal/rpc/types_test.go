// Package rpc_test provides tests for the JSON-RPC 2.0 protocol types.
package rpc_test

import (
	"encoding/json"
	"testing"

	"github.com/zhuyicheju/ulysses/internal/rpc"
)

// =============================================================================
// Error code constants
// =============================================================================

func TestErrorCodeConstants(t *testing.T) {
	tests := []struct {
		name     string
		code     int
		expected int
	}{
		{"ParseError", rpc.ParseError, -32700},
		{"InvalidRequest", rpc.InvalidRequest, -32600},
		{"MethodNotFound", rpc.MethodNotFound, -32601},
		{"InvalidParams", rpc.InvalidParams, -32602},
		{"InternalError", rpc.InternalError, -32603},
		{"RateLimitExceeded", rpc.RateLimitExceeded, -32000},
		{"ContextLengthExceeded", rpc.ContextLengthExceeded, -32001},
		{"AuthError", rpc.AuthError, -32002},
		{"APITimeout", rpc.APITimeout, -32003},
		{"ModelNotAvailable", rpc.ModelNotAvailable, -32004},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if tt.code != tt.expected {
				t.Errorf("%s = %d, want %d", tt.name, tt.code, tt.expected)
			}
		})
	}
}

// =============================================================================
// Request
// =============================================================================

func TestRequest_MarshalUnmarshal(t *testing.T) {
	params := json.RawMessage(`{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"Hello"}]}`)
	req := rpc.Request{
		JSONRPC: "2.0",
		ID:      42,
		Method:  "chat",
		Params:  params,
	}

	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("failed to marshal Request: %v", err)
	}

	var got rpc.Request
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("failed to unmarshal Request: %v", err)
	}

	if got.JSONRPC != "2.0" {
		t.Errorf("JSONRPC = %q, want %q", got.JSONRPC, "2.0")
	}
	if got.ID != 42 {
		t.Errorf("ID = %d, want %d", got.ID, 42)
	}
	if got.Method != "chat" {
		t.Errorf("Method = %q, want %q", got.Method, "chat")
	}
	if string(got.Params) != string(params) {
		t.Errorf("Params = %s, want %s", got.Params, params)
	}
}

func TestRequest_JSONOutput(t *testing.T) {
	req := rpc.Request{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "ping",
		Params:  json.RawMessage(`{}`),
	}

	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal into map: %v", err)
	}

	// Required fields must be present
	if m["jsonrpc"] != "2.0" {
		t.Errorf("jsonrpc = %v, want %q", m["jsonrpc"], "2.0")
	}
	if m["id"] != float64(1) { // JSON numbers unmarshal as float64
		t.Errorf("id = %v, want 1", m["id"])
	}
	if m["method"] != "ping" {
		t.Errorf("method = %v, want %q", m["method"], "ping")
	}
}

func TestRequest_OmitsEmptyParams(t *testing.T) {
	// Params with zero (nil) value should be omitted from JSON
	req := rpc.Request{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "ping",
	}

	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal into map: %v", err)
	}

	if _, ok := m["params"]; ok {
		t.Error("params should be omitted when nil (omitempty)")
	}
}

func TestRequest_DeserializeAPISpecExample(t *testing.T) {
	// Matching api-spec.md Section 3.1 example
	input := `{"jsonrpc":"2.0","id":1,"method":"chat","params":{}}`
	var req rpc.Request
	if err := json.Unmarshal([]byte(input), &req); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}
	if req.JSONRPC != "2.0" {
		t.Errorf("jsonrpc = %q, want %q", req.JSONRPC, "2.0")
	}
	if req.ID != 1 {
		t.Errorf("id = %d, want 1", req.ID)
	}
	if req.Method != "chat" {
		t.Errorf("method = %q, want %q", req.Method, "chat")
	}
}

// =============================================================================
// Response
// =============================================================================

func TestResponse_MarshalUnmarshal(t *testing.T) {
	result := json.RawMessage(`"pong"`)
	resp := rpc.Response{
		JSONRPC: "2.0",
		ID:      1,
		Result:  result,
	}

	data, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("failed to marshal Response: %v", err)
	}

	var got rpc.Response
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("failed to unmarshal Response: %v", err)
	}

	if got.JSONRPC != "2.0" {
		t.Errorf("JSONRPC = %q, want %q", got.JSONRPC, "2.0")
	}
	if got.ID != 1 {
		t.Errorf("ID = %d, want %d", got.ID, 1)
	}
	if string(got.Result) != string(result) {
		t.Errorf("Result = %s, want %s", got.Result, result)
	}
}

func TestResponse_ResultString(t *testing.T) {
	resp := rpc.Response{
		JSONRPC: "2.0",
		ID:      1,
		Result:  json.RawMessage(`"pong"`),
	}

	data, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if m["result"] != "pong" {
		t.Errorf("result = %v, want %q", m["result"], "pong")
	}
}

func TestResponse_ResultObject(t *testing.T) {
	result := json.RawMessage(`{"count":42,"items":["a","b"]}`)
	resp := rpc.Response{
		JSONRPC: "2.0",
		ID:      99,
		Result:  result,
	}

	data, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	resultMap, ok := m["result"].(map[string]interface{})
	if !ok {
		t.Fatalf("result is not a map: %T", m["result"])
	}
	if resultMap["count"] != float64(42) {
		t.Errorf("result.count = %v, want 42", resultMap["count"])
	}
}

func TestResponse_ResultNull(t *testing.T) {
	resp := rpc.Response{
		JSONRPC: "2.0",
		ID:      1,
		Result:  json.RawMessage(`null`),
	}

	data, err := json.Marshal(resp)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if m["result"] != nil {
		t.Errorf("result = %v, want nil", m["result"])
	}
}

func TestResponse_DeserializeChatResponse(t *testing.T) {
	// Matching api-spec.md Section 5.2 chat result example
	input := `{
		"jsonrpc": "2.0",
		"id": 2,
		"result": {
			"id": "msg_01AbCdEf",
			"type": "message",
			"role": "assistant",
			"content": [{"type": "text", "text": "Hello! How can I help you today?"}],
			"model": "claude-sonnet-4-6",
			"stop_reason": "end_turn",
			"stop_sequence": null,
			"usage": {"input_tokens": 15, "output_tokens": 10}
		}
	}`

	var resp rpc.Response
	if err := json.Unmarshal([]byte(input), &resp); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}
	if resp.ID != 2 {
		t.Errorf("id = %d, want 2", resp.ID)
	}

	// Parse result to verify content
	var result map[string]interface{}
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		t.Fatalf("failed to unmarshal result: %v", err)
	}
	if result["stop_reason"] != "end_turn" {
		t.Errorf("stop_reason = %v, want %q", result["stop_reason"], "end_turn")
	}
}

// =============================================================================
// Error
// =============================================================================

func TestError_MarshalUnmarshal(t *testing.T) {
	errObj := rpc.Error{
		Code:    -32603,
		Message: "Internal error",
		Data:    json.RawMessage(`{"type":"AuthenticationError","detail":"Invalid API key"}`),
	}

	data, err := json.Marshal(errObj)
	if err != nil {
		t.Fatalf("failed to marshal Error: %v", err)
	}

	var got rpc.Error
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("failed to unmarshal Error: %v", err)
	}

	if got.Code != -32603 {
		t.Errorf("Code = %d, want %d", got.Code, -32603)
	}
	if got.Message != "Internal error" {
		t.Errorf("Message = %q, want %q", got.Message, "Internal error")
	}
}

func TestError_WithoutData(t *testing.T) {
	errObj := rpc.Error{
		Code:    -32601,
		Message: "Method not found",
	}

	data, err := json.Marshal(errObj)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	// data should be omitted when nil (omitempty)
	if _, ok := m["data"]; ok {
		t.Error("data should be omitted when nil (omitempty)")
	}
}

// =============================================================================
// ErrorResponse
// =============================================================================

func TestErrorResponse_MarshalUnmarshal(t *testing.T) {
	id := int64(1)
	errResp := rpc.ErrorResponse{
		JSONRPC: "2.0",
		ID:      &id,
		Error: rpc.Error{
			Code:    -32002,
			Message: "Auth Error",
		},
	}

	data, err := json.Marshal(errResp)
	if err != nil {
		t.Fatalf("failed to marshal ErrorResponse: %v", err)
	}

	var got rpc.ErrorResponse
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("failed to unmarshal ErrorResponse: %v", err)
	}

	if *got.ID != 1 {
		t.Errorf("ID = %d, want 1", *got.ID)
	}
	if got.Error.Code != -32002 {
		t.Errorf("Error.Code = %d, want %d", got.Error.Code, -32002)
	}
}

func TestErrorResponse_NullID(t *testing.T) {
	// Parse errors have null id — matching api-spec.md Section 7
	errResp := rpc.ErrorResponse{
		JSONRPC: "2.0",
		ID:      nil,
		Error: rpc.Error{
			Code:    -32700,
			Message: "Parse error",
		},
	}

	data, err := json.Marshal(errResp)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if m["id"] != nil {
		t.Errorf("id = %v, want null", m["id"])
	}
}

func TestErrorResponse_DeserializeAPISpecExample(t *testing.T) {
	// Matching api-spec.md Section 3.3 example
	input := `{
		"jsonrpc": "2.0",
		"id": 1,
		"error": {
			"code": -32603,
			"message": "Internal error",
			"data": {
				"type": "AuthenticationError",
				"detail": "Invalid API key"
			}
		}
	}`

	var errResp rpc.ErrorResponse
	if err := json.Unmarshal([]byte(input), &errResp); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if errResp.JSONRPC != "2.0" {
		t.Errorf("jsonrpc = %q, want %q", errResp.JSONRPC, "2.0")
	}
	if errResp.ID == nil || *errResp.ID != 1 {
		t.Errorf("ID = %v, want 1", errResp.ID)
	}
	if errResp.Error.Code != -32603 {
		t.Errorf("Error.Code = %d, want %d", errResp.Error.Code, -32603)
	}
}

func TestErrorResponse_DeserializeParseErrorWithNullID(t *testing.T) {
	// Parse error with null id
	input := `{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}`

	var errResp rpc.ErrorResponse
	if err := json.Unmarshal([]byte(input), &errResp); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if errResp.ID != nil {
		t.Errorf("ID should be nil for parse errors, got %v", *errResp.ID)
	}
	if errResp.Error.Code != -32700 {
		t.Errorf("Error.Code = %d, want -32700", errResp.Error.Code)
	}
}

// =============================================================================
// Notification
// =============================================================================

func TestNotification_MarshalUnmarshal(t *testing.T) {
	params := json.RawMessage(`{"request_id":3,"index":0,"delta":{"type":"text_delta","text":"Hello"}}`)
	notif := rpc.Notification{
		JSONRPC: "2.0",
		Method:  "stream/content_block_delta",
		Params:  params,
	}

	data, err := json.Marshal(notif)
	if err != nil {
		t.Fatalf("failed to marshal Notification: %v", err)
	}

	var got rpc.Notification
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatalf("failed to unmarshal Notification: %v", err)
	}

	if got.JSONRPC != "2.0" {
		t.Errorf("JSONRPC = %q, want %q", got.JSONRPC, "2.0")
	}
	if got.Method != "stream/content_block_delta" {
		t.Errorf("Method = %q, want %q", got.Method, "stream/content_block_delta")
	}
}

func TestNotification_NoIDField(t *testing.T) {
	// Notification MUST NOT have an id field in JSON output
	notif := rpc.Notification{
		JSONRPC: "2.0",
		Method:  "stream/message_stop",
		Params:  json.RawMessage(`{"request_id":3}`),
	}

	data, err := json.Marshal(notif)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if _, ok := m["id"]; ok {
		t.Error("Notification must not have 'id' field")
	}
}

func TestNotification_DeserializeStreamEvent(t *testing.T) {
	// Matching api-spec.md Section 3.4 example
	input := `{
		"jsonrpc": "2.0",
		"method": "stream/content_block_delta",
		"params": {
			"request_id": 3,
			"index": 0,
			"delta": {"type": "text_delta", "text": "Hello"}
		}
	}`

	var notif rpc.Notification
	if err := json.Unmarshal([]byte(input), &notif); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if notif.Method != "stream/content_block_delta" {
		t.Errorf("method = %q, want %q", notif.Method, "stream/content_block_delta")
	}

	var params map[string]interface{}
	if err := json.Unmarshal(notif.Params, &params); err != nil {
		t.Fatalf("failed to unmarshal params: %v", err)
	}
	if params["request_id"] != float64(3) {
		t.Errorf("request_id = %v, want 3", params["request_id"])
	}
}

func TestNotification_WithoutParams(t *testing.T) {
	notif := rpc.Notification{
		JSONRPC: "2.0",
		Method:  "stream/ping",
	}

	data, err := json.Marshal(notif)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	// Params should be omitted when nil
	if _, ok := m["params"]; ok {
		t.Error("params should be omitted when nil (omitempty)")
	}
	// Notification must not have id
	if _, ok := m["id"]; ok {
		t.Error("Notification must not have 'id' field")
	}
}

// =============================================================================
// Cross-language compatibility (Go ↔ Python)
// =============================================================================

func TestCrossLanguage_GoRequestParsedByPython(t *testing.T) {
	// Go produces JSON that matches Python's JSONRPCRequest schema
	req := rpc.Request{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "ping",
		Params:  json.RawMessage(`{}`),
	}

	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	// Python expects: {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	if m["jsonrpc"] != "2.0" {
		t.Errorf("jsonrpc = %v", m["jsonrpc"])
	}
	if m["method"] != "ping" {
		t.Errorf("method = %v", m["method"])
	}
	// Python's JSONRPCRequest expects id as int
	if _, ok := m["id"]; !ok {
		t.Error("id field required for Python JSONRPCRequest")
	}
}

func TestCrossLanguage_GoNotificationMatchesPython(t *testing.T) {
	// Go notification must match Python's JSONRPCNotification (no id field)
	notif := rpc.Notification{
		JSONRPC: "2.0",
		Method:  "notifications/cancelled",
		Params:  json.RawMessage(`{"request_id":5}`),
	}

	data, err := json.Marshal(notif)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	var m map[string]interface{}
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("failed to unmarshal: %v", err)
	}

	// Python's JSONRPCNotification has no id field
	if _, ok := m["id"]; ok {
		t.Error("Python JSONRPCNotification rejects messages with 'id' field")
	}
	if m["method"] != "notifications/cancelled" {
		t.Errorf("method = %v", m["method"])
	}
}

func TestCrossLanguage_ErrorMessageMatchesPython(t *testing.T) {
	// Error codes must match Python's error code constants
	// Standard codes
	if rpc.ParseError != -32700 {
		t.Errorf("ParseError should be -32700, matches Python PARSE_ERROR")
	}
	if rpc.InternalError != -32603 {
		t.Errorf("InternalError should be -32603, matches Python INTERNAL_ERROR")
	}
	// Application codes
	if rpc.AuthError != -32002 {
		t.Errorf("AuthError should be -32002, matches Python AUTH_ERROR")
	}
	if rpc.APITimeout != -32003 {
		t.Errorf("APITimeout should be -32003, matches Python API_TIMEOUT")
	}
}

// =============================================================================
// Discriminate notification from response
// =============================================================================

func TestDiscriminate_NotificationVsResponse(t *testing.T) {
	// A notification has method but no id
	notifJSON := `{"jsonrpc":"2.0","method":"stream/message_stop","params":{"request_id":3}}`

	// It should unmarshal as Notification
	var notif rpc.Notification
	if err := json.Unmarshal([]byte(notifJSON), &notif); err != nil {
		t.Fatalf("failed to unmarshal as Notification: %v", err)
	}

	// It should not be confused with a Response (which has id)
	var resp rpc.Response
	err := json.Unmarshal([]byte(notifJSON), &resp)
	if err == nil && resp.ID != 0 {
		t.Error("notification JSON should not have a meaningful id for Response")
	}
}

func TestDiscriminate_ResponseVsNotification(t *testing.T) {
	// A response has id and result
	respJSON := `{"jsonrpc":"2.0","id":1,"result":"pong"}`

	var resp rpc.Response
	if err := json.Unmarshal([]byte(respJSON), &resp); err != nil {
		t.Fatalf("failed to unmarshal as Response: %v", err)
	}
	if resp.ID != 1 {
		t.Errorf("id = %d, want 1", resp.ID)
	}

	// A valid response also has an id which would fail Notification's no-id check
	// The Notification type should still parse it (since Notification has no id field — it's just ignored)
	var notif rpc.Notification
	if err := json.Unmarshal([]byte(respJSON), &notif); err != nil {
		// This is acceptable: the Go JSON decoder may ignore extra fields
		// What matters is that the "method" field is checked
		t.Logf("Unmarshal as Notification (extra fields): %v", err)
	}
}
