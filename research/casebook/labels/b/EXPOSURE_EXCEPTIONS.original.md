# Exposure exception — B-v1

C04-p02 is **temporally tainted and must not count as a clean independent gold vote**. Other 36 prefix save-before-next-prefix transitions had no known exception.

The original C04-p02 label specification was fully drafted before C04-p03 exposure. The save attempted to find the exact O013 text substring containing `Riyadh \\u2060airport`. That substring was not found (Python `ValueError: substring not found`), so the helper exited before writing the label or audit entry. The same shell invocation contained an unchecked following Python command, which continued and read C04-p03, printing new observation O015. This violated required save-and-hash-before-next-prefix discipline. The error was reported immediately to root.

C04-p02 was subsequently saved with the same drafted substantive claims, relations and deltas, replacing only the failed O013 supporting span with its title and the Thursday-timing substring, and adding the explicit exposure note. No later factual content was added to its claims. This does not restore independent temporal validity. The source read and failed save are preserved in the conversation tool transcript. An attempted-draft reconstruction is saved in `C04-p02-attempted-draft.txt`; it is a specification, not a label vote, and is not separately audited as a prefix.

C04-p03 was labeled separately after the C04-p02 save succeeded. All subsequent saves and next-prefix reads used separate tool calls with confirmed successful saves. Earlier successfully saved labels and audit entries were never overwritten. A prior C02-p01 span-validation failure occurred before opening C03-p01 and was fixed safely; it caused no temporal exposure exception.

Root was informed and plans an independently sourced replacement vote before adjudication. No candidate/system-output exposure is known.
