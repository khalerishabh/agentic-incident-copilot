from mcp_servers.runbook.chunking import chunk_markdown

DOC = """# Database pool exhaustion

Applies to orders and inventory.

## Symptoms
Requests time out with `pool timeout` errors.

## Diagnosis
### Database
Check active connections.

```sql
# not a heading inside a code block
SELECT count(*) FROM pg_stat_activity;
```

### Application
Look for slow transactions.
"""


def test_sections_keep_their_heading_path_and_title():
    chunks = chunk_markdown("db-pool", DOC, max_chars=1500)
    assert {c.title for c in chunks} == {"Database pool exhaustion"}
    assert [c.section for c in chunks] == [
        "Overview",
        "Symptoms",
        "Diagnosis > Database",
        "Diagnosis > Application",
    ]
    assert "# not a heading inside a code block" in chunks[2].content
    assert [c.index for c in chunks] == [0, 1, 2, 3]


def test_long_sections_are_split_without_losing_text():
    body = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    chunks = chunk_markdown("long", f"# Long\n\n## Steps\n{body}", max_chars=400)
    assert len(chunks) > 1
    assert all(len(c.content) <= 400 for c in chunks)
    assert all(c.section == "Steps" for c in chunks)
    joined = " ".join(c.content for c in chunks)
    assert all(f"Paragraph {i}" in joined for i in range(10))


def test_digest_changes_only_when_text_changes():
    a = chunk_markdown("x", DOC, 1500)
    b = chunk_markdown("x", DOC, 1500)
    c = chunk_markdown("x", DOC.replace("slow transactions", "long transactions"), 1500)
    assert [x.digest for x in a] == [x.digest for x in b]
    assert a[3].digest != c[3].digest
    assert a[1].digest == c[1].digest
