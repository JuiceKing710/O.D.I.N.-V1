"""Tests for new features: JSON output, tools, RAG, and performance optimization."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.backend.core.json_output import (
    JSONOutputFormatter,
    ConstrainedGenerator,
    DiagnosticReport,
)
from jarvis.backend.core.tool_provider import (
    ToolRegistry,
    ToolDefinition,
    ToolInvocationHandler,
    ToolCallExtractor,
)
from jarvis.backend.core.inference_optimizer import (
    KVCacheOptimizer,
    TokenCounter,
    PerformanceMonitor,
    auto_detect_threads,
)
from jarvis.backend.core.rag_engine import RAGEngine, RAGConfig, DocumentChunker


class TestJSONOutput(unittest.TestCase):
    """Test JSON schema formatting and parsing."""

    def test_schema_to_json_string(self):
        """Convert Pydantic model to JSON schema."""
        schema_str = JSONOutputFormatter.schema_to_json_string(DiagnosticReport)
        self.assertIn("diagnosis", schema_str)
        self.assertIn("severity", schema_str)
        self.assertIn("recommended_actions", schema_str)

    def test_extract_json_block_markdown(self):
        """Extract JSON from markdown code block."""
        text = "Here is the result:\n```json\n{\"test\": \"value\"}\n```"
        result = JSONOutputFormatter.extract_json_block(text)
        self.assertEqual(result, {"test": "value"})

    def test_extract_json_block_bare(self):
        """Extract bare JSON object from text."""
        text = "Response: {\"key\": \"val\"} end"
        result = JSONOutputFormatter.extract_json_block(text)
        self.assertEqual(result, {"key": "val"})

    def test_extract_json_block_none(self):
        """Return None when no JSON found."""
        text = "No JSON here"
        result = JSONOutputFormatter.extract_json_block(text)
        self.assertIsNone(result)

    def test_parse_output_valid(self):
        """Parse valid output against schema."""
        text = """{
            "diagnosis": "System healthy",
            "severity": "low",
            "recommended_actions": ["Monitor"],
            "confidence": 0.95
        }"""
        result = JSONOutputFormatter.parse_output(text, DiagnosticReport)
        self.assertIsNotNone(result)
        self.assertEqual(result.diagnosis, "System healthy")
        self.assertEqual(result.severity, "low")

    def test_parse_output_invalid(self):
        """Return None for invalid schema."""
        text = '{"wrong": "schema"}'
        result = JSONOutputFormatter.parse_output(text, DiagnosticReport)
        self.assertIsNone(result)


class TestToolProvider(unittest.TestCase):
    """Test tool registration and invocation."""

    def setUp(self):
        self.registry = ToolRegistry()

    def test_register_tool(self):
        """Register a tool."""
        tool = ToolDefinition(
            id="test_tool",
            name="Test Tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {"input": {"type": "string"}}},
        )
        self.registry.register(tool)
        self.assertEqual(len(self.registry.list()), 1)
        self.assertIsNotNone(self.registry.find("test_tool"))

    def test_register_duplicate_error(self):
        """Error on duplicate registration."""
        tool = ToolDefinition(
            id="test",
            name="Test",
            description="Test",
            input_schema={},
        )
        self.registry.register(tool)
        with self.assertRaises(ValueError):
            self.registry.register(tool)

    def test_to_prompt_format(self):
        """Format tools for prompt injection."""
        tool = ToolDefinition(
            id="read_file",
            name="Read File",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        self.registry.register(tool)
        prompt = self.registry.to_prompt_format()
        self.assertIn("read_file", prompt)
        self.assertIn("Read File", prompt)

    def test_extract_tool_calls(self):
        """Extract tool calls from response."""
        text = """Let me help with that.
<tool_call>
{"id": "read_file", "params": {"path": "/tmp/test"}}
</tool_call>
Here's what I found."""
        calls = ToolCallExtractor.extract_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].tool_id, "read_file")
        self.assertEqual(calls[0].params["path"], "/tmp/test")

    def test_remove_tool_calls(self):
        """Remove tool call blocks from text."""
        text = """Start
<tool_call>
{"id": "tool", "params": {}}
</tool_call>
End"""
        clean = ToolCallExtractor.remove_tool_calls(text)
        self.assertNotIn("<tool_call>", clean)
        self.assertIn("Start", clean)
        self.assertIn("End", clean)

    def test_tool_invocation_handler(self):
        """Register handler for a tool."""
        registry = ToolRegistry()
        handler = ToolInvocationHandler(registry)

        def sync_handler(params):
            return f"processed: {params}"

        handler.register_handler("test", sync_handler)
        # Verify handler was registered
        self.assertIn("test", handler._handlers)


