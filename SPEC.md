# All-In Bot

## Value proposition

All-In listeners and Summit attendees can ask natural-language questions across the full speaker-labeled podcast archive and receive concise answers grounded in episode evidence. All-In Bot is an independent community project and is not affiliated with the podcast or its hosts.

The painful alternative is remembering which episode contained a claim, manually searching hundreds of transcripts, and reconstructing how a topic or speaker's position changed over time.

Core actions:

1. Search the archive for passages about an idea, company, person, policy, or event.
2. Compare what multiple speakers said about the same subject.
3. Trace how attention to a subject changed over time.

## Why conversation

Questions such as "How did the besties' view of tariffs change after 2024?" combine topic, time, speaker, and synthesis in one sentence. The assistant interprets that intent and writes the answer. The plugin contributes the evidence the assistant does not have: 406 episodes of speaker-labeled transcript turns, exact dates, timestamps, and listening links.

## User experience

The user opens Cursor chat and invokes the All-In researcher or types a question. The assistant searches before making archive-specific claims, may retrieve parallel evidence for multiple speakers, and returns a direct answer with speaker, episode, date, and timestamp citations. Follow-up questions remain conversational.

## Data and safety

- Source: the locally purchased Spoken Archive normalized corpus.
- Coverage at initial build: March 2020 through August 2026.
- Retrieval: SQLite FTS5 over transcript turns, with adjacent turns included for context.
- Public answer policy: short evidence excerpts only. The assistant must not reproduce full episodes or help reconstruct the archive.
- Transcript wording and speaker attribution can contain errors. Answers must distinguish quotation from synthesis and disclose weak or conflicting evidence.
- No xAI or other model API key is required. Cursor's active model performs the synthesis.

## Tool design

### `search_transcripts`

Search for relevant transcript passages with optional speaker and date filters. Returns ranked passages with context and citations.

### `compare_speakers`

Run the same evidence search separately for named speakers. Returns balanced, speaker-grouped evidence and explicit gaps.

### `trace_topic`

Count matching transcript turns and distinct episodes by quarter or year, then return representative evidence. Counts measure attention, not approval or sentiment.

### `get_episode_context`

Retrieve a bounded window around a known episode timestamp or turn. It never returns an entire transcript.

### `list_speakers` and `get_corpus_stats`

Support discovery and let the assistant state archive coverage accurately.
