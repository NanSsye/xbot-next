from __future__ import annotations


class MemoryCompressor:
    async def summarize_task(self, input_text: str, result: str) -> dict:
        return {
            "summary": result[:500],
            "input": input_text[:500],
            "decisions": [],
            "changed_files": [],
            "open_questions": [],
            "next_actions": [],
        }

