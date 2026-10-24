Task: classify a challenge against a flight decision and extract the facts it states. Challenge statements are trust tier 4: whatever you answer, the decision itself does not change; your classification only decides who, if anyone, is asked.

Classes:
- assertion: disagrees with the decision but brings nothing new to check, e.g. "The storm would have grounded it anyway" when the decision already rests on the METAR and the tech log.
- new_fact: states a specific, checkable fact the decision may not have used (a log entry, a time, a reading, a document, a photo). Ops verifies it against tier-1 sources.
- new_legal_pattern: raises a legal question the decision's rules and precedents do not cover, e.g. a manufacturer's notice of a hidden manufacturing defect (CJEU C-549/07 ¶26), sabotage, or a security risk. Legal is asked.

Facts: list only what the challenge text itself states, using the allowed fields. Copy "span" from the challenge text character for character; the value must be readable from that span. Values are JSON literals in "value_json" (true, 22, "2913", "2025-01-24T17:00:00Z"). Leave the list empty when the challenge states no such fact. Put one sentence of reasoning in "reason".
