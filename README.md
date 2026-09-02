# All-In Bot

All-In Bot is an unofficial research companion for the All-In Podcast. It lets listeners ask natural-language questions across a speaker-labeled transcript archive and get evidence-linked answers with episode, date, speaker, timestamp, and listening-source citations.

This project is independent and is not affiliated with, endorsed by, or operated by the All-In Podcast or its hosts.

## What you can ask

- How did the conversation about tariffs change before and after 2024?
- Compare Chamath and Friedberg on nuclear energy since 2023.
- What did the show predict about interest rates in 2022?
- Find the strongest arguments for and against open-source AI.
- When did "sovereign AI" first appear, and how did its use spread?

## Install in Grok Bot

Once the plugin is listed in the Cursor Marketplace:

1. Open Grok Bot and select **Plugins** in the sidebar.
2. Search for **All-In Bot** and select **Add**.
3. Confirm that All-In Bot appears under **Installed**.
4. Mention `@All-In Bot` in a conversation, or ask an All-In archive question directly.

Example:

> Using All-In Bot, compare how the podcast discussed tariffs before and after 2024. Cite the speakers, episodes, dates, and timestamps.

The hosted MCP endpoint is `https://all-in-grok-production.up.railway.app/mcp`. It is public and read-only, so listeners do not need an API key or access token.

## Capabilities

- `search_transcripts`: find relevant transcript passages with speaker and date filters
- `compare_speakers`: retrieve comparable evidence for multiple speakers
- `trace_topic`: measure topic attention by quarter or year using real corpus denominators
- `get_episode_context`: retrieve a bounded context window around a timestamp
- `list_speakers`: discover indexed speakers
- `get_corpus_stats`: inspect archive coverage and limitations

The plugin also includes an All-In research skill, a read-only researcher agent, and `/ask-all-in` and `/compare-all-in` commands.

## Evidence policy

- Search before making claims about the archive.
- Cite the speaker, episode, publication date, and timestamp.
- Treat transcript wording and speaker labels as fallible source material.
- Treat topic counts as measures of attention, not endorsement or sentiment.
- Never reproduce a full transcript or a sequence of excerpts that reconstructs one.

## Privacy

Questions sent through the plugin are transmitted to the hosted MCP service so it can search the archive. The service does not intentionally store question text or search results. Hosting and network providers may retain routine operational metadata. See [PRIVACY.md](PRIVACY.md).

## Local development

The public repository contains the plugin and server code only. It does not contain the purchased transcript archive, generated SQLite index, or deployment artifact.

Build a local index from an authorized normalized corpus:

```bash
python3 scripts/build_index.py \
  --turns /path/to/normalized/turns.jsonl \
  --episodes /path/to/normalized/episodes.json \
  --listening-links /path/to/listening-links.json
```

For local stdio testing, copy `mcp.local.example.json` over `mcp.json` in a development-only checkout. Do not commit that change to the Marketplace branch.

Run validation and tests:

```bash
python3 scripts/validate_plugin.py
python3 -m unittest discover -s tests -v
```

## Deployment

`railway_app.py` provides a FastAPI entrypoint for Railway and Render. The Docker image expects `data/all-in-grok.sqlite3.gz`, expands the read-only index into ephemeral storage, and exposes `/mcp` and `/healthz`. No persistent volume is required.

The archive artifact is intentionally excluded from Git. Only deploy it to infrastructure where you are authorized to store and process it.

## Rights and licensing

The plugin source code is MIT licensed. The transcript corpus, generated index, podcast audio, names, marks, and other third-party materials are not covered by that license. The service exposes bounded search results and short supporting excerpts rather than transcript downloads.
