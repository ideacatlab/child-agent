"""scion — a self-improving generalist Claude agent harness.

scion is a *base*: a generalist, no-scope agent that can build its own tools,
ingest knowledge, remember across runs, talk to you on Telegram, and publish its
own improvements back to GitHub. Fork it and grow a specialist (a marketer, an
SRE, a researcher) that gets better from the feedback of the people who use it.

The whole core runs on the Python standard library. The only hard dependency is
the LLM SDK (``anthropic``); RAG, web access, and richer embeddings are optional
extras that degrade gracefully.

Architecture, in one breath::

    channels (Telegram/CLI)  ->  task queue (durable SQLite)
                                      |
                                 worker drains it
                                      v
        AgentLoop( LLM, ToolRegistry, Memory, RAG, Skills )
                                      |
            +-------------------------+-------------------------+
            |             |            |            |           |
         tools        memory        skills        rag      self-tooling
       (hot-load)   (markdown +   (SKILL.md +   (hybrid   (author->verify->
                     blocks)      progressive    search)    register->publish)
                                  disclosure)
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
