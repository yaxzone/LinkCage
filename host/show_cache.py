#!/usr/bin/env python3
# Copyright 2026 Luis Yax
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Show all entries in the LinkCage verdict cache."""
import os
import platform
import sqlite3
import sys

if platform.system() == "Windows":
    db = os.path.join(os.environ.get("LOCALAPPDATA", ""), "LinkCage", "cache.sqlite")
else:
    db = os.path.expanduser("~/.linkcage/cache.sqlite")

if not os.path.exists(db):
    print("No cache found at: " + db)
    sys.exit(1)

conn = sqlite3.connect(db)
rows = conn.execute(
    'SELECT url_canonical, verdict, source, reason, '
    'datetime(checked_at, "unixepoch", "localtime"), '
    'datetime(expires_at, "unixepoch", "localtime") '
    'FROM url_verdicts ORDER BY checked_at DESC'
).fetchall()
conn.close()

print("LinkCage Verdict Cache: {} entries".format(len(rows)))
print("")
for i, r in enumerate(rows, 1):
    print("{}. [{}] {} - {}".format(i, r[1], r[4], r[0][:80]))
