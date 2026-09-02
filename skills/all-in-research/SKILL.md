---
name: all-in-research
description: Answer questions about the All-In Podcast using the indexed speaker-labeled transcript archive, with episode and timestamp citations. Use for claims, viewpoints, predictions, terminology, events, topic evolution, and comparisons involving the podcast.
---

# All-In transcript research

Use the `all-in-bot` MCP tools whenever the answer depends on what was said on the podcast.

## Workflow

1. Convert the user's question into one or more focused archive searches. Preserve important named entities and phrases.
2. Use `search_transcripts` for a factual or thematic question, `compare_speakers` for viewpoints, and `trace_topic` for change over time.
3. Retrieve more evidence when the first results come from only one episode, one speaker, or one side of a disagreement.
4. Synthesize the answer. Do not confuse a guest's position with a host's, or attention with endorsement.
5. Cite each archive-specific claim in this form: `Speaker, “Episode title” (YYYY-MM-DD, timestamp)` and link the episode when `listen_url` is present.

## Evidence standards

- Quote only exact words returned by a tool. Keep quotations short.
- Paraphrase broader conclusions and label them as synthesis.
- If evidence is thin, mixed, or speaker attribution looks uncertain, say so.
- For "how views changed" questions, retrieve evidence from at least two time periods.
- For comparisons, use comparable date ranges and give each requested speaker a genuine evidence search.
- Use counts only as measures of transcript attention. Do not call them sentiment, importance, or agreement.
- Never provide a full transcript or a sequence of excerpts that reconstructs an episode.

## Answer shape

Lead with the answer in plain language. Follow with the strongest evidence, then note disagreement, evolution, or uncertainty when it materially changes the conclusion. Avoid explaining retrieval mechanics unless the user asks.
