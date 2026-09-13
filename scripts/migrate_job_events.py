"""Idempotent migration: create job_events table if missing."""
import sqlite3

con = sqlite3.connect("system.db")
cols = [r[1] for r in con.execute("PRAGMA table_info(job_events)").fetchall()]
if not cols:
    con.execute(
        """
        CREATE TABLE job_events (
            id INTEGER PRIMARY KEY,
            stage VARCHAR(30) NOT NULL,
            video_ref VARCHAR(255),
            title VARCHAR(500),
            percent INTEGER,
            detail TEXT,
            created_at TIMESTAMP
        )
        """
    )
    con.commit()
    print("job_events table created")
else:
    print("job_events already exists")
con.close()