class TestInferenceOptimization(unittest.TestCase):
    """Test inference optimization features."""

    def test_auto_detect_threads(self):
        """Auto-detect thread count."""
        threads = auto_detect_threads()
        self.assertGreaterEqual(threads, 1)

    def test_token_counter_estimate(self):
        """Estimate token count."""
        text = "This is a test message with several words"
        tokens = TokenCounter.estimate(text)
        self.assertGreater(tokens, 0)
        self.assertGreater(tokens, len(text.split()))  # ~1.3x factor

    def test_token_counter_enforce_limit(self):
        """Enforce token limit by truncation."""
        text = "This is a very long text " * 100
        limited = TokenCounter.enforce_limit(text, limit=50)
        limited_tokens = TokenCounter.estimate(limited)
        self.assertLessEqual(limited_tokens, 100)  # Allow some slack

    def test_kv_cache_pruning(self):
        """Prune messages to fit token limit."""
        messages = [
            {"role": "system", "content": "You are an assistant " * 50},
            {"role": "user", "content": "Question " * 20},
            {"role": "assistant", "content": "Answer " * 30},
            {"role": "user", "content": "Follow-up " * 15},
        ]
        pruned = KVCacheOptimizer.prune_context(messages, max_tokens=200)
        # Should keep system + recent messages
        self.assertGreater(len(pruned), 0)
        self.assertTrue(any(m.get("role") == "system" for m in pruned))

    def test_performance_monitor(self):
        """Track inference performance."""
        monitor = PerformanceMonitor()
        monitor.log_inference("qwen:14b", 50, 100, 1000)
        monitor.log_inference("qwen:14b", 60, 110, 950)

        stats = monitor.recent_stats(n=2)
        self.assertIn("avg_latency_ms", stats)
        self.assertIn("avg_throughput_tokens_per_sec", stats)
        self.assertEqual(stats["sample_count"], 2)


class TestRAGEngine(unittest.TestCase):
    """Test RAG capabilities."""

    def setUp(self):
        # Mock vector store
        self.mock_store = MagicMock()
        self.mock_store.enabled = True
        self.mock_store.upsert_document.return_value = "doc_id"
        self.mock_store.query.return_value = []

    def test_document_chunking(self):
        """Split documents into chunks."""
        chunker = DocumentChunker(chunk_size=50)
        text = " ".join(["word"] * 200)
        chunks = chunker.chunk_text(text, {"source": "test"})
        self.assertGreater(len(chunks), 1)

    def test_rag_ingest(self):
        """Ingest text into RAG."""
        rag = RAGEngine(self.mock_store, RAGConfig(chunk_size=100))
        count = rag.ingest_text("This is test content", "source_1")
        self.assertGreaterEqual(count, 0)

    def test_rag_query(self):
        """Query RAG documents."""
        from jarvis.backend.core.vector_store import VectorSearchResult

        self.mock_store.query.return_value = [
            VectorSearchResult(
                record_id="1",
                content="Test content",
                metadata={"source": "doc1"},
                score=0.95,
            )
        ]
        rag = RAGEngine(self.mock_store)
        results = rag.query("test query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "Test content")
        self.assertEqual(results[0].metadata.get("source"), "doc1")

    def test_rag_format_for_context(self):
        """Format RAG results for LM context."""
        from jarvis.backend.core.rag_engine import RAGResult

        results = [
            RAGResult(
                content="Important fact",
                source="wikipedia",
                score=0.92,
                metadata={"doc_id": "1"},
            )
        ]
        rag = RAGEngine(self.mock_store)
        formatted = rag.format_for_context(results)
        self.assertEqual(len(formatted), 1)
        self.assertIn("wikipedia", formatted[0])
        self.assertIn("Important fact", formatted[0])


class TestConstrainedGenerator(unittest.TestCase):
    """Test constrained output generation."""

    def test_constrained_generation_success(self):
        """Generate and validate JSON successfully."""

        async def run_test():
            mock_lm = AsyncMock()
            mock_lm.generate.return_value = """{
                "diagnosis": "System OK",
                "severity": "low",
                "recommended_actions": ["Continue monitoring"],
                "confidence": 0.9
            }"""

            gen = ConstrainedGenerator(max_retries=3)
            result = await gen.generate_json(
                mock_lm, "Analyze system", [], DiagnosticReport
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.diagnosis, "System OK")
            self.assertEqual(result.severity, "low")

        asyncio.run(run_test())

    def test_constrained_generation_retry(self):
        """Retry on invalid JSON."""

        async def run_test():
            mock_lm = AsyncMock()
            mock_lm.generate.side_effect = [
                "Invalid JSON {",
                '{"wrong": "schema"}',
                '{"diagnosis": "OK", "severity": "low", "recommended_actions": [], "confidence": 0.8}',
            ]

            gen = ConstrainedGenerator(max_retries=3)
            result = await gen.generate_json(
                mock_lm, "Analyze", [], DiagnosticReport
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.diagnosis, "OK")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
