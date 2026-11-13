from pathlib import Path
p = Path("OutlookMailFinder/OutlookMailFinder.py")
s = p.read_text(encoding="utf-8")
head, tail = s.split("def self_test():", 1)
tail = tail.replace("        with db_connection() as conn:\n", "        conn = db_connection()\n        try:\n", 1)
tail = tail.replace("    return 0\n", "        finally:\n            conn.close()\n    return 0\n", 1)
p.write_text(head + "def self_test():" + tail, encoding="utf-8")
