# Privacy

All-In Bot sends the user's archive question and tool parameters to the hosted MCP endpoint so the service can search the transcript index and return relevant evidence.

The application code does not intentionally persist question text, archive search results, or conversation history. The current server emits standard HTTP access logs that contain request method, path, status code, and infrastructure-level network metadata. It does not log authorization headers or request bodies.

The service is hosted on Railway. Cursor and Railway may process or retain data according to their own policies. Do not include passwords, financial information, health information, or other sensitive personal information in archive questions.

The public source repository excludes the transcript corpus, generated search index, deployment artifact, and access credentials.

For privacy questions, open an issue in the public GitHub repository.
